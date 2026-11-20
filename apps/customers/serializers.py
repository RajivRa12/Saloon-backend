from decimal import Decimal
from rest_framework import serializers
from apps.core.models import (
    Store, ServiceCategory, Service, User,
    Appointment, AppointmentItem, Wallet, WalletTransaction,
    CustomerMembership, Review,
    GiftCard, ServicePackage, CustomerPackage,
    FavoriteTherapist, CustomerFavourite, Invoice, Coupon,
    Notification, ProfessionalReview,
    Conversation, ChatMessage,
    StorePublicProfile,
)
class MicrositeSerializer(serializers.ModelSerializer):
    store_id = serializers.CharField(source='store.id', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    address = serializers.CharField(source='store.address', read_only=True)
    location = serializers.CharField(source='store.location', read_only=True)
    contact_number = serializers.CharField(source='store.contact_number', read_only=True)
    working_hours = serializers.JSONField(source='store.working_hours', read_only=True)
    is_premium_listing = serializers.SerializerMethodField()
    class Meta:
        model = StorePublicProfile
        fields = [
            'slug', 'headline', 'about', 'cover_image_url', 'gallery', 'amenities',
            'cancellation_policy_text', 'store_id', 'store_name', 'address', 'location',
            'contact_number', 'working_hours', 'is_premium_listing',
        ]
    def get_is_premium_listing(self, obj):
        return bool(obj.store.is_premium_listing) and obj.store.has_plan_feature('includes_premium_listing')
class PublicStoreSerializer(serializers.ModelSerializer):
    brand_name = serializers.CharField(source='brand.name', read_only=True)
    business_type = serializers.CharField(source='business.business_type', read_only=True, default='SALON')
    has_online_booking = serializers.SerializerMethodField()
    is_premium_listing = serializers.SerializerMethodField()
    slug = serializers.SerializerMethodField()
    avg_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    city = serializers.SerializerMethodField()
    zone = serializers.SerializerMethodField()
    class Meta:
        model = Store
        fields = ['id', 'name', 'brand_name', 'business_type', 'address', 'location', 'contact_number', 'email', 'has_online_booking', 'working_hours', 'is_premium_listing', 'slug', 'avg_rating', 'review_count', 'city', 'zone']
    def get_city(self, obj):
        if obj.outlet and obj.outlet.city:
            return obj.outlet.city.name
        return None
    def get_zone(self, obj):
        if obj.outlet and obj.outlet.zone:
            return obj.outlet.zone.name
        return None
    def get_has_online_booking(self, obj):
        return obj.outlet_id is not None
    def get_slug(self, obj):
        profile = getattr(obj, 'public_profile', None)
        return profile.slug if profile else None
    def get_is_premium_listing(self, obj):
        return bool(obj.is_premium_listing) and obj.has_plan_feature('includes_premium_listing')
    def get_avg_rating(self, obj):
        from django.db.models import Avg
        result = Review.objects.filter(store=obj).aggregate(avg=Avg('rating'))
        avg = result.get('avg')
        return round(float(avg), 1) if avg is not None else None
    def get_review_count(self, obj):
        return Review.objects.filter(store=obj).count()
class PublicServiceSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    store_id = serializers.SerializerMethodField()
    store_name = serializers.SerializerMethodField()
    class Meta:
        model = Service
        fields = ['id', 'name', 'price', 'duration_minutes', 'category_name', 'is_premium_listing', 'store_id', 'store_name']
    def get_store(self, obj):
        return obj.category.business.stores.filter(status='ACTIVE').first()
    def get_store_id(self, obj):
        store = self.get_store(obj)
        return store.id if store else None
    def get_store_name(self, obj):
        store = self.get_store(obj)
        return store.name if store else None
class PublicServiceCategorySerializer(serializers.ModelSerializer):
    services = serializers.SerializerMethodField()
    class Meta:
        model = ServiceCategory
        fields = ['id', 'name', 'services']
    def get_services(self, obj):
        services = Service.objects.filter(category=obj, is_active=True)
        return PublicServiceSerializer(services, many=True).data
class PublicReviewSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.first_name', read_only=True)
    class Meta:
        model = Review
        fields = ['id', 'rating', 'comment', 'customer_name', 'created_at']
class CustomerProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'phone', 'loyalty_points', 'expo_push_token']
        read_only_fields = ['id', 'loyalty_points']

    def update(self, instance, validated_data):
        user = super().update(instance, validated_data)
        full_name = (user.get_full_name() or user.first_name or '').strip()
        if full_name:
            from apps.core.models import GlobalCustomer, normalize_e164
            gc = None
            if user.phone:
                gc = GlobalCustomer.objects.filter(phone_e164=normalize_e164(user.phone)).first()
            if not gc and user.email:
                gc = GlobalCustomer.objects.filter(email=user.email).first()
            if gc:
                gc.name = full_name
                gc.save(update_fields=['name'])
        return user
class CustomerWalletTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletTransaction
        fields = ['id', 'transaction_type', 'amount', 'description', 'created_at']
class CustomerWalletSerializer(serializers.ModelSerializer):
    transactions = CustomerWalletTransactionSerializer(many=True, read_only=True)
    class Meta:
        model = Wallet
        fields = ['id', 'balance', 'updated_at', 'transactions']
class CustomerMembershipSerializer(serializers.ModelSerializer):
    tier_name = serializers.CharField(source='tier.name', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    class Meta:
        model = CustomerMembership
        fields = ['id', 'tier_name', 'store_name', 'start_date', 'end_date', 'is_active']
class CustomerAppointmentItemSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)
    price = serializers.DecimalField(source='service.price', max_digits=10, decimal_places=2, read_only=True)
    class Meta:
        model = AppointmentItem
        fields = ['id', 'service', 'service_name', 'price']
class CustomerAppointmentSerializer(serializers.ModelSerializer):
    items = CustomerAppointmentItemSerializer(many=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    total_amount = serializers.SerializerMethodField()
    class Meta:
        model = Appointment
        fields = ['id', 'store', 'store_name', 'start_time', 'end_time', 'status', 'total_amount', 'notes', 'items']
        read_only_fields = ['id', 'store_name', 'end_time', 'status', 'total_amount']
    def get_total_amount(self, obj):
        return sum((item.price for item in obj.items.all()), start=Decimal('0'))
    def create(self, validated_data):
        import datetime
        items_data = validated_data.pop('items')
        start_time = validated_data.get('start_time')
        if start_time:
            validated_data['end_time'] = start_time + datetime.timedelta(hours=1)
        appointment = Appointment.objects.create(**validated_data)
        for item_data in items_data:
            AppointmentItem.objects.create(appointment=appointment, **item_data)
        return appointment
class GiftCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = GiftCard
        fields = ['id', 'code', 'store', 'initial_value', 'current_balance', 'recipient_email', 'expiry_date', 'is_active']
        read_only_fields = ['id', 'code', 'current_balance', 'expiry_date', 'is_active']
class ServicePackageSerializer(serializers.ModelSerializer):
    services_list = PublicServiceSerializer(source='services', many=True, read_only=True)
    class Meta:
        model = ServicePackage
        fields = ['id', 'name', 'description', 'price', 'services_list']
class CustomerPackageSerializer(serializers.ModelSerializer):
    package_details = ServicePackageSerializer(source='package', read_only=True)
    class Meta:
        model = CustomerPackage
        fields = ['id', 'package', 'package_details', 'purchase_date', 'is_active']
        read_only_fields = ['id', 'package_details', 'purchase_date', 'is_active']
class FavoriteTherapistSerializer(serializers.ModelSerializer):
    therapist_name = serializers.CharField(source='therapist.get_full_name', read_only=True)
    therapist_id = serializers.IntegerField(source='therapist.id', read_only=True)
    class Meta:
        model = FavoriteTherapist
        fields = ['id', 'therapist', 'therapist_id', 'therapist_name', 'created_at']
        read_only_fields = ['id', 'created_at']
class CustomerFavouriteSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_address = serializers.CharField(source='store.address', read_only=True)
    professional_account_name = serializers.CharField(source='professional_account.name', read_only=True)
    class Meta:
        model = CustomerFavourite
        fields = ['id', 'store', 'store_name', 'store_address', 'professional_account', 'professional_account_name', 'created_at']
        read_only_fields = ['id', 'created_at']
    def validate_store(self, store):
        customer = self.context.get('customer')
        if customer and CustomerFavourite.objects.filter(customer=customer, store=store).exists():
            raise serializers.ValidationError("This salon is already saved.")
        return store
class CustomerInvoiceSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    class Meta:
        model = Invoice
        fields = ['id', 'invoice_number', 'store_name', 'grand_total_paise', 'status', 'created_at']
        read_only_fields = ['id']
class CustomerNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'title', 'message', 'is_read', 'type', 'created_at']
class CustomerReviewSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store_group.name', read_only=True)
    professional_name = serializers.CharField(source='professional_account.name', read_only=True, default=None)
    class Meta:
        model = ProfessionalReview
        fields = ['id', 'store_name', 'professional_name', 'store_rating', 'professional_rating', 'comment', 'media_url', 'created_at']
class ChatMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source='sender.get_full_name', read_only=True)
    is_mine = serializers.SerializerMethodField()
    class Meta:
        model = ChatMessage
        fields = ['id', 'sender', 'sender_name', 'content', 'is_read', 'created_at', 'is_mine']
    def get_is_mine(self, obj):
        request = self.context.get('request')
        return bool(request and obj.sender_id == request.user.id)
class ConversationSerializer(serializers.ModelSerializer):
    therapist_name = serializers.CharField(source='therapist.get_full_name', read_only=True)
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    class Meta:
        model = Conversation
        fields = ['id', 'therapist', 'therapist_name', 'last_message', 'unread_count', 'created_at']
    def get_last_message(self, obj):
        m = obj.messages.order_by('-created_at').first()
        if not m:
            return None
        request = self.context.get('request')
        is_mine = bool(request and m.sender_id == request.user.id)
        return {
            'id': m.id,
            'content': m.content,
            'created_at': m.created_at.isoformat() if m.created_at else None,
            'is_mine': is_mine,
            'sender_id': m.sender_id,
        }
    def get_unread_count(self, obj):
        request = self.context.get('request')
        if not request:
            return 0
        return obj.messages.exclude(sender=request.user).filter(is_read=False).count()
class PublicCouponSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    city = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()

    class Meta:
        model = Coupon
        fields = [
            'id', 'code', 'discount_type', 'discount_value', 'maximum_discount',
            'store', 'store_name', 'city', 'start_date', 'end_date', 'title', 'description'
        ]

    def get_city(self, obj):
        if not obj.store:
            return None
        if obj.store.outlet and obj.store.outlet.city:
            return obj.store.outlet.city.name
        addr = (obj.store.address or "").lower()
        if 'chennai' in addr:
            return 'Chennai'
        if 'bengaluru' in addr or 'bangalore' in addr:
            return 'Bengaluru'
        if 'mumbai' in addr:
            return 'Mumbai'
        if 'delhi' in addr:
            return 'Delhi NCR'
        if 'hyderabad' in addr:
            return 'Hyderabad'
        return 'Bengaluru'

    def get_title(self, obj):
        val = int(obj.discount_value) if obj.discount_value == int(obj.discount_value) else float(obj.discount_value)
        if obj.discount_type == 'PERCENTAGE':
            cap_str = f" up to ₹{int(obj.maximum_discount)}" if obj.maximum_discount else ""
            return f"{val}% OFF{cap_str}"
        return f"Flat ₹{val} OFF"

    def get_description(self, obj):
        val = int(obj.discount_value) if obj.discount_value == int(obj.discount_value) else float(obj.discount_value)
        if obj.discount_type == 'PERCENTAGE':
            if obj.maximum_discount:
                return f"Get {val}% discount on your booking (max ₹{int(obj.maximum_discount)})."
            return f"Get {val}% discount on your booking."
        return f"Save flat ₹{val} on your salon appointment."

class PublicTherapistSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    city = serializers.SerializerMethodField()
    store_name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'name', 'city', 'store_name', 'role']

    def get_name(self, obj):
        return obj.get_full_name() or obj.first_name or "Specialist"

    def get_city(self, obj):
        if obj.outlet and obj.outlet.city:
            return obj.outlet.city.name
        if obj.store:
            if obj.store.outlet and obj.store.outlet.city:
                return obj.store.outlet.city.name
            addr = (obj.store.address or "").lower()
            if 'chennai' in addr:
                return 'Chennai'
            if 'bengaluru' in addr or 'bangalore' in addr:
                return 'Bengaluru'
            if 'mumbai' in addr:
                return 'Mumbai'
            if 'delhi' in addr:
                return 'Delhi NCR'
            if 'hyderabad' in addr:
                return 'Hyderabad'
        return "Bengaluru"

    def get_store_name(self, obj):
        return getattr(obj.store, 'name', None) or (obj.outlet.name if obj.outlet else "")

    def get_role(self, obj):
        profile = getattr(obj, 'therapist_profile', None)
        return getattr(profile, 'specialization', None) or "Top Rated"
from apps.core.models import StoreService, Professional
class Phase1StoreServiceSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='canonical_service.category.name', read_only=True, default=None)
    skill_tag = serializers.CharField(source='canonical_service.skill_tag', read_only=True, default=None)
    class Meta:
        model = StoreService
        fields = ['id', 'name', 'default_price_paise', 'deposit_percentage', 'duration_min', 'category_name', 'skill_tag']
        read_only_fields = fields
class Phase1ProfessionalSerializer(serializers.ModelSerializer):
    is_online = serializers.SerializerMethodField()
    availability_status = serializers.SerializerMethodField()

    class Meta:
        model = Professional
        fields = ['id', 'display_name', 'display_role', 'is_online', 'availability_status']
        read_only_fields = fields

    def get_is_online(self, obj):
        from apps.core.models import Attendance
        from django.utils import timezone
        if not obj.user_account_id or not obj.user_account.user_id:
            return True
        today = timezone.localtime().date()
        att = Attendance.objects.filter(staff=obj.user_account.user, date=today).first()
        if att:
            return bool(att.clock_in and not att.clock_out)
        return False

    def get_availability_status(self, obj):
        return "online" if self.get_is_online(obj) else "offline"
class Phase1BookingRequestSerializer(serializers.Serializer):
    store_service_id = serializers.UUIDField()
    professional_id = serializers.UUIDField(required=False, allow_null=True)
    slot_start = serializers.DateTimeField()
    slot_end = serializers.DateTimeField()
    is_home_service = serializers.BooleanField(required=False, default=False)
    service_address = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    hold_id = serializers.UUIDField(required=False, allow_null=True)
    pay_with_wallet = serializers.BooleanField(required=False, default=False)
    razorpay_order_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    razorpay_payment_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    razorpay_signature = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    def validate(self, attrs):
        if attrs.get('is_home_service') and not (attrs.get('service_address') or '').strip():
            raise serializers.ValidationError({"service_address": "An address is required for home service bookings."})
        return attrs
class SlotHoldRequestSerializer(serializers.Serializer):
    store_service_id = serializers.UUIDField()
    professional_id = serializers.UUIDField(required=False, allow_null=True)
    slot_start = serializers.DateTimeField()
    slot_end = serializers.DateTimeField()
    session_token = serializers.CharField(max_length=64)
class CreatePaymentOrderSerializer(serializers.Serializer):
    store_service_id = serializers.UUIDField()
    hold_id = serializers.UUIDField(required=False, allow_null=True)
    payment_type = serializers.ChoiceField(choices=['full', 'deposit'], required=False, default='full')
from apps.core.models import Booking, AppointmentSlot
class CustomerBookingSlotSerializer(serializers.ModelSerializer):
    store_service_name = serializers.CharField(source='store_service.name', read_only=True)
    professional_name = serializers.CharField(source='professional.display_name', read_only=True, default=None)
    class Meta:
        model = AppointmentSlot
        fields = [
            'id', 'store_service', 'store_service_name', 'professional', 'professional_name',
            'slot_start', 'slot_end', 'actual_start_time', 'actual_end_time',
            'start_variance_minutes', 'end_variance_minutes', 'override_reason', 'was_overridden',
            'price_paise', 'status',
        ]
        read_only_fields = fields
class CustomerBookingSerializer(serializers.ModelSerializer):
    outlet_name = serializers.CharField(source='outlet.name', read_only=True)
    slots = serializers.SerializerMethodField()
    has_review = serializers.SerializerMethodField()
    review = serializers.SerializerMethodField()
    professional_id = serializers.SerializerMethodField()
    store_id = serializers.SerializerMethodField()
    payment = serializers.SerializerMethodField()
    amount = serializers.SerializerMethodField()
    slot_time = serializers.SerializerMethodField()
    service_name = serializers.SerializerMethodField()
    therapist_name = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            'id', 'booking_code', 'outlet', 'outlet_name', 'status', 'booking_start', 'booking_end', 'slots', 'has_review', 'review', 'professional_id', 'store_id',
            'is_home_service', 'service_address', 'notes', 'on_the_way_at', 'therapist_lat', 'therapist_lng', 'location_updated_at',
            'payment', 'amount', 'slot_time', 'service_name', 'therapist_name',
        ]
        read_only_fields = fields

    def get_amount(self, obj):
        payment = getattr(obj, 'online_payment', None)
        if payment and payment.total_amount_paise:
            return round(float(payment.total_amount_paise) / 100, 2)
        from apps.core.models import AppointmentSlotStatus
        active_slots = obj.slots.exclude(status=AppointmentSlotStatus.CANCELLED)
        if not active_slots.exists():
            active_slots = obj.slots.all()
        total_paise = sum(s.price_paise for s in active_slots if s.price_paise)
        if total_paise:
            return round(float(total_paise) / 100, 2)
        return 0.0

    def get_slot_time(self, obj):
        if obj.booking_start:
            try:
                import zoneinfo
                kolkata_tz = zoneinfo.ZoneInfo('Asia/Kolkata')
                dt = obj.booking_start.astimezone(kolkata_tz)
                return dt.strftime('%I:%M %p')
            except Exception:
                from django.utils import timezone
                dt = timezone.localtime(obj.booking_start)
                return dt.strftime('%I:%M %p')
        return "11:30 AM"

    def get_service_name(self, obj):
        from apps.core.models import AppointmentSlotStatus
        active_slots = obj.slots.exclude(status=AppointmentSlotStatus.CANCELLED)
        if not active_slots.exists():
            active_slots = obj.slots.all()
        names = [s.store_service.name for s in active_slots if s.store_service and s.store_service.name]
        if len(names) > 1:
            return " + ".join(names)
        notes = getattr(obj, 'notes', '') or ''
        if 'Services:' in notes:
            try:
                part = notes.split('Services:')[1].split('(Home Visit)')[0].strip()
                if part:
                    return part
            except Exception:
                pass
        return " + ".join(names) if names else "Salon Service"

    def get_therapist_name(self, obj):
        first = obj.slots.first()
        if first and first.professional:
            return getattr(first.professional, 'display_name', None) or getattr(first.professional, 'name', None)
        return None
    def get_slots(self, obj):
        from apps.core.models import AppointmentSlotStatus
        active_slots = obj.slots.exclude(status=AppointmentSlotStatus.CANCELLED)
        if active_slots.count() > 1:
            return CustomerBookingSlotSerializer(active_slots, many=True).data
        notes = getattr(obj, 'notes', '') or ''
        if 'Services:' in notes:
            try:
                import re
                part = notes.split('Services:')[1].split('(Home Visit)')[0].strip()
                if part and ('+' in part or ',' in part):
                    sub_names = [s.strip() for s in re.split(r'[\+,]', part) if s.strip()]
                    if len(sub_names) > 1:
                        tot_paise = sum(s.price_paise for s in active_slots if s.price_paise) or 0
                        sub_paise = int(round(tot_paise / len(sub_names))) if tot_paise else 0
                        first_s = active_slots.first()
                        prof_name = getattr(first_s.professional, 'display_name', None) if first_s and first_s.professional else None
                        return [
                            {
                                "id": f"{first_s.id if first_s else obj.id}-{idx}",
                                "store_service_name": nm,
                                "price_paise": sub_paise,
                                "professional_name": prof_name,
                                "status": "scheduled",
                                "slot_start": obj.booking_start.isoformat() if obj.booking_start else None,
                                "slot_end": obj.booking_end.isoformat() if obj.booking_end else None,
                            }
                            for idx, nm in enumerate(sub_names)
                        ]
            except Exception:
                pass
        return CustomerBookingSlotSerializer(active_slots, many=True).data
    def get_store_id(self, obj):
        store = Store.objects.filter(outlet_id=obj.outlet_id).first()
        return store.id if store else None
    def get_payment(self, obj):
        payment = getattr(obj, 'online_payment', None)
        if not payment:
            return None
        return {
            "payment_type": payment.payment_type,
            "status": payment.status,
            "amount_paise": payment.amount_paise,
            "total_amount_paise": payment.total_amount_paise,
            "balance_due_paise": payment.total_amount_paise - payment.amount_paise,
        }
    def get_has_review(self, obj):
        from apps.core.models import ProfessionalReview
        return ProfessionalReview.objects.filter(booking=obj).exists()

    def get_review(self, obj):
        from apps.core.models import ProfessionalReview
        rev = ProfessionalReview.objects.filter(booking=obj).first()
        if not rev:
            return None
        return {
            "id": str(rev.id),
            "store_rating": rev.store_rating,
            "professional_rating": rev.professional_rating or rev.store_rating,
            "comment": rev.comment or "",
            "created_at": rev.created_at.isoformat() if rev.created_at else None,
        }

    def get_professional_id(self, obj):
        first = obj.slots.filter(professional__isnull=False).first()
        if first and first.professional_id:
            return str(first.professional_id)
        return None
class BookingTipRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('1.00'))
    professional_id = serializers.UUIDField()
class BookingReviewRequestSerializer(serializers.Serializer):
    store_rating = serializers.IntegerField(min_value=1, max_value=5)
    professional_rating = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True)
    professional_id = serializers.UUIDField(required=False, allow_null=True)
    therapist_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    comment = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    media_url = serializers.URLField(required=False, allow_blank=True, allow_null=True)
