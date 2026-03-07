from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.cache import cache
from django.test import TestCase
from django.test import override_settings
from django.urls import NoReverseMatch
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils import timezone

from core.models import BusinessUnit, Role, UserProfile
from crm.models import CallLog, SalesRep
from dashboard.models import Announcement
from dashboard.models import AdminInviteRequest
from dashboard.models import Offer
from dashboard.models import OperationsAdminInviteRequest
from dashboard.models import SharedResource
from dashboard.services.team_personal_info_service import compute_team_personal_metrics
from dashboard.services.team_personal_info_service import sanitize_team_payload_for_actor
from dashboard.services.sales_team_service import compute_sales_team_summary
from finance.models import FinancingPartner
from rewards.models import Tier

User = get_user_model()


class DashboardSmokeTests(TestCase):
    def setUp(self):
        self.bu = BusinessUnit.objects.create(name="Internet", code="internet")
        self.other_bu = BusinessUnit.objects.create(name="Techo", code="techo")
        BusinessUnit.objects.create(name="Solar Home Power", code="solar-home-power")
        BusinessUnit.objects.create(name="SunVida", code="sunvida")
        BusinessUnit.objects.create(name="Cash D", code="cash-d")
        BusinessUnit.objects.create(name="Agua", code="agua")
        self.tier = Tier.objects.create(name="Base", rank=1)
        self.user = User.objects.create_user(username="rep", email="rep@example.com", password="secretpass123")
        self.user.first_name = "Carlos"
        self.user.last_name = "Andujar"
        self.user.save(update_fields=["first_name", "last_name"])
        self.admin = User.objects.create_superuser(username="admin_test", email="admin@test.com", password="secretpass123")
        self.platform_admin = User.objects.create_user(
            username="platform_admin",
            email="platform_admin@test.com",
            password="secretpass123",
        )
        self.platform_admin.profile.role = UserProfile.Role.ADMIN
        self.platform_admin.profile.save(update_fields=["role"])
        self.manager_hybrid = User.objects.create_user(
            username="manager_hybrid",
            email="manager_hybrid@test.com",
            password="secretpass123",
        )
        self.operations_admin = User.objects.create_user(
            username="ops_admin",
            email="ops_admin@test.com",
            password="secretpass123",
            is_staff=True,
        )
        self.manager_hybrid.profile.role = UserProfile.Role.MANAGER
        self.manager_hybrid.profile.business_unit = self.bu
        self.manager_hybrid.profile.save(update_fields=["role", "business_unit"])
        self.operations_admin.profile.role = UserProfile.Role.ADMINISTRADOR
        self.operations_admin.profile.business_unit = self.bu
        self.operations_admin.profile.save(update_fields=["role", "role_ref", "business_unit"])
        profile = self.user.profile
        profile.role = UserProfile.Role.SALES_REP
        profile.business_unit = self.bu
        profile.save(update_fields=["role", "business_unit"])
        self.rep_sales_profile = SalesRep.objects.create(user=self.user, business_unit=self.bu, tier=self.tier)
        self.manager_sales_profile = SalesRep.objects.create(
            user=self.manager_hybrid,
            business_unit=self.bu,
            tier=self.tier,
        )
        self.operations_admin_sales_profile = SalesRep.objects.create(
            user=self.operations_admin,
            business_unit=self.bu,
            tier=self.tier,
        )
        CallLog.objects.create(
            sales_rep=self.rep_sales_profile,
            contact_type=CallLog.ContactType.CALL,
            subject="Llamada asociada",
        )
        CallLog.objects.create(
            sales_rep=self.manager_sales_profile,
            contact_type=CallLog.ContactType.CALL,
            subject="Llamada manager",
        )
        self.bank_partner = FinancingPartner.objects.create(
            name="Banco Horizonte",
            partner_type=FinancingPartner.PartnerType.BANK,
            contact_name="Mesa Comercial",
            contact_email="finanzas@horizonte.com",
            contact_phone="(787)555-0001",
            services="Préstamos personales, financiamiento comercial y líneas verdes.",
            is_active=True,
            priority=10,
        )
        self.bank_partner.business_units.add(self.bu)
        FinancingPartner.objects.create(
            name="Cooperativa Central",
            partner_type=FinancingPartner.PartnerType.COOPERATIVE,
            services="Préstamos a socios y refinanciamiento.",
            is_active=False,
            priority=20,
        )

    def test_salesrep_can_open_dashboard(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 302)

        response = self.client.get(reverse("dashboard:sales_overview"))
        self.assertEqual(response.status_code, 200)

    def test_salesrep_home_redirects_to_admin_overview(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:admin_overview"))

    def test_salesrep_can_access_admin_overview(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:admin_overview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Resumen")

    def test_salesrep_can_access_associate_only_pages(self):
        self.client.login(username="rep", password="secretpass123")
        points = self.client.get(reverse("dashboard:points_summary"))
        self.assertEqual(points.status_code, 200)
        create_call_log = self.client.get(reverse("dashboard:call_log_create"))
        self.assertEqual(create_call_log.status_code, 200)

    def test_manager_with_salesrep_record_can_access_operational_pages(self):
        self.client.login(username="manager_hybrid", password="secretpass123")

        points = self.client.get(reverse("dashboard:points_summary"))
        self.assertEqual(points.status_code, 200)

        create_call_log = self.client.get(reverse("dashboard:call_log_create"))
        self.assertEqual(create_call_log.status_code, 200)

        call_logs = self.client.get(reverse("dashboard:call_logs"))
        self.assertEqual(call_logs.status_code, 200)
        self.assertContains(call_logs, "Llamada asociada")
        self.assertContains(call_logs, "Llamada manager")
        self.assertNotContains(call_logs, "Nuevo registro")

        sales_list = self.client.get(reverse("dashboard:sales_list"))
        self.assertEqual(sales_list.status_code, 200)
        self.assertContains(sales_list, reverse("dashboard:points_summary"))

    def test_login_required(self):
        response = self.client.get(reverse("dashboard:sales_overview"))
        self.assertEqual(response.status_code, 302)

    def test_login_page_renders_without_main_navbar(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Iniciar sesión")
        self.assertContains(response, "¿Ha olvidado tu contraseña?")
        self.assertNotContains(response, "OneGroup Platform</a>")

    def test_salesrep_sees_grouped_operations_menu(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:sales_overview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gestión Comercial")
        self.assertContains(response, reverse("dashboard:sales_list"))
        self.assertContains(response, reverse("dashboard:financing"))
        self.assertContains(response, reverse("dashboard:points_summary"))
        self.assertContains(response, reverse("dashboard:call_logs"))

    def test_salesrep_sees_grouped_products_menu(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:sales_overview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Línea Comercial")
        self.assertContains(response, reverse("dashboard:unit_solar"))
        self.assertContains(response, reverse("dashboard:unit_techo"))
        self.assertContains(response, reverse("dashboard:unit_sunvida"))
        self.assertContains(response, reverse("dashboard:unit_cash_d"))
        self.assertContains(response, reverse("dashboard:unit_agua"))
        self.assertContains(response, reverse("dashboard:unit_internet"))

    def test_navbar_shows_profile_name(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:sales_overview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Carlos Andujar")
        self.assertContains(response, "Asociado")
        self.assertContains(response, reverse("dashboard:legal"))
        self.assertContains(response, reverse("dashboard:help_center"))
        self.assertContains(response, reverse("password_change"))

    def test_admin_navbar_shows_superadmin_role(self):
        self.client.login(username="admin_test", password="secretpass123")
        response = self.client.get(reverse("dashboard:home"), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Superadministrador")

    def test_superadmin_grouped_operations_menu_shows_points(self):
        self.client.login(username="admin_test", password="secretpass123")
        response = self.client.get(reverse("dashboard:sales_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gestión Comercial")
        self.assertContains(response, reverse("dashboard:sales_list"))
        self.assertContains(response, reverse("dashboard:financing"))
        self.assertContains(response, reverse("dashboard:call_logs"))
        self.assertContains(response, reverse("dashboard:points_summary"))

    def test_superadmin_can_access_points_summary(self):
        self.client.login(username="admin_test", password="secretpass123")
        response = self.client.get(reverse("dashboard:points_summary"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Resumen de Puntos")

    def test_superadmin_can_open_access_management(self):
        self.client.login(username="admin_test", password="secretpass123")
        response = self.client.get(reverse("dashboard:access_management"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gestión de Accesos")
        self.assertContains(response, "Crear Usuario")

    def test_superadmin_can_create_partner_and_associate_from_access_management(self):
        self.client.login(username="admin_test", password="secretpass123")
        partner_response = self.client.post(
            reverse("dashboard:access_management"),
            data={
                "action": "create",
                "username": "partner_new",
                "email": "partner_new@test.com",
                "first_name": "Partner",
                "last_name": "Nuevo",
                "password": "TempPass123!",
                "role": UserProfile.Role.ADMIN,
                "business_units": [],
                "tier": "",
            },
            follow=True,
        )
        self.assertEqual(partner_response.status_code, 200)
        partner_user = User.objects.get(username="partner_new")
        self.assertEqual(partner_user.profile.role, UserProfile.Role.ADMIN)

        associate_response = self.client.post(
            reverse("dashboard:access_management"),
            data={
                "action": "create",
                "username": "associate_new",
                "email": "associate_new@test.com",
                "first_name": "Associate",
                "last_name": "Nuevo",
                "password": "TempPass123!",
                "role": UserProfile.Role.SALES_REP,
                "business_units": [self.bu.id],
                "tier": self.tier.id,
            },
            follow=True,
        )
        self.assertEqual(associate_response.status_code, 200)
        associate_user = User.objects.get(username="associate_new")
        self.assertEqual(associate_user.profile.role, UserProfile.Role.SALES_REP)
        self.assertTrue(SalesRep.objects.filter(user=associate_user).exists())

    def test_partner_cannot_access_access_management(self):
        self.client.login(username="platform_admin", password="secretpass123")
        response = self.client.get(reverse("dashboard:access_management"))
        self.assertEqual(response.status_code, 403)

    def test_manager_with_multiple_units_can_access_both_unit_pages(self):
        self.manager_hybrid.profile.business_units.add(self.bu, self.other_bu)
        self.client.login(username="manager_hybrid", password="secretpass123")
        self.assertEqual(self.client.get(reverse("dashboard:unit_internet")).status_code, 200)
        self.assertEqual(self.client.get(reverse("dashboard:unit_techo")).status_code, 200)

    def test_superadmin_sees_products_menu_even_without_business_units(self):
        BusinessUnit.objects.all().delete()
        self.client.login(username="admin_test", password="secretpass123")

        response = self.client.get(reverse("dashboard:sales_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Línea Comercial")
        self.assertContains(response, reverse("dashboard:unit_solar"))
        self.assertContains(response, reverse("dashboard:unit_internet"))

        unit_response = self.client.get(reverse("dashboard:unit_solar"))
        self.assertEqual(unit_response.status_code, 200)

    def test_superadmin_without_profile_still_has_global_access(self):
        self.admin.profile.delete()
        self.client.login(username="admin_test", password="secretpass123")

        home = self.client.get(reverse("dashboard:home"))
        self.assertEqual(home.status_code, 302)
        self.assertRedirects(home, reverse("dashboard:admin_overview"))

        admin_overview = self.client.get(reverse("dashboard:admin_overview"))
        self.assertEqual(admin_overview.status_code, 200)
        self.assertContains(admin_overview, "Superadministrador")

        sales = self.client.get(reverse("dashboard:sales_list"))
        self.assertEqual(sales.status_code, 200)

        unit = self.client.get(reverse("dashboard:unit_solar"))
        self.assertEqual(unit.status_code, 200)

    def test_platform_admin_has_full_access_without_django_admin_link(self):
        self.client.login(username="platform_admin", password="secretpass123")

        sales = self.client.get(reverse("dashboard:sales_list"))
        self.assertEqual(sales.status_code, 200)
        self.assertContains(sales, reverse("dashboard:points_summary"))
        self.assertContains(sales, reverse("dashboard:unit_solar"))
        self.assertNotContains(sales, 'href="/admin/"')

        points = self.client.get(reverse("dashboard:points_summary"))
        self.assertEqual(points.status_code, 200)

        unit = self.client.get(reverse("dashboard:unit_solar"))
        self.assertEqual(unit.status_code, 200)

        django_admin = self.client.get("/admin/")
        self.assertNotEqual(django_admin.status_code, 200)

    def test_operations_admin_cannot_access_django_admin(self):
        self.client.login(username="ops_admin", password="secretpass123")
        response = self.client.get("/admin/")
        self.assertNotEqual(response.status_code, 200)

    def test_operations_admin_cannot_access_commission_structure(self):
        self.client.login(username="ops_admin", password="secretpass123")
        response = self.client.get(reverse("dashboard:commission_structure"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:sales_overview"))

    def test_associate_create_route_removed(self):
        with self.assertRaises(NoReverseMatch):
            reverse("dashboard:associate_create")

    def test_financing_page_shows_active_partners_by_default(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:financing"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Banco Horizonte")
        self.assertNotContains(response, "Cooperativa Central")

    def test_financing_page_can_filter_by_partner_type(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:financing"), data={"type": "COOPERATIVE", "active": "0"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cooperativa Central")
        self.assertNotContains(response, "Banco Horizonte")

    def test_salesrep_sees_operations_workspace_menu(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:sales_overview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Operación")
        self.assertContains(response, reverse("dashboard:client_management"))
        self.assertContains(response, reverse("dashboard:my_team"))
        self.assertContains(response, reverse("dashboard:tasks"))
        self.assertContains(response, reverse("dashboard:tools"))

    def test_manager_sales_overview_redirects_to_admin_overview(self):
        self.client.login(username="manager_hybrid", password="secretpass123")
        response = self.client.get(reverse("dashboard:sales_overview"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:admin_overview"))

    def test_workspace_pages_are_accessible_for_authenticated_users(self):
        self.client.login(username="rep", password="secretpass123")
        for url_name in [
            "dashboard:client_management",
            "dashboard:my_team",
            "dashboard:tasks",
            "dashboard:tools",
            "dashboard:legal",
            "dashboard:help_center",
        ]:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200)

    def test_level_changes_is_blocked_for_non_partner_users(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:level_changes"))
        self.assertEqual(response.status_code, 403)

    def test_level_changes_is_available_for_partner_users(self):
        self.client.login(username="platform_admin", password="secretpass123")
        response = self.client.get(reverse("dashboard:level_changes"))
        self.assertEqual(response.status_code, 200)

    def test_my_team_page_renders_new_layout(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:my_team"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Equipo Personal")
        self.assertContains(response, "Accesos rapidos del equipo")
        self.assertContains(response, "quick-access-card")

    def test_my_team_api_limits_salesrep_to_own_record(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:my_team_data_api"), {"draw": 1, "start": 0, "length": 10})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["recordsFiltered"], 1)
        self.assertEqual(len(payload["data"]), 1)
        self.assertEqual(payload["data"][0]["username"], "rep")

    def test_my_team_api_manager_scope_and_all_forbidden(self):
        self.client.login(username="manager_hybrid", password="secretpass123")
        response = self.client.get(reverse("dashboard:my_team_data_api"), {"draw": 1, "start": 0, "length": 10})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(payload["recordsFiltered"], 2)
        usernames = {row["username"] for row in payload["data"]}
        self.assertIn("manager_hybrid", usernames)
        self.assertIn("rep", usernames)

        denied = self.client.get(reverse("dashboard:my_team_data_api"), {"all": "true"})
        self.assertEqual(denied.status_code, 403)

    def test_my_team_api_platform_admin_can_request_all(self):
        self.client.login(username="platform_admin", password="secretpass123")
        response = self.client.get(reverse("dashboard:my_team_data_api"), {"all": "true", "draw": 1, "start": 0, "length": 10})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(payload["recordsFiltered"], 2)

    def test_tools_page_allows_uploading_pdf_resource(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.post(
            reverse("dashboard:tools"),
            data={
                "action": "create_resource",
                "resource-title": "Presentacion Ventas",
                "resource-description": "Material oficial de entrenamiento.",
                "resource-resource_type": SharedResource.ResourceType.FILE,
                "resource-file": SimpleUploadedFile("ventas.pdf", b"%PDF-1.4 training material", content_type="application/pdf"),
                "resource-video_url": "",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recurso publicado correctamente.")
        self.assertEqual(SharedResource.objects.count(), 1)
        self.assertContains(response, "Presentacion Ventas")

    def test_tools_page_embeds_supported_video_link(self):
        self.client.login(username="rep", password="secretpass123")
        self.client.post(
            reverse("dashboard:tools"),
            data={
                "action": "create_resource",
                "resource-title": "Demo",
                "resource-description": "",
                "resource-resource_type": SharedResource.ResourceType.VIDEO,
                "resource-video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            },
            follow=True,
        )
        created = SharedResource.objects.get(title="Demo")
        response = self.client.get(reverse("dashboard:tools_resource_present", args=[created.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://www.youtube.com/embed/dQw4w9WgXcQ")
        self.assertContains(response, "origin=http%3A%2F%2Ftestserver")
        self.assertContains(response, "widget_referrer=")

    def test_tools_page_rejects_unsupported_video_provider(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.post(
            reverse("dashboard:tools"),
            data={
                "action": "create_resource",
                "resource-title": "Video no soportado",
                "resource-description": "",
                "resource-resource_type": SharedResource.ResourceType.VIDEO,
                "resource-video_url": "https://example.com/video/123",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "El enlace debe ser de YouTube, Vimeo, Loom o Google Drive.")

    def test_tools_page_embeds_google_drive_video_link(self):
        self.client.login(username="rep", password="secretpass123")
        self.client.post(
            reverse("dashboard:tools"),
            data={
                "action": "create_resource",
                "resource-title": "Drive Demo",
                "resource-description": "",
                "resource-resource_type": SharedResource.ResourceType.VIDEO,
                "resource-video_url": "https://drive.google.com/file/d/17tUWkFl--qrShyI/view?usp=sharing",
            },
            follow=True,
        )
        created = SharedResource.objects.get(title="Drive Demo")
        response = self.client.get(reverse("dashboard:tools_resource_present", args=[created.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://drive.google.com/file/d/17tUWkFl--qrShyI/preview")

    def test_google_drive_resourcekey_is_preserved_for_embed(self):
        self.client.login(username="rep", password="secretpass123")
        self.client.post(
            reverse("dashboard:tools"),
            data={
                "action": "create_resource",
                "resource-title": "Drive con resourcekey",
                "resource-description": "",
                "resource-resource_type": SharedResource.ResourceType.VIDEO,
                "resource-video_url": "https://drive.google.com/file/d/FILE123/view?usp=sharing&resourcekey=KEY456",
            },
            follow=True,
        )
        created = SharedResource.objects.get(title="Drive con resourcekey")
        response = self.client.get(reverse("dashboard:tools_resource_present", args=[created.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://drive.google.com/file/d/FILE123/preview?resourcekey=KEY456")

    def test_tools_page_rejects_malformed_google_drive_link(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.post(
            reverse("dashboard:tools"),
            data={
                "action": "create_resource",
                "resource-title": "Drive mal formado",
                "resource-description": "",
                "resource-resource_type": SharedResource.ResourceType.VIDEO,
                "resource-video_url": "https://drive.google.com/drive/folders/123456",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "En Google Drive usa un enlace de archivo compartido valido")

    @override_settings(ALLOWED_HOSTS=["testserver", "127.0.0.1"])
    def test_tools_present_redirects_loopback_ip_to_localhost(self):
        self.client.login(username="rep", password="secretpass123")
        video = SharedResource.objects.create(
            title="Video localhost",
            description="",
            provider="YouTube",
            resource_type=SharedResource.ResourceType.VIDEO,
            video_url="https://youtu.be/dQw4w9WgXcQ",
            created_by=self.user,
        )
        response = self.client.get(
            reverse("dashboard:tools_resource_present", args=[video.pk]),
            HTTP_HOST="127.0.0.1:8000",
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("http://localhost:"))
        self.assertIn(reverse("dashboard:tools_resource_present", args=[video.pk]), response["Location"])

    def test_manager_can_create_announcement_from_tools(self):
        self.client.login(username="manager_hybrid", password="secretpass123")
        response = self.client.post(
            reverse("dashboard:tools"),
            data={
                "action": "create_announcement",
                "announcement-title": "Mantenimiento CRM",
                "announcement-message": "Habra mantenimiento programado.",
                "announcement-start_date": "2026-02-14",
                "announcement-end_date": "2026-02-20",
                "announcement-media_type": Announcement.MediaType.NONE,
                "announcement-is_active": "on",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anuncio publicado correctamente.")
        self.assertTrue(Announcement.objects.filter(title="Mantenimiento CRM").exists())

    def test_announcement_message_allows_safe_formatting_and_strips_scripts(self):
        self.client.login(username="manager_hybrid", password="secretpass123")
        self.client.post(
            reverse("dashboard:tools"),
            data={
                "action": "create_announcement",
                "announcement-title": "Formato seguro",
                "announcement-message": "<p><strong>Hola</strong></p><script>alert('x')</script>",
                "announcement-start_date": "2026-02-14",
                "announcement-end_date": "2026-02-20",
                "announcement-media_type": Announcement.MediaType.NONE,
                "announcement-is_active": "on",
            },
            follow=True,
        )
        created = Announcement.objects.get(title="Formato seguro")
        self.assertIn("<strong>Hola</strong>", created.message)
        self.assertNotIn("<script>", created.message)

    def test_salesrep_cannot_create_announcement_from_tools(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.post(
            reverse("dashboard:tools"),
            data={
                "action": "create_announcement",
                "announcement-title": "No permitido",
                "announcement-message": "test",
                "announcement-start_date": "2026-02-14",
                "announcement-end_date": "2026-02-20",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_manager_can_update_announcement_from_tools(self):
        announcement = Announcement.objects.create(
            title="Inicial",
            message="Mensaje inicial.",
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=2),
            media_type=Announcement.MediaType.NONE,
            is_active=True,
            created_by=self.admin,
        )
        self.client.login(username="manager_hybrid", password="secretpass123")
        response = self.client.post(
            reverse("dashboard:tools"),
            data={
                "action": "update_announcement",
                "announcement_id": announcement.id,
                "announcement-title": "Actualizado",
                "announcement-message": "Mensaje actualizado.",
                "announcement-start_date": timezone.localdate().isoformat(),
                "announcement-end_date": (timezone.localdate() + timedelta(days=3)).isoformat(),
                "announcement-media_type": Announcement.MediaType.NONE,
                "announcement-is_active": "on",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anuncio actualizado correctamente.")
        announcement.refresh_from_db()
        self.assertEqual(announcement.title, "Actualizado")
        self.assertEqual(announcement.message, "Mensaje actualizado.")

    def test_manager_can_delete_announcement_from_tools(self):
        announcement = Announcement.objects.create(
            title="Eliminar",
            message="Eliminar anuncio.",
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=2),
            media_type=Announcement.MediaType.NONE,
            is_active=True,
            created_by=self.admin,
        )
        self.client.login(username="manager_hybrid", password="secretpass123")
        response = self.client.post(
            reverse("dashboard:tools"),
            data={"action": "delete_announcement", "announcement_id": announcement.id},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anuncio eliminado correctamente.")
        self.assertFalse(Announcement.objects.filter(pk=announcement.id).exists())

    def test_salesrep_cannot_update_or_delete_announcement_from_tools(self):
        announcement = Announcement.objects.create(
            title="Protegido",
            message="No editable por asociado.",
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=2),
            media_type=Announcement.MediaType.NONE,
            is_active=True,
            created_by=self.admin,
        )
        self.client.login(username="rep", password="secretpass123")
        update_response = self.client.post(
            reverse("dashboard:tools"),
            data={
                "action": "update_announcement",
                "announcement_id": announcement.id,
                "announcement-title": "Intento",
                "announcement-message": "Intento",
                "announcement-start_date": timezone.localdate().isoformat(),
                "announcement-end_date": (timezone.localdate() + timedelta(days=1)).isoformat(),
                "announcement-media_type": Announcement.MediaType.NONE,
            },
        )
        self.assertEqual(update_response.status_code, 403)

        delete_response = self.client.post(
            reverse("dashboard:tools"),
            data={"action": "delete_announcement", "announcement_id": announcement.id},
        )
        self.assertEqual(delete_response.status_code, 403)

    def test_manager_can_create_offer_from_tools(self):
        self.client.login(username="manager_hybrid", password="secretpass123")
        response = self.client.post(
            reverse("dashboard:tools"),
            data={
                "action": "create_offer",
                "offer-title": "Oferta Producto",
                "offer-message": "Oferta por tiempo limitado.",
                "offer-start_date": "2026-02-14",
                "offer-end_date": "2026-02-20",
                "offer-business_units": [self.bu.id],
                "offer-media_type": Offer.MediaType.NONE,
                "offer-is_active": "on",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Oferta publicada correctamente.")
        self.assertTrue(Offer.objects.filter(title="Oferta Producto").exists())

    def test_salesrep_cannot_create_offer_from_tools(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.post(
            reverse("dashboard:tools"),
            data={
                "action": "create_offer",
                "offer-title": "No permitido",
                "offer-message": "test",
                "offer-start_date": "2026-02-14",
                "offer-end_date": "2026-02-20",
                "offer-business_units": [self.bu.id],
                "offer-media_type": Offer.MediaType.NONE,
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_active_offer_is_visible_in_solar_page(self):
        offer = Offer.objects.create(
            title="Oferta Solar Activa",
            message="Descuento especial.",
            start_date=timezone.localdate() - timedelta(days=1),
            end_date=timezone.localdate() + timedelta(days=2),
            is_active=True,
            media_type=Offer.MediaType.NONE,
            created_by=self.admin,
        )
        solar_unit = BusinessUnit.objects.get(code="solar-home-power")
        offer.business_units.add(solar_unit)
        self.client.login(username="admin_test", password="secretpass123")
        response = self.client.get(reverse("dashboard:unit_solar"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ofertas vigentes")
        self.assertContains(response, "Oferta Solar Activa")

    def test_offer_is_not_visible_in_non_designated_product_page(self):
        offer = Offer.objects.create(
            title="Oferta solo Solar",
            message="No debe salir en Internet.",
            start_date=timezone.localdate() - timedelta(days=1),
            end_date=timezone.localdate() + timedelta(days=2),
            is_active=True,
            media_type=Offer.MediaType.NONE,
            created_by=self.admin,
        )
        solar_unit = BusinessUnit.objects.get(code="solar-home-power")
        offer.business_units.add(solar_unit)
        self.client.login(username="admin_test", password="secretpass123")
        response = self.client.get(reverse("dashboard:unit_internet"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Ofertas vigentes")
        self.assertNotContains(response, "Oferta solo Solar")

    def test_all_product_pages_show_active_offers(self):
        units_and_urls = [
            ("solar-home-power", "dashboard:unit_solar"),
            ("techo", "dashboard:unit_techo"),
            ("sunvida", "dashboard:unit_sunvida"),
            ("cash-d", "dashboard:unit_cash_d"),
            ("agua", "dashboard:unit_agua"),
            ("internet", "dashboard:unit_internet"),
        ]

        created_offers = {}
        for code, _ in units_and_urls:
            unit = BusinessUnit.objects.get(code=code)
            offer = Offer.objects.create(
                title=f"Oferta {code}",
                message=f"Promocion para {code}",
                start_date=timezone.localdate() - timedelta(days=1),
                end_date=timezone.localdate() + timedelta(days=2),
                is_active=True,
                media_type=Offer.MediaType.NONE,
                created_by=self.admin,
            )
            offer.business_units.add(unit)
            created_offers[code] = offer.title

        self.client.login(username="admin_test", password="secretpass123")
        for code, url_name in units_and_urls:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, created_offers[code])

    def test_active_announcement_is_visible_in_admin_overview(self):
        Announcement.objects.create(
            title="Comunicado Oficial",
            message="Nuevo proceso en vigor.",
            start_date=timezone.localdate() - timedelta(days=1),
            end_date=timezone.localdate() + timedelta(days=2),
            is_active=True,
            created_by=self.admin,
        )
        self.client.login(username="admin_test", password="secretpass123")
        response = self.client.get(reverse("dashboard:admin_overview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anuncios vigentes")
        self.assertContains(response, "Comunicado Oficial")

    def test_active_announcement_is_visible_for_salesrep_in_sales_overview(self):
        Announcement.objects.create(
            title="Comunicado Global",
            message="Visible para todos.",
            start_date=timezone.localdate() - timedelta(days=1),
            end_date=timezone.localdate() + timedelta(days=2),
            is_active=True,
            media_type=Announcement.MediaType.NONE,
            created_by=self.admin,
        )
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:sales_overview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anuncios vigentes")
        self.assertContains(response, "Comunicado Global")

    def test_admin_overview_embeds_youtube_announcement_video(self):
        Announcement.objects.create(
            title="Video semanal",
            message="Actualizacion operativa.",
            start_date=timezone.localdate() - timedelta(days=1),
            end_date=timezone.localdate() + timedelta(days=2),
            media_type=Announcement.MediaType.VIDEO,
            video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            is_active=True,
            created_by=self.admin,
        )
        self.client.login(username="admin_test", password="secretpass123")
        response = self.client.get(reverse("dashboard:admin_overview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://www.youtube.com/embed/dQw4w9WgXcQ")
        self.assertContains(response, "origin=http%3A%2F%2Ftestserver")

    def test_admin_overview_embeds_pdf_announcement(self):
        Announcement.objects.create(
            title="PDF operativo",
            message="Manual actualizado.",
            start_date=timezone.localdate() - timedelta(days=1),
            end_date=timezone.localdate() + timedelta(days=2),
            media_type=Announcement.MediaType.PDF,
            media_file=SimpleUploadedFile("manual.pdf", b"%PDF-1.4 test", content_type="application/pdf"),
            is_active=True,
            created_by=self.admin,
        )
        self.client.login(username="admin_test", password="secretpass123")
        response = self.client.get(reverse("dashboard:admin_overview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PDF de anuncio")
        self.assertContains(response, "/media/announcements/")

    def test_expired_announcement_is_not_visible_in_admin_overview(self):
        Announcement.objects.create(
            title="Anuncio Expirado",
            message="Ya no aplica.",
            start_date=timezone.localdate() - timedelta(days=5),
            end_date=timezone.localdate() - timedelta(days=1),
            is_active=True,
            created_by=self.admin,
        )
        self.client.login(username="admin_test", password="secretpass123")
        response = self.client.get(reverse("dashboard:admin_overview"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Anuncios vigentes")
        self.assertNotContains(response, "Anuncio Expirado")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_password_reset_request_sends_email(self):
        response = self.client.post(reverse("password_reset"), data={"email": self.user.email})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Restablecimiento de contraseña", mail.outbox[0].subject)

    def test_password_reset_confirm_page_renders(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        response = self.client.get(
            reverse("password_reset_confirm", kwargs={"uidb64": uidb64, "token": token}),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Crear nueva contraseña")

    def test_grow_team_generates_invitation_register_link(self):
        self.client.login(username="admin_test", password="secretpass123")
        response = self.client.get(reverse("dashboard:grow_team"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/pages/authentication/signup-invited/")

    def test_salesrep_can_access_grow_team(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:grow_team"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Crece tu Equipo")
        self.assertNotContains(response, "Invitar Administrador (Solo Partner)")

    def test_partner_sees_admin_invite_block_in_grow_team(self):
        self.client.login(username="platform_admin", password="secretpass123")
        self.platform_admin.profile.role = UserProfile.Role.PARTNER
        self.platform_admin.profile.save(update_fields=["role"])
        response = self.client.get(reverse("dashboard:grow_team"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invitar Administrador (Solo Partner)")
        self.assertContains(response, "invite_role=admin")

    def test_superadmin_can_invite_partner_but_partner_cannot(self):
        self.client.login(username="admin_test", password="secretpass123")
        superadmin_response = self.client.get(reverse("dashboard:grow_team"))
        self.assertEqual(superadmin_response.status_code, 200)
        self.assertContains(superadmin_response, 'value="PARTNER"')

        self.client.login(username="platform_admin", password="secretpass123")
        self.platform_admin.profile.role = UserProfile.Role.PARTNER
        self.platform_admin.profile.save(update_fields=["role"])
        partner_response = self.client.get(reverse("dashboard:grow_team"))
        self.assertEqual(partner_response.status_code, 200)
        self.assertNotContains(partner_response, 'value="PARTNER"')

    def test_jr_partner_and_business_manager_invite_limits(self):
        jr_user = User.objects.create_user(username="jr_inviter", email="jr_inviter@test.com", password="secretpass123")
        jr_user.profile.role = UserProfile.Role.JR_PARTNER
        jr_user.profile.save(update_fields=["role"])

        bm_user = User.objects.create_user(username="bm_inviter", email="bm_inviter@test.com", password="secretpass123")
        bm_user.profile.role = UserProfile.Role.BUSINESS_MANAGER
        bm_user.profile.save(update_fields=["role"])

        self.client.login(username="jr_inviter", password="secretpass123")
        jr_response = self.client.get(reverse("dashboard:grow_team"))
        self.assertEqual(jr_response.status_code, 200)
        self.assertNotContains(jr_response, 'value="PARTNER"')
        self.assertNotContains(jr_response, 'value="JR_PARTNER"')

        self.client.login(username="bm_inviter", password="secretpass123")
        bm_response = self.client.get(reverse("dashboard:grow_team"))
        self.assertEqual(bm_response.status_code, 200)
        self.assertNotContains(bm_response, 'value="PARTNER"')
        self.assertNotContains(bm_response, 'value="JR_PARTNER"')
        self.assertNotContains(bm_response, 'value="BUSINESS_MANAGER"')

    def test_signup_invited_blocks_manual_bypass_for_higher_role(self):
        inviter = User.objects.create_user(username="bm_direct", email="bm_direct@test.com", password="secretpass123")
        inviter.profile.role = UserProfile.Role.BUSINESS_MANAGER
        inviter.profile.save(update_fields=["role"])

        partner_role, _ = Role.objects.get_or_create(
            code=UserProfile.Role.PARTNER,
            defaults={"name": "Partner", "priority": 100},
        )
        response = self.client.get(reverse("dashboard:signup_invited", args=[inviter.id, partner_role.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You must be invited to register.")

    def test_invitation_register_page_renders_for_valid_token(self):
        token = signing.TimestampSigner(salt="grow-team-invite").sign(f"{self.admin.id}:{UserProfile.Role.PARTNER}")
        response = self.client.get(reverse("dashboard:invitation_register", args=[token]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Crear una nueva cuenta")
        self.assertContains(response, "registrarse como un Partner")
        self.assertNotContains(response, "OneGroup Platform</a>")

    def test_invitation_register_post_creates_consultant_account(self):
        token = signing.TimestampSigner(salt="grow-team-invite").sign(f"{self.admin.id}:{UserProfile.Role.SOLAR_CONSULTANT}")
        response = self.client.post(
            reverse("dashboard:invitation_register", args=[token]),
            data={
                "email": "new.invited@example.com",
                "first_name": "Nuevo",
                "last_name": "Invitado",
                "second_last_name": "Segundo",
                "password1": "T9m!River#829",
                "password2": "T9m!River#829",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        created = User.objects.filter(username="new.invited@example.com").first()
        self.assertIsNotNone(created)
        self.assertEqual(created.profile.role, UserProfile.Role.SOLAR_CONSULTANT)
        self.assertEqual(created.profile.manager_id, self.admin.id)
        self.assertTrue(SalesRep.objects.filter(user=created, second_last_name="Segundo").exists())

    def test_legacy_invite_query_redirects_to_invitation_register(self):
        token = signing.TimestampSigner(salt="grow-team-invite").sign(f"{self.admin.id}:{UserProfile.Role.SOLAR_CONSULTANT}")
        response = self.client.get(f"{reverse('dashboard:sales_overview')}?invite={token}")
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("dashboard:invitation_register", args=[token]), response.url)

    def test_signup_invited_valid_normal_invitation(self):
        inviter = self.user
        level_role, _ = Role.objects.get_or_create(
            code=UserProfile.Role.SOLAR_CONSULTANT,
            defaults={"name": "Solar Consultant", "priority": 30},
        )
        response = self.client.get(reverse("dashboard:signup_invited", args=[inviter.id, level_role.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invitado por")
        self.assertContains(response, "registrarse como un")

    def test_signup_invited_registration_persists_username_as_email(self):
        inviter = self.user
        level_role, _ = Role.objects.get_or_create(
            code=UserProfile.Role.SOLAR_CONSULTANT,
            defaults={"name": "Solar Consultant", "priority": 30},
        )
        response = self.client.post(
            reverse("dashboard:signup_invited", args=[inviter.id, level_role.id]),
            data={
                "email": "Invited.User@Example.com",
                "first_name": "Invited",
                "last_name": "User",
                "second_last_name": "Account",
                "password1": "A!strongpass991",
                "password2": "A!strongpass991",
                "parent_id": inviter.id,
                "level_id": level_role.id,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        created = User.objects.filter(email="invited.user@example.com").first()
        self.assertIsNotNone(created)
        self.assertEqual(created.username, "invited.user@example.com")

    def test_signup_invited_allows_empty_second_last_name(self):
        inviter = self.user
        level_role, _ = Role.objects.get_or_create(
            code=UserProfile.Role.SOLAR_CONSULTANT,
            defaults={"name": "Solar Consultant", "priority": 30},
        )
        response = self.client.post(
            reverse("dashboard:signup_invited", args=[inviter.id, level_role.id]),
            data={
                "email": "nosecond@example.com",
                "first_name": "No",
                "last_name": "Second",
                "second_last_name": "",
                "password1": "C!strongpass991",
                "password2": "C!strongpass991",
                "parent_id": inviter.id,
                "level_id": level_role.id,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        created = User.objects.filter(email="nosecond@example.com").first()
        self.assertIsNotNone(created)

    def test_signup_invited_redirects_to_login_after_submit(self):
        inviter = self.user
        level_role, _ = Role.objects.get_or_create(
            code=UserProfile.Role.SOLAR_CONSULTANT,
            defaults={"name": "Solar Consultant", "priority": 30},
        )
        response = self.client.post(
            reverse("dashboard:signup_invited", args=[inviter.id, level_role.id]),
            data={
                "email": "redirect.login@example.com",
                "first_name": "Redirect",
                "last_name": "Login",
                "second_last_name": "",
                "password1": "D!strongpass991",
                "password2": "D!strongpass991",
                "parent_id": inviter.id,
                "level_id": level_role.id,
            },
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("login"))

    def test_signup_invited_inherits_inviter_scope_without_salesrep_profile(self):
        inviter = User.objects.create_user(
            username="inviter_no_salesrep",
            email="inviter_no_salesrep@example.com",
            password="secretpass123",
        )
        inviter.profile.role = UserProfile.Role.MANAGER
        inviter.profile.business_unit = self.other_bu
        inviter.profile.save(update_fields=["role", "business_unit"])
        inviter.profile.business_units.add(self.other_bu)

        level_role, _ = Role.objects.get_or_create(
            code=UserProfile.Role.SOLAR_CONSULTANT,
            defaults={"name": "Solar Consultant", "priority": 30},
        )
        response = self.client.post(
            reverse("dashboard:signup_invited", args=[inviter.id, level_role.id]),
            data={
                "email": "inherit.scope@example.com",
                "first_name": "Inherit",
                "last_name": "Scope",
                "second_last_name": "",
                "password1": "D!strongpass992",
                "password2": "D!strongpass992",
                "parent_id": inviter.id,
                "level_id": level_role.id,
            },
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("login"))

        created = User.objects.get(email="inherit.scope@example.com")
        self.assertEqual(created.profile.manager_id, inviter.id)
        self.assertEqual(created.profile.role, UserProfile.Role.SOLAR_CONSULTANT)
        self.assertEqual(created.sales_rep_profile.business_unit_id, self.other_bu.id)

    def test_signup_invited_admin_invitation_valid_sets_pending(self):
        partner = User.objects.create_user(username="partner_signup", email="partner_signup@example.com", password="secretpass123")
        partner.profile.role = UserProfile.Role.PARTNER
        partner.profile.business_unit = self.bu
        partner.profile.save(update_fields=["role", "business_unit"])
        partner.profile.business_units.add(self.bu)
        SalesRep.objects.create(user=partner, business_unit=self.bu, tier=self.tier)

        level_role, _ = Role.objects.get_or_create(
            code=UserProfile.Role.ADMINISTRADOR,
            defaults={"name": "Administrador", "priority": 90},
        )
        admin_invite = AdminInviteRequest.objects.create(
            token="admin-token-valid-001",
            inviter=partner,
            level=level_role,
            status=AdminInviteRequest.Status.INVITED,
            expires_at=timezone.now() + timedelta(hours=1),
        )

        response = self.client.post(
            reverse("dashboard:signup_invited", args=[partner.id, level_role.id]) + "?invite_role=admin&invite_token=admin-token-valid-001",
            data={
                "email": "admin.invited@example.com",
                "first_name": "Admin",
                "last_name": "Invited",
                "second_last_name": "Pending",
                "password1": "B!strongpass991",
                "password2": "B!strongpass991",
                "parent_id": partner.id,
                "level_id": level_role.id,
                "invite_role": "admin",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        admin_invite.refresh_from_db()
        self.assertEqual(admin_invite.status, AdminInviteRequest.Status.PENDING)
        self.assertIsNotNone(admin_invite.invited_user_id)
        self.assertIsNotNone(admin_invite.used_at)

    def test_signup_invited_admin_invitation_invalid_or_expired_blocks(self):
        partner = User.objects.create_user(username="partner_expired", email="partner_expired@example.com", password="secretpass123")
        partner.profile.role = UserProfile.Role.PARTNER
        partner.profile.business_unit = self.bu
        partner.profile.save(update_fields=["role", "business_unit"])
        level_role, _ = Role.objects.get_or_create(
            code=UserProfile.Role.ADMINISTRADOR,
            defaults={"name": "Administrador", "priority": 90},
        )
        AdminInviteRequest.objects.create(
            token="admin-token-expired-001",
            inviter=partner,
            level=level_role,
            status=AdminInviteRequest.Status.INVITED,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        response = self.client.get(
            reverse("dashboard:signup_invited", args=[partner.id, level_role.id]) + "?invite_role=admin&invite_token=admin-token-expired-001"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You must be invited to register.")

    def test_signup_invited_without_invitation_blocked(self):
        response = self.client.get(reverse("dashboard:signup_invited", args=[999999, 999999]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You must be invited to register.")

    def test_signup_invited_renders_even_when_user_is_authenticated(self):
        inviter = self.user
        level_role, _ = Role.objects.get_or_create(
            code=UserProfile.Role.SOLAR_CONSULTANT,
            defaults={"name": "Solar Consultant", "priority": 30},
        )
        self.client.login(username="admin_test", password="secretpass123")
        response = self.client.get(reverse("dashboard:signup_invited", args=[inviter.id, level_role.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Crear una nueva cuenta")

    def test_salesrep_can_access_all_business_unit_pages(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:unit_solar"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Propuesta Solar")
        self.assertContains(response, "Cotizador")
        self.assertContains(response, "Accede SUNRUN")
        self.assertContains(response, "Accede a tu Correo", count=1)
        self.assertContains(response, "Cliente Residencial")
        self.assertContains(response, "Venta Residencial")
        self.assertContains(response, "Cliente Comercial")
        self.assertContains(response, "Venta Comercial")
        self.assertContains(response, reverse("dashboard:solar_client_residential"))
        self.assertContains(response, reverse("dashboard:solar_sale_residential"))
        self.assertContains(response, reverse("dashboard:solar_client_commercial"))
        self.assertContains(response, reverse("dashboard:solar_sale_commercial"))

        response = self.client.get(reverse("dashboard:unit_internet"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Propuesta Solar")

        response = self.client.get(reverse("dashboard:unit_techo"))
        self.assertEqual(response.status_code, 200)

    def test_solar_segment_pages_are_available(self):
        self.client.login(username="rep", password="secretpass123")

        client_res = self.client.get(reverse("dashboard:solar_client_residential"))
        self.assertEqual(client_res.status_code, 200)
        self.assertContains(client_res, "Cliente Residencial")
        self.assertContains(client_res, "Clientes Totales")

        sale_res = self.client.get(reverse("dashboard:solar_sale_residential"))
        self.assertEqual(sale_res.status_code, 200)
        self.assertContains(sale_res, "Venta Residencial")
        self.assertContains(sale_res, "Ventas Totales")

        client_com = self.client.get(reverse("dashboard:solar_client_commercial"))
        self.assertEqual(client_com.status_code, 200)
        self.assertContains(client_com, "Cliente Comercial")
        self.assertContains(client_com, "Clientes Totales")

        sale_com = self.client.get(reverse("dashboard:solar_sale_commercial"))
        self.assertEqual(sale_com.status_code, 200)
        self.assertContains(sale_com, "Venta Comercial")
        self.assertContains(sale_com, "Ventas Totales")

    def test_salesrep_profile_page_get_and_post(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:associate_profile"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("dashboard:associate_profile"),
            data={
                "first_name": "Carlos",
                "last_name": "Andujar",
                "email": "carlos@example.com",
                "phone": "(555)100-2000",
                "second_last_name": "Ortiz",
                "postal_address_line_1": "Urb Villa el Recreo",
                "postal_address_line_2": "AA19 CALLE 2",
                "postal_city": "Yabucoa",
                "postal_state": "PR",
                "postal_zip_code": "00767-3433",
                "physical_same_as_postal": "on",
                "hire_date": "2026-01-01",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Carlos")
        self.assertEqual(self.user.last_name, "Andujar")
        self.assertEqual(self.user.email, "carlos@example.com")

        rep = SalesRep.objects.get(user=self.user)
        self.assertEqual(rep.phone, "(555)100-2000")
        self.assertEqual(rep.second_last_name, "Ortiz")
        self.assertEqual(rep.postal_address_line_1, "Urb Villa el Recreo")
        self.assertEqual(rep.postal_address_line_2, "AA19 CALLE 2")
        self.assertEqual(rep.postal_city, "Yabucoa")
        self.assertEqual(rep.postal_state, "PR")
        self.assertEqual(rep.postal_zip_code, "00767-3433")
        self.assertTrue(rep.physical_same_as_postal)
        self.assertEqual(rep.physical_address_line_1, "Urb Villa el Recreo")
        self.assertEqual(rep.physical_city, "Yabucoa")
        self.assertEqual(rep.physical_state, "PR")
        self.assertEqual(rep.physical_zip_code, "00767-3433")
        self.assertEqual(self.user.profile.hire_date, parse_date("2026-01-01"))

    def test_avatar_requires_valid_image_file(self):
        self.client.login(username="rep", password="secretpass123")
        oversized = SimpleUploadedFile("avatar.jpg", b"x" * (2 * 1024 * 1024 + 1), content_type="image/jpeg")
        response = self.client.post(
            reverse("dashboard:associate_profile"),
            data={
                "first_name": "Carlos",
                "last_name": "Andujar",
                "email": "carlos@example.com",
                "phone": "(555)100-2000",
                "postal_address_line_1": "PO Box 999",
                "postal_city": "Yabucoa",
                "postal_state": "PR",
                "postal_zip_code": "00767",
                "physical_same_as_postal": "on",
                "hire_date": "2026-01-01",
                "avatar": oversized,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "imagen válida")

    def test_phone_must_match_required_format(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.post(
            reverse("dashboard:associate_profile"),
            data={
                "first_name": "Carlos",
                "last_name": "Andujar",
                "email": "carlos@example.com",
                "phone": "5551002000",
                "postal_address_line_1": "Urb Villa el Recreo",
                "postal_city": "Yabucoa",
                "postal_state": "PR",
                "postal_zip_code": "00767-3433",
                "physical_same_as_postal": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Use teléfono en formato (XXX)XXX-XXXX.")

    def test_admin_can_open_profile_page(self):
        self.client.login(username="admin_test", password="secretpass123")
        response = self.client.get(reverse("dashboard:associate_profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="hire_date"')
        self.assertContains(response, 'name="avatar"')

    def test_admin_can_update_hire_date_in_profile(self):
        self.client.login(username="admin_test", password="secretpass123")
        response = self.client.post(
            reverse("dashboard:associate_profile"),
            data={
                "active_tab": "pane-work",
                "first_name": "Admin",
                "last_name": "Test",
                "email": "admin@test.com",
                "hire_date": "2025-10-10",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.admin.profile.refresh_from_db()
        self.assertEqual(self.admin.profile.hire_date, parse_date("2025-10-10"))

    def test_personal_tab_can_save_without_address_fields(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.post(
            reverse("dashboard:associate_profile"),
            data={
                "active_tab": "pane-personal",
                "first_name": "Carlos",
                "last_name": "Andujar",
                "email": "carlos.personal@example.com",
                "phone": "(787)555-1234",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "carlos.personal@example.com")
        rep = SalesRep.objects.get(user=self.user)
        self.assertEqual(rep.phone, "(787)555-1234")


class TeamPersonalInfoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.bu = BusinessUnit.objects.create(name="Internet", code="internet-team-personal")
        self.tier = Tier.objects.create(name="Base Team", rank=99)
        self.partner = User.objects.create_user(username="partner_tp", password="secretpass123")
        self.manager = User.objects.create_user(username="manager_tp", password="secretpass123")
        self.consultant = User.objects.create_user(username="consultant_tp", email="consultant@zensell.ai", password="secretpass123")
        self.advisor = User.objects.create_user(username="advisor_tp", email="advisor@zensell.ai", password="secretpass123")

        self.partner.profile.role = UserProfile.Role.PARTNER
        self.partner.profile.save(update_fields=["role", "role_ref"])
        self.manager.profile.role = UserProfile.Role.MANAGER
        self.manager.profile.manager = self.partner
        self.manager.profile.business_unit = self.bu
        self.manager.profile.save(update_fields=["role", "role_ref", "manager", "business_unit"])
        self.manager.profile.business_units.add(self.bu)

        self.consultant.profile.role = UserProfile.Role.SOLAR_CONSULTANT
        self.consultant.profile.manager = self.partner
        self.consultant.profile.business_unit = self.bu
        self.consultant.profile.save(update_fields=["role", "role_ref", "manager", "business_unit"])
        self.advisor.profile.role = UserProfile.Role.SOLAR_ADVISOR
        self.advisor.profile.manager = self.manager
        self.advisor.profile.business_unit = self.bu
        self.advisor.profile.save(update_fields=["role", "role_ref", "manager", "business_unit"])

        SalesRep.objects.create(
            user=self.consultant,
            business_unit=self.bu,
            tier=self.tier,
            phone="(787)598-5039",
            postal_city="Yabucoa",
            is_active=True,
        )
        SalesRep.objects.create(
            user=self.advisor,
            business_unit=self.bu,
            tier=self.tier,
            phone="(787)500-0000",
            postal_city="Humacao",
            is_active=True,
        )

    def test_access_denied_without_team_permission(self):
        outsider = User.objects.create_user(username="outsider_tp", password="secretpass123")
        self.client.login(username="outsider_tp", password="secretpass123")
        response = self.client.get(reverse("dashboard:associates_info"), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No tienes permisos para acceder a Mi Equipo.")

    def test_partner_data_hidden_for_non_partner_actor(self):
        actor = self.manager
        rows = [
            {
                "full_name": "Partner Row",
                "level_name": "Partner",
                "partner_name": "partner_tp",
                "parent_name": "",
                "partner_rate": 10,
                "is_operations_admin": False,
            },
            {
                "full_name": "Consultant Row",
                "level_name": "Solar Consultant",
                "partner_name": "partner_tp",
                "parent_name": "partner_tp",
                "partner_rate": 5,
                "is_operations_admin": False,
            },
        ]
        sanitized = sanitize_team_payload_for_actor(rows, actor)
        self.assertEqual(len(sanitized), 1)
        self.assertEqual(sanitized[0]["full_name"], "Consultant Row")
        self.assertEqual(sanitized[0]["partner_name"], "")
        self.assertEqual(sanitized[0]["partner_rate"], 0)
        self.assertEqual(sanitized[0]["parent_name"], "")

    def test_level_and_city_filters_work_in_api(self):
        self.client.login(username="partner_tp", password="secretpass123")
        response = self.client.get(
            reverse("dashboard:salesrep_profile_api"),
            {
                "format": "datatables",
                "draw": 1,
                "start": 0,
                "length": 25,
                "level": "Solar Consultant",
                "city": "Yabucoa",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["recordsFiltered"], 1)
        self.assertEqual(payload["data"][0]["city"], "Yabucoa")
        self.assertEqual(payload["data"][0]["level_name"], "Solar Consultant")

    def test_contactable_pct_calculation(self):
        metrics = compute_team_personal_metrics(
            [
                {"phone": "(787)111-1111", "email": "a@a.com", "level_name": "Solar Consultant", "city": "Yabucoa"},
                {"phone": "(787)222-2222", "email": "", "level_name": "Solar Advisor", "city": "Humacao"},
            ]
        )
        self.assertEqual(metrics["team_totals"]["total"], 2)
        self.assertEqual(metrics["team_totals"]["fully_contactable"], 1)
        self.assertEqual(metrics["team_totals"]["contactable_pct"], 50.0)


class SalesTeamTests(TestCase):
    def setUp(self):
        cache.clear()
        self.bu = BusinessUnit.objects.create(name="Solar Sales Team", code="solar-team")
        self.tier = Tier.objects.create(name="Team Base", rank=10)

        self.partner = User.objects.create_user(username="partner_st", password="secretpass123", email="partner_st@example.com")
        self.manager = User.objects.create_user(username="manager_st", password="secretpass123", email="manager_st@example.com")
        self.manager_direct = User.objects.create_user(username="manager_direct_st", password="secretpass123", email="manager_direct_st@example.com")
        self.jr_partner = User.objects.create_user(username="jr_partner_st", password="secretpass123", email="jr_partner_st@example.com")
        self.consultant = User.objects.create_user(
            username="consultant_st",
            password="secretpass123",
            email="consultant_st@example.com",
            first_name="Carlos",
            last_name="Andujar",
        )
        self.advisor = User.objects.create_user(username="advisor_st", password="secretpass123", email="advisor_st@example.com")

        self.partner.profile.role = UserProfile.Role.PARTNER
        self.partner.profile.business_unit = self.bu
        self.partner.profile.save(update_fields=["role", "business_unit"])
        self.partner.profile.business_units.add(self.bu)

        self.manager.profile.role = UserProfile.Role.SENIOR_MANAGER
        self.manager.profile.manager = self.partner
        self.manager.profile.business_unit = self.bu
        self.manager.profile.save(update_fields=["role", "manager", "business_unit"])
        self.manager.profile.business_units.add(self.bu)

        self.manager_direct.profile.role = UserProfile.Role.MANAGER
        self.manager_direct.profile.manager = self.partner
        self.manager_direct.profile.business_unit = self.bu
        self.manager_direct.profile.save(update_fields=["role", "manager", "business_unit"])
        self.manager_direct.profile.business_units.add(self.bu)

        self.jr_partner.profile.role = UserProfile.Role.JR_PARTNER
        self.jr_partner.profile.manager = self.partner
        self.jr_partner.profile.business_unit = self.bu
        self.jr_partner.profile.save(update_fields=["role", "manager", "business_unit"])
        self.jr_partner.profile.business_units.add(self.bu)

        self.advisor.profile.role = UserProfile.Role.SOLAR_ADVISOR
        self.advisor.profile.manager = self.manager
        self.advisor.profile.business_unit = self.bu
        self.advisor.profile.save(update_fields=["role", "manager", "business_unit"])
        self.advisor.profile.business_units.add(self.bu)

        self.consultant.profile.role = UserProfile.Role.SOLAR_CONSULTANT
        self.consultant.profile.manager = self.advisor
        self.consultant.profile.business_unit = self.bu
        self.consultant.profile.save(update_fields=["role", "manager", "business_unit"])

        SalesRep.objects.create(user=self.partner, business_unit=self.bu, tier=self.tier, phone="(787)100-1000", postal_city="Aibonito")
        SalesRep.objects.create(user=self.manager, business_unit=self.bu, tier=self.tier, phone="(787)200-2000", postal_city="Yabucoa")
        SalesRep.objects.create(user=self.manager_direct, business_unit=self.bu, tier=self.tier, phone="(787)555-7777", postal_city="Yabucoa")
        SalesRep.objects.create(user=self.jr_partner, business_unit=self.bu, tier=self.tier, phone="(787)555-9999", postal_city="Yabucoa")
        self.consultant_rep = SalesRep.objects.create(
            user=self.consultant,
            business_unit=self.bu,
            tier=self.tier,
            phone="(787)598-5039",
            postal_city="Yabucoa",
        )
        SalesRep.objects.create(user=self.advisor, business_unit=self.bu, tier=self.tier, phone="(787)300-3000", postal_city="Humacao")

    def test_sales_team_access_denied_without_permission(self):
        outsider = User.objects.create_user(username="outsider_st", password="secretpass123")
        self.client.login(username="outsider_st", password="secretpass123")
        response = self.client.get(reverse("dashboard:apps_crm_sales_team_view"), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No tienes permisos para acceder a Mi Equipo.")

    def test_sales_team_partner_data_hidden_for_non_partner(self):
        self.client.login(username="manager_st", password="secretpass123")
        response = self.client.get(
            reverse("dashboard:salesrep_profile_api"),
            {"view": "salesteam", "format": "datatables"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertTrue(all(row["level_name"] != "Partner" for row in payload))
        self.assertTrue(all((row.get("partner_name") or "") == "" for row in payload))

    def test_sales_team_filter_level_and_sponsor(self):
        self.client.login(username="partner_st", password="secretpass123")
        response = self.client.get(
            reverse("dashboard:salesrep_profile_api"),
            {
                "view": "salesteam",
                "format": "datatables",
                "level": "Solar Consultant",
                "parent": "advisor_st",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["recordsFiltered"], 1)
        self.assertEqual(payload["data"][0]["full_name"], "Carlos Andujar")

    def test_sales_team_contactable_pct_calculation(self):
        summary = compute_sales_team_summary(
            [
                {"phone": "(787)111-1111", "username": "corp1", "level_name": "Solar Consultant", "sort_value": 30},
                {"phone": "", "username": "corp2", "level_name": "Manager", "sort_value": 50},
            ],
            self.partner.profile,
        )
        self.assertEqual(summary["team_totals"]["total"], 2)
        self.assertEqual(summary["team_totals"]["contactable"], 1)
        self.assertEqual(summary["team_totals"]["contactable_pct"], 50.0)

    def test_sales_team_commission_distribution_for_consultant_chain(self):
        self.client.login(username="partner_st", password="secretpass123")
        response = self.client.get(
            reverse("dashboard:salesrep_profile_api"),
            {"view": "salesteam", "format": "datatables", "level": "Solar Consultant"},
        )
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]
        consultant_row = next(row for row in rows if row["username"] == "consultant_st")
        self.assertAlmostEqual(float(consultant_row["solar_consultant_rate"]), 0.06, places=3)
        self.assertAlmostEqual(float(consultant_row["solar_advisor_rate"]), 0.06, places=3)
        self.assertAlmostEqual(float(consultant_row["senior_manager_rate"]), 0.02, places=3)
        self.assertAlmostEqual(float(consultant_row["partner_rate"]), 0.05, places=3)

    def test_sales_team_commission_distribution_for_manager_direct_to_partner(self):
        self.client.login(username="partner_st", password="secretpass123")
        response = self.client.get(
            reverse("dashboard:salesrep_profile_api"),
            {"view": "salesteam", "format": "datatables", "level": "Manager"},
        )
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]
        manager_row = next(row for row in rows if row["username"] == "manager_direct_st")
        self.assertAlmostEqual(float(manager_row["manager_rate"]), 0.13, places=3)
        self.assertAlmostEqual(float(manager_row["partner_rate"]), 0.06, places=3)

    def test_sales_team_commission_distribution_for_jr_partner_direct_to_partner(self):
        self.client.login(username="partner_st", password="secretpass123")
        response = self.client.get(
            reverse("dashboard:salesrep_profile_api"),
            {"view": "salesteam", "format": "datatables", "level": "Jr Partner"},
        )
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]
        jr_row = next(row for row in rows if row["username"] == "jr_partner_st")
        self.assertAlmostEqual(float(jr_row["jr_partner_rate"]), 0.17, places=3)
        self.assertAlmostEqual(float(jr_row["partner_rate"]), 0.02, places=3)

    def test_sales_team_partner_rate_visible_for_partner_chain_only(self):
        self.client.login(username="partner_st", password="secretpass123")
        response = self.client.get(
            reverse("dashboard:salesrep_profile_api"),
            {"view": "salesteam", "format": "datatables"},
        )
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]
        own_row = next(row for row in rows if row["username"] == "partner_st")
        self.assertAlmostEqual(float(own_row.get("partner_rate") or 0), 0.19, places=3)
        jr_row = next(row for row in rows if row["username"] == "jr_partner_st")
        self.assertAlmostEqual(float(jr_row.get("partner_rate") or 0), 0.02, places=3)

        self.client.login(username="manager_st", password="secretpass123")
        manager_response = self.client.get(
            reverse("dashboard:salesrep_profile_api"),
            {"view": "salesteam", "format": "datatables"},
        )
        self.assertEqual(manager_response.status_code, 200)
        manager_rows = manager_response.json()["data"]
        self.assertTrue(all(float(row.get("partner_rate") or 0) == 0 for row in manager_rows))

    def test_sales_team_parent_rate_is_hidden_for_all_users(self):
        self.client.login(username="partner_st", password="secretpass123")
        response = self.client.get(
            reverse("dashboard:salesrep_profile_api"),
            {"view": "salesteam", "format": "datatables"},
        )
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]
        self.assertTrue(all(float(row.get("parent_rate") or 0) == 0 for row in rows))

    def test_sales_team_modal_action_ajax_success(self):
        self.client.login(username="partner_st", password="secretpass123")
        response = self.client.post(
            reverse("dashboard:salesrep_promotion_modal", args=[self.consultant_rep.id]),
            {"reason": "Promocion por desempeño"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])

    def test_admin_invite_action_approve(self):
        invite = OperationsAdminInviteRequest.objects.create(
            invited_user=self.consultant,
            inviter_partner=self.partner,
            status=OperationsAdminInviteRequest.Status.PENDING,
            expires_at=timezone.now() + timedelta(days=2),
        )
        self.client.login(username="partner_st", password="secretpass123")
        response = self.client.post(
            reverse("dashboard:apps_crm_salesteam_admin_invite_action", args=[invite.id]),
            {"action": "approve"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        invite.refresh_from_db()
        self.assertEqual(invite.status, OperationsAdminInviteRequest.Status.APPROVED)


class SalesTeamGraphTests(TestCase):
    def setUp(self):
        self.bu = BusinessUnit.objects.create(name="Graph BU", code="graph-bu")
        self.tier = Tier.objects.create(name="Graph Tier", rank=20)

        self.partner = User.objects.create_user(username="partner_graph", password="secretpass123", email="partner_graph@example.com")
        self.partner.profile.role = UserProfile.Role.PARTNER
        self.partner.profile.business_unit = self.bu
        self.partner.profile.save(update_fields=["role", "business_unit"])
        self.partner.profile.business_units.add(self.bu)
        self.partner_rep = SalesRep.objects.create(
            user=self.partner,
            business_unit=self.bu,
            tier=self.tier,
            phone="(787)777-7777",
            postal_city="Yabucoa",
            postal_state="PR",
            is_active=True,
        )

    def test_graph_access_denied_without_permission(self):
        outsider = User.objects.create_user(username="outsider_graph", password="secretpass123")
        self.client.login(username="outsider_graph", password="secretpass123")
        response = self.client.get(reverse("dashboard:apps_crm_salesteam_graph"), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No tienes permisos para acceder a Mi Equipo.")

    def test_graph_user_without_salesrep_profile(self):
        manager = User.objects.create_user(username="manager_graph", password="secretpass123")
        manager.profile.role = UserProfile.Role.MANAGER
        manager.profile.business_unit = self.bu
        manager.profile.save(update_fields=["role", "business_unit"])
        manager.profile.business_units.add(self.bu)
        self.client.login(username="manager_graph", password="secretpass123")
        response = self.client.get(reverse("dashboard:apps_crm_salesteam_graph"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mapa de Jerarquía")

    def test_graph_csv_has_expected_headers(self):
        self.client.login(username="partner_graph", password="secretpass123")
        response = self.client.get(reverse("dashboard:apps_crm_salesteam_graph_source"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="hierarchy.csv"')
        first_line = response.content.decode("utf-8").splitlines()[0]
        self.assertEqual(
            first_line,
            "name,imageUrl,area,profileUrl,office,tags,isLoggedUser,positionName,id,parentId,size",
        )

    def test_graph_csv_dataset_empty_and_non_empty(self):
        self.client.login(username="partner_graph", password="secretpass123")
        non_empty = self.client.get(reverse("dashboard:apps_crm_salesteam_graph_source"))
        self.assertGreaterEqual(len(non_empty.content.decode("utf-8").splitlines()), 2)

        self.partner_rep.is_active = False
        self.partner_rep.save(update_fields=["is_active"])
        empty = self.client.get(reverse("dashboard:apps_crm_salesteam_graph_source"))
        self.assertEqual(len(empty.content.decode("utf-8").splitlines()), 1)

    def test_graph_uses_parent_fallback_when_manager_profile_link_is_missing(self):
        missing_manager = User.objects.create_user(username="missing_manager_graph", password="secretpass123")
        child = User.objects.create_user(
            username="child_graph",
            password="secretpass123",
            first_name="Child",
            last_name="Graph",
            email="child_graph@example.com",
        )
        child.profile.role = UserProfile.Role.SOLAR_CONSULTANT
        child.profile.business_unit = self.bu
        child.profile.manager = missing_manager
        child.profile.save(update_fields=["role", "business_unit", "manager"])
        child.profile.business_units.add(self.bu)
        SalesRep.objects.create(
            user=child,
            business_unit=self.bu,
            tier=self.tier,
            parent=self.partner_rep,
            is_active=True,
        )

        cache.clear()
        self.client.login(username="partner_graph", password="secretpass123")
        response = self.client.get(reverse("dashboard:apps_crm_salesteam_graph_source"))
        self.assertEqual(response.status_code, 200)
        csv_content = response.content.decode("utf-8")
        self.assertIn("Child Graph", csv_content)
