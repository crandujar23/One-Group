from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from crm.models import Sale
from finance.services import process_sale_compensation


@receiver(pre_save, sender=Sale)
def cache_previous_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_status = None
        return

    previous = Sale.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
    instance._previous_status = previous


@receiver(post_save, sender=Sale)
def on_sale_saved(sender, instance, created, **kwargs):
    previous_status = getattr(instance, "_previous_status", None)
    became_confirmed = instance.status == Sale.Status.CONFIRMED and (created or previous_status != Sale.Status.CONFIRMED)
    if became_confirmed:
        process_sale_compensation(instance)
