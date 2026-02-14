from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction

from finance.models import Commission
from rewards.models import PlanTierRule, RewardPoint

TWOPLACES = Decimal("0.01")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


@transaction.atomic
def process_sale_compensation(sale):
    if sale.status != sale.Status.CONFIRMED:
        return None

    if sale.sales_rep.tier is None:
        raise ValidationError("SalesRep must have an assigned tier before confirming a sale.")

    try:
        rule = PlanTierRule.objects.get(plan=sale.plan, tier=sale.sales_rep.tier)
    except PlanTierRule.DoesNotExist as exc:
        raise ValidationError("No PlanTierRule found for the selected plan and SalesRep tier.") from exc

    amount = Decimal(sale.amount)
    commission_value = _quantize(amount * (rule.commission_percent / Decimal("100")))
    bonus_value = _quantize(amount * (rule.bonus_percent / Decimal("100")))
    points_value = _quantize(amount * rule.points_per_dollar)

    commission, _ = Commission.objects.get_or_create(
        sale=sale,
        defaults={
            "sales_rep": sale.sales_rep,
            "business_unit": sale.business_unit,
            "commission_amount": commission_value,
            "bonus_amount": bonus_value,
            "total_amount": commission_value + bonus_value,
        },
    )

    RewardPoint.objects.get_or_create(
        sale=sale,
        defaults={
            "sales_rep": sale.sales_rep,
            "points": points_value,
        },
    )

    return commission
