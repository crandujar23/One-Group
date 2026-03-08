from __future__ import annotations

from datetime import timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import BusinessUnit, Role
from core.rbac.constants import RoleCode
from crm.models import CrmDeal
from crm.models import InvoiceDuplicateReviewRequest
from crm.models import Lead
from crm.models import LeadSource
from crm.models import SalesRep
from crm.models import SalesrepLevel
from openpyxl import Workbook

User = get_user_model()


class SalesRepAdminChangeViewTests(TestCase):
    def setUp(self) -> None:
        self.partner_role = Role.objects.get(code=RoleCode.PARTNER)
        self.consultant_role = Role.objects.get(code=RoleCode.SOLAR_CONSULTANT)
        self.business_unit = BusinessUnit.objects.create(name="OneGroup", code="onegroup")

        self.target_user = User.objects.create_user(username="target", password="Test@123")
        self.salesrep = SalesRep.objects.create(
            user=self.target_user,
            business_unit=self.business_unit,
            level=self.consultant_role,
        )

    def _change_url(self, extra_query: str = "") -> str:
        base = reverse("admin:crm_salesrep_change", args=[self.salesrep.id])
        return f"{base}?{extra_query}" if extra_query else base

    def test_non_staff_user_cannot_access_change_form(self) -> None:
        user = User.objects.create_user(username="nonstaff", password="Test@123")
        self.client.force_login(user)

        response = self.client.get(self._change_url())

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_change_form_renders_with_expected_labels_for_authorized_staff(self) -> None:
        staff_user = User.objects.create_user(
            username="staffer",
            password="Test@123",
            is_staff=True,
        )
        change_perm = Permission.objects.get(codename="change_salesrep")
        view_perm = Permission.objects.get(codename="view_salesrep")
        staff_user.user_permissions.add(change_perm, view_perm)
        self.client.login(username="staffer", password="Test@123")

        response = self.client.get(self._change_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Indicador de cuenta Sunrun")
        self.assertContains(response, "Sponsor (Parent)")
        self.assertContains(response, "Jr Partner rate")

    def test_save_updates_modified_at_and_preserves_changelist_filters(self) -> None:
        staff_user = User.objects.create_user(
            username="editor",
            password="Test@123",
            is_staff=True,
        )
        change_perm = Permission.objects.get(codename="change_salesrep")
        view_perm = Permission.objects.get(codename="view_salesrep")
        staff_user.user_permissions.add(change_perm, view_perm)
        self.client.login(username="editor", password="Test@123")

        before_modified_at = self.salesrep.modified_at
        url = self._change_url("_changelist_filters=level__id__exact%3D1")
        payload = {
            "user": str(self.target_user.id),
            "sunrun_account_flag": "on",
            "level": str(self.consultant_role.id),
            "zoho_id": "ZOHO-8",
            "business_unit": str(self.business_unit.id),
            "tier": "",
            "is_active": "on",
            "parent": "",
            "parent_rate": "0.1000",
            "trainee_rate": "0.0600",
            "consultant": "",
            "consultant_rate": "0.1200",
            "teamleader": "",
            "teamleader_rate": "0.1300",
            "manager": "",
            "manager_rate": "0.1400",
            "promanager": "",
            "promanager_rate": "0.1500",
            "executivemanager": "",
            "executivemanager_rate": "0.1600",
            "jr_partner": "",
            "jr_partner_rate": "0.1700",
            "partner": "",
            "partner_rate": "0.1900",
            "_save": "Save",
        }

        response = self.client.post(url, data=payload)

        self.assertEqual(response.status_code, 302)
        self.assertIn("level__id__exact=1", response.url)

        self.salesrep.refresh_from_db()
        self.assertTrue(self.salesrep.sunrun_account_flag)
        self.assertEqual(self.salesrep.zoho_id, "ZOHO-8")
        self.assertNotEqual(self.salesrep.modified_at, before_modified_at)


class SalesrepLevelAdminTests(TestCase):
    def setUp(self) -> None:
        self.staff_user = User.objects.create_user(
            username="levels_admin",
            password="Test@123",
            is_staff=True,
        )
        self.view_perm = Permission.objects.get(codename="view_salesreplevel")
        self.add_perm = Permission.objects.get(codename="add_salesreplevel")
        self.change_perm = Permission.objects.get(codename="change_salesreplevel")
        self.delete_perm = Permission.objects.get(codename="delete_salesreplevel")

    def _login_with_perms(self, *perms: Permission) -> None:
        self.staff_user.user_permissions.set(perms)
        self.client.login(username="levels_admin", password="Test@123")

    def test_changelist_columns_search_and_default_order(self) -> None:
        self._login_with_perms(self.view_perm)
        first = SalesrepLevel.objects.create(
            name="Alpha Level",
            sales_goal=10,
            indirect_sales_cap_percentage=12.50,
            sort_value=1,
        )
        second = SalesrepLevel.objects.create(
            name="Beta Level",
            sales_goal=20,
            indirect_sales_cap_percentage=25.00,
            sort_value=2,
        )

        response = self.client.get(reverse("admin:crm_salesreplevel_changelist"))
        self.assertEqual(response.status_code, 200)
        content = response.content.lower()
        self.assertIn(b"name", content)
        self.assertIn(b"sales goal", content)
        self.assertIn(b"indirect sales cap percentage", content)

        result_ids = [obj.id for obj in response.context["cl"].result_list]
        self.assertEqual(result_ids, [first.id, second.id])

        search_response = self.client.get(reverse("admin:crm_salesreplevel_changelist"), {"q": "Beta"})
        self.assertEqual(search_response.status_code, 200)
        self.assertContains(search_response, "Beta Level")
        self.assertNotContains(search_response, "Alpha Level")

    def test_crud_with_permissions(self) -> None:
        self._login_with_perms(self.view_perm, self.add_perm, self.change_perm, self.delete_perm)

        add_response = self.client.post(
            reverse("admin:crm_salesreplevel_add"),
            {
                "name": "Solar Advisor",
                "sales_goal": 100,
                "indirect_sales_cap_percentage": "15.00",
                "sort_value": 40,
                "_save": "Save",
            },
        )
        self.assertEqual(add_response.status_code, 302)
        level = SalesrepLevel.objects.get(name="Solar Advisor")

        change_response = self.client.post(
            reverse("admin:crm_salesreplevel_change", args=[level.id]),
            {
                "name": "Solar Advisor Updated",
                "sales_goal": 110,
                "indirect_sales_cap_percentage": "16.50",
                "sort_value": 41,
                "_save": "Save",
            },
        )
        self.assertEqual(change_response.status_code, 302)
        level.refresh_from_db()
        self.assertEqual(level.name, "Solar Advisor Updated")
        self.assertEqual(level.sales_goal, 110)

        delete_response = self.client.post(
            reverse("admin:crm_salesreplevel_delete", args=[level.id]),
            {"post": "yes"},
        )
        self.assertEqual(delete_response.status_code, 302)
        self.assertFalse(SalesrepLevel.objects.filter(id=level.id).exists())

    def test_access_denied_without_view_permission(self) -> None:
        self._login_with_perms()
        response = self.client.get(reverse("admin:crm_salesreplevel_changelist"))
        self.assertIn(response.status_code, (302, 403))


class ResidentialLeadsFlowTests(TestCase):
    def setUp(self) -> None:
        self.business_unit = BusinessUnit.objects.create(name="Solar Home Power", code="solar-home-power")
        self.consultant_role = Role.objects.get(code=RoleCode.SOLAR_CONSULTANT)

        self.partner = User.objects.create_user(username="partner_leads", email="partner@example.com", password="secretpass123")
        self.partner.profile.role = RoleCode.PARTNER
        self.partner.profile.save(update_fields=["role"])
        self.partner_rep = SalesRep.objects.create(user=self.partner, business_unit=self.business_unit, level=self.consultant_role)

        self.associate = User.objects.create_user(username="assoc_leads", email="assoc@example.com", password="secretpass123")
        self.associate.profile.role = RoleCode.SOLAR_CONSULTANT
        self.associate.profile.manager = self.partner
        self.associate.profile.save(update_fields=["role", "manager"])
        self.associate_rep = SalesRep.objects.create(user=self.associate, business_unit=self.business_unit, level=self.consultant_role)

    def _lead(self, *, salesrep: SalesRep, name: str = "Lead Test", **extra) -> Lead:
        payload = {
            "business_unit": self.business_unit,
            "sales_rep": salesrep,
            "full_name": name,
            "customer_name": name,
            "lead_kind": Lead.LeadKind.RESIDENTIAL,
            "status": Lead.Status.NEW,
            "is_accepted": True,
        }
        payload.update(extra)
        return Lead.objects.create(**payload)

    def _pdf(self, name: str = "invoice.pdf", content: bytes = b"fake pdf content") -> SimpleUploadedFile:
        return SimpleUploadedFile(name=name, content=content, content_type="application/pdf")

    def _create_payload(self, **extra):
        payload = {
            "status": Lead.Status.NEW,
            "lead_source": "Meta",
            "customer_name": "Cliente Nuevo",
            "customer_phone": "(787)555-1234",
            "customer_phone2": "",
            "customer_address": "Calle 1",
            "customer_city": "San Juan",
            "customer_latitude": "18.4655",
            "customer_longitude": "-66.1057",
            "customer_email": "cliente@example.com",
            "roof_type": "Hormigon",
            "owns_property": "SI",
            "electricity_bill": "120.50",
            "system_size": "",
            "electricity_invoice_language": "es",
            "invoice_name": "Factura",
            "account_number": "A100",
            "meter_number": "M100",
            "location_id": "L100",
            "consumo_promedio_kwh": "450",
            "id_consumo_historial": "[450,420,430,410,400,390,380,370,360,350,340,330]",
            "hsp": "4.5",
            "eff": "0.8",
            "offset": "0.95",
            "last_4_ssn_luma": "1234",
            "account_occupation_luma": "Owner",
            "marital_status": "Single",
            "username_luma": "user_luma",
            "password_luma": "pass_luma",
            "sunrun_contract_signed": "on",
            "sunrun_call_completed": "on",
            "loan_reference_number": "LRN-1",
            "financing": "Loan",
            "battery_option": "Powerwall",
            "total_project_cost": "22000.00",
            "use_invoice_images": "",
        }
        payload.update(extra)
        return payload

    def test_api_privacy_returns_only_own_residential_leads(self):
        self._lead(salesrep=self.associate_rep, name="Lead Propio")
        self._lead(salesrep=self.partner_rep, name="Lead Ajeno")

        self.client.login(username="assoc_leads", password="secretpass123")
        response = self.client.get(reverse("dashboard:crm_leads_api"))
        self.assertEqual(response.status_code, 200)
        names = [row["full_name"] for row in response.json()["data"]]
        self.assertEqual(names, ["Lead Propio"])

    def test_assign_and_accept_with_24h_window(self):
        lead = self._lead(salesrep=self.partner_rep, is_accepted=True)
        self.client.login(username="partner_leads", password="secretpass123")
        assign_response = self.client.post(
            reverse("dashboard:crm_assign_lead_api", args=[lead.id]),
            {"salesrep_id": str(self.associate_rep.id)},
        )
        self.assertEqual(assign_response.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.sales_rep_id, self.associate_rep.id)
        self.assertFalse(lead.is_accepted)
        self.assertIsNotNone(lead.acceptance_deadline)

        self.client.login(username="assoc_leads", password="secretpass123")
        accept_response = self.client.post(reverse("dashboard:crm_accept_lead_api", args=[lead.id]))
        self.assertEqual(accept_response.status_code, 200)
        lead.refresh_from_db()
        self.assertTrue(lead.is_accepted)

    def test_accept_expired_lead_unassigns(self):
        lead = self._lead(
            salesrep=self.associate_rep,
            is_accepted=False,
            acceptance_deadline=timezone.now() - timedelta(minutes=1),
        )
        self.client.login(username="assoc_leads", password="secretpass123")
        response = self.client.post(reverse("dashboard:crm_accept_lead_api", args=[lead.id]))
        self.assertEqual(response.status_code, 400)
        lead.refresh_from_db()
        self.assertIsNone(lead.sales_rep)
        self.assertFalse(lead.is_accepted)

    def test_create_valid(self):
        self.client.login(username="assoc_leads", password="secretpass123")
        response = self.client.post(
            reverse("dashboard:crm_lead_create_modal"),
            data={**self._create_payload(), "electricity_invoice_pdf": self._pdf()},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("success"))
        self.assertEqual(Lead.objects.filter(sales_rep=self.associate_rep).count(), 1)

    def test_nuevo_cliente_modal_open_and_submit_ajax(self):
        self.client.login(username="assoc_leads", password="secretpass123")

        open_response = self.client.get(
            reverse("dashboard:crm_lead_create_modal") + "?_modal=1",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(open_response.status_code, 200)
        self.assertContains(open_response, 'id="lead-create-form"')
        self.assertContains(open_response, "Datos de LUMA")
        self.assertContains(open_response, "Cierre de Ventas")

        submit_response = self.client.post(
            reverse("dashboard:crm_lead_create_modal"),
            data={**self._create_payload(customer_name="Cliente Modal"), "electricity_invoice_pdf": self._pdf()},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(submit_response.status_code, 200)
        payload = submit_response.json()
        self.assertTrue(payload.get("success"))
        created = Lead.objects.get(id=payload["id"])
        self.assertEqual(created.customer_name, "Cliente Modal")

    def test_duplicate_block_and_review_request(self):
        base = self._lead(salesrep=self.associate_rep, account_number="A1", meter_number="M1", location_id="L1")
        self.client.login(username="assoc_leads", password="secretpass123")
        create_response = self.client.post(
            reverse("dashboard:crm_lead_create_modal"),
            data={**self._create_payload(account_number="A1", meter_number="M1", location_id="L1"), "electricity_invoice_pdf": self._pdf("account_A1_meter_M1_location_L1.pdf")},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(create_response.status_code, 409)
        self.assertEqual(create_response.json().get("code"), "duplicate_service_keys")
        review_response = self.client.post(
            reverse("dashboard:crm_duplicate_review_request"),
            {"duplicate_lead_id": str(base.id), "reason": "prueba"},
        )
        self.assertEqual(review_response.status_code, 200)
        self.assertTrue(
            InvoiceDuplicateReviewRequest.objects.filter(
                lead=base,
                requester=self.associate_rep,
                status=InvoiceDuplicateReviewRequest.Status.PENDING,
            ).exists()
        )

    def test_duplicate_invoice_hash_block(self):
        existing = self._lead(salesrep=self.associate_rep, name="Existente")
        existing.invoice_hash = "HASH-1"
        existing.save(update_fields=["invoice_hash"])
        self.client.login(username="assoc_leads", password="secretpass123")

        response = self.client.post(
            reverse("dashboard:crm_lead_create_modal"),
            data={**self._create_payload(account_number="", meter_number="", location_id=""), "electricity_invoice_pdf": self._pdf(content=b"same content")},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        # first create should pass because hash differs from manual literal hash
        self.assertIn(response.status_code, (200, 409))

        # enforce duplicate by creating using computed hash
        probe_pdf = self._pdf(content=b"dup content")
        import hashlib
        h = hashlib.sha256(probe_pdf.read()).hexdigest()
        existing.invoice_hash = h
        existing.save(update_fields=["invoice_hash"])
        probe_pdf.seek(0)
        dup_response = self.client.post(
            reverse("dashboard:crm_lead_create_modal"),
            data={**self._create_payload(account_number="", meter_number="", location_id=""), "electricity_invoice_pdf": probe_pdf},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(dup_response.status_code, 409)
        self.assertEqual(dup_response.json().get("code"), "duplicate_invoice")

    def test_filters_and_kpis(self):
        self._lead(salesrep=self.associate_rep, name="Uno", status=Lead.Status.NEW, phone="123")
        self._lead(salesrep=self.associate_rep, name="Dos", status=Lead.Status.CLOSED, email="a@b.com")
        self.client.login(username="assoc_leads", password="secretpass123")
        response = self.client.get(reverse("dashboard:crm_leads_api"), {"status": Lead.Status.NEW})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["data"]), 1)
        self.assertIn("kpis", payload)
        self.assertEqual(payload["kpis"]["total"], 1)

    def test_system_size_calculation(self):
        self.client.login(username="assoc_leads", password="secretpass123")
        response = self.client.post(
            reverse("dashboard:crm_lead_create_modal"),
            data={**self._create_payload(system_size="", consumo_promedio_kwh="450", hsp="4.5", eff="0.8", offset="0.95"), "electricity_invoice_pdf": self._pdf("account_A100_meter_M100_location_L100.pdf")},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        lead = Lead.objects.latest("id")
        self.assertIsNotNone(lead.system_size)
        self.assertGreater(float(lead.system_size), 0)

    def test_parse_invoice_preview_reads_pdf_text_and_fills_fields(self):
        self.client.login(username="assoc_leads", password="secretpass123")
        pdf_content = (
            b"Numero de cuenta: A2222\n"
            b"Numero de contador: M2222\n"
            b"Location ID: L2222\n"
            b"Monto total: $187.35\n"
            b"Consumo promedio kWh: 512\n"
        )
        response = self.client.post(
            reverse("dashboard:crm_leads_parse_invoice_preview"),
            data={"electricity_invoice_pdf": self._pdf("Bill Luz.pdf", pdf_content)},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("success"))
        extracted = payload.get("extracted", {})
        self.assertEqual(extracted.get("account_number"), "A2222")
        self.assertEqual(extracted.get("meter_number"), "M2222")
        self.assertEqual(extracted.get("location_id"), "L2222")
        self.assertEqual(extracted.get("electricity_bill"), "187.35")
        self.assertEqual(extracted.get("consumo_promedio_kwh"), "512")

    def test_delete_permissions(self):
        lead = self._lead(salesrep=self.associate_rep)
        self.client.login(username="assoc_leads", password="secretpass123")
        denied = self.client.post(reverse("dashboard:crm_lead_delete_modal", args=[lead.id]))
        self.assertEqual(denied.status_code, 403)

        own_partner_lead = self._lead(salesrep=self.partner_rep, name="Partner Lead")
        self.client.login(username="partner_leads", password="secretpass123")
        allowed = self.client.post(reverse("dashboard:crm_lead_delete_modal", args=[own_partner_lead.id]))
        self.assertEqual(allowed.status_code, 200)
        self.assertFalse(Lead.objects.filter(id=own_partner_lead.id).exists())

    @override_settings(LEAD_GENERATION_BASE_URL="https://example.test/apps/crm/lead-generation/public")
    def test_lead_generation_private_builds_share_link(self):
        self.client.login(username="assoc_leads", password="secretpass123")
        response = self.client.get(reverse("dashboard:crm_lead_generation_private"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "salesrep_id=" + str(self.associate_rep.id))
        self.assertContains(response, "email=assoc%40example.com")

    def test_lead_generation_public_create_success(self):
        payload = {
            "salesrep_id": str(self.associate_rep.id),
            "email": "assoc@example.com",
            "customer_name": "Lead Publico",
            "customer_phone": "(787)555-1122",
            "customer_email": "publico@example.com",
            "customer_address": "Calle A",
            "customer_city": "San Juan",
            "roof_type": "Cemento",
            "owns_property": "true",
            "electricity_bill": "$1,234.56",
        }
        response = self.client.post(reverse("dashboard:crm_lead_generation_public"), data=payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gracias por tu solicitud")
        created = Lead.objects.filter(customer_name="Lead Publico").latest("id")
        self.assertEqual(created.sales_rep_id, self.associate_rep.id)
        self.assertEqual(created.lead_source, "Lead Generation")
        self.assertEqual(str(created.electricity_bill), "1234.56")
        self.assertEqual(created.status, Lead.Status.NEW)
        self.assertTrue(LeadSource.objects.filter(name="Lead Generation").exists())

    def test_lead_generation_public_errors_for_unknown_salesrep(self):
        response = self.client.get(reverse("dashboard:crm_lead_generation_public"), {"salesrep_id": 999999})
        self.assertEqual(response.status_code, 404)
        self.assertIn("No se encontro un perfil de asociado valido.", response.content.decode("utf-8"))

    def test_lead_generation_public_phone_validation(self):
        response = self.client.post(
            reverse("dashboard:crm_lead_generation_public"),
            data={
                "salesrep_id": str(self.associate_rep.id),
                "customer_name": "Lead Invalido",
                "customer_phone": "7875551122",
                "customer_city": "San Juan",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Use formato (XXX)XXX-XXXX", response.content.decode("utf-8"))

    def test_lead_generation_public_parses_electricity_bill_formats(self):
        response = self.client.post(
            reverse("dashboard:crm_lead_generation_public"),
            data={
                "salesrep_id": str(self.associate_rep.id),
                "customer_name": "Lead Bill",
                "customer_phone": "(787)555-3344",
                "customer_city": "San Juan",
                "electricity_bill": "1,250.40",
            },
        )
        self.assertEqual(response.status_code, 200)
        lead = Lead.objects.filter(customer_name="Lead Bill").latest("id")
        self.assertEqual(str(lead.electricity_bill), "1250.40")

    def test_lead_generation_public_invalid_bill_renders_field_error(self):
        response = self.client.post(
            reverse("dashboard:crm_lead_generation_public"),
            data={
                "salesrep_id": str(self.associate_rep.id),
                "customer_name": "Lead Bill Error",
                "customer_phone": "(787)555-9988",
                "customer_city": "San Juan",
                "electricity_bill": "abc$%",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Ingresa un monto valido. Ejemplo: 245.50", response.content.decode("utf-8"))

    def test_lead_generation_public_required_field_error_re_renders_form(self):
        response = self.client.post(
            reverse("dashboard:crm_lead_generation_public"),
            data={
                "salesrep_id": str(self.associate_rep.id),
                "customer_phone": "(787)555-0099",
                "customer_city": "San Juan",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("nombre del cliente", response.content.decode("utf-8").lower())

    def test_lead_generation_public_has_no_internal_navigation(self):
        response = self.client.get(
            reverse("dashboard:crm_lead_generation_public"),
            {"salesrep_id": str(self.associate_rep.id), "email": "assoc@example.com"},
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertNotIn("navbar-neo", html)
        self.assertNotIn("Operación", html)
        self.assertIn("Solicitud de informacion", html)

    def test_qrcode_endpoint_requires_auth_and_returns_png(self):
        unauth = self.client.get(reverse("dashboard:crm_leads_qrcode"))
        self.assertEqual(unauth.status_code, 302)
        self.client.login(username="assoc_leads", password="secretpass123")
        auth = self.client.get(reverse("dashboard:crm_leads_qrcode"))
        self.assertEqual(auth.status_code, 200)
        self.assertEqual(auth["Content-Type"], "image/png")

    def test_qrcode_download_sets_attachment_header(self):
        self.client.login(username="assoc_leads", password="secretpass123")
        response = self.client.get(reverse("dashboard:crm_leads_qrcode"), {"download": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn("attachment;", response.get("Content-Disposition", ""))
        self.assertIn("onegroup-qr-lead-generation-", response.get("Content-Disposition", ""))

    def test_qrcode_marketing_download_has_marketing_filename(self):
        self.client.login(username="assoc_leads", password="secretpass123")
        response = self.client.get(reverse("dashboard:crm_leads_qrcode"), {"download": "1", "style": "marketing"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn("attachment;", response.get("Content-Disposition", ""))
        self.assertIn("onegroup-qr-marketing-", response.get("Content-Disposition", ""))

    def test_superadmin_without_salesrep_can_generate_link_and_qr(self):
        admin = User.objects.create_superuser(username="root_admin", email="root@example.com", password="secretpass123")
        self.client.login(username="root_admin", password="secretpass123")
        page = self.client.get(reverse("dashboard:crm_lead_generation_private"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "salesrep_id=" + str(self.partner_rep.id))
        self.assertContains(page, "Descargar QR")
        self.assertContains(page, "Descargar QR Marketing")
        qr = self.client.get(reverse("dashboard:crm_leads_qrcode"))
        self.assertEqual(qr.status_code, 200)
        self.assertEqual(qr["Content-Type"], "image/png")


class ResidentialDealsPipelineTests(TestCase):
    def setUp(self) -> None:
        self.business_unit = BusinessUnit.objects.create(name="Solar Home Power", code="solar-home-power")
        self.consultant_role = Role.objects.get(code=RoleCode.SOLAR_CONSULTANT)

        self.partner = User.objects.create_user(username="partner_deals", email="partner@x.com", password="secretpass123")
        self.partner.profile.role = RoleCode.PARTNER
        self.partner.profile.save(update_fields=["role"])
        self.partner_rep = SalesRep.objects.create(user=self.partner, business_unit=self.business_unit, level=self.consultant_role)

        self.manager = User.objects.create_user(username="manager_deals", email="manager@x.com", password="secretpass123")
        self.manager.profile.role = RoleCode.MANAGER
        self.manager.profile.manager = self.partner
        self.manager.profile.save(update_fields=["role", "manager"])
        self.manager_rep = SalesRep.objects.create(user=self.manager, business_unit=self.business_unit, level=self.consultant_role)

        self.associate = User.objects.create_user(username="assoc_deals", email="assoc@x.com", password="secretpass123")
        self.associate.profile.role = RoleCode.SOLAR_CONSULTANT
        self.associate.profile.manager = self.manager
        self.associate.profile.save(update_fields=["role", "manager"])
        self.associate_rep = SalesRep.objects.create(user=self.associate, business_unit=self.business_unit, level=self.consultant_role)

        self.outside = User.objects.create_user(username="outside_deals", email="outside@x.com", password="secretpass123")
        self.outside.profile.role = RoleCode.SOLAR_CONSULTANT
        self.outside.profile.save(update_fields=["role"])
        self.outside_rep = SalesRep.objects.create(user=self.outside, business_unit=self.business_unit, level=self.consultant_role)

    def _deal(self, *, salesrep=None, kind=CrmDeal.DealKind.RESIDENTIAL, proposal="P-1", contract="SC-1", stage=CrmDeal.Stage.PLANNED, **extra):
        payload = {
            "deal_kind": kind,
            "salesrep": salesrep,
            "proposal_id": proposal,
            "sunrun_service_contract_id": contract,
            "customer_name": "Cliente Deal",
            "customer_phone": "(787)555-9000",
            "customer_email": "deal@example.com",
            "stage": stage,
        }
        payload.update(extra)
        return CrmDeal.objects.create(**payload)

    def _excel_file(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "FEBRERO 2026"
        ws.append(["SERVICE CONTRACT+/PROPOSAL ID", "SALES REP. NAME", "DATE APPROVED", "EPC PRICED", "SYSTEM SIZE DC", "EPC BASE", "EPC TABLA", "AJUSTE POR EPC"])
        ws.append(["SC-EXCEL/P-EXCEL", "assoc_deals", "2026-02-08", "15000.25", "6.40", "14500", "300", "200.25"])
        buffer = BytesIO()
        wb.save(buffer)
        return SimpleUploadedFile("deals.xlsx", buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def test_access_denied_without_sales_permission(self):
        no_profile = User.objects.create_user(username="noperm_deals", password="secretpass123")
        no_profile.profile.role = ""
        no_profile.profile.save(update_fields=["role"])
        self.client.login(username="noperm_deals", password="secretpass123")
        response = self.client.get(reverse("dashboard:crm_deals_list"))
        self.assertEqual(response.status_code, 403)

    def test_scope_filter_individual_user_only_own_deals(self):
        own = self._deal(salesrep=self.associate_rep, proposal="P-OWN", contract="SC-OWN")
        self._deal(salesrep=self.outside_rep, proposal="P-OUT", contract="SC-OUT")
        self.client.login(username="assoc_deals", password="secretpass123")
        response = self.client.get(reverse("dashboard:crm_deals_details_api"), {"deal_kind": "residential"})
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["proposal_id"], own.proposal_id)

    def test_scope_filter_manager_sees_team_scope(self):
        self._deal(salesrep=self.associate_rep, proposal="P-TEAM", contract="SC-TEAM")
        self._deal(salesrep=self.outside_rep, proposal="P-OUT", contract="SC-OUT")
        self.client.login(username="manager_deals", password="secretpass123")
        response = self.client.get(reverse("dashboard:crm_deals_details_api"), {"deal_kind": "residential"})
        self.assertEqual(response.status_code, 200)
        proposal_ids = {row["proposal_id"] for row in response.json()["data"]}
        self.assertIn("P-TEAM", proposal_ids)
        self.assertNotIn("P-OUT", proposal_ids)

    def test_import_excel_dry_run_and_real(self):
        self.client.login(username="partner_deals", password="secretpass123")
        dry = self.client.post(
            reverse("dashboard:crm_deals_list"),
            data={"deal_kind": "residential", "sheet_name": "FEBRERO 2026", "dry_run": "on", "report_file": self._excel_file()},
        )
        self.assertEqual(dry.status_code, 200)
        self.assertEqual(CrmDeal.objects.count(), 0)
        real = self.client.post(
            reverse("dashboard:crm_deals_list"),
            data={"deal_kind": "residential", "sheet_name": "FEBRERO 2026", "report_file": self._excel_file()},
        )
        self.assertEqual(real.status_code, 200)
        self.assertEqual(CrmDeal.objects.count(), 1)

    def test_update_ajax_success_and_error(self):
        deal = self._deal(salesrep=self.associate_rep, proposal="P-UPD", contract="SC-UPD")
        self.client.login(username="partner_deals", password="secretpass123")
        bad = self.client.post(
            reverse("dashboard:crm_deal_update_modal", args=[deal.id]),
            data={"deal_kind": "residential", "salesrep": "999999"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post(
            reverse("dashboard:crm_deal_update_modal", args=[deal.id]),
            data={"deal_kind": "residential", "salesrep": str(self.manager_rep.id)},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.json()["success"])
        deal.refresh_from_db()
        self.assertEqual(deal.salesrep_id, self.manager_rep.id)

    def test_delete_authorized_and_not_authorized(self):
        deal = self._deal(salesrep=self.associate_rep, proposal="P-DEL", contract="SC-DEL")
        self.client.login(username="assoc_deals", password="secretpass123")
        denied = self.client.delete(reverse("dashboard:crm_deal_delete_api", args=[deal.id]) + "?deal_kind=residential")
        self.assertEqual(denied.status_code, 403)
        self.client.login(username="partner_deals", password="secretpass123")
        allowed = self.client.delete(reverse("dashboard:crm_deal_delete_api", args=[deal.id]) + "?deal_kind=residential")
        self.assertEqual(allowed.status_code, 200)
        self.assertFalse(CrmDeal.objects.filter(id=deal.id).exists())

    def test_api_filtered_by_deal_kind(self):
        self._deal(salesrep=self.partner_rep, kind=CrmDeal.DealKind.RESIDENTIAL, proposal="P-RES", contract="SC-RES")
        self._deal(salesrep=self.partner_rep, kind=CrmDeal.DealKind.COMMERCIAL, proposal="P-COM", contract="SC-COM")
        self.client.login(username="partner_deals", password="secretpass123")
        response = self.client.get(reverse("dashboard:crm_deals_details_api"), {"deal_kind": "residential"})
        self.assertEqual(response.status_code, 200)
        proposal_ids = {row["proposal_id"] for row in response.json()["data"]}
        self.assertIn("P-RES", proposal_ids)
        self.assertNotIn("P-COM", proposal_ids)
