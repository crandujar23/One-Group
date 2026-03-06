from django.core.management.base import BaseCommand

from core.rbac.services import ensure_seeded_roles_and_permissions


class Command(BaseCommand):
    help = "Seed RBAC roles and module permissions for One-Group."

    def handle(self, *args, **options):
        ensure_seeded_roles_and_permissions()
        self.stdout.write(self.style.SUCCESS("RBAC roles and permissions seeded."))
