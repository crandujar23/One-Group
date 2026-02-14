from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import BusinessUnit
from crm.models import Sale, SalesRep
from finance.models import Commission
from inventory.models import Product
from rewards.models import CompensationPlan, PlanTierRule, RewardPoint, Tier

User = get_user_model()


class CompensationFlowTests(TestCase):
    def setUp(self):
        self.bu = BusinessUnit.objects.create(name="Techo", code="techo")
        self.tier = Tier.objects.create(name="Junior", rank=1)
        self.user = User.objects.create_user(username="rep1", password="secretpass123")
        self.rep = SalesRep.objects.create(user=self.user, business_unit=self.bu, tier=self.tier)
        self.product = Product.objects.create(
            business_unit=self.bu,
            name="Solar Kit",
            sku="SKU-1",
            price=Decimal("1000.00"),
        )
        self.plan = CompensationPlan.objects.create(business_unit=self.bu, product=self.product, name="PPA")
        self.rule = PlanTierRule.objects.create(
            plan=self.plan,
            tier=self.tier,
            commission_percent=Decimal("10.00"),
            bonus_percent=Decimal("2.00"),
            points_per_dollar=Decimal("0.10"),
        )

    def test_confirmed_sale_creates_commission_and_points_once(self):
        sale = Sale.objects.create(
            business_unit=self.bu,
            sales_rep=self.rep,
            product=self.product,
            plan=self.plan,
            amount=Decimal("1000.00"),
            status=Sale.Status.CONFIRMED,
        )

        self.assertEqual(Commission.objects.count(), 1)
        self.assertEqual(RewardPoint.objects.count(), 1)

        sale.status = Sale.Status.CONFIRMED
        sale.save()

        self.assertEqual(Commission.objects.count(), 1)
        self.assertEqual(RewardPoint.objects.count(), 1)

        commission = Commission.objects.get(sale=sale)
        points = RewardPoint.objects.get(sale=sale)
        self.assertEqual(commission.commission_amount, Decimal("100.00"))
        self.assertEqual(commission.bonus_amount, Decimal("20.00"))
        self.assertEqual(commission.total_amount, Decimal("120.00"))
        self.assertEqual(points.points, Decimal("100.00"))
