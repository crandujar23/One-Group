from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils import timezone

from core.models import BusinessUnit, UserProfile
from crm.models import CallLog, SalesRep
from dashboard.models import Announcement
from dashboard.models import Offer
from dashboard.models import SharedResource
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
        self.manager_hybrid.profile.role = UserProfile.Role.MANAGER
        self.manager_hybrid.profile.business_unit = self.bu
        self.manager_hybrid.profile.save(update_fields=["role", "business_unit"])
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

    def test_salesrep_cannot_access_admin_overview(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:admin_overview"))
        self.assertEqual(response.status_code, 403)

    def test_salesrep_can_access_associate_only_pages(self):
        self.client.login(username="rep", password="secretpass123")
        points = self.client.get(reverse("dashboard:points_summary"))
        self.assertEqual(points.status_code, 200)
        create_call_log = self.client.get(reverse("dashboard:call_log_create"))
        self.assertEqual(create_call_log.status_code, 200)

    def test_manager_with_salesrep_record_does_not_get_associate_permissions(self):
        self.client.login(username="manager_hybrid", password="secretpass123")

        points = self.client.get(reverse("dashboard:points_summary"))
        self.assertEqual(points.status_code, 403)

        create_call_log = self.client.get(reverse("dashboard:call_log_create"))
        self.assertEqual(create_call_log.status_code, 403)

        call_logs = self.client.get(reverse("dashboard:call_logs"))
        self.assertEqual(call_logs.status_code, 200)
        self.assertContains(call_logs, "Llamada asociada")
        self.assertContains(call_logs, "Llamada manager")
        self.assertNotContains(call_logs, "Nuevo registro")

        sales_list = self.client.get(reverse("dashboard:sales_list"))
        self.assertEqual(sales_list.status_code, 200)
        self.assertNotContains(sales_list, reverse("dashboard:points_summary"))

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
        response = self.client.get(reverse("dashboard:home"))
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

    def test_platform_admin_can_create_associate_access(self):
        self.client.login(username="platform_admin", password="secretpass123")
        response = self.client.get(reverse("dashboard:associate_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Crear Nuevo Asociado")

        response = self.client.post(
            reverse("dashboard:associate_create"),
            data={
                "username": "rep_new_access",
                "email": "rep_new_access@test.com",
                "first_name": "Rep",
                "last_name": "Nuevo",
                "password": "TempPass123!",
                "business_units": [self.bu.id],
                "tier": self.tier.id,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Asociado creado: rep_new_access")
        created_user = User.objects.get(username="rep_new_access")
        self.assertEqual(created_user.profile.role, UserProfile.Role.SALES_REP)
        self.assertTrue(SalesRep.objects.filter(user=created_user, business_unit=self.bu).exists())

    def test_manager_cannot_access_associate_create(self):
        self.client.login(username="manager_hybrid", password="secretpass123")
        response = self.client.get(reverse("dashboard:associate_create"))
        self.assertEqual(response.status_code, 403)

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
        response = self.client.get(reverse("password_reset_confirm", kwargs={"uidb64": uidb64, "token": token}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Crear nueva contraseña")

    def test_salesrep_can_access_all_business_unit_pages(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:unit_solar"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Asesor Energetico")
        self.assertContains(response, "Cotizador")
        self.assertContains(response, "Accede SUNRUN")
        self.assertContains(response, "Accede a tu Correo")

        response = self.client.get(reverse("dashboard:unit_internet"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Asesor Energetico")

        response = self.client.get(reverse("dashboard:unit_techo"))
        self.assertEqual(response.status_code, 200)

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
        self.assertContains(response, "Upload a valid image")

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
