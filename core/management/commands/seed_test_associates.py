from __future__ import annotations

import base64
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from core.models import BusinessUnit
from core.models import Role
from core.models import UserProfile
from core.rbac.constants import RoleCode
from core.rbac.constants import role_priority
from core.rbac.services import ensure_seeded_roles_and_permissions
from crm.models import SalesRep
from rewards.models import Tier

User = get_user_model()

# 1x1 PNG transparente
_AVATAR_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WlH0hQAAAAASUVORK5CYII="
)


@dataclass(frozen=True)
class AssociateSeed:
    username: str
    first_name: str
    last_name: str
    second_last_name: str
    email: str
    role: str
    manager_username: str | None
    city: str
    state: str


class Command(BaseCommand):
    help = "Crea 20 asociados de prueba con jerarquía completa (2 equipos) y password Test@123."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="Test@123")
        parser.add_argument(
            "--business-unit-code",
            default="solar-home-power",
            help="Código de unidad de negocio para asignar a los asociados.",
        )

    def handle(self, *args, **options):
        password = options["password"]
        bu_code = options["business_unit_code"]

        ensure_seeded_roles_and_permissions()
        business_unit = self._get_or_create_business_unit(bu_code)
        tier = self._get_or_create_tier()

        seeds = self._build_seed_matrix()
        users_by_username: dict[str, User] = {}

        # Primera pasada: crear usuarios base
        for idx, seed in enumerate(seeds, start=1):
            user = self._upsert_user(seed, password)
            users_by_username[seed.username] = user
            self._upsert_profile(
                user=user,
                role_code=seed.role,
                manager=None,
                business_unit=business_unit,
            )
            self._upsert_salesrep(
                user=user,
                tier=tier,
                business_unit=business_unit,
                city=seed.city,
                state=seed.state,
                second_last_name=seed.second_last_name,
                phone=self._phone_for(idx),
            )

        # Segunda pasada: enlazar jerarquía manager
        for seed in seeds:
            user = users_by_username[seed.username]
            manager = users_by_username.get(seed.manager_username) if seed.manager_username else None
            self._upsert_profile(
                user=user,
                role_code=seed.role,
                manager=manager,
                business_unit=business_unit,
            )

        self.stdout.write(self.style.SUCCESS("Se crearon/actualizaron 20 asociados de prueba correctamente."))
        self.stdout.write(self.style.SUCCESS("Password común: Test@123"))

    def _get_or_create_business_unit(self, code: str) -> BusinessUnit:
        bu, _ = BusinessUnit.objects.get_or_create(
            code=code,
            defaults={"name": "Solar Home Power", "is_active": True},
        )
        if not bu.is_active:
            bu.is_active = True
            bu.save(update_fields=["is_active"])
        return bu

    def _get_or_create_tier(self) -> Tier:
        tier = Tier.objects.filter(name="Test Tier").first()
        if tier:
            return tier
        max_rank = Tier.objects.order_by("-rank").values_list("rank", flat=True).first() or 0
        return Tier.objects.create(name="Test Tier", rank=max_rank + 1, description="Tier de pruebas para seed de asociados")

    def _avatar_file(self, username: str) -> ContentFile:
        raw = base64.b64decode(_AVATAR_PNG_B64)
        return ContentFile(raw, name=f"{username}.png")

    def _upsert_user(self, seed: AssociateSeed, password: str) -> User:
        user, created = User.objects.get_or_create(
            username=seed.username,
            defaults={
                "email": seed.email,
                "first_name": seed.first_name,
                "last_name": seed.last_name,
                "is_active": True,
            },
        )
        dirty = []
        if user.email != seed.email:
            user.email = seed.email
            dirty.append("email")
        if user.first_name != seed.first_name:
            user.first_name = seed.first_name
            dirty.append("first_name")
        if user.last_name != seed.last_name:
            user.last_name = seed.last_name
            dirty.append("last_name")
        if not user.is_active:
            user.is_active = True
            dirty.append("is_active")
        if created or dirty:
            user.save(update_fields=dirty or None)

        user.set_password(password)
        user.save(update_fields=["password"])
        return user

    def _upsert_profile(self, *, user: User, role_code: str, manager: User | None, business_unit: BusinessUnit) -> None:
        profile = user.profile
        role_obj = Role.objects.filter(code=role_code).first()

        update_fields = []
        if profile.role != role_code:
            profile.role = role_code
            update_fields.append("role")
        if profile.role_ref_id != (role_obj.id if role_obj else None):
            profile.role_ref = role_obj
            update_fields.append("role_ref")
        if profile.manager_id != (manager.id if manager else None):
            profile.manager = manager
            update_fields.append("manager")

        # Mantener unidad principal en todos y alcance por M2M en roles aplicables
        if profile.business_unit_id != business_unit.id:
            profile.business_unit = business_unit
            update_fields.append("business_unit")

        avatar = self._avatar_file(user.username)
        profile.avatar.save(avatar.name, avatar, save=False)
        update_fields.append("avatar")

        if update_fields:
            profile.save(update_fields=update_fields)

        profile.business_units.set([business_unit])

    def _upsert_salesrep(
        self,
        *,
        user: User,
        tier: Tier,
        business_unit: BusinessUnit,
        city: str,
        state: str,
        second_last_name: str,
        phone: str,
    ) -> None:
        rep, _ = SalesRep.objects.get_or_create(
            user=user,
            defaults={"business_unit": business_unit, "tier": tier, "is_active": True},
        )
        rep.business_unit = business_unit
        rep.tier = tier
        rep.second_last_name = second_last_name
        rep.phone = phone
        rep.postal_city = city
        rep.postal_state = state
        rep.postal_address_line_1 = "123 Main St"
        rep.postal_zip_code = "00901"
        rep.physical_same_as_postal = True
        rep.physical_address_line_1 = "123 Main St"
        rep.physical_city = city
        rep.physical_state = state
        rep.physical_zip_code = "00901"
        rep.is_active = True

        avatar = self._avatar_file(user.username)
        rep.avatar.save(avatar.name, avatar, save=False)
        rep.save()

    def _phone_for(self, index: int) -> str:
        return f"(787){500 + index:03d}-{1000 + index:04d}"

    def _build_seed_matrix(self) -> list[AssociateSeed]:
        # 20 asociados exactos: 1 Partner, 1 Admin, 2 BM, 2 EM, 2 SM, 2 M, 4 SA, 6 SC.
        return [
            AssociateSeed("test_partner_01", "Carlos", "Marquez", "Rivera", "test_partner_01@onegroup.test", RoleCode.PARTNER, None, "San Juan", "PR"),
            AssociateSeed("test_admin_01", "Andrea", "Lopez", "Soto", "test_admin_01@onegroup.test", RoleCode.ADMINISTRADOR, "test_partner_01", "San Juan", "PR"),

            AssociateSeed("test_bm_a", "Bruno", "Diaz", "Vega", "test_bm_a@onegroup.test", RoleCode.BUSINESS_MANAGER, "test_partner_01", "Ponce", "PR"),
            AssociateSeed("test_em_a", "Elena", "Mora", "Rios", "test_em_a@onegroup.test", RoleCode.ELITE_MANAGER, "test_bm_a", "Ponce", "PR"),
            AssociateSeed("test_sm_a", "Sergio", "Nunez", "Lugo", "test_sm_a@onegroup.test", RoleCode.SENIOR_MANAGER, "test_em_a", "Ponce", "PR"),
            AssociateSeed("test_m_a", "Marco", "Pena", "Ortiz", "test_m_a@onegroup.test", RoleCode.MANAGER, "test_sm_a", "Ponce", "PR"),
            AssociateSeed("test_sa_a1", "Sofia", "Ramos", "Ibarra", "test_sa_a1@onegroup.test", RoleCode.SOLAR_ADVISOR, "test_m_a", "Yauco", "PR"),
            AssociateSeed("test_sa_a2", "Samuel", "Castro", "Roldan", "test_sa_a2@onegroup.test", RoleCode.SOLAR_ADVISOR, "test_m_a", "Yauco", "PR"),
            AssociateSeed("test_sc_a1", "Clara", "Mendez", "Vila", "test_sc_a1@onegroup.test", RoleCode.SOLAR_CONSULTANT, "test_sa_a1", "Yauco", "PR"),
            AssociateSeed("test_sc_a2", "Cesar", "Torres", "Leon", "test_sc_a2@onegroup.test", RoleCode.SOLAR_CONSULTANT, "test_sa_a1", "Yauco", "PR"),
            AssociateSeed("test_sc_a3", "Camila", "Ruiz", "Santos", "test_sc_a3@onegroup.test", RoleCode.SOLAR_CONSULTANT, "test_sa_a2", "Yauco", "PR"),

            AssociateSeed("test_bm_b", "Bianca", "Suarez", "Matos", "test_bm_b@onegroup.test", RoleCode.BUSINESS_MANAGER, "test_partner_01", "Mayaguez", "PR"),
            AssociateSeed("test_em_b", "Ernesto", "Vargas", "Mena", "test_em_b@onegroup.test", RoleCode.ELITE_MANAGER, "test_bm_b", "Mayaguez", "PR"),
            AssociateSeed("test_sm_b", "Silvia", "Pardo", "Felix", "test_sm_b@onegroup.test", RoleCode.SENIOR_MANAGER, "test_em_b", "Mayaguez", "PR"),
            AssociateSeed("test_m_b", "Mateo", "Quiles", "Ayala", "test_m_b@onegroup.test", RoleCode.MANAGER, "test_sm_b", "Mayaguez", "PR"),
            AssociateSeed("test_sa_b1", "Selena", "Lora", "Miranda", "test_sa_b1@onegroup.test", RoleCode.SOLAR_ADVISOR, "test_m_b", "Aguadilla", "PR"),
            AssociateSeed("test_sa_b2", "Santino", "Bautista", "Riera", "test_sa_b2@onegroup.test", RoleCode.SOLAR_ADVISOR, "test_m_b", "Aguadilla", "PR"),
            AssociateSeed("test_sc_b1", "Carla", "Gil", "Zayas", "test_sc_b1@onegroup.test", RoleCode.SOLAR_CONSULTANT, "test_sa_b1", "Aguadilla", "PR"),
            AssociateSeed("test_sc_b2", "Ciro", "Negron", "Peres", "test_sc_b2@onegroup.test", RoleCode.SOLAR_CONSULTANT, "test_sa_b1", "Aguadilla", "PR"),
            AssociateSeed("test_sc_b3", "Celia", "Morales", "Sierra", "test_sc_b3@onegroup.test", RoleCode.SOLAR_CONSULTANT, "test_sa_b2", "Aguadilla", "PR"),
        ]
