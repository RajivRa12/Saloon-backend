from rest_framework import serializers
import re
from apps.core.models import (
    ServiceCategory, Service, StaffAvailability,
    Appointment, AppointmentItem, User, Invoice, InvoiceItem, Payment, Tip,
    MembershipTier, CustomerMembership,
    Vendor, Product, PurchaseOrder, PurchaseOrderItem,
    Expense, Commission, GiftCard, ServicePackage, CustomerPackage,
    Room, Shift, Attendance, LeaveRequest, MarketingCampaign, DailyRegister, Coupon,
    StaffDocument, StaffTarget, Payroll,
    ServiceProduct, StockTransfer, Referral, Waitlist,
    CustomerProfile, StaffTraining,
    KycDocument, KycDocType, BankSettlementAccount
)
class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = '__all__'
class ServiceCategorySerializer(serializers.ModelSerializer):
    services = ServiceSerializer(many=True, read_only=True)
    class Meta:
        model = ServiceCategory
        fields = ['id', 'business', 'name', 'is_active', 'created_at', 'updated_at', 'services']
        read_only_fields = ['business']
class StaffAvailabilitySerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source='staff.get_full_name', read_only=True)
    staff_email = serializers.CharField(source='staff.email', read_only=True)
    class Meta:
        model = StaffAvailability
        fields = '__all__'
        read_only_fields = ['staff']
class AppointmentItemSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)
    therapist_name = serializers.SerializerMethodField()
    class Meta:
        model = AppointmentItem
        fields = ['id', 'service', 'service_name', 'therapist', 'therapist_name', 'price']
    def get_therapist_name(self, obj):
        if obj.therapist:
            return obj.therapist.get_full_name() or obj.therapist.email
        return None
class AppointmentSerializer(serializers.ModelSerializer):
    items = AppointmentItemSerializer(many=True, read_only=True)
    customer_details = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    service_name = serializers.SerializerMethodField()
    therapist_name = serializers.SerializerMethodField()
    room_name = serializers.CharField(source='room.name', read_only=True)
    class Meta:
        model = Appointment
        fields = [
            'id', 'store', 'customer', 'customer_name', 'customer_details',
            'guest_name', 'guest_phone', 'room', 'room_name',
            'status', 'start_time', 'end_time', 'notes', 'service_name', 'therapist_name',
            'created_at', 'updated_at', 'items'
        ]
        read_only_fields = ['store', 'end_time']
    def get_customer_details(self, obj):
        if obj.customer:
            return {
                "name": obj.customer.get_full_name() or "Guest",
                "email": obj.customer.email,
                "phone": obj.customer.phone
            }
        return None
    def get_customer_name(self, obj):
        if obj.customer:
            name = obj.customer.get_full_name()
            if name and name.strip():
                return name
            return obj.customer.email.split('@')[0].capitalize()
        return obj.guest_name or "Walk-in"
    def get_service_name(self, obj):
        first_item = obj.items.first()
        if first_item and first_item.service:
            return first_item.service.name
        return "General Booking"
    def get_therapist_name(self, obj):
        first_item = obj.items.first()
        if first_item and first_item.therapist:
            t_name = first_item.therapist.get_full_name()
            return t_name if t_name and t_name.strip() else first_item.therapist.email.split('@')[0].capitalize()
        return "Any available"
class CreateAppointmentItemSerializer(serializers.Serializer):
    service_id = serializers.IntegerField()
    therapist_id = serializers.IntegerField(required=False, allow_null=True)
class CreateAppointmentSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField(required=False, allow_null=True)
    start_time = serializers.DateTimeField()
    notes = serializers.CharField(required=False, allow_blank=True)
    is_group = serializers.BooleanField(required=False, default=False)
    group_size = serializers.IntegerField(required=False, default=1)
    is_recurring = serializers.BooleanField(required=False, default=False)
    recurrence_pattern = serializers.CharField(required=False, allow_null=True)
    recurrence_end_date = serializers.DateField(required=False, allow_null=True)
    items = CreateAppointmentItemSerializer(many=True)
class InvoiceItemSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)
    class Meta:
        model = InvoiceItem
        fields = ['id', 'service', 'service_name', 'quantity', 'price', 'tax_rate', 'tax_amount', 'total']
class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ['id', 'method', 'amount', 'transaction_reference', 'created_at']
class TipSerializer(serializers.ModelSerializer):
    therapist_name = serializers.CharField(source='therapist.get_full_name', read_only=True)
    class Meta:
        model = Tip
        fields = ['id', 'therapist', 'therapist_name', 'amount', 'created_at']
class InvoiceSerializer(serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    tips = TipSerializer(many=True, read_only=True)
    customer_details = serializers.SerializerMethodField()
    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'store', 'appointment', 'customer', 'customer_details',
            'subtotal', 'discount_amount', 'tax_amount', 'grand_total', 'status',
            'created_at', 'updated_at', 'items', 'payments', 'tips'
        ]
        read_only_fields = ['invoice_number', 'store']
    def get_customer_details(self, obj):
        if obj.customer:
            return {
                "name": obj.customer.get_full_name() or "Guest",
                "email": obj.customer.email,
                "phone": obj.customer.phone
            }
        return None
class SplitPaymentSerializer(serializers.Serializer):
    method = serializers.CharField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    transaction_reference = serializers.CharField(required=False, allow_blank=True)
class CheckoutPaymentSerializer(serializers.Serializer):
    payments = SplitPaymentSerializer(many=True)
class MembershipTierSerializer(serializers.ModelSerializer):
    class Meta:
        model = MembershipTier
        fields = '__all__'
        read_only_fields = ['store']
class CustomerMembershipSerializer(serializers.ModelSerializer):
    tier_name = serializers.CharField(source='tier.name', read_only=True)
    discount_percentage = serializers.DecimalField(source='tier.discount_percentage', max_digits=5, decimal_places=2, read_only=True)
    class Meta:
        model = CustomerMembership
        fields = ['id', 'customer', 'tier', 'tier_name', 'discount_percentage', 'start_date', 'end_date', 'is_active']
class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = '__all__'
        read_only_fields = ['store']
class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = '__all__'
        read_only_fields = ['store']
class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    class Meta:
        model = PurchaseOrderItem
        fields = ['id', 'product', 'product_name', 'quantity', 'unit_cost', 'total']
        read_only_fields = ['total']
class PurchaseOrderSerializer(serializers.ModelSerializer):
    items = PurchaseOrderItemSerializer(many=True, read_only=True)
    vendor_name = serializers.CharField(source='vendor.name', read_only=True)
    class Meta:
        model = PurchaseOrder
        fields = ['id', 'vendor', 'vendor_name', 'order_date', 'status', 'total_amount', 'created_at', 'items']
        read_only_fields = ['store', 'total_amount', 'status']
class ExpenseSerializer(serializers.ModelSerializer):
    recorded_by_name = serializers.CharField(source='recorded_by.get_full_name', read_only=True)
    class Meta:
        model = Expense
        fields = '__all__'
        read_only_fields = ['store', 'recorded_by']
class CommissionSerializer(serializers.ModelSerializer):
    therapist_name = serializers.CharField(source='therapist.get_full_name', read_only=True)
    class Meta:
        model = Commission
        fields = '__all__'
        read_only_fields = ['store']
class ERPGiftCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = GiftCard
        fields = '__all__'
        read_only_fields = ['store', 'current_balance']
class ERPServicePackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServicePackage
        fields = '__all__'
        read_only_fields = ['store']
class ERPCustomerPackageSerializer(serializers.ModelSerializer):
    customer_email = serializers.CharField(source='customer.email', read_only=True)
    package_name = serializers.CharField(source='package.name', read_only=True)
    class Meta:
        model = CustomerPackage
        fields = '__all__'
        read_only_fields = ['store']
class ERPRoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = '__all__'
        read_only_fields = ['store']
class ShiftSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source='staff.get_full_name', read_only=True)
    class Meta:
        model = Shift
        fields = '__all__'
        read_only_fields = ['store']
class AttendanceSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source='staff.get_full_name', read_only=True)
    class Meta:
        model = Attendance
        fields = '__all__'
        read_only_fields = ['store']
class LeaveRequestSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source='staff.get_full_name', read_only=True)
    class Meta:
        model = LeaveRequest
        fields = '__all__'
        read_only_fields = ['store']
class MarketingCampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketingCampaign
        fields = '__all__'
        read_only_fields = ['store']
class ERPCouponSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coupon
        fields = '__all__'
        read_only_fields = ['store']
class DailyRegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyRegister
        fields = '__all__'
        read_only_fields = ['store']
class StaffDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffDocument
        fields = '__all__'
        read_only_fields = ['staff']
class StaffTargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffTarget
        fields = '__all__'
        read_only_fields = ['store', 'staff']
class PayrollSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source='staff.get_full_name', read_only=True)
    class Meta:
        model = Payroll
        fields = '__all__'
        read_only_fields = ['store', 'staff', 'total_payout']
class ServiceProductSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    class Meta:
        model = ServiceProduct
        fields = '__all__'
class StockTransferSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    from_store_name = serializers.CharField(source='from_store.name', read_only=True)
    to_store_name = serializers.CharField(source='to_store.name', read_only=True)
    class Meta:
        model = StockTransfer
        fields = '__all__'
        read_only_fields = ['from_store']
class ReferralSerializer(serializers.ModelSerializer):
    referrer_name = serializers.CharField(source='referrer.get_full_name', read_only=True)
    referred_user_name = serializers.CharField(source='referred_user.get_full_name', read_only=True)
    class Meta:
        model = Referral
        fields = '__all__'
class WaitlistSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.get_full_name', read_only=True)
    service_name = serializers.CharField(source='service.name', read_only=True)
    class Meta:
        model = Waitlist
        fields = '__all__'
        read_only_fields = ['store']
class CustomerProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerProfile
        fields = '__all__'
        read_only_fields = ['user']
class CustomerCRMDataSerializer(serializers.ModelSerializer):
    crm_profile = CustomerProfileSerializer(read_only=True)
    loyalty_points = serializers.IntegerField(read_only=True)
    total_visits = serializers.IntegerField(read_only=True, default=0)
    total_spend = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True, default=0.00)
    average_spend = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True, default=0.00)
    outstanding_balance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True, default=0.00)
    favorite_therapist_name = serializers.CharField(read_only=True, default=None)
    active_membership = serializers.SerializerMethodField()
    def get_active_membership(self, obj):
        from apps.core.models import CustomerMembership
        from datetime import date
        today = date.today()
        cm = CustomerMembership.objects.filter(
            customer=obj,
            is_active=True,
            end_date__gte=today
        ).order_by('-end_date').first()
        if cm:
            return {
                "id": cm.id,
                "tier_name": cm.tier.name,
                "tier_type": cm.tier.tier_type,
                "discount_percentage": cm.tier.discount_percentage,
                "start_date": cm.start_date,
                "end_date": cm.end_date,
                "is_frozen": cm.is_frozen
            }
        return None
    class Meta:
        model = User
        fields = [
            'id', 'first_name', 'last_name', 'email', 'phone',
            'loyalty_points', 'crm_profile',
            'total_visits', 'total_spend', 'average_spend',
            'outstanding_balance', 'favorite_therapist_name',
            'active_membership'
        ]
class ERPStaffSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, default='changeme123')
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'email', 'phone', 'name', 'role', 'password', 'is_active']
        read_only_fields = ['id']
    def get_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()
class StaffTrainingSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source='staff.get_full_name', read_only=True)
    class Meta:
        model = StaffTraining
        fields = '__all__'
        read_only_fields = ['store', 'created_at']
ALLOWED_DOC_TYPES = [d[0] for d in KycDocType.choices]
ALLOWED_EXTENSIONS = ['.pdf', '.jpg', '.jpeg', '.png']
MAX_FILE_SIZE_MB = 10
GSTIN_REGEX = re.compile(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$')
IFSC_REGEX = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')
class KycUploadSerializer(serializers.Serializer):
    doc_type = serializers.ChoiceField(choices=KycDocType.choices)
    file = serializers.FileField()
    def validate_file(self, value):
        name = value.name.lower()
        if not any(name.endswith(ext) for ext in ALLOWED_EXTENSIONS):
            raise serializers.ValidationError(
                f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
            )
        if value.size > MAX_FILE_SIZE_MB * 1024 * 1024:
            raise serializers.ValidationError(
                f"File too large. Maximum allowed size is {MAX_FILE_SIZE_MB} MB."
            )
        return value
class KycDocumentReadSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    doc_type_display = serializers.CharField(source='get_doc_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    class Meta:
        model = KycDocument
        fields = [
            'id', 'doc_type', 'doc_type_display', 'file_url',
            'status', 'status_display', 'uploaded_at',
            'reviewed_at', 'rejection_reason'
        ]
    def get_file_url(self, obj):
        return obj.file_display_url
class BankSettlementSerializer(serializers.ModelSerializer):
    ifsc_code = serializers.CharField(max_length=11)
    class Meta:
        model = BankSettlementAccount
        fields = [
            'id', 'account_holder_name', 'account_number',
            'ifsc_code', 'bank_name', 'branch_name', 'account_type',
            'submitted_at', 'is_verified', 'weekly_payout_enabled', 'rejection_reason'
        ]
        read_only_fields = ['id', 'submitted_at', 'is_verified', 'weekly_payout_enabled', 'rejection_reason']
    def validate_ifsc_code(self, value):
        value = value.upper().strip()
        if not IFSC_REGEX.match(value):
            raise serializers.ValidationError(
                "Invalid IFSC code format. Must be 11 characters: 4 letters + 0 + 6 alphanumeric (e.g. HDFC0001234)."
            )
        return value
    def validate_account_number(self, value):
        value = value.strip()
        if not value.isdigit() or not (9 <= len(value) <= 18):
            raise serializers.ValidationError(
                "Account number must be 9–18 digits."
            )
        return value
