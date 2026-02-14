from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from core.models import BusinessUnit, UserProfile
from crm.models import SalesRep
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
        profile = self.user.profile
        profile.role = UserProfile.Role.SALES_REP
        profile.business_unit = self.bu
        profile.save(update_fields=["role", "business_unit"])
        SalesRep.objects.create(user=self.user, business_unit=self.bu, tier=self.tier)
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
        self.assertContains(response, "Productos")
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
        self.assertContains(response, "Superadmin")

    def test_admin_grouped_operations_menu_hides_points(self):
        self.client.login(username="admin_test", password="secretpass123")
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gestión Comercial")
        self.assertContains(response, reverse("dashboard:sales_list"))
        self.assertContains(response, reverse("dashboard:financing"))
        self.assertContains(response, reverse("dashboard:call_logs"))
        self.assertNotContains(response, reverse("dashboard:points_summary"))

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
        self.assertContains(response, "Accede Tu Email")

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
