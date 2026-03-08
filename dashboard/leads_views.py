from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import random
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
from decimal import InvalidOperation
from urllib.parse import urlencode
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.models import BusinessUnit
from core.rbac.constants import ModuleCode
from core.rbac.constants import PermissionAction
from core.rbac.constants import RoleCode
from core.rbac.services import has_module_permission
from crm.forms import LeadForm
from crm.forms import LeadGenerationPublicForm
from crm.forms import LeadNoteForm
from crm.models import InvoiceDuplicateOverride
from crm.models import InvoiceDuplicateReviewRequest
from crm.models import Lead
from crm.models import LeadActivityLog
from crm.models import LeadNote
from crm.models import LeadSource
from crm.models import SalesRep
from dashboard.services.hierarchy_scope_service import get_downline_user_ids

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional at runtime in some environments
    PdfReader = None

try:
    import pytesseract
except Exception:  # pragma: no cover - optional at runtime in some environments
    pytesseract = None

try:
    import pypdfium2 as pdfium
except Exception:  # pragma: no cover - optional at runtime in some environments
    pdfium = None

try:
    from PIL import Image
    from PIL import ImageDraw
    from PIL import ImageFont
    from PIL import ImageOps
except Exception:  # pragma: no cover - optional at runtime in some environments
    Image = None
    ImageDraw = None
    ImageFont = None
    ImageOps = None

try:
    import qrcode
except Exception:  # pragma: no cover - optional at runtime in some environments
    qrcode = None

logger = logging.getLogger(__name__)


def _safe_slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower())
    return cleaned.strip("-") or "asociado"


def _load_marketing_font(size: int, *, bold: bool = False):
    if ImageFont is None:
        return None
    candidates = []
    if bold:
        candidates.extend(
            [
                "DejaVuSans-Bold.ttf",
                "arialbd.ttf",
                "segoeuib.ttf",
                r"C:\Windows\Fonts\arialbd.ttf",
                r"C:\Windows\Fonts\segoeuib.ttf",
            ]
        )
    else:
        candidates.extend(
            [
                "DejaVuSans.ttf",
                "arial.ttf",
                "segoeui.ttf",
                r"C:\Windows\Fonts\arial.ttf",
                r"C:\Windows\Fonts\segoeui.ttf",
            ]
        )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


@dataclass(frozen=True)
class LeadAccess:
    salesrep: SalesRep | None
    can_assign: bool
    can_delete: bool
    is_superadmin_or_partner: bool


def _profile(user):
    return getattr(user, "profile", None)


def _my_salesrep(user):
    return SalesRep.objects.select_related("user", "business_unit").filter(user=user, is_active=True).first()


def _can_access_customer_management_section(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = _profile(user)
    if not profile:
        return False
    return bool(
        has_module_permission(user, module=ModuleCode.SALES, action=PermissionAction.VIEW)
        or has_module_permission(user, module=ModuleCode.SALES, action=PermissionAction.MANAGE)
    )


def _lead_access(user) -> LeadAccess:
    profile = _profile(user)
    is_superadmin_or_partner = bool(user.is_superuser or (profile and profile.role == RoleCode.PARTNER))
    return LeadAccess(
        salesrep=_my_salesrep(user),
        can_assign=is_superadmin_or_partner,
        can_delete=is_superadmin_or_partner,
        is_superadmin_or_partner=is_superadmin_or_partner,
    )


def _target_salesrep_for_user(user) -> SalesRep | None:
    access = _lead_access(user)
    if access.salesrep:
        return access.salesrep
    if access.is_superadmin_or_partner:
        qs = SalesRep.objects.select_related("user").filter(is_active=True)
        if user.is_superuser:
            return qs.order_by("id").first()
        visible_ids = get_downline_user_ids(user)
        return qs.filter(user_id__in=visible_ids).order_by("id").first()
    return None


def _solar_unit() -> BusinessUnit | None:
    return BusinessUnit.objects.filter(code="solar-home-power").first()


def _base_residential_queryset(user):
    access = _lead_access(user)
    scoped_salesrep = access.salesrep or _target_salesrep_for_user(user)
    if not scoped_salesrep:
        return Lead.objects.none()
    now = timezone.now()
    return (
        Lead.objects.filter(
            sales_rep=scoped_salesrep,
            lead_kind=Lead.LeadKind.RESIDENTIAL,
        )
        .filter(Q(is_accepted=True) | Q(acceptance_deadline__isnull=True) | Q(acceptance_deadline__gte=now))
        .select_related("sales_rep__user", "assigned_by")
        .annotate(
            pending_duplicate_requests=Count(
                "duplicate_review_requests",
                filter=Q(duplicate_review_requests__status=InvoiceDuplicateReviewRequest.Status.PENDING),
            )
        )
        .order_by("-created_at")
    )


def _serialize_lead(lead: Lead) -> dict:
    left = lead.acceptance_time_left()
    if left < 0:
        left_display = "Sin ventana"
    else:
        hours = left // 3600
        minutes = (left % 3600) // 60
        left_display = f"{hours:02d}:{minutes:02d}"

    return {
        "id": lead.id,
        "full_name": lead.customer_name or lead.full_name,
        "phone": lead.customer_phone or lead.phone,
        "email": lead.customer_email or lead.email,
        "message": lead.message,
        "city": lead.customer_city or lead.city,
        "source": lead.lead_source or lead.source,
        "lead_source_name": lead.lead_source or lead.source or "Sin fuente",
        "roof_type": lead.roof_type,
        "owner_name": (lead.owner_name or "").strip() or ("Si" if lead.owns_property == "SI" else "No" if lead.owns_property == "NO" else ""),
        "electricity_bill": float(lead.electricity_bill or 0),
        "system_size_kw": float(lead.system_size or lead.system_size_kw or 0),
        "map_url": f"https://maps.google.com/?q={lead.customer_latitude or lead.latitude},{lead.customer_longitude or lead.longitude}" if (lead.customer_latitude or lead.latitude) and (lead.customer_longitude or lead.longitude) else "",
        "status": lead.status,
        "status_display": lead.get_status_display(),
        "created_at": lead.created_at.strftime("%d-%m-%Y"),
        "create_date": lead.created_at.isoformat(),
        "acceptance_time_left": left_display,
        "assigned_by_name": (lead.assigned_by.get_full_name().strip() or lead.assigned_by.get_username()) if lead.assigned_by else "",
        "pending_duplicate_requests": int(getattr(lead, "pending_duplicate_requests", 0) or 0),
        "is_accepted": bool(lead.is_accepted),
        "acceptance_deadline": lead.acceptance_deadline.isoformat() if lead.acceptance_deadline else "",
    }


def _salesrep_choices_for_user(user):
    access = _lead_access(user)
    if not access.can_assign:
        return []
    qs = SalesRep.objects.select_related("user").filter(is_active=True)
    if not user.is_superuser:
        visible_ids = get_downline_user_ids(user)
        qs = qs.filter(user_id__in=visible_ids)
    return [
        {
            "id": rep.id,
            "label": rep.user.get_full_name().strip() or rep.user.get_username(),
        }
        for rep in qs.order_by("user__first_name", "user__last_name", "user__username")
    ]


def _compute_kpis(rows: list[dict]) -> dict:
    total = len(rows)
    with_phone = sum(1 for row in rows if (row.get("phone") or "").strip())
    with_email = sum(1 for row in rows if (row.get("email") or "").strip())
    contactable = sum(1 for row in rows if (row.get("phone") or "").strip() and (row.get("email") or "").strip())
    contactable_pct = round((contactable / total) * 100, 1) if total else 0.0
    by_status = {}
    for row in rows:
        label = row.get("status_display") or "Sin estado"
        by_status[label] = by_status.get(label, 0) + 1
    return {
        "total": total,
        "with_phone": with_phone,
        "with_email": with_email,
        "contactable_pct": contactable_pct,
        "status_distribution": by_status,
    }


def _render_form(request, *, form: LeadForm, lead: Lead | None = None, title: str):
    return render(
        request,
        "dashboard/leads/_lead_form_modal.html",
        {
            "form": form,
            "lead": lead,
            "title": title,
            "parse_invoice_preview_url": reverse("dashboard:crm_leads_parse_invoice_preview"),
            "duplicate_request_url": reverse("dashboard:crm_duplicate_review_request"),
        },
    )


def _invoice_hash(file_obj) -> str:
    current_pos = None
    if hasattr(file_obj, "tell"):
        try:
            current_pos = file_obj.tell()
        except Exception:
            current_pos = None
    hasher = hashlib.sha256()
    for chunk in file_obj.chunks():
        hasher.update(chunk)
    if hasattr(file_obj, "seek"):
        try:
            file_obj.seek(current_pos if current_pos is not None else 0)
        except Exception:
            pass
    return hasher.hexdigest()


def _normalize_ocr_language(language: str) -> str:
    value = (language or "").strip().lower()
    if value in {"es", "spa", "spanish", "espanol", "español"}:
        return "spa"
    if value in {"en", "eng", "english"}:
        return "eng"
    return "spa+eng"


def _extract_invoice_holder(raw_text: str) -> str:
    if not raw_text:
        return ""
    patterns = [
        r"\n\s*([A-ZÁÉÍÓÚÑ ,.'-]{6,})\s*\n\s*(?:su\s*n[uú]mero\s*de\s*cuenta|n[uú]mero\s*de\s*cuenta|numero\s*de\s*cuenta)\b",
        r"\n\s*([A-ZÁÉÍÓÚÑ ,.'-]{6,})\s*\n\s*(?:villa|urb|calle|direccion|direcci[oó]n)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw_text, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = re.sub(r"\s+", " ", (match.group(1) or "").strip())
        candidate = candidate.strip(" ,.-")
        if len(candidate) >= 6:
            return candidate
    return ""


def _title_case_token(value: str) -> str:
    token = (value or "").strip()
    if not token:
        return ""
    if len(token) == 1 and token.isalpha():
        return token.upper()
    return token[:1].upper() + token[1:].lower()


def _normalize_customer_name(raw_name: str) -> str:
    name = re.sub(r"\s+", " ", (raw_name or "").strip().strip(" ,.-"))
    if not name:
        return ""
    if "," in name:
        left, right = name.split(",", 1)
        first_names = [_title_case_token(x) for x in re.split(r"\s+", right.strip()) if x.strip()]
        last_names = [_title_case_token(x) for x in re.split(r"\s+", left.strip()) if x.strip()]
        ordered = first_names + last_names
        return " ".join([x for x in ordered if x]).strip()
    return " ".join([_title_case_token(x) for x in re.split(r"\s+", name) if x.strip()]).strip()


def _extract_customer_address_block(raw_text: str, invoice_holder: str = "") -> tuple[str, str, str, str]:
    if not raw_text:
        return "", "", "", ""
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw_text.splitlines()]
    holder_norm = re.sub(r"[^A-Z0-9]", "", (invoice_holder or "").upper())
    holder_indexes: list[int] = []
    if holder_norm:
        for idx, line in enumerate(lines):
            line_norm = re.sub(r"[^A-Z0-9]", "", line.upper())
            if line_norm and (line_norm in holder_norm or holder_norm in line_norm):
                holder_indexes.append(idx)
    for holder_idx in holder_indexes:
        scope = lines[holder_idx + 1 : min(len(lines), holder_idx + 12)]
        for i, line in enumerate(scope):
            if not re.search(r"\bPR\b\s*\d{5}", line, flags=re.IGNORECASE):
                continue
            city_match = re.search(r"([A-ZÁÉÍÓÚÑ ]+)\s+PR\s*(\d{5}(?:-\d{4})?)?", line, flags=re.IGNORECASE)
            city = city_match.group(1).strip().title() if city_match else ""
            postal_code = (city_match.group(2) or "").strip() if city_match else ""
            prev1 = scope[i - 1].strip(" ,.-") if i - 1 >= 0 else ""
            prev2 = scope[i - 2].strip(" ,.-") if i - 2 >= 0 else ""
            parts = [x for x in [prev2, prev1] if x]
            address = ", ".join(parts).strip()
            if not address:
                address = re.sub(r"\s+[A-ZÁÉÍÓÚÑ ]+\s+PR\s*\d{5}(?:-\d{4})?$", "", line.strip(" ,.-"), flags=re.IGNORECASE).strip(" ,.-")
            upper_address = address.upper()
            if (
                address
                and "PO BOX" not in upper_address
                and "DIRECCIÓN POSTAL DE LUMA" not in upper_address
                and "DIRECCION POSTAL DE LUMA" not in upper_address
            ):
                return address, city, postal_code, "PR"
    for idx, line in enumerate(lines):
        if not line:
            continue
        if "DIRECCIÓN POSTAL DE LUMA" in line.upper() or "DIRECCION POSTAL DE LUMA" in line.upper():
            continue
        if "PO BOX" in line.upper():
            continue
        if not re.search(r"\bPR\b\s*\d{5}", line, flags=re.IGNORECASE):
            continue
        city_match = re.search(r"([A-ZÁÉÍÓÚÑ ]+)\s+PR\s*(\d{5}(?:-\d{4})?)?", line, flags=re.IGNORECASE)
        city = city_match.group(1).strip().title() if city_match else ""
        postal_code = (city_match.group(2) or "").strip() if city_match else ""
        prev1 = lines[idx - 1].strip(" ,.-") if idx - 1 >= 0 else ""
        prev2 = lines[idx - 2].strip(" ,.-") if idx - 2 >= 0 else ""
        if prev1 and prev2 and not any(ch.isdigit() for ch in prev2 + prev1 + line):
            # skip weak matches without street-like info
            continue
        parts = [x for x in [prev2, prev1] if x]
        address = ", ".join(parts).strip()
        if not address:
            address = re.sub(r"\s+[A-ZÁÉÍÓÚÑ ]+\s+PR\s*\d{5}(?:-\d{4})?$", "", line.strip(" ,.-"), flags=re.IGNORECASE).strip(" ,.-")
        upper_address = address.upper()
        if "PO BOX" in upper_address or "DIRECCIÓN POSTAL DE LUMA" in upper_address or "DIRECCION POSTAL DE LUMA" in upper_address:
            continue
        if len(address) >= 12:
            return address, city, postal_code, "PR"
    return "", "", "", "PR"


def _extract_consumption_history(raw_text: str) -> list[float]:
    if not raw_text:
        return []
    month_line = re.search(
        r"ene-\d{2}\s+feb\s+mar\s+abr\s+may\s+jun\s+jul\s+ago\s+sep\s+oct\s+nov\s+dic\s+ene-\d{2}",
        raw_text,
        flags=re.IGNORECASE,
    )
    if not month_line:
        return []
    context = raw_text[max(0, month_line.start() - 500) : month_line.start()]
    values = [int(x) for x in re.findall(r"\b(\d{2,4})\b", context)]
    values = [v for v in values if 100 <= v <= 1200]
    if len(values) < 12:
        return []
    seq = values[-13:] if len(values) >= 13 else values[-12:]
    if len(seq) == 13:
        # LUMA suele traer ene-xx..dic + ene-(xx+1). Reordenamos para llenar Ene..Dic con 12 datos.
        seq = [seq[-1]] + seq[1:-1]
    return [float(v) for v in seq[:12]]


def _configure_tesseract_cmd() -> bool:
    if not pytesseract:
        return False
    current = getattr(pytesseract.pytesseract, "tesseract_cmd", "") or ""
    if current and os.path.exists(current):
        return True
    from_path = shutil.which("tesseract")
    if from_path:
        pytesseract.pytesseract.tesseract_cmd = from_path
        return True
    candidates = [
        os.environ.get("TESSERACT_CMD", ""),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            return True
    return False


def _ocr_text_from_image_bytes(content: bytes, language: str = "") -> str:
    if not content or not Image or not pytesseract:
        return ""
    if not _configure_tesseract_cmd():
        return ""
    try:
        image = Image.open(io.BytesIO(content))
        text = pytesseract.image_to_string(image, lang=_normalize_ocr_language(language))
        return (text or "").strip()
    except Exception:
        return ""


def _ocr_text_from_pdf_bytes(content: bytes, language: str = "") -> str:
    if not content or not pdfium or not pytesseract:
        return ""
    if not _configure_tesseract_cmd():
        return ""
    try:
        doc = pdfium.PdfDocument(io.BytesIO(content))
    except Exception:
        return ""
    chunks: list[str] = []
    try:
        total_pages = min(len(doc), 3)
        for idx in range(total_pages):
            page = doc[idx]
            try:
                pil_image = page.render(scale=2.0).to_pil()
                txt = pytesseract.image_to_string(pil_image, lang=_normalize_ocr_language(language))
                if txt:
                    chunks.append(txt)
            finally:
                page.close()
    except Exception:
        return ""
    finally:
        try:
            doc.close()
        except Exception:
            pass
    return "\n".join(chunks).strip()


def _normalize_decimal(value: str) -> Decimal | None:
    raw = (value or "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _parse_electricity_invoice(uploaded_pdf, *, lead_id: int | None = None, language: str = "") -> dict:
    filename = (uploaded_pdf.name or "").lower()
    account = re.search(r"account[_-]?(\d+)", filename)
    meter = re.search(r"meter[_-]?(\d+)", filename)
    location = re.search(r"location[_-]?(\d+)", filename)
    inv_hash = _invoice_hash(uploaded_pdf)
    raw_text = ""
    if hasattr(uploaded_pdf, "read"):
        try:
            if hasattr(uploaded_pdf, "seek"):
                uploaded_pdf.seek(0)
            content = uploaded_pdf.read()
            if hasattr(uploaded_pdf, "seek"):
                uploaded_pdf.seek(0)
            if isinstance(content, bytes):
                if PdfReader is not None and content.lstrip().startswith(b"%PDF"):
                    try:
                        reader = PdfReader(io.BytesIO(content))
                        pages_text = []
                        for page in reader.pages:
                            pages_text.append(page.extract_text() or "")
                        raw_text = "\n".join(pages_text).strip()
                    except Exception:
                        raw_text = ""
                if len(raw_text.strip()) < 40:
                    raw_text = content.decode("utf-8", errors="ignore")
                if len(raw_text.strip()) < 40:
                    raw_text = content.decode("latin-1", errors="ignore")
                if len(raw_text.strip()) < 40 and content.lstrip().startswith(b"%PDF"):
                    raw_text = _ocr_text_from_pdf_bytes(content, language=language)
            else:
                raw_text = str(content)
        except Exception:
            raw_text = ""

    def _find(patterns: list[str]) -> str:
        for pattern in patterns:
            match = re.search(pattern, raw_text, flags=re.IGNORECASE)
            if match:
                return (match.group(1) or "").strip()
        return ""

    account_from_text = _find(
        [
            r"(?:su\s*n[uú]mero\s*de\s*cuenta|numero\s*de\s*cuenta|n[uú]mero\s*de\s*cuenta)\s*[:#-]?\s*([0-9]{6,})",
            r"(?:account(?:\s*number)?|cuenta)\s*[:#-]?\s*([A-Z0-9-]{4,})",
        ]
    )
    meter_from_text = _find(
        [
            r"(?:numero\s*de\s*contador|n[uú]mero\s*de\s*contador)\s*[:#-]?\s*([0-9]{5,})",
            r"(?:numero\s*de\s*contador|n[uú]mero\s*de\s*contador)\s*[:#-]?\s*([A-Z-]*\d[A-Z0-9-]{3,})",
            r"(?:meter(?:\s*number)?)\s*[:#-]?\s*([A-Z0-9-]{4,})",
        ]
    )
    if not meter_from_text:
        meter_block = re.search(
            r"(?:numero\s*de\s*contador|n[uú]mero\s*de\s*contador)([\s\S]{0,220})",
            raw_text,
            flags=re.IGNORECASE,
        )
        if meter_block:
            meter_candidate = re.search(r"\b([0-9]{6,})\b", meter_block.group(1))
            if meter_candidate:
                meter_from_text = meter_candidate.group(1)
    location_from_text = _find(
        [
            r"(?:id\s*localidad|location(?:\s*id)?|service\s*point|localidad|premise)\s*[:#-]?\s*([A-Z0-9-]{4,})",
        ]
    )
    bill_from_text = _find(
        [
            r"(?:cantidad\s*total\s*adeudada|total\s*adeudada|monto\s*total|importe\s*total|balance\s*due|total\s*amount)\s*[:\s$-]*\$?\s*([0-9]{1,6}(?:[.,][0-9]{1,2})?)",
            r"(?:cargo\s*por\s*cliente)\s*[:\s$-]*\$?\s*([0-9]{1,6}(?:[.,][0-9]{1,2})?)",
        ]
    )
    avg_kwh_from_text = _find(
        [
            r"(?:consumo\s*promedio(?:\s*kwh)?|average(?:\s*monthly)?\s*kwh|kwh\s*promedio)\s*[:#-]?\s*([0-9]{2,6}(?:[.,][0-9]{1,2})?)",
            r"(?:consumo\s*de\s*kwh)\s*[:#-]?\s*([0-9]{2,6}(?:[.,][0-9]{1,2})?)",
            r"(?:consumo)\s*(?:kwh)?\s*[:#-]?\s*([0-9]{2,6}(?:[.,][0-9]{1,2})?)",
        ]
    )
    invoice_holder = _extract_invoice_holder(raw_text)
    normalized_name = _normalize_customer_name(invoice_holder)
    customer_address, customer_city, customer_postal_code, customer_country = _extract_customer_address_block(raw_text, invoice_holder=invoice_holder)
    monthly_history = _extract_consumption_history(raw_text)
    if monthly_history:
        avg_kwh_from_text = f"{(sum(monthly_history) / len(monthly_history)):.2f}"
    return {
        "invoice_name": invoice_holder or uploaded_pdf.name,
        "customer_name": normalized_name or invoice_holder or "",
        "customer_address": customer_address,
        "customer_city": customer_city,
        "customer_postal_code": customer_postal_code,
        "customer_country": customer_country,
        "invoice_hash": inv_hash,
        "account_number": account_from_text or (account.group(1) if account else ""),
        "meter_number": meter_from_text or (meter.group(1) if meter else ""),
        "location_id": location_from_text or (location.group(1) if location else ""),
        "electricity_bill": bill_from_text.replace(",", "."),
        "consumo_promedio_kwh": avg_kwh_from_text.replace(",", "."),
        "id_consumo_historial": json.dumps(monthly_history) if monthly_history else "",
        "lead_id": lead_id,
    }


def _parse_invoice_from_uploaded_images(images: list, language: str = "") -> dict:
    raw_text_parts: list[str] = []
    for image in images:
        if hasattr(image, "seek"):
            try:
                image.seek(0)
            except Exception:
                pass
        try:
            raw_text_parts.append((image.name or "").lower())
        except Exception:
            pass
        try:
            blob = image.read()
            if hasattr(image, "seek"):
                image.seek(0)
            if isinstance(blob, bytes):
                raw_text_parts.append(blob.decode("utf-8", errors="ignore"))
                raw_text_parts.append(blob.decode("latin-1", errors="ignore"))
                ocr_text = _ocr_text_from_image_bytes(blob, language=language)
                if ocr_text:
                    raw_text_parts.append(ocr_text)
            else:
                raw_text_parts.append(str(blob))
        except Exception:
            continue
    raw_text = "\n".join(raw_text_parts)

    def _find(patterns: list[str]) -> str:
        for pattern in patterns:
            m = re.search(pattern, raw_text, flags=re.IGNORECASE)
            if m:
                return (m.group(1) or "").strip()
        return ""

    account = _find(
        [
            r"(?:su\s*n[uú]mero\s*de\s*cuenta|numero\s*de\s*cuenta|n[uú]mero\s*de\s*cuenta)\s*[:#-]?\s*([0-9]{6,})",
            r"(?:cuenta|account(?:\s*number)?)\s*[:#-]?\s*([A-Z0-9-]{4,})",
        ]
    )
    meter = _find(
        [
            r"(?:numero\s*de\s*contador|n[uú]mero\s*de\s*contador)\s*[:#-]?\s*([0-9]{5,})",
            r"(?:numero\s*de\s*contador|n[uú]mero\s*de\s*contador)\s*[:#-]?\s*([A-Z-]*\d[A-Z0-9-]{3,})",
            r"(?:meter(?:\s*number)?)\s*[:#-]?\s*([A-Z0-9-]{4,})",
        ]
    )
    if not meter:
        meter_block = re.search(
            r"(?:numero\s*de\s*contador|n[uú]mero\s*de\s*contador)([\s\S]{0,220})",
            raw_text,
            flags=re.IGNORECASE,
        )
        if meter_block:
            meter_candidate = re.search(r"\b([0-9]{6,})\b", meter_block.group(1))
            if meter_candidate:
                meter = meter_candidate.group(1)
    location = _find([r"(?:id\s*localidad|location(?:\s*id)?|localidad|premise)\s*[:#-]?\s*([A-Z0-9-]{4,})"])
    bill = _find(
        [
            r"(?:cantidad\s*total\s*adeudada|total\s*adeudada|monto\s*total|importe\s*total|total)\s*[:\s$-]*\$?\s*([0-9]{1,6}(?:[.,][0-9]{1,2})?)",
        ]
    )
    avg = _find(
        [
            r"(?:consumo\s*promedio(?:\s*kwh)?|average\s*kwh)\s*[:#-]?\s*([0-9]{2,6}(?:[.,][0-9]{1,2})?)",
            r"(?:consumo\s*de\s*kwh)\s*[:#-]?\s*([0-9]{2,6}(?:[.,][0-9]{1,2})?)",
        ]
    )
    invoice_holder = _extract_invoice_holder(raw_text)
    normalized_name = _normalize_customer_name(invoice_holder)
    customer_address, customer_city, customer_postal_code, customer_country = _extract_customer_address_block(raw_text, invoice_holder=invoice_holder)
    monthly_history = _extract_consumption_history(raw_text)
    if monthly_history:
        avg = f"{(sum(monthly_history) / len(monthly_history)):.2f}"

    return {
        "invoice_name": invoice_holder or "Factura por imagenes",
        "customer_name": normalized_name or invoice_holder or "",
        "customer_address": customer_address,
        "customer_city": customer_city,
        "customer_postal_code": customer_postal_code,
        "customer_country": customer_country,
        "invoice_hash": "",
        "account_number": account,
        "meter_number": meter,
        "location_id": location,
        "electricity_bill": bill.replace(",", "."),
        "consumo_promedio_kwh": avg.replace(",", "."),
        "id_consumo_historial": json.dumps(monthly_history) if monthly_history else "",
        "electricity_invoice_language": language or "",
    }


def _is_ajax(request) -> bool:
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _parse_money_to_decimal(value: str | Decimal | None) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    raw = str(value).strip().replace("$", "").replace(" ", "")
    if not raw:
        return None
    if "," in raw and "." in raw:
        raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if amount < 0:
        return None
    return amount


def _public_lead_generation_base(request) -> str:
    configured = (getattr(settings, "LEAD_GENERATION_BASE_URL", "") or "").strip()
    if configured:
        return configured
    return request.build_absolute_uri(reverse("dashboard:crm_lead_generation_public"))


def _build_lead_generation_share_link(request, salesrep: SalesRep | None) -> str:
    base_url = _public_lead_generation_base(request)
    if not salesrep:
        return base_url
    params = {"salesrep_id": salesrep.id}
    user_email = (getattr(request.user, "email", "") or "").strip()
    if user_email:
        params["email"] = user_email
    qs = urlencode(params)
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{qs}"


def _lead_generation_salesrep_for_user(user) -> SalesRep | None:
    own = _my_salesrep(user)
    if own:
        return own
    return _target_salesrep_for_user(user)


@login_required
@require_http_methods(["GET"])
def crm_lead_generation_private(request):
    if not _can_access_customer_management_section(request.user):
        return JsonResponse({"detail": "No autorizado"}, status=403)

    salesrep = _lead_generation_salesrep_for_user(request.user)
    share_link = _build_lead_generation_share_link(request, salesrep)
    salesrep_name = ""
    if salesrep:
        salesrep_name = salesrep.user.get_full_name().strip() or salesrep.user.get_username()
    context = {
        "title": "Lead Generation",
        "share_link": share_link,
        "public_base_url": _public_lead_generation_base(request),
        "has_salesrep_profile": bool(salesrep),
        "salesrep_id": salesrep.id if salesrep else None,
        "salesrep_name": salesrep_name,
        "email_associated": (request.user.email or "").strip(),
        "qr_url": reverse("dashboard:crm_leads_qrcode"),
        "qr_download_url": f"{reverse('dashboard:crm_leads_qrcode')}?download=1",
        "qr_marketing_download_url": f"{reverse('dashboard:crm_leads_qrcode')}?download=1&style=marketing",
    }
    return render(request, "dashboard/leads/lead_generation_private.html", context)


@login_required
@require_http_methods(["GET"])
def crm_leads_qrcode(request):
    if not _can_access_customer_management_section(request.user):
        return JsonResponse({"detail": "No autorizado"}, status=403)
    salesrep = _lead_generation_salesrep_for_user(request.user)
    if not salesrep:
        return JsonResponse({"success": False, "error": "No tienes perfil de asociado."}, status=400)
    link = _build_lead_generation_share_link(request, salesrep)
    qr_lib = qrcode
    if qr_lib is None:
        try:
            import qrcode as qr_lib  # lazy import in case dependency was installed after process start
        except Exception:
            qr_lib = None
    if qr_lib is not None:
        qr = qr_lib.QRCode(
            version=1,
            error_correction=qr_lib.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(link)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")
        style = str(request.GET.get("style", "")).strip().lower()
        if style == "marketing" and Image is not None and ImageDraw is not None and ImageOps is not None:
            qr_img = image.convert("RGB")
            qr_img = ImageOps.contain(qr_img, (320, 320))
            canvas = Image.new("RGB", (1080, 1080), "#f4f8ff")
            draw = ImageDraw.Draw(canvas)
            font_h1 = _load_marketing_font(48, bold=True)
            font_h2 = _load_marketing_font(32, bold=True)
            font_h3 = _load_marketing_font(26, bold=True)
            font_body = _load_marketing_font(24, bold=False)
            font_small = _load_marketing_font(20, bold=False)
            brand_name = "One-Group"
            salesrep_name = salesrep.user.get_full_name().strip() or salesrep.user.get_username()
            associated_email = (request.user.email or "").strip()
            generated_at = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M")

            # Header band
            draw.rectangle((0, 0, 1080, 170), fill="#123a6f")
            draw.rectangle((0, 145, 1080, 170), fill="#1a6fb2")
            draw.text((62, 48), f"{brand_name}  |  QR de Mercadeo", fill="#ffffff", font=font_h3)

            # Main card
            draw.rounded_rectangle((48, 210, 1032, 930), radius=34, fill="#ffffff", outline="#d7e3f4", width=2)
            draw.text((90, 254), "Escanea para solicitar asesoria solar", fill="#0f172a", font=font_h2)
            draw.text((90, 302), "Lead Generation  •  Campana digital", fill="#4b5563", font=font_body)

            # QR frame
            draw.rounded_rectangle((88, 360, 462, 734), radius=24, fill="#f8fbff", outline="#c9d9ee", width=2)
            canvas.paste(qr_img, (115, 387))
            draw.text((150, 748), "Escanea aqui", fill="#1e3a8a", font=font_h3)

            # Commercial info block
            draw.rounded_rectangle((520, 360, 980, 734), radius=24, fill="#f8fbff", outline="#c9d9ee", width=2)
            draw.text((552, 396), f"Asociado: {salesrep_name}", fill="#0f172a", font=font_body)
            draw.text((552, 438), f"Codigo asesor: {salesrep.id}", fill="#1f2937", font=font_body)
            if associated_email:
                draw.text((552, 480), f"Email: {associated_email}", fill="#334155", font=font_small)
            draw.text((552, 548), "Usalo en redes sociales,", fill="#1e293b", font=font_small)
            draw.text((552, 580), "flyers, WhatsApp o material impreso.", fill="#1e293b", font=font_small)
            draw.text((552, 644), "CTA recomendado:", fill="#1d4ed8", font=font_small)
            draw.text((552, 678), '"Solicita tu asesoria solar hoy"', fill="#0f172a", font=font_small)

            # Footer line
            draw.line((88, 970, 992, 970), fill="#d4deec", width=2)
            draw.text((90, 988), f"Generado: {generated_at}", fill="#64748b", font=font_small)
            draw.text((730, 988), "one-group lead system", fill="#64748b", font=font_small)
            image = canvas
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        response = HttpResponse(buffer.getvalue(), content_type="image/png")
        if str(request.GET.get("download", "")).strip().lower() in {"1", "true", "yes"}:
            style = str(request.GET.get("style", "")).strip().lower()
            rep_slug = _safe_slug(salesrep.user.get_full_name().strip() or salesrep.user.get_username())
            stamp = timezone.localtime(timezone.now()).strftime("%Y%m%d")
            if style == "marketing":
                filename = f"onegroup-qr-marketing-{rep_slug}-{salesrep.id}-{stamp}.png"
            else:
                filename = f"onegroup-qr-lead-generation-{rep_slug}-{salesrep.id}-{stamp}.png"
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    return JsonResponse({"success": False, "error": "No se pudo generar QR en este entorno."}, status=500)


@require_http_methods(["GET", "POST"])
def crm_lead_generation_public(request):
    associated_email = (request.GET.get("email") or request.POST.get("email") or "").strip()
    salesrep_id_raw = (
        request.GET.get("salesrep_id")
        if request.method == "GET"
        else request.POST.get("salesrep_id") or request.GET.get("salesrep_id")
    )
    salesrep_id = int(salesrep_id_raw or 0) if str(salesrep_id_raw or "").isdigit() else 0
    salesrep = SalesRep.objects.select_related("user").filter(pk=salesrep_id, is_active=True).first()
    if not salesrep:
        status = 404 if salesrep_id else 400
        return render(
            request,
            "dashboard/leads/lead_generation_public.html",
            {
                "title": "Lead Generation Publico",
                "form": LeadGenerationPublicForm(),
                "salesrep_id": salesrep_id_raw or "",
                "associated_email": associated_email,
                "salesrep": None,
                "salesrep_error": "No se encontro un perfil de asociado valido.",
            },
            status=status,
        )

    if request.method == "GET":
        form = LeadGenerationPublicForm()
        return render(
            request,
            "dashboard/leads/lead_generation_public.html",
            {
                "title": "Lead Generation Publico",
                "form": form,
                "salesrep_id": salesrep.id,
                "associated_email": associated_email,
                "salesrep": salesrep,
            },
        )

    form = LeadGenerationPublicForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "dashboard/leads/lead_generation_public.html",
            {
                "title": "Lead Generation Publico",
                "form": form,
                "salesrep_id": salesrep.id,
                "associated_email": associated_email,
                "salesrep": salesrep,
            },
            status=400,
        )

    try:
        lead = form.save(commit=False)
        solar_unit = _solar_unit()
        if not solar_unit:
            raise ValueError("Unidad solar no disponible.")
        lead_source, _ = LeadSource.objects.get_or_create(name="Lead Generation", defaults={"is_active": True})
        lead.business_unit = solar_unit
        lead.sales_rep = salesrep
        lead.lead_kind = Lead.LeadKind.RESIDENTIAL
        lead.lead_source = lead_source.name
        lead.source = lead_source.name
        lead.full_name = lead.customer_name
        lead.phone = lead.customer_phone
        lead.email = lead.customer_email or ""
        lead.city = lead.customer_city
        lead.address = lead.customer_address or ""
        lead.electricity_bill = _parse_money_to_decimal(form.cleaned_data.get("electricity_bill"))
        lead_status = (lead.status or "").strip()
        lead.status = Lead.Status.NEW if lead_status in {"", Lead.Status.NUEVO} else lead_status
        # Extension point: OCR can be added here if public upload is enabled in future.
        lead.save()
    except Exception:
        logger.exception("Error guardando lead desde formulario publico", extra={"salesrep_id": salesrep.id})
        form.add_error(None, "Ocurrio un error guardando tu solicitud. Intenta nuevamente.")
        return render(
            request,
            "dashboard/leads/lead_generation_public.html",
            {
                "title": "Lead Generation Publico",
                "form": form,
                "salesrep_id": salesrep.id,
                "associated_email": associated_email,
                "salesrep": salesrep,
            },
            status=500,
        )

    return render(
        request,
        "dashboard/leads/lead_generation_thankyou.html",
        {
            "title": "Gracias por tu interes",
            "salesrep": salesrep,
        },
    )


def _duplicate_exists(*, lead: Lead, actor_salesrep: SalesRep | None) -> tuple[bool, dict]:
    now = timezone.now()
    invoice_hash = (lead.electricity_invoice_hash or lead.invoice_hash or "").strip()
    hash_match = Lead.objects.filter(Q(invoice_hash=invoice_hash) | Q(electricity_invoice_hash=invoice_hash)).exclude(pk=lead.pk) if invoice_hash else Lead.objects.none()
    combo_match = Lead.objects.filter(
        account_number=lead.account_number,
        meter_number=lead.meter_number,
        location_id=lead.location_id,
    ).exclude(pk=lead.pk)
    has_hash_dup = hash_match.exists()
    has_combo_dup = bool(lead.account_number and lead.meter_number and lead.location_id and combo_match.exists())
    if not has_hash_dup and not has_combo_dup:
        return False, {}

    if actor_salesrep:
        override_qs = InvoiceDuplicateOverride.objects.filter(requester=actor_salesrep, expires_at__gte=now, used_at__isnull=True)
        if invoice_hash and override_qs.filter(invoice_hash=invoice_hash).exists():
            return False, {}
        if lead.account_number and lead.meter_number and lead.location_id:
            if override_qs.filter(
                account_number=lead.account_number,
                meter_number=lead.meter_number,
                location_id=lead.location_id,
            ).exists():
                return False, {}

    dup = hash_match.first() or combo_match.first()
    error_code = "duplicate_invoice" if has_hash_dup else "duplicate_service_keys"
    return True, {
        "duplicate_lead_id": dup.id if dup else None,
        "duplicate_by": "hash" if has_hash_dup else "cuenta+contador+localidad",
        "error_code": error_code,
    }


def _is_partner_or_superadmin(user) -> bool:
    profile = _profile(user)
    return bool(user.is_superuser or (profile and profile.role == RoleCode.PARTNER))


def _lead_for_owner_or_404(user, lead_id: int) -> Lead:
    access = _lead_access(user)
    scoped_salesrep = access.salesrep or _target_salesrep_for_user(user)
    if not scoped_salesrep:
        raise Http404
    return get_object_or_404(Lead, pk=lead_id, sales_rep=scoped_salesrep, lead_kind=Lead.LeadKind.RESIDENTIAL)


@login_required
@require_http_methods(["GET"])
def crm_leads_list_page(request):
    if not _can_access_customer_management_section(request.user):
        return JsonResponse({"detail": "No autorizado"}, status=403)

    access = _lead_access(request.user)
    rows = [_serialize_lead(item) for item in _base_residential_queryset(request.user)]
    context = {
        "title": "CRM Leads Residencial",
        "api_url": reverse("dashboard:crm_leads_api"),
        "can_assign_leads_ui": access.can_assign,
        "is_superadmin_or_partner": access.is_superadmin_or_partner,
        "my_profile_id": access.salesrep.id if access.salesrep else None,
        "salesreps_choices_json": json.dumps(_salesrep_choices_for_user(request.user)),
        "kpis": _compute_kpis(rows),
        "initial_rows": rows,
    }
    return render(request, "dashboard/leads/leads_list.html", context)


@login_required
@require_http_methods(["GET"])
def crm_leads_api(request):
    if not _can_access_customer_management_section(request.user):
        return JsonResponse({"detail": "No autorizado"}, status=403)

    lead_kind = (request.GET.get("lead_kind") or Lead.LeadKind.RESIDENTIAL).strip() or Lead.LeadKind.RESIDENTIAL
    status_filter = (request.GET.get("status") or "").strip()
    city_filter = (request.GET.get("city") or "").strip()
    source_filter = (request.GET.get("source") or "").strip()
    q = (request.GET.get("search") or request.GET.get("search[value]") or "").strip().lower()

    qs = _base_residential_queryset(request.user).filter(lead_kind=lead_kind)
    if status_filter:
        qs = qs.filter(status=status_filter)
    if city_filter:
        qs = qs.filter(Q(city__iexact=city_filter) | Q(customer_city__iexact=city_filter))
    if source_filter:
        qs = qs.filter(Q(source__iexact=source_filter) | Q(lead_source__iexact=source_filter))
    if q:
        qs = qs.filter(
            Q(full_name__icontains=q)
            | Q(customer_name__icontains=q)
            | Q(phone__icontains=q)
            | Q(customer_phone__icontains=q)
            | Q(email__icontains=q)
            | Q(customer_email__icontains=q)
            | Q(city__icontains=q)
            | Q(customer_city__icontains=q)
            | Q(source__icontains=q)
            | Q(lead_source__icontains=q)
        )

    data = [_serialize_lead(item) for item in qs.order_by("-created_at")]
    return JsonResponse({"data": data, "recordsTotal": len(data), "recordsFiltered": len(data), "kpis": _compute_kpis(data)})


@login_required
@require_http_methods(["GET", "POST"])
def crm_lead_create_modal(request):
    access = _lead_access(request.user)
    target_salesrep = access.salesrep or _target_salesrep_for_user(request.user)
    if not target_salesrep:
        return JsonResponse({"success": False, "message": "No tienes perfil comercial."}, status=403)

    if request.method == "GET":
        return _render_form(request, form=LeadForm(), title="Nuevo Lead")

    form = LeadForm(request.POST, request.FILES)
    if not form.is_valid():
        if _is_ajax(request):
            return JsonResponse({"success": False, "errors": form.errors, "html": _render_form(request, form=form, title="Crear lead").content.decode("utf-8")}, status=400)
        messages.error(request, "Revisa los campos del formulario.")
        return _render_form(request, form=form, title="Crear lead")

    lead = form.save(commit=False)
    solar_unit = _solar_unit()
    if not solar_unit:
        return JsonResponse({"success": False, "message": "Unidad solar no disponible."}, status=400)

    lead.business_unit = solar_unit
    lead.sales_rep = target_salesrep
    lead.lead_kind = Lead.LeadKind.RESIDENTIAL
    lead.is_accepted = True
    lead.full_name = lead.customer_name or lead.full_name
    lead.phone = lead.customer_phone or lead.phone
    lead.email = lead.customer_email or lead.email
    lead.city = lead.customer_city or lead.city
    lead.address = lead.customer_address or lead.address
    lead.source = lead.lead_source or lead.source
    lead.latitude = lead.customer_latitude or lead.latitude
    lead.longitude = lead.customer_longitude or lead.longitude
    lead.monthly_consumption_history = lead.id_consumo_historial or lead.monthly_consumption_history
    if lead.system_size is not None:
        lead.system_size_kw = lead.system_size

    uploaded_pdf = request.FILES.get("electricity_invoice_pdf")
    image_inputs = [
        request.FILES.get("electricity_invoice_page1_img"),
        request.FILES.get("electricity_invoice_page2_img"),
        request.FILES.get("electricity_invoice_page3_img"),
        request.FILES.get("electricity_invoice_page4_img"),
    ]
    image_inputs = [img for img in image_inputs if img]
    parsed = {}
    if uploaded_pdf:
        parsed = _parse_electricity_invoice(
            uploaded_pdf,
            lead_id=None,
            language=(request.POST.get("electricity_invoice_language") or ""),
        )
        lead.invoice_pdf = uploaded_pdf
        lead.electricity_invoice_pdf = uploaded_pdf
    elif image_inputs:
        parsed = _parse_invoice_from_uploaded_images(image_inputs, language=(request.POST.get("electricity_invoice_language") or ""))

    if parsed:
        lead.invoice_name = parsed.get("invoice_name") or lead.invoice_name
        lead.invoice_hash = parsed.get("invoice_hash") or lead.invoice_hash
        lead.electricity_invoice_hash = parsed.get("invoice_hash") or lead.electricity_invoice_hash
        if parsed.get("account_number") and not lead.account_number:
            lead.account_number = parsed["account_number"]
        if parsed.get("meter_number") and not lead.meter_number:
            lead.meter_number = parsed["meter_number"]
        if parsed.get("location_id") and not lead.location_id:
            lead.location_id = parsed["location_id"]
        if parsed.get("electricity_bill") and not lead.electricity_bill:
            lead.electricity_bill = _normalize_decimal(parsed["electricity_bill"])
        if parsed.get("consumo_promedio_kwh") and not lead.consumo_promedio_kwh:
            lead.consumo_promedio_kwh = _normalize_decimal(parsed["consumo_promedio_kwh"])

    if not lead.system_size and lead.consumo_promedio_kwh and lead.hsp and lead.eff and lead.offset:
        kwh_mensual = Decimal(lead.consumo_promedio_kwh)
        system_size = ((kwh_mensual / Decimal("30")) / (Decimal(lead.hsp) * Decimal(lead.eff))) * Decimal(lead.offset)
        lead.system_size = system_size.quantize(Decimal("0.001"))
        lead.system_size_kw = lead.system_size

    is_dup, payload = _duplicate_exists(lead=lead, actor_salesrep=target_salesrep)
    if is_dup:
        if _is_ajax(request):
            return JsonResponse(
                {
                    "success": False,
                    "code": payload.get("error_code"),
                    "message": "Se detecto posible duplicado. Solicita revision al Partner.",
                    "errors": {"__all__": ["Se detecto posible duplicado."]},
                    "duplicate": payload,
                    "can_request_review": True,
                },
                status=409,
            )
        messages.error(request, "Se detecto posible duplicado.")
        return redirect("dashboard:crm_leads_list")

    lead.save()

    override = InvoiceDuplicateOverride.objects.filter(
        requester=target_salesrep,
        expires_at__gte=timezone.now(),
    ).filter(
        Q(invoice_hash=lead.invoice_hash)
        | Q(invoice_hash=lead.electricity_invoice_hash)
        | Q(account_number=lead.account_number, meter_number=lead.meter_number, location_id=lead.location_id)
    ).first()
    if override:
        # consume override once used by a successful save.
        override.used_at = timezone.now()
        override.used_on_lead = lead
        override.save(update_fields=["used_at", "used_on_lead"])

    if _is_ajax(request):
        return JsonResponse({"success": True, "message": "Lead creado correctamente.", "id": lead.id})
    messages.success(request, "Lead creado correctamente.")
    return redirect("dashboard:crm_leads_list")


@login_required
@require_http_methods(["GET", "POST"])
def crm_lead_fill_table_modal(request):
    target_salesrep = _target_salesrep_for_user(request.user)
    if not target_salesrep:
        return JsonResponse({"success": False, "message": "No tienes perfil comercial."}, status=403)

    if request.method == "GET":
        return render(request, "dashboard/leads/_lead_fill_table_modal.html")

    try:
        count = max(1, min(int(request.POST.get("count", "5")), 50))
    except ValueError:
        count = 5

    city = (request.POST.get("city") or "San Juan").strip()[:80]
    source = (request.POST.get("source") or "Carga modal").strip()[:80]
    solar_unit = _solar_unit()
    if not solar_unit:
        return JsonResponse({"success": False, "message": "Unidad solar no disponible."}, status=400)

    batch = []
    for idx in range(count):
        suffix = random.randint(1000, 9999)
        name = f"Cliente Demo {suffix}"
        batch.append(
            Lead(
                business_unit=solar_unit,
                sales_rep=target_salesrep,
                lead_kind=Lead.LeadKind.RESIDENTIAL,
                status=Lead.Status.NEW,
                is_accepted=True,
                customer_name=name,
                full_name=name,
                customer_phone=f"(787)555-{suffix:04d}"[:30],
                phone=f"(787)555-{suffix:04d}"[:30],
                customer_city=city,
                city=city,
                lead_source=source,
                source=source,
                customer_email=f"demo{suffix}@example.com",
                email=f"demo{suffix}@example.com",
            )
        )
    Lead.objects.bulk_create(batch)
    return JsonResponse({"success": True, "message": f"Se crearon {count} clientes demo."})


@login_required
@require_http_methods(["GET", "POST"])
def crm_lead_update_modal(request, lead_id: int):
    lead = _lead_for_owner_or_404(request.user, lead_id)

    if request.method == "GET":
        return _render_form(request, form=LeadForm(instance=lead), lead=lead, title="Editar lead")

    form = LeadForm(request.POST, request.FILES, instance=lead)
    if not form.is_valid():
        return JsonResponse(
            {
                "success": False,
                "errors": form.errors,
                "html": _render_form(request, form=form, lead=lead, title="Editar lead").content.decode("utf-8"),
            },
            status=400,
        )

    lead = form.save(commit=False)
    lead.sales_rep = _lead_access(request.user).salesrep or _target_salesrep_for_user(request.user)
    lead.lead_kind = Lead.LeadKind.RESIDENTIAL
    # Keep table/search fields in sync with modal fields.
    lead.full_name = lead.customer_name or lead.full_name
    lead.phone = lead.customer_phone or lead.phone
    lead.email = lead.customer_email or lead.email
    lead.city = lead.customer_city or lead.city
    lead.address = lead.customer_address or lead.address
    lead.source = lead.lead_source or lead.source
    lead.latitude = lead.customer_latitude or lead.latitude
    lead.longitude = lead.customer_longitude or lead.longitude
    lead.monthly_consumption_history = lead.id_consumo_historial or lead.monthly_consumption_history
    if lead.system_size is not None:
        lead.system_size_kw = lead.system_size
    uploaded_pdf = request.FILES.get("electricity_invoice_pdf")
    image_inputs = [
        request.FILES.get("electricity_invoice_page1_img"),
        request.FILES.get("electricity_invoice_page2_img"),
        request.FILES.get("electricity_invoice_page3_img"),
        request.FILES.get("electricity_invoice_page4_img"),
    ]
    image_inputs = [img for img in image_inputs if img]
    parsed = {}
    if uploaded_pdf:
        parsed = _parse_electricity_invoice(
            uploaded_pdf,
            lead_id=lead.id,
            language=(request.POST.get("electricity_invoice_language") or ""),
        )
        lead.invoice_pdf = uploaded_pdf
        lead.electricity_invoice_pdf = uploaded_pdf
    elif image_inputs:
        parsed = _parse_invoice_from_uploaded_images(image_inputs, language=(request.POST.get("electricity_invoice_language") or ""))
    if parsed:
        if parsed.get("invoice_hash"):
            lead.invoice_hash = parsed["invoice_hash"]
            lead.electricity_invoice_hash = parsed["invoice_hash"]
        for key in ("account_number", "meter_number", "location_id", "invoice_name"):
            if parsed.get(key):
                setattr(lead, key, parsed[key])
        if parsed.get("electricity_bill"):
            lead.electricity_bill = _normalize_decimal(parsed["electricity_bill"]) or lead.electricity_bill
        if parsed.get("consumo_promedio_kwh"):
            lead.consumo_promedio_kwh = _normalize_decimal(parsed["consumo_promedio_kwh"]) or lead.consumo_promedio_kwh

    is_dup, payload = _duplicate_exists(lead=lead, actor_salesrep=_lead_access(request.user).salesrep)
    if is_dup:
        return JsonResponse(
            {
                "success": False,
                "message": "Se detecto posible duplicado. Solicita revision al Partner.",
                "duplicate": payload,
                "can_request_review": True,
            },
            status=409,
        )

    lead.save()
    return JsonResponse({"success": True, "message": "Lead actualizado."})


@login_required
@require_http_methods(["GET"])
def crm_lead_detail(request, lead_id: int):
    lead = _lead_for_owner_or_404(request.user, lead_id)
    LeadActivityLog.objects.create(lead=lead, actor=request.user, activity_type=LeadActivityLog.ActivityType.VIEW)
    return render(request, "dashboard/leads/_lead_detail_modal.html", {"lead": lead, "notes": lead.notes.all()[:20]})


@login_required
@require_http_methods(["GET", "POST"])
def crm_lead_delete_modal(request, lead_id: int):
    lead = _lead_for_owner_or_404(request.user, lead_id)
    if not _lead_access(request.user).can_delete:
        return JsonResponse({"success": False, "message": "No autorizado."}, status=403)

    if request.method == "GET":
        return render(request, "dashboard/leads/_lead_delete_modal.html", {"lead": lead})

    lead.delete()
    return JsonResponse({"success": True, "message": "Lead eliminado."})


@login_required
@require_http_methods(["POST"])
def crm_lead_note_create(request, lead_id: int):
    lead = _lead_for_owner_or_404(request.user, lead_id)
    form = LeadNoteForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"success": False, "errors": form.errors}, status=400)

    note = form.save(commit=False)
    note.lead = lead
    note.author = request.user
    note.save()
    return JsonResponse({"success": True, "message": "Nota creada.", "note": {"id": note.id, "body": note.body}})


@login_required
@require_http_methods(["POST"])
def crm_leads_log_activity(request):
    lead_id = request.POST.get("lead_id")
    activity_type = (request.POST.get("activity_type") or "").upper().strip()
    payload_raw = request.POST.get("payload") or "{}"
    lead = _lead_for_owner_or_404(request.user, int(lead_id))
    try:
        payload = json.loads(payload_raw)
    except Exception:
        payload = {}
    if activity_type not in {choice for choice, _ in LeadActivityLog.ActivityType.choices}:
        return JsonResponse({"success": False, "message": "Tipo de actividad invalido."}, status=400)
    LeadActivityLog.objects.create(lead=lead, actor=request.user, activity_type=activity_type, payload=payload)
    return JsonResponse({"success": True})


@login_required
@require_http_methods(["POST"])
def crm_leads_parse_invoice_preview(request):
    if not _can_access_customer_management_section(request.user):
        return JsonResponse({"success": False, "error": "No autorizado."}, status=403)
    file_obj = request.FILES.get("electricity_invoice_pdf") or request.FILES.get("invoice_pdf")
    img1 = request.FILES.get("electricity_invoice_page1_img")
    img2 = request.FILES.get("electricity_invoice_page2_img")
    img3 = request.FILES.get("electricity_invoice_page3_img")
    img4 = request.FILES.get("electricity_invoice_page4_img")
    images = [img for img in [img1, img2, img3, img4] if img]
    if not file_obj and not images:
        return JsonResponse({"success": False, "error": "Debes subir PDF o imagenes de la factura."}, status=400)

    lead_id = int(request.POST.get("lead_id") or 0) or None
    language = (request.POST.get("electricity_invoice_language") or "").strip()
    if file_obj:
        extracted = _parse_electricity_invoice(file_obj, lead_id=lead_id, language=language)
    else:
        extracted = _parse_invoice_from_uploaded_images(images, language=language)

    invoice_hash = (extracted.get("invoice_hash") or "").strip()
    dup_hash_qs = Lead.objects.filter(Q(invoice_hash=invoice_hash) | Q(electricity_invoice_hash=invoice_hash)).exclude(pk=lead_id) if invoice_hash else Lead.objects.none()
    duplicate_invoice = dup_hash_qs.exists() if invoice_hash else False
    duplicate_lead_id = dup_hash_qs.values_list("id", flat=True).first() if invoice_hash else None
    duplicate_service_keys = (
        bool(extracted.get("account_number") and extracted.get("meter_number") and extracted.get("location_id"))
        and Lead.objects.filter(
            account_number=extracted["account_number"],
            meter_number=extracted["meter_number"],
            location_id=extracted["location_id"],
        ).exclude(pk=lead_id).exists()
    )
    if not duplicate_lead_id and duplicate_service_keys:
        duplicate_lead_id = (
            Lead.objects.filter(
                account_number=extracted["account_number"],
                meter_number=extracted["meter_number"],
                location_id=extracted["location_id"],
            ).exclude(pk=lead_id).values_list("id", flat=True).first()
        )
    if duplicate_invoice or duplicate_service_keys:
        code = "duplicate_invoice" if duplicate_invoice else "duplicate_service_keys"
        return JsonResponse(
            {
                "success": False,
                "code": code,
                "error_code": code,
                "error": "Se detecto posible duplicado en factura.",
                "duplicate_invoice": duplicate_invoice,
                "duplicate_service_keys": duplicate_service_keys,
                "duplicate_lead_id": duplicate_lead_id,
                "can_request_review": True,
                "data": extracted,
                "extracted": extracted,
            },
            status=409,
        )

    checklist_keys = [
        "invoice_name",
        "account_number",
        "meter_number",
        "location_id",
        "electricity_bill",
        "consumo_promedio_kwh",
        "id_consumo_historial",
    ]
    checklist = {key: bool(extracted.get(key)) for key in checklist_keys}
    return JsonResponse(
        {
            "success": True,
            "data": extracted,
            "extracted": extracted,
            "checklist": checklist,
        }
    )


@login_required
@require_http_methods(["POST"])
def crm_duplicate_review_request(request):
    if not _can_access_customer_management_section(request.user):
        return JsonResponse({"success": False, "error": "No autorizado."}, status=403)
    lead_id = int(request.POST.get("lead_id") or 0)
    reason = (request.POST.get("reason") or "").strip()
    if lead_id:
        lead = _lead_for_owner_or_404(request.user, lead_id)
    else:
        duplicate_id = int(request.POST.get("duplicate_lead_id") or 0)
        if not duplicate_id:
            preview_pdf = request.FILES.get("electricity_invoice_pdf")
            preview_images = [
                request.FILES.get("electricity_invoice_page1_img"),
                request.FILES.get("electricity_invoice_page2_img"),
                request.FILES.get("electricity_invoice_page3_img"),
                request.FILES.get("electricity_invoice_page4_img"),
            ]
            preview_images = [img for img in preview_images if img]
            parsed = {}
            if preview_pdf:
                parsed = _parse_electricity_invoice(
                    preview_pdf,
                    lead_id=None,
                    language=(request.POST.get("electricity_invoice_language") or ""),
                )
            elif preview_images:
                parsed = _parse_invoice_from_uploaded_images(preview_images, language=(request.POST.get("electricity_invoice_language") or ""))
            invoice_hash = (parsed.get("invoice_hash") or "").strip()
            if invoice_hash:
                duplicate = Lead.objects.filter(Q(invoice_hash=invoice_hash) | Q(electricity_invoice_hash=invoice_hash), lead_kind=Lead.LeadKind.RESIDENTIAL).order_by("-id").first()
                if duplicate:
                    lead = duplicate
                else:
                    return JsonResponse({"success": False, "message": "No se encontro duplicado para solicitar revision."}, status=400)
            else:
                account_number = (parsed.get("account_number") or "").strip()
                meter_number = (parsed.get("meter_number") or "").strip()
                location_id = (parsed.get("location_id") or "").strip()
                if not (account_number and meter_number and location_id):
                    return JsonResponse({"success": False, "message": "Lead de referencia requerido."}, status=400)
                duplicate = Lead.objects.filter(
                    account_number=account_number,
                    meter_number=meter_number,
                    location_id=location_id,
                    lead_kind=Lead.LeadKind.RESIDENTIAL,
                ).order_by("-id").first()
                if not duplicate:
                    return JsonResponse({"success": False, "message": "No se encontro duplicado para solicitar revision."}, status=400)
                lead = duplicate
        else:
            lead = get_object_or_404(Lead, pk=duplicate_id, lead_kind=Lead.LeadKind.RESIDENTIAL)
    salesrep = _lead_access(request.user).salesrep
    if not salesrep:
        return JsonResponse({"success": False, "message": "No tienes perfil comercial."}, status=403)

    req, created = InvoiceDuplicateReviewRequest.objects.get_or_create(
        lead=lead,
        requester=salesrep,
        status=InvoiceDuplicateReviewRequest.Status.PENDING,
        defaults={"reason": reason},
    )
    if not created and reason:
        req.reason = reason
        req.save(update_fields=["reason"])
    return JsonResponse({"success": True, "request_id": req.id, "message": "Solicitud enviada para revision al Partner."})


@login_required
@require_http_methods(["GET"])
def crm_duplicate_review_pending(request):
    if not _is_partner_or_superadmin(request.user):
        return JsonResponse({"detail": "No autorizado"}, status=403)
    lead_id = int(request.GET.get("lead_id") or 0)
    items = InvoiceDuplicateReviewRequest.objects.filter(
        lead_id=lead_id,
        status=InvoiceDuplicateReviewRequest.Status.PENDING,
    ).select_related("requester__user")
    data = [
        {
            "id": item.id,
            "requester_name": item.requester.user.get_full_name().strip() or item.requester.user.get_username(),
            "reason": item.reason,
            "created_at": item.created_at.strftime("%Y-%m-%d %H:%M"),
        }
        for item in items
    ]
    return JsonResponse({"data": data})


@login_required
@require_http_methods(["POST"])
def crm_duplicate_review_action(request, request_id: int):
    if not _is_partner_or_superadmin(request.user):
        return JsonResponse({"success": False, "message": "No autorizado."}, status=403)

    decision = (request.POST.get("action") or "").strip().lower()
    notes = (request.POST.get("notes") or "").strip()
    review = get_object_or_404(InvoiceDuplicateReviewRequest.objects.select_related("lead", "requester"), pk=request_id)
    if review.status != InvoiceDuplicateReviewRequest.Status.PENDING:
        return JsonResponse({"success": False, "message": "La solicitud ya fue procesada."}, status=400)

    if decision == "approve":
        review.status = InvoiceDuplicateReviewRequest.Status.APPROVED
        review.lead.sales_rep = review.requester
        review.lead.is_accepted = True
        review.lead.acceptance_deadline = None
        review.lead.duplicate_blocked = False
        review.lead.save(update_fields=["sales_rep", "is_accepted", "acceptance_deadline", "duplicate_blocked", "updated_at"])
        InvoiceDuplicateOverride.objects.create(
            requester=review.requester,
            account_number=review.lead.account_number,
            meter_number=review.lead.meter_number,
            location_id=review.lead.location_id,
            invoice_hash=review.lead.invoice_hash,
            expires_at=timezone.now() + timedelta(hours=48),
        )
    elif decision == "reject":
        review.status = InvoiceDuplicateReviewRequest.Status.REJECTED
    else:
        return JsonResponse({"success": False, "message": "Accion invalida."}, status=400)

    review.resolver = request.user
    review.resolver_notes = notes
    review.resolved_at = timezone.now()
    review.save(update_fields=["status", "resolver", "resolver_notes", "resolved_at"])
    return JsonResponse({"success": True, "message": "Solicitud procesada."})


@login_required
@require_http_methods(["POST"])
def crm_assign_lead_api(request, lead_id: int):
    if not _is_partner_or_superadmin(request.user):
        return JsonResponse({"success": False, "message": "No autorizado."}, status=403)

    lead = _lead_for_owner_or_404(request.user, lead_id)
    target_salesrep_id = int(request.POST.get("salesrep_id") or 0)
    work_deadline_str = (request.POST.get("work_deadline") or "").strip()
    target = get_object_or_404(SalesRep, pk=target_salesrep_id, is_active=True)

    if not request.user.is_superuser:
        visible_ids = get_downline_user_ids(request.user)
        if target.user_id not in visible_ids:
            return JsonResponse({"success": False, "message": "No puedes asignar fuera de tu red."}, status=403)

    lead.sales_rep = target
    lead.assigned_by = request.user
    lead.assigned_at = timezone.now()
    lead.acceptance_deadline = timezone.now() + timedelta(hours=24)
    lead.is_accepted = False
    if work_deadline_str:
        try:
            lead.work_deadline = datetime.fromisoformat(work_deadline_str)
        except Exception:
            pass
    lead.save(update_fields=["sales_rep", "assigned_by", "assigned_at", "acceptance_deadline", "is_accepted", "work_deadline", "updated_at"])

    LeadActivityLog.objects.create(lead=lead, actor=request.user, activity_type=LeadActivityLog.ActivityType.ASSIGN)
    return JsonResponse({"success": True, "message": "Lead asignado."})


@login_required
@require_http_methods(["POST"])
def crm_accept_lead_api(request, lead_id: int):
    lead = _lead_for_owner_or_404(request.user, lead_id)
    now = timezone.now()
    if lead.is_accepted:
        return JsonResponse({"success": True, "message": "Lead ya aceptado."})

    if lead.acceptance_deadline and lead.acceptance_deadline < now:
        lead.sales_rep = None
        lead.is_accepted = False
        lead.assigned_by = None
        lead.assigned_at = None
        lead.acceptance_deadline = None
        lead.save(update_fields=["sales_rep", "is_accepted", "assigned_by", "assigned_at", "acceptance_deadline", "updated_at"])
        return JsonResponse({"success": False, "message": "La ventana de aceptacion expiro y el lead fue desasignado."}, status=400)

    lead.is_accepted = True
    lead.save(update_fields=["is_accepted", "updated_at"])
    LeadActivityLog.objects.create(lead=lead, actor=request.user, activity_type=LeadActivityLog.ActivityType.ACCEPT)
    return JsonResponse({"success": True, "message": "Lead aceptado correctamente."})
