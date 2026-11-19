from rest_framework import serializers
from apps.core.models import (
    ProfessionalAccount, ProfessionalPortfolio, ProfessionalCertification,
    PayoutDestination, ProfessionalTip, ProfessionalReview, ReviewResponse,
    ReputationAggregate, ReputationConsent, CommissionAccrual, AppointmentSlot,
)
class ProfessionalPortfolioSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProfessionalPortfolio
        fields = ['id', 'media_url', 'caption', 'display_order']
        read_only_fields = ['id']
class ProfessionalCertificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProfessionalCertification
        fields = ['id', 'title', 'issuer', 'year', 'media_url']
        read_only_fields = ['id']
class ReputationAggregateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReputationAggregate
        fields = ['avg_rating', 'total_reviews', 'total_services', 'updated_at']
class ProfessionalAccountSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', read_only=True)
    portfolio_items = ProfessionalPortfolioSerializer(many=True, required=False)
    certifications = ProfessionalCertificationSerializer(many=True, required=False)
    reputation = serializers.SerializerMethodField()
    class Meta:
        model = ProfessionalAccount
        fields = [
            'id', 'name', 'email', 'phone_e164', 'bio', 'years_experience',
            'profile_photo_url', 'created_at', 'portfolio_items', 'certifications', 'reputation',
        ]
        read_only_fields = ['id', 'created_at']
    def get_reputation(self, obj):
        agg = getattr(obj, 'reputation', None)
        if agg is None:
            return {'avg_rating': 0, 'total_reviews': 0, 'total_services': 0}
        return ReputationAggregateSerializer(agg).data
    def update(self, instance, validated_data):
        portfolio_data = validated_data.pop('portfolio_items', None)
        certifications_data = validated_data.pop('certifications', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if portfolio_data is not None:
            instance.portfolio_items.all().delete()
            ProfessionalPortfolio.objects.bulk_create([
                ProfessionalPortfolio(professional_account=instance, **item) for item in portfolio_data
            ])
        if certifications_data is not None:
            instance.certifications.all().delete()
            ProfessionalCertification.objects.bulk_create([
                ProfessionalCertification(professional_account=instance, **item) for item in certifications_data
            ])
        return instance
class ReputationConsentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReputationConsent
        fields = ['portability_granted', 'updated_at']
        read_only_fields = ['updated_at']
class PayoutDestinationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayoutDestination
        fields = ['id', 'type', 'vpa', 'bank_account_masked', 'holder_name', 'verification_status', 'verified_at', 'is_active', 'created_at']
        read_only_fields = ['id', 'verification_status', 'verified_at', 'created_at']
class ProfessionalTipSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    booking_id = serializers.UUIDField(source='booking.id', read_only=True)
    class Meta:
        model = ProfessionalTip
        fields = ['id', 'booking_id', 'appointment_slot', 'customer_name', 'amount_paise', 'method', 'status', 'payment_ref', 'initiated_at', 'confirmed_at']
        read_only_fields = fields
    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer_id else None
class ReviewResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReviewResponse
        fields = ['id', 'response_text', 'created_at']
        read_only_fields = ['id', 'created_at']
class ProfessionalReviewSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    response = ReviewResponseSerializer(read_only=True)
    class Meta:
        model = ProfessionalReview
        fields = ['id', 'booking', 'store_group', 'customer_name', 'store_rating', 'professional_rating', 'comment', 'media_url', 'moderation_status', 'created_at', 'response']
        read_only_fields = fields
    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer_id else None
class CommissionAccrualSerializer(serializers.ModelSerializer):
    invoice_number = serializers.SerializerMethodField()
    service_name = serializers.SerializerMethodField()
    class Meta:
        model = CommissionAccrual
        fields = ['id', 'invoice_line', 'invoice_number', 'service_name', 'base_paise', 'commission_paise', 'created_at']
        read_only_fields = fields
    def get_invoice_number(self, obj):
        return obj.invoice_line.invoice.invoice_number
    def get_service_name(self, obj):
        line = obj.invoice_line
        if line.store_service_id:
            return line.store_service.name
        if line.service_id:
            return line.service.name
        return None
class AppointmentSlotScheduleSerializer(serializers.ModelSerializer):
    outlet_name = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    store_service_name = serializers.SerializerMethodField()
    items = serializers.SerializerMethodField()
    notes = serializers.CharField(source='booking.notes', read_only=True)
    is_home_service = serializers.BooleanField(source='booking.is_home_service', read_only=True)
    service_address = serializers.CharField(source='booking.service_address', read_only=True)
    on_the_way_at = serializers.DateTimeField(source='booking.on_the_way_at', read_only=True)
    status = serializers.SerializerMethodField()
    class Meta:
        model = AppointmentSlot
        fields = [
            'id', 'booking', 'store_service_name', 'items', 'notes', 'outlet_name', 'customer_name', 'slot_start', 'slot_end',
            'actual_start_time', 'actual_end_time', 'start_variance_minutes', 'end_variance_minutes',
            'override_reason', 'was_overridden',
            'price_paise', 'status', 'is_home_service', 'service_address', 'on_the_way_at',
        ]
        read_only_fields = fields
    def get_status(self, obj):
        if obj.booking and getattr(obj.booking, 'status', None) in ('cancelled', 'CANCELLED'):
            return 'cancelled'
        return obj.status
    def get_outlet_name(self, obj):
        return obj.booking.outlet.name
    def get_customer_name(self, obj):
        if not obj.booking.customer_id:
            return None
        c = obj.booking.customer
        name = c.name or ''
        phone = c.phone_e164 or ''
        if not name or '@phone.nearbyme.local' in name:
            raw_p = phone or (name.split('@')[0] if name else "")
            if len(raw_p) == 12 and raw_p.startswith('91'):
                ten = raw_p[2:]
                return f"+91 {ten[:5]} {ten[5:]}"
            elif len(raw_p) == 10:
                return f"+91 {raw_p[:5]} {raw_p[5:]}"
            return raw_p or "Customer"
        return name

    def get_store_service_name(self, obj):
        if obj.booking_id:
            sibling_slots = obj.booking.slots.select_related('store_service').all()
            if sibling_slots.count() > 1:
                names = [s.store_service.name for s in sibling_slots if s.store_service]
                if names:
                    return " + ".join(names)
            notes = getattr(obj.booking, 'notes', '') or ''
            if 'Services:' in notes:
                try:
                    part = notes.split('Services:')[1].split('(Home Visit)')[0].strip()
                    if part:
                        return part
                except Exception:
                    pass
        return obj.store_service.name if obj.store_service else "Salon Service"

    def get_items(self, obj):
        if obj.booking_id:
            sibling_slots = obj.booking.slots.select_related('store_service').all()
            if sibling_slots.count() > 1:
                return [
                    {
                        "id": str(s.id),
                        "service_name": s.store_service.name if s.store_service else "Salon Service",
                        "price": (s.price_paise or 0) / 100,
                    }
                    for s in sibling_slots
                ]
            try:
                from apps.core.models import InvoiceLine
                lines = InvoiceLine.objects.filter(invoice__booking=obj.booking).select_related('store_service')
                if lines.count() > 1:
                    return [
                        {
                            "id": str(line.id),
                            "service_name": line.store_service.name if line.store_service else "Salon Service",
                            "price": (line.total_paise or 0) / 100,
                        }
                        for line in lines
                    ]
            except Exception:
                pass
            notes = getattr(obj.booking, 'notes', '') or ''
            if 'Services:' in notes:
                try:
                    import re
                    part = notes.split('Services:')[1].split('(Home Visit)')[0].strip()
                    if part and ('+' in part or ',' in part):
                        sub_names = [s.strip() for s in re.split(r'[\+,]', part) if s.strip()]
                        if len(sub_names) > 1:
                            tot_price = (obj.price_paise or 0) / 100
                            sub_price = round(tot_price / len(sub_names), 2)
                            return [
                                {
                                    "id": f"{obj.id}-{idx}",
                                    "service_name": nm,
                                    "price": sub_price,
                                }
                                for idx, nm in enumerate(sub_names)
                            ]
                except Exception:
                    pass
        single_price = (obj.price_paise or 0) / 100
        name = obj.store_service.name if obj.store_service else "Salon Service"
        return [
            {
                "id": str(obj.id),
                "service_name": name,
                "price": single_price,
            }
        ]
