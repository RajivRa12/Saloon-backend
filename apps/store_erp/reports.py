from decimal import Decimal
from django.db.models import Sum, Count
from apps.core.models import InvoiceItem, CommissionAccrual, Payment, Invoice
def _finalised_items(store_group, date_from, date_to):
    return InvoiceItem.objects.filter(
        invoice__outlet__store_group=store_group, invoice__finalised_at__isnull=False,
        invoice__finalised_at__date__gte=date_from, invoice__finalised_at__date__lte=date_to,
    )
def revenue_by_professional(store_group, date_from, date_to):
    rows = _finalised_items(store_group, date_from, date_to).exclude(professional__isnull=True).values(
        'professional_id', 'professional__display_name'
    ).annotate(revenue=Sum('total'), line_count=Count('id')).order_by('-revenue')
    return [
        {"professional_id": str(r['professional_id']), "professional_name": r['professional__display_name'],
         "revenue": r['revenue'], "line_count": r['line_count']}
        for r in rows
    ]
def revenue_by_category(store_group, date_from, date_to):
    items = _finalised_items(store_group, date_from, date_to).select_related('store_service__canonical_service__category')
    buckets = {}
    for item in items:
        name = "Uncategorized"
        if item.store_service_id and item.store_service.canonical_service_id and item.store_service.canonical_service.category_id:
            name = item.store_service.canonical_service.category.name
        buckets[name] = buckets.get(name, Decimal('0')) + item.total
    return [{"category": k, "revenue": v} for k, v in sorted(buckets.items(), key=lambda kv: -kv[1])]
def commission_payout_report(store_group, date_from, date_to):
    rows = CommissionAccrual.objects.filter(
        invoice_line__invoice__outlet__store_group=store_group,
        created_at__date__gte=date_from, created_at__date__lte=date_to,
    ).values('professional_id', 'professional__display_name').annotate(
        total_commission_paise=Sum('commission_paise'), accrual_count=Count('id')
    ).order_by('-total_commission_paise')
    return [
        {"professional_id": str(r['professional_id']), "professional_name": r['professional__display_name'],
         "total_commission_paise": r['total_commission_paise'], "accrual_count": r['accrual_count']}
        for r in rows
    ]
def daily_register_summary(store_group, date):
    payments = Payment.objects.filter(invoice__outlet__store_group=store_group, invoice__finalised_at__date=date)
    by_method = payments.values('method').annotate(total=Sum('amount'), count=Count('id')).order_by('-total')
    grand_total = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    invoice_count = Invoice.objects.filter(outlet__store_group=store_group, finalised_at__date=date).count()
    return {
        "date": str(date), "invoice_count": invoice_count, "grand_total": grand_total,
        "by_method": [{"method": r['method'], "total": r['total'], "count": r['count']} for r in by_method],
    }
def gst_report(store_group, date_from, date_to):
    items = _finalised_items(store_group, date_from, date_to).select_related('store_service__canonical_service')
    buckets = {}
    for item in items:
        code = "N/A"
        if item.store_service_id and item.store_service.canonical_service_id:
            code = item.store_service.canonical_service.hsn_sac_code or "N/A"
        key = (code, item.tax_rate)
        b = buckets.setdefault(key, {"hsn_sac_code": code, "tax_rate": item.tax_rate, "taxable_value": Decimal('0'), "tax_collected": Decimal('0')})
        b["taxable_value"] += item.price * item.quantity
        b["tax_collected"] += item.tax_amount
    return sorted(buckets.values(), key=lambda b: b["hsn_sac_code"])
