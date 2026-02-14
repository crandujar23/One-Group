from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.models import BusinessUnit, UserProfile
from crm.models import SalesRep
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
        self.user = User.objects.create_user(username="rep", password="secretpass123")
        self.admin = User.objects.create_superuser(username="admin_test", email="admin@test.com", password="secretpass123")
        profile = self.user.profile
        profile.role = UserProfile.Role.SALES_REP
        profile.business_unit = self.bu
        profile.save(update_fields=["role", "business_unit"])
        SalesRep.objects.create(user=self.user, business_unit=self.bu, tier=self.tier)

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
        self.assertNotContains(response, "OneGroup Platform</a>")

    def test_salesrep_can_access_all_business_unit_pages(self):
        self.client.login(username="rep", password="secretpass123")
        response = self.client.get(reverse("dashboard:unit_internet"))
        self.assertEqual(response.status_code, 200)

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
