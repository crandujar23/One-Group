from __future__ import annotations

from typing import Any

from dashboard.services.team_service import TeamScope


class TeamMemberSerializer:
    columns = [
        "full_name",
        "username",
        "level",
        "city",
        "business_unit",
        "contactability",
        "status",
        "phone",
        "email",
        "hire_date",
    ]

    @classmethod
    def _mask_phone(cls, value: str) -> str:
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) < 4:
            return ""
        return f"***-***-{digits[-4:]}"

    @classmethod
    def _mask_email(cls, value: str) -> str:
        if "@" not in value:
            return ""
        local, domain = value.split("@", 1)
        if not local:
            return f"***@{domain}"
        head = local[0]
        return f"{head}***@{domain}"

    @classmethod
    def serialize(cls, row: dict[str, Any], *, scope: TeamScope, viewer_sales_rep_id: int | None) -> dict[str, Any]:
        full_phone = (row.get("phone") or "").strip()
        full_email = (row.get("email") or "").strip()
        row_sales_rep_id = row.get("sales_rep_id")

        can_view_sensitive = bool(
            scope.global_scope
            or scope.can_view_all
            or (viewer_sales_rep_id is not None and row_sales_rep_id == viewer_sales_rep_id)
        )

        phone = full_phone if can_view_sensitive else cls._mask_phone(full_phone)
        email = full_email if can_view_sensitive else cls._mask_email(full_email)

        return {
            "full_name": row.get("full_name") or "-",
            "username": row.get("username") or "-",
            "level": row.get("level") or "Sin nivel",
            "city": row.get("city") or "-",
            "business_unit": row.get("business_unit") or "-",
            "contactability": row.get("contactability") or "Sin contacto",
            "status": row.get("status") or "Inactivo",
            "phone": phone,
            "email": email,
            "phone_raw": full_phone,
            "email_raw": full_email,
            "hire_date": row.get("hire_date") or "",
        }
