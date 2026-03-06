from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from core.models import BusinessUnit, Role
from core.rbac.constants import RoleCode
from crm.models import SalesRep
from crm.models import SalesrepLevel

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
