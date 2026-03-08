from __future__ import annotations

from crm.models import CrmDeal


class CrmDealDetailSerializer:
    def __init__(self, instance: CrmDeal):
        self.instance = instance

    def _salesrep_name(self) -> str:
        if self.instance.salesrep_id and self.instance.salesrep and self.instance.salesrep.user_id:
            user = self.instance.salesrep.user
            return user.get_full_name().strip() or user.get_username()
        return (self.instance.imported_salesrep_name or "").strip() or "Pendiente por adjudicar"

    @property
    def data(self) -> dict:
        deal = self.instance
        return {
            "id": deal.id,
            "deal_kind": deal.deal_kind,
            "salesrep_name": self._salesrep_name(),
            "adjudication_label": "Asignada" if deal.salesrep_id else "Pendiente",
            "customer_name": deal.customer_name,
            "proposal_id": deal.proposal_id,
            "sunrun_service_contract_id": deal.sunrun_service_contract_id,
            "customer_phone": deal.customer_phone,
            "customer_email": deal.customer_email,
            "system_size": float(deal.system_size or 0),
            "epc_price": float(deal.epc_price or 0),
            "epc_base": float(deal.epc_base or 0),
            "epc_table": float(deal.epc_table or 0),
            "epc_adjustment": float(deal.epc_adjustment or 0),
            "closing_date": deal.closing_date.isoformat() if deal.closing_date else "",
            "stage": deal.stage,
            "stage_display": deal.get_stage_display(),
            "sr_signoff_date": deal.sr_signoff_date.isoformat() if deal.sr_signoff_date else "",
            "customer_sign_off_date": deal.customer_sign_off_date.isoformat() if deal.customer_sign_off_date else "",
            "final_completion_date": deal.final_completion_date.isoformat() if deal.final_completion_date else "",
            "imported_at": deal.imported_at.isoformat() if deal.imported_at else "",
            "created_at": deal.created_at.isoformat() if deal.created_at else "",
        }

    @classmethod
    def serialize_many(cls, queryset) -> list[dict]:
        return [cls(instance=item).data for item in queryset]
