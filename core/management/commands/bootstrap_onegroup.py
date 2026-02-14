from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.models import BusinessUnit, UserProfile
from crm.models import SalesRep
from inventory.models import Product
from rewards.models import CompensationPlan, PlanTierRule, Prize, Tier

User = get_user_model()


class Command(BaseCommand):
    help = "Seed initial OneGroup data and create an admin user."

    def add_arguments(self, parser):
        parser.add_argument("--admin-username", default="admin")
        parser.add_argument("--admin-email", default="admin@example.com")
        parser.add_argument("--admin-password", default="ChangeMe123!")

    def handle(self, *args, **options):
        business_units = ["Techo", "Solar Home Power", "SunVida", "Cash D", "Agua", "Internet"]
        bu_map = {}
        for name in business_units:
            bu, _ = BusinessUnit.objects.get_or_create(
                code=name.lower().replace(" ", "-"),
                defaults={"name": name},
            )
            if bu.name != name:
                bu.name = name
                bu.save(update_fields=["name"])
            bu_map[name] = bu

        tier_junior, _ = Tier.objects.get_or_create(name="Junior", rank=1)
        tier_senior, _ = Tier.objects.get_or_create(name="Senior", rank=2)

        techo_bu = bu_map["Techo"]
        product, _ = Product.objects.get_or_create(
            business_unit=techo_bu,
            sku="TECHO-SOLAR-001",
            defaults={"name": "Solar Roof Basic", "price": Decimal("10000.00")},
        )

        for plan_name in ["PPA", "SunRun", "Directa", "Promo"]:
            plan, _ = CompensationPlan.objects.get_or_create(
                business_unit=techo_bu,
                product=product,
                name=plan_name,
            )
            PlanTierRule.objects.get_or_create(
                plan=plan,
                tier=tier_junior,
                defaults={
                    "commission_percent": Decimal("5.00"),
                    "bonus_percent": Decimal("1.00"),
                    "points_per_dollar": Decimal("0.10"),
                },
            )
            PlanTierRule.objects.get_or_create(
                plan=plan,
                tier=tier_senior,
                defaults={
                    "commission_percent": Decimal("7.50"),
                    "bonus_percent": Decimal("2.00"),
                    "points_per_dollar": Decimal("0.15"),
                },
            )

        Prize.objects.get_or_create(
            business_unit=techo_bu,
            name="Gift Card $50",
            defaults={"points_cost": Decimal("500.00"), "stock": 50},
        )

        username = options["admin_username"]
        email = options["admin_email"]
        password = options["admin_password"]

        admin_user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email, "is_staff": True, "is_superuser": True},
        )
        if created:
            admin_user.set_password(password)
            admin_user.save()
            self.stdout.write(self.style.SUCCESS(f"Admin user created: {username}"))
        else:
            if not admin_user.is_superuser:
                admin_user.is_staff = True
                admin_user.is_superuser = True
                admin_user.save(update_fields=["is_staff", "is_superuser"])
            self.stdout.write(self.style.WARNING(f"Admin user already exists: {username}"))

        profile = admin_user.profile
        profile.role = UserProfile.Role.ADMIN
        profile.business_unit = None
        profile.save(update_fields=["role", "business_unit"])

        rep_user, _ = User.objects.get_or_create(username="salesrep_demo", defaults={"email": "rep@example.com"})
        rep_user.set_password("ChangeMe123!")
        rep_user.save()
        rep_profile = rep_user.profile
        rep_profile.role = UserProfile.Role.SALES_REP
        rep_profile.business_unit = techo_bu
        rep_profile.save(update_fields=["role", "business_unit"])
        SalesRep.objects.get_or_create(user=rep_user, defaults={"business_unit": techo_bu, "tier": tier_junior})

        self.stdout.write(self.style.SUCCESS("Seed completed."))
