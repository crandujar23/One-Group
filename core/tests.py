from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import UserProfile

User = get_user_model()


class UserProfileSmokeTests(TestCase):
    def test_profile_is_created_automatically(self):
        user = User.objects.create_user(username="john", password="secretpass123")
        self.assertTrue(hasattr(user, "profile"))
        self.assertEqual(user.profile.role, UserProfile.Role.SALES_REP)
