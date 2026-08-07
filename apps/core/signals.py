from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from .models import (
    Invoice, InvoiceStatus, User, Appointment, Product, Vendor,
    PurchaseOrder, Expense, Room, Shift, Attendance, LeaveRequest,
    Payroll, DailyRegister, MarketingCampaign, StaffIncentive, Outlet,
    KycDocument, KycDocStatus, KycDocType, StoreGroupStatus, StoreStatusHistory
)
@receiver(pre_save, sender=Invoice)
def auto_accrue_loyalty_points(sender, instance, **kwargs):
    if not instance.pk:
        return
    try:
        old_invoice = Invoice.objects.get(pk=instance.pk)
    except Invoice.DoesNotExist:
        return
    if old_invoice.status != InvoiceStatus.PAID and instance.status == InvoiceStatus.PAID:
        if instance.customer:
            points_to_award = int(instance.grand_total / 100)
            if points_to_award > 0:
                instance.customer.loyalty_points += points_to_award
                instance.customer.save(update_fields=['loyalty_points'])
@receiver(pre_save)
def auto_sync_outlet_to_store_record(sender, instance, **kwargs):
    operational_models = (
        User, Appointment, Invoice, Product, Vendor, PurchaseOrder,
        Expense, Room, Shift, Attendance, LeaveRequest, Payroll,
        DailyRegister, MarketingCampaign, StaffIncentive
    )
    if not isinstance(instance, operational_models):
        return
    if hasattr(instance, 'outlet') and getattr(instance, 'outlet_id', None) is None:
        store = getattr(instance, 'store', None)
        if store:
            matching_outlet = None
            if getattr(store, 'store_group_id', None):
                matching_outlet = Outlet.objects.filter(store_group_id=store.store_group_id).first()
            if not matching_outlet and getattr(store, 'city', None):
                matching_outlet = Outlet.objects.filter(city=store.city).first()
            if not matching_outlet:
                matching_outlet = Outlet.objects.first()
            if matching_outlet:
                instance.outlet = matching_outlet
@receiver(post_save, sender=KycDocument)
def auto_activate_store_on_kyc_completion(sender, instance, **kwargs):
    store_group = instance.store_group
    if instance.status != KycDocStatus.APPROVED:
        return
    if store_group.status in (StoreGroupStatus.ACTIVE, StoreGroupStatus.OFFBOARDED):
        return
    required_types = {
        KycDocType.GST_CERT,
        KycDocType.BANK_PROOF,
        KycDocType.BUSINESS_CERT,
    }
    pan_or_trade = KycDocument.objects.filter(
        store_group=store_group,
        doc_type__in=[KycDocType.PAN, KycDocType.TRADE_LICENCE],
        status=KycDocStatus.APPROVED
    ).exists()
    required_docs_approved = all(
        KycDocument.objects.filter(
            store_group=store_group,
            doc_type=doc_type,
            status=KycDocStatus.APPROVED
        ).exists()
        for doc_type in required_types
    )
    if required_docs_approved and pan_or_trade:
        old_status = store_group.status
        store_group.status = StoreGroupStatus.ACTIVE
        store_group.save(update_fields=['status'])
        StoreStatusHistory.objects.create(
            store_group=store_group,
            from_status=old_status,
            to_status=StoreGroupStatus.ACTIVE,
            reason="All required KYC documents verified and approved by Master Admin. Store automatically activated.",
            changed_by="system",
            changed_by_type="system"
        )
