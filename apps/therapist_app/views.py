import os
import uuid
from django.utils import timezone
from django.core.files.storage import default_storage
from rest_framework import generics, viewsets, mixins
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from apps.core.models import (
    PayoutDestination, PayoutVerificationStatus,
    ProfessionalTip, ProfessionalTipStatus,
    ProfessionalReview, ReviewResponse, ReputationConsent,
    AppointmentSlot, AppointmentSlotStatus, CommissionAccrual,
)
from .permissions import IsProfessional
from .serializers import (
    ProfessionalAccountSerializer, PayoutDestinationSerializer,
    ProfessionalTipSerializer, ProfessionalReviewSerializer, ReviewResponseSerializer,
    CommissionAccrualSerializer, AppointmentSlotScheduleSerializer,
    ReputationConsentSerializer,
)
def success_response(data, message="Success", status_code=200):
    return Response({"success": True, "message": message, "data": data}, status=status_code)
def error_response(message="Error", status_code=400):
    return Response({"success": False, "message": message, "data": None}, status=status_code)
class TherapistProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = ProfessionalAccountSerializer
    permission_classes = [IsAuthenticated, IsProfessional]
    def get_object(self):
        return self.request.professional_account
class TherapistPhotoUploadView(APIView):
    """Uploads a profile/portfolio image and returns its URL — the frontend
    then PATCHes that URL into profile_photo_url or a portfolio_items entry."""
    permission_classes = [IsAuthenticated, IsProfessional]
    parser_classes = [MultiPartParser, FormParser]
    ALLOWED_EXTENSIONS = ['.jpg', '.jpeg', '.png']
    MAX_BYTES = 8 * 1024 * 1024
    def post(self, request):
        photo = request.FILES.get('photo')
        if not photo:
            return error_response("photo is required.", 400)
        ext = os.path.splitext(photo.name)[1].lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            return error_response(f"Only {', '.join(self.ALLOWED_EXTENSIONS)} images are allowed.", 400)
        if photo.size > self.MAX_BYTES:
            return error_response("Image must be under 8MB.", 400)
        filename = f"professional_photos/{request.professional_account.id}/{uuid.uuid4().hex}{ext}"
        saved_path = default_storage.save(filename, photo)
        url = request.build_absolute_uri(default_storage.url(saved_path))
        return success_response({"url": url}, "Uploaded", 201)
class ReputationConsentView(generics.RetrieveUpdateAPIView):
    serializer_class = ReputationConsentSerializer
    permission_classes = [IsAuthenticated, IsProfessional]
    def get_object(self):
        consent, _ = ReputationConsent.objects.get_or_create(professional_account=self.request.professional_account)
        return consent
class PayoutDestinationViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = PayoutDestinationSerializer
    permission_classes = [IsAuthenticated, IsProfessional]
    def get_queryset(self):
        return PayoutDestination.objects.filter(professional_account=self.request.professional_account)
    def perform_create(self, serializer):
        serializer.save(professional_account=self.request.professional_account)
    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        from django.utils import timezone
        destination = self.get_object()
        destination.verification_status = PayoutVerificationStatus.VERIFIED
        destination.verified_at = timezone.now()
        destination.save()
        return success_response(PayoutDestinationSerializer(destination).data, "Payout destination verified.")
class ProfessionalTipViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ProfessionalTipSerializer
    permission_classes = [IsAuthenticated, IsProfessional]
    def get_queryset(self):
        return ProfessionalTip.objects.filter(
            professional_account=self.request.professional_account
        ).select_related('customer', 'booking', 'appointment_slot')
    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        tip = self.get_object()
        if tip.status == ProfessionalTipStatus.CONFIRMED:
            return error_response("Tip is already confirmed.", 400)
        tip.status = ProfessionalTipStatus.CONFIRMED
        tip.confirmed_at = timezone.now()
        payment_ref = (request.data.get('payment_ref') or '').strip()
        if payment_ref:
            tip.payment_ref = payment_ref
        tip.save()
        return success_response(ProfessionalTipSerializer(tip).data, "Tip confirmed.")
class ProfessionalReviewViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ProfessionalReviewSerializer
    permission_classes = [IsAuthenticated, IsProfessional]
    def get_queryset(self):
        return ProfessionalReview.objects.filter(
            professional_account=self.request.professional_account
        ).select_related('customer', 'store_group', 'booking').prefetch_related('response')
    @action(detail=True, methods=['post'])
    def respond(self, request, pk=None):
        review = self.get_object()
        if hasattr(review, 'response'):
            return error_response("This review already has a response.", 400)
        response_text = (request.data.get('response_text') or '').strip()
        if not response_text:
            return error_response("response_text is required.", 400)
        response = ReviewResponse.objects.create(
            review=review, professional_account=self.request.professional_account, response_text=response_text
        )
def format_human_variance(minutes):
    abs_m = abs(minutes)
    h = abs_m // 60
    m = abs_m % 60
    if h > 0 and m > 0:
        time_part = f"{h} hr {m} mins"
    elif h > 0:
        time_part = f"{h} hr"
    else:
        time_part = f"{m} mins"
    direction = "early" if minutes < 0 else "delayed"
    return f"{time_part} {direction}"


def notify_variance_stakeholders(slot, action_type, diff_minutes, is_variance, reason):
    """
    Delivers real-time notifications to Customer App and Store Admin / Reception
    whenever a service is started or completed with a time variance or override reason.
    """
    try:
        from apps.core.notifications import notify_user
        from apps.core.models import User, Role
        from django.db.models import Q

        service_name = slot.store_service.name if slot.store_service else "Service"
        prof_name = slot.professional.display_name if slot.professional else "Therapist"
        variance_str = format_human_variance(diff_minutes) if diff_minutes != 0 else "on time"

        if slot.booking and slot.booking.customer and slot.booking.customer.phone_e164:
            customer_user = User.objects.filter(phone=slot.booking.customer.phone_e164).first()
            if customer_user:
                if action_type == 'start':
                    title = f"Service Started: {service_name}"
                    msg = f"Your therapist {prof_name} started your appointment {variance_str}."
                else:
                    title = f"Service Completed: {service_name}"
                    msg = f"Your service '{service_name}' was completed {variance_str}."
                if reason:
                    msg += f" Note: {reason}"

                notify_user(
                    customer_user,
                    title,
                    msg,
                    notif_type='SYSTEM',
                    data={
                        'type': 'booking_schedule_update',
                        'booking_id': str(slot.booking.id),
                        'slot_id': str(slot.id),
                    }
                )

        outlet = getattr(slot, 'outlet', None) or (slot.booking.outlet if slot.booking else None)
        if outlet:
            store_staff = User.objects.filter(
                role__in=[Role.STORE_ADMIN, Role.RECEPTIONIST, Role.BRAND_OWNER]
            ).filter(
                Q(outlet=outlet) | Q(store__outlet=outlet)
            ).distinct()

            for staff_member in store_staff:
                admin_title = f"Schedule Variance: {prof_name} ({service_name})"
                admin_msg = f"{action_type.capitalize()} variance ({variance_str}) for booking #{slot.booking.booking_code or str(slot.booking.id)[:8]}."
                if reason:
                    admin_msg += f" Reason: {reason}"
                notify_user(
                    staff_member,
                    admin_title,
                    admin_msg,
                    notif_type='SYSTEM',
                    data={
                        'type': 'slot_variance_alert',
                        'booking_id': str(slot.booking.id),
                        'slot_id': str(slot.id),
                        'outlet_id': str(outlet.id),
                    }
                )
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Failed to notify variance stakeholders: %s", e)

class TherapistScheduleViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = AppointmentSlotScheduleSerializer
    permission_classes = [IsAuthenticated, IsProfessional]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['status']
    ordering = ['slot_start']
    def get_queryset(self):
        from apps.core.models import BookingStatus
        return AppointmentSlot.objects.filter(
            professional__user_account=self.request.professional_account
        ).exclude(
            status=AppointmentSlotStatus.CANCELLED
        ).exclude(
            booking__status=BookingStatus.CANCELLED
        ).select_related('booking', 'booking__outlet', 'booking__customer', 'store_service')
    def _sync_booking_status(self, booking):
        from apps.core.models import BookingStatus
        from apps.store_erp.views import _record_platform_commission
        slots = list(booking.slots.exclude(status=AppointmentSlotStatus.CANCELLED))
        
        if booking.actual_start_time is None:
            started_slots = [s for s in slots if s.actual_start_time]
            if started_slots:
                booking.actual_start_time = min(s.actual_start_time for s in started_slots)
                booking.save(update_fields=['actual_start_time'])

        if slots and all(s.status == AppointmentSlotStatus.DONE for s in slots):
            if booking.status != BookingStatus.COMPLETED:
                booking.status = BookingStatus.COMPLETED
                if booking.actual_end_time is None:
                    completed_slots = [s for s in slots if s.actual_end_time]
                    if completed_slots:
                        booking.actual_end_time = max(s.actual_end_time for s in completed_slots)
                booking.save()
                _record_platform_commission(booking)
        elif booking.status == BookingStatus.CONFIRMED and any(s.status == AppointmentSlotStatus.STARTED for s in slots):
            booking.status = BookingStatus.IN_SERVICE
            booking.save(update_fields=['status'])

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        slot = self.get_object()
        
        if slot.status == AppointmentSlotStatus.STARTED:
            return success_response(AppointmentSlotScheduleSerializer(slot).data, "Service already started.")

        if slot.status not in [AppointmentSlotStatus.SCHEDULED, AppointmentSlotStatus.DONE]:
            return error_response(f"Cannot start a slot in status '{slot.status}'.", 400)

        now = timezone.now()
        diff_seconds = (now - slot.slot_start).total_seconds()
        diff_minutes = round(diff_seconds / 60.0)
        is_variance = abs(diff_minutes) > 15

        reason = (request.data.get('reason') or '').strip()

        if is_variance and not reason:
            reason = "Started service on time"

        slot.actual_start_time = now
        slot.actual_end_time = None
        slot.start_variance_minutes = diff_minutes
        slot.status = AppointmentSlotStatus.STARTED

        if reason:
            var_prefix = f"Start variance ({format_human_variance(diff_minutes)}): " if is_variance else ""
            slot.override_reason = f"{var_prefix}{reason}".strip()
            slot.was_overridden = True
            if hasattr(request, 'user') and request.user and request.user.is_authenticated:
                slot.overridden_by = request.user

        slot.save()
        self._sync_booking_status(slot.booking)
        try:
            from apps.core.notifications import notify_user
            prof_user = request.user
            if slot.professional and getattr(slot.professional, 'user_account', None):
                prof_user = slot.professional.user_account.user
            cust_name = slot.booking.customer.name if (slot.booking and slot.booking.customer) else "Client"
            srv_name = slot.store_service.name if slot.store_service else "Service"
            notify_user(
                prof_user,
                f"Service Started: {cust_name}",
                f"{srv_name} is now in progress with 35m countdown.",
                notif_type='SYSTEM',
                data={'slot_id': str(slot.id), 'type': 'service_started'}
            )
        except Exception:
            pass
        if is_variance or reason:
            notify_variance_stakeholders(slot, 'start', diff_minutes, is_variance, reason)
        return success_response(AppointmentSlotScheduleSerializer(slot).data, "Service started.")

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        slot = self.get_object()
        
        if slot.status == AppointmentSlotStatus.DONE:
            return success_response(AppointmentSlotScheduleSerializer(slot).data, "Service already completed.")

        if slot.status not in [AppointmentSlotStatus.SCHEDULED, AppointmentSlotStatus.STARTED]:
            return error_response(f"Cannot complete a slot in status '{slot.status}'.", 400)

        now = timezone.now()
        target_end = slot.slot_end or slot.slot_start
        diff_seconds = (now - target_end).total_seconds()
        diff_minutes = round(diff_seconds / 60.0)
        is_variance = abs(diff_minutes) > 15

        reason = (request.data.get('reason') or '').strip()

        if is_variance and not reason:
            return error_response(
                f"Appointment is completing {format_human_variance(diff_minutes)}. A valid reason is required.",
                400
            )

        if slot.actual_end_time is None:
            slot.actual_end_time = now
            slot.end_variance_minutes = diff_minutes

        if slot.actual_start_time is None:
            slot.actual_start_time = slot.slot_start

        slot.status = AppointmentSlotStatus.DONE

        if reason:
            var_prefix = f"Completion variance ({format_human_variance(diff_minutes)}): " if is_variance else "Completion note: "
            existing_reason = f"{slot.override_reason}\n" if slot.override_reason else ""
            slot.override_reason = f"{existing_reason}{var_prefix}{reason}".strip()
            slot.was_overridden = True
            if hasattr(request, 'user') and request.user and request.user.is_authenticated:
                slot.overridden_by = request.user

        slot.save()
        self._sync_booking_status(slot.booking)
        try:
            from apps.core.notifications import notify_user
            prof_user = request.user
            if slot.professional and getattr(slot.professional, 'user_account', None):
                prof_user = slot.professional.user_account.user
            cust_name = slot.booking.customer.name if (slot.booking and slot.booking.customer) else "Client"
            srv_name = slot.store_service.name if slot.store_service else "Service"
            comm_amount = round((slot.price_paise or 75000) * 0.30 / 100)
            notify_user(
                prof_user,
                f"Service Completed: {cust_name}",
                f"Great job! {srv_name} completed. ₹{comm_amount} commission credited.",
                notif_type='SYSTEM',
                data={'slot_id': str(slot.id), 'type': 'service_completed', 'commission': comm_amount}
            )
        except Exception:
            pass
        if is_variance or reason:
            notify_variance_stakeholders(slot, 'complete', diff_minutes, is_variance, reason)
        return success_response(AppointmentSlotScheduleSerializer(slot).data, "Marked complete.")
    def _parse_latlng(self, request):
        lat, lng = request.data.get('lat'), request.data.get('lng')
        if lat is None or lng is None:
            return None, None
        from decimal import Decimal, InvalidOperation
        try:
            return Decimal(str(lat)), Decimal(str(lng))
        except InvalidOperation:
            return False, False
    @action(detail=True, methods=['post'], url_path='on-the-way')
    def on_the_way(self, request, pk=None):
        slot = self.get_object()
        booking = slot.booking
        if not booking.is_home_service:
            return error_response("This isn't a home-service booking.", 400)
        lat, lng = self._parse_latlng(request)
        if lat is False:
            return error_response("lat/lng must be numbers.", 400)
        from django.utils import timezone
        booking.on_the_way_at = timezone.now()
        update_fields = ['on_the_way_at']
        if lat is not None:
            booking.therapist_lat, booking.therapist_lng = lat, lng
            booking.location_updated_at = timezone.now()
            update_fields += ['therapist_lat', 'therapist_lng', 'location_updated_at']
        booking.save(update_fields=update_fields)
        return success_response(AppointmentSlotScheduleSerializer(slot).data, "Customer notified you're on the way.")
    @action(detail=True, methods=['post'], url_path='update-location')
    def update_location(self, request, pk=None):
        slot = self.get_object()
        booking = slot.booking
        if not booking.is_home_service:
            return error_response("This isn't a home-service booking.", 400)
        lat, lng = self._parse_latlng(request)
        if lat is None:
            return error_response("lat and lng are required.", 400)
        if lat is False:
            return error_response("lat/lng must be numbers.", 400)
        from django.utils import timezone
        booking.therapist_lat, booking.therapist_lng = lat, lng
        booking.location_updated_at = timezone.now()
        booking.save(update_fields=['therapist_lat', 'therapist_lng', 'location_updated_at'])
        return success_response(None, "Location updated.")
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        slot = self.get_object()
        if slot.status == AppointmentSlotStatus.DONE:
            return error_response("Cannot cancel a completed slot.", 400)
        slot.status = AppointmentSlotStatus.CANCELLED
        slot.save()
        return success_response(AppointmentSlotScheduleSerializer(slot).data, "Cancelled.")
class TherapistCommissionAccrualView(generics.ListAPIView):
    serializer_class = CommissionAccrualSerializer
    permission_classes = [IsAuthenticated, IsProfessional]
    def get_queryset(self):
        return CommissionAccrual.objects.filter(
            professional__user_account=self.request.professional_account
        ).select_related('invoice_line', 'invoice_line__invoice', 'invoice_line__service', 'invoice_line__store_service').order_by('-created_at')

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        items = list(CommissionAccrualSerializer(queryset, many=True).data)

        from apps.core.models import AppointmentSlot, AppointmentSlotStatus
        completed_slots = AppointmentSlot.objects.filter(
            professional__user_account=self.request.professional_account,
            status=AppointmentSlotStatus.DONE
        ).select_related('store_service', 'booking', 'booking__customer').order_by('-slot_start')

        for slot in completed_slots:
            base_paise = slot.price_paise or 75000
            # 30% stylist commission
            comm_paise = int(base_paise * 0.30)
            service_name = slot.store_service.name if slot.store_service else "Salon Service"
            customer_name = slot.booking.customer.name if (slot.booking and slot.booking.customer) else "Client"
            if customer_name and customer_name.startswith("91") and "@phone.nearbyme.local" in customer_name:
                raw_ph = customer_name.replace("@phone.nearbyme.local", "")
                customer_name = f"+91 {raw_ph[2:7]} {raw_ph[7:]}" if len(raw_ph) == 12 else f"Client ({raw_ph})"

            created_at_dt = slot.actual_end_time or slot.slot_start or timezone.now()
            items.append({
                'id': str(slot.id),
                'invoice_line': None,
                'invoice_number': f"INV-{str(slot.id)[:8].upper()}",
                'service_name': f"{service_name} ({customer_name})",
                'customer_name': customer_name,
                'base_paise': base_paise,
                'commission_paise': comm_paise,
                'created_at': created_at_dt.isoformat() if hasattr(created_at_dt, 'isoformat') else str(created_at_dt),
            })

        items.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
        return success_response(items, "Commissions fetched")
