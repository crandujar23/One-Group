from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from core.rbac.constants import ModuleCode
from core.rbac.constants import PermissionAction
from core.rbac.constants import RoleCode
from core.rbac.constants import role_priority

User = get_user_model()


class BusinessUnit(models.Model):
    name = models.CharField(max_length=120, unique=True)
    code = models.SlugField(max_length=40, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Role(models.Model):
    code = models.CharField(max_length=40, unique=True, choices=RoleCode.choices)
    name = models.CharField(max_length=80)
    priority = models.PositiveSmallIntegerField(db_index=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "id"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class ModulePermission(models.Model):
    class Module(models.TextChoices):
        USERS = ModuleCode.USERS, "Usuarios"
        SALES = ModuleCode.SALES, "Ventas"
        REPORTS = ModuleCode.REPORTS, "Reportes"
        SETTINGS = ModuleCode.SETTINGS, "Configuracion"
        COMMISSIONS = ModuleCode.COMMISSIONS, "Comisiones"

    class Action(models.TextChoices):
        VIEW = PermissionAction.VIEW, "Ver"
        MANAGE = PermissionAction.MANAGE, "Gestionar"
        APPROVE = PermissionAction.APPROVE, "Aprobar"

    module = models.CharField(max_length=40, choices=Module.choices)
    action = models.CharField(max_length=40, choices=Action.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("module", "action")
        ordering = ["module", "action"]

    def __str__(self) -> str:
        return f"{self.module}:{self.action}"


class RoleModulePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="module_permissions")
    permission = models.ForeignKey(ModulePermission, on_delete=models.CASCADE, related_name="role_permissions")
    allowed = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("role", "permission")
        ordering = ["role__priority", "permission__module", "permission__action"]

    def __str__(self) -> str:
        return f"{self.role.code}:{self.permission.module}:{self.permission.action}={self.allowed}"


class UserProfile(models.Model):
    Role = RoleCode

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=40, choices=RoleCode.choices, default=RoleCode.SOLAR_CONSULTANT)
    role_ref = models.ForeignKey(
        "core.Role",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="profiles",
    )
    manager = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_profiles",
    )
    business_unit = models.ForeignKey(
        BusinessUnit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_profiles",
    )
    business_units = models.ManyToManyField(
        BusinessUnit,
        blank=True,
        related_name="scoped_user_profiles",
    )
    hire_date = models.DateField(null=True, blank=True)
    avatar = models.ImageField(
        upload_to="profiles/avatars/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])],
    )
    class Meta:
        ordering = ["user__username"]

    def clean(self):
        if self.manager_id and self.manager_id == self.user_id:
            raise ValidationError({"manager": "Un usuario no puede ser su propio manager."})

    def save(self, *args, **kwargs):
        if self.role and (not self.role_ref_id or (self.role_ref and self.role_ref.code != self.role)):
            role_obj = Role.objects.filter(code=self.role).only("id", "code").first()
            if role_obj:
                self.role_ref = role_obj
        elif self.role_ref and not self.role:
            self.role = self.role_ref.code
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.user.username} ({self.role})"

    @property
    def role_priority(self) -> int:
        if self.role_ref:
            return self.role_ref.priority
        return role_priority(self.role)

    @property
    def is_admin(self) -> bool:
        return self.role in {RoleCode.PARTNER, RoleCode.ADMINISTRADOR, RoleCode.JR_PARTNER} or self.user.is_superuser


class RoleChangeAudit(models.Model):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="role_changes_performed")
    target = models.ForeignKey(User, on_delete=models.CASCADE, related_name="role_changes_received")
    previous_role = models.CharField(max_length=40, choices=RoleCode.choices)
    new_role = models.CharField(max_length=40, choices=RoleCode.choices)
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.target} {self.previous_role} -> {self.new_role}"


@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, **kwargs):
    if created:
        role_code = RoleCode.PARTNER if instance.is_superuser else RoleCode.SOLAR_CONSULTANT
        role_obj = Role.objects.filter(code=role_code).first()
        UserProfile.objects.create(user=instance, role=role_code, role_ref=role_obj)
        return

    if hasattr(instance, "profile") and instance.is_superuser and instance.profile.role != RoleCode.PARTNER:
        partner_role = Role.objects.filter(code=RoleCode.PARTNER).first()
        instance.profile.role = RoleCode.PARTNER
        instance.profile.role_ref = partner_role
        instance.profile.save(update_fields=["role", "role_ref"])
