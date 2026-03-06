from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse

from core.models import ModulePermission
from core.models import Role
from core.models import RoleChangeAudit
from core.models import UserProfile
from core.rbac.constants import ModuleCode
from core.rbac.constants import RoleCode
from core.rbac.services import assign_role
from core.rbac.services import can_approve
from core.rbac.services import can_manage
from core.rbac.services import can_view
from core.rbac.services import ensure_seeded_roles_and_permissions

User = get_user_model()


class RBACBaseTestCase(TestCase):
    def setUp(self):
        ensure_seeded_roles_and_permissions()

    def set_role(self, user, role_code, manager=None):
        role = Role.objects.get(code=role_code)
        profile = user.profile
        profile.role = role_code
        profile.role_ref = role
        profile.manager = manager
        profile.save(update_fields=["role", "role_ref", "manager"])
        return profile


class UserProfileSmokeTests(RBACBaseTestCase):
    def test_profile_is_created_automatically(self):
        user = User.objects.create_user(username="john", password="secretpass123")
        self.assertTrue(hasattr(user, "profile"))
        self.assertEqual(user.profile.role, UserProfile.Role.SOLAR_CONSULTANT)

    def test_seed_creates_full_hierarchy(self):
        self.assertEqual(Role.objects.count(), 9)
        self.assertTrue(Role.objects.filter(code=RoleCode.PARTNER, priority=100).exists())
        self.assertTrue(Role.objects.filter(code=RoleCode.SOLAR_CONSULTANT, priority=30).exists())
        self.assertEqual(ModulePermission.objects.count(), 15)


class AuthorizationServiceTests(RBACBaseTestCase):
    def setUp(self):
        super().setUp()
        self.partner = User.objects.create_user(username="partner", password="secretpass123")
        self.admin = User.objects.create_user(username="admin", password="secretpass123")
        self.manager = User.objects.create_user(username="manager", password="secretpass123")
        self.advisor = User.objects.create_user(username="advisor", password="secretpass123")
        self.consultant = User.objects.create_user(username="consultant", password="secretpass123")
        self.other_consultant = User.objects.create_user(username="other_consultant", password="secretpass123")

        self.set_role(self.partner, RoleCode.PARTNER)
        self.set_role(self.admin, RoleCode.ADMINISTRADOR)
        self.set_role(self.manager, RoleCode.MANAGER, manager=self.admin)
        self.set_role(self.advisor, RoleCode.SOLAR_ADVISOR, manager=self.manager)
        self.set_role(self.consultant, RoleCode.SOLAR_CONSULTANT, manager=self.advisor)
        self.set_role(self.other_consultant, RoleCode.SOLAR_CONSULTANT)

    def test_can_manage_hierarchy_descendant_only(self):
        self.assertTrue(can_manage(self.partner, self.admin))
        self.assertFalse(can_manage(self.admin, self.partner))
        self.assertTrue(can_manage(self.advisor, self.consultant))
        self.assertFalse(can_manage(self.advisor, self.other_consultant))

    def test_can_view_scope(self):
        self.assertTrue(can_view(self.partner, target=self.consultant, module=ModuleCode.USERS))
        self.assertFalse(can_view(self.consultant, target=self.advisor, module=ModuleCode.USERS))
        self.assertTrue(can_view(self.consultant, target=self.consultant, module=ModuleCode.USERS))

    def test_can_approve_by_module(self):
        self.assertTrue(can_approve(self.partner, ModuleCode.COMMISSIONS, target=self.consultant))
        self.assertFalse(can_approve(self.manager, ModuleCode.SETTINGS, target=self.consultant))

    def test_assign_role_blocks_self_escalation_and_logs_audit(self):
        with self.assertRaises(PermissionDenied):
            assign_role(actor=self.consultant, target=self.consultant, new_role_code=RoleCode.MANAGER)

        updated = assign_role(
            actor=self.partner,
            target=self.other_consultant,
            new_role_code=RoleCode.SOLAR_ADVISOR,
            reason="Promocion interna",
            manager=self.manager,
        )
        self.assertEqual(updated.role, RoleCode.SOLAR_ADVISOR)
        self.assertEqual(RoleChangeAudit.objects.count(), 1)


class DecoratorIntegrationTests(RBACBaseTestCase):
    def setUp(self):
        super().setUp()
        self.partner = User.objects.create_user(username="owner", password="secretpass123")
        self.manager = User.objects.create_user(username="manager_view", password="secretpass123")
        self.consultant = User.objects.create_user(username="consultant_view", password="secretpass123")
        self.outside = User.objects.create_user(username="outside_view", password="secretpass123")

        self.set_role(self.partner, RoleCode.PARTNER)
        self.set_role(self.manager, RoleCode.MANAGER, manager=self.partner)
        self.set_role(self.consultant, RoleCode.SOLAR_CONSULTANT, manager=self.manager)
        self.set_role(self.outside, RoleCode.SOLAR_CONSULTANT)

    def test_module_decorator_allows_reports_view(self):
        self.client.login(username="manager_view", password="secretpass123")
        response = self.client.get(reverse("core:rbac_health"))
        self.assertEqual(response.status_code, 200)

    def test_hierarchy_decorator_forbids_non_descendant(self):
        self.client.login(username="manager_view", password="secretpass123")
        allowed = self.client.get(reverse("core:rbac_manage_user", kwargs={"user_id": self.consultant.id}))
        denied = self.client.get(reverse("core:rbac_manage_user", kwargs={"user_id": self.outside.id}))
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(denied.status_code, 403)
