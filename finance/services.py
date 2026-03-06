from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import UserProfile
from core.rbac.constants import RoleCode
from finance.models import Commission
from finance.models import CommissionAllocation
from crm.models import SalesRep
from rewards.models import PlanTierRule, RewardPoint

TWOPLACES = Decimal("0.01")
MAX_COMMISSION_RATE = Decimal("0.19")
ROLE_BASE_RATE = {
    RoleCode.PARTNER: Decimal("0.19"),
    RoleCode.JR_PARTNER: Decimal("0.17"),
    RoleCode.BUSINESS_MANAGER: Decimal("0.16"),
    RoleCode.ELITE_MANAGER: Decimal("0.15"),
    RoleCode.SENIOR_MANAGER: Decimal("0.14"),
    RoleCode.MANAGER: Decimal("0.13"),
    RoleCode.SOLAR_ADVISOR: Decimal("0.12"),
    RoleCode.SOLAR_CONSULTANT: Decimal("0.06"),
}


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _commission_distribution_for_sale(sale) -> tuple[dict[int, Decimal], dict[int, str]]:
    seller_profile = getattr(sale.sales_rep.user, "profile", None)
    if not seller_profile:
        return {}, {}

    chain: list[UserProfile] = []
    current = seller_profile
    visited: set[int] = set()
    while current and current.user_id and current.user_id not in visited:
        visited.add(current.user_id)
        chain.append(current)
        if not current.manager_id:
            break
        current = getattr(current.manager, "profile", None)

    if not chain:
        return {}, {}

    seller_rate = ROLE_BASE_RATE.get(chain[0].role, Decimal("0"))
    if seller_rate <= 0:
        return {}, {}

    role_by_user = {node.user_id: node.role for node in chain}
    distribution: dict[int, Decimal] = {chain[0].user_id: seller_rate}
    current_max = seller_rate

    for ancestor in chain[1:]:
        target_rate = ROLE_BASE_RATE.get(ancestor.role, Decimal("0"))
        if target_rate <= current_max:
            continue
        share = target_rate - current_max
        if share > 0:
            distribution[ancestor.user_id] = share
            current_max = target_rate
        if current_max >= MAX_COMMISSION_RATE:
            break

    return distribution, role_by_user


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
    distribution, role_by_user = _commission_distribution_for_sale(sale)
    seller_share = distribution.get(sale.sales_rep.user_id, Decimal("0"))
    commission_value = _quantize(amount * seller_share)
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

    salesrep_by_user = {
        rep.user_id: rep
        for rep in SalesRep.objects.filter(user_id__in=distribution.keys())
    }
    expected_rep_ids: set[int] = set()
    for user_id, share in distribution.items():
        rep = salesrep_by_user.get(user_id)
        if not rep:
            continue
        expected_rep_ids.add(rep.id)
        CommissionAllocation.objects.update_or_create(
            commission=commission,
            sales_rep=rep,
            defaults={
                "sale": sale,
                "role_code": role_by_user.get(user_id, ""),
                "share_percent": share,
                "amount": _quantize(amount * share),
            },
        )
    CommissionAllocation.objects.filter(commission=commission).exclude(sales_rep_id__in=expected_rep_ids).delete()

    RewardPoint.objects.get_or_create(
        sale=sale,
        defaults={
            "sales_rep": sale.sales_rep,
            "points": points_value,
        },
    )

    return commission
