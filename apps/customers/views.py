import logging
from rest_framework import viewsets, generics, status
from rest_framework.views import APIView

logger = logging.getLogger(__name__)
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from django.db.models import Prefetch
from django.utils import timezone
from apps.core.models import (
    Store, ServiceCategory, Service, User, Role,
    Appointment, Wallet, CustomerMembership, Review,
    GiftCard, CustomerPackage, FavoriteTherapist, CustomerFavourite, Invoice, Coupon, Tip, WalletTransaction,
    Booking, GlobalCustomer, normalize_e164, resolve_customer_name,
    Notification, ProfessionalReview,
    Conversation, ChatMessage, Referral,
    SlotHold, SlotHoldStatus, Professional, Resource, ResourceType,
    AppointmentSlot, AppointmentSlotStatus, StorePublicProfile,
    OnlinePayment, OnlinePaymentStatus, MembershipTier,
)
from .serializers import (
    PublicStoreSerializer, PublicServiceCategorySerializer,
    PublicReviewSerializer, CustomerProfileSerializer,
    CustomerWalletSerializer, CustomerMembershipSerializer,
    CustomerAppointmentSerializer, GiftCardSerializer,
    CustomerPackageSerializer,
    FavoriteTherapistSerializer, CustomerFavouriteSerializer, CustomerInvoiceSerializer,
    PublicServiceSerializer, PublicCouponSerializer, PublicTherapistSerializer,
    Phase1StoreServiceSerializer, Phase1ProfessionalSerializer, Phase1BookingRequestSerializer,
    SlotHoldRequestSerializer, MicrositeSerializer, CreatePaymentOrderSerializer,
    CustomerBookingSerializer, BookingTipRequestSerializer, BookingReviewRequestSerializer,
    CustomerNotificationSerializer, CustomerReviewSerializer,
    ConversationSerializer, ChatMessageSerializer,
)
from .permissions import IsCustomer
def success_response(data, message="Success", status_code=200):
    return Response({"success": True, "message": message, "data": data}, status=status_code)
def error_response(message="Error", status_code=400):
    return Response({"success": False, "message": message, "data": None}, status=status_code)
class MicrositeView(generics.RetrieveAPIView):
    """A store's own public booking page — /s/<slug>. Deliberately built as a
    RetrieveAPIView with no list action anywhere on this class: there is no
    query here that could ever return more than one store, so a competitor
    appearing on a store's own page isn't a filter someone could forget —
    it's structurally not possible. See build guide rule 25."""
    permission_classes = [AllowAny]
    serializer_class = MicrositeSerializer
    lookup_field = 'slug'
    queryset = StorePublicProfile.objects.filter(is_microsite_live=True).select_related('store')
def _clean_customer_defaults(user, req_name=None):
    if req_name:
        req = str(req_name).strip()
        if req and '@' not in req and not req.startswith('+') and not req.isdigit() and req not in ('Valued Customer', 'Valued Client', 'Client'):
            return {'name': req, 'email': user.email if '@phone.nearbyme.local' not in (user.email or '') else None}
    name = (user.get_full_name() or user.first_name or '').strip()
    if name and '@' not in name and not name.startswith('+') and not name.isdigit():
        return {'name': name, 'email': user.email if '@phone.nearbyme.local' not in (user.email or '') else None}
    digits = ''.join(ch for ch in str(getattr(user, 'phone', '') or '') if ch.isdigit())
    last4 = digits[-4:] if len(digits) >= 4 else ''
    clean_name = f"Client {last4}" if last4 else "Valued Client"
    return {'name': clean_name, 'email': user.email if '@phone.nearbyme.local' not in (user.email or '') else None}


class PublicStoreViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Store.objects.filter(status='ACTIVE').select_related('platform_subscription__plan', 'public_profile')
    serializer_class = PublicStoreSerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['brand', 'business__business_type']
    search_fields = ['name', 'address', 'location']
    ordering = ['name']
    def list(self, request, *args, **kwargs):
        from apps.core.models import CityMarketplaceFlag
        queryset = self.filter_queryset(self.get_queryset())
        city_param = request.query_params.get('city')
        if city_param:
            queryset = queryset.filter(outlet__city__name__iexact=city_param.strip())
        cat_param = request.query_params.get('category') or request.query_params.get('business_type')
        if cat_param and cat_param.upper() != 'ALL':
            queryset = queryset.filter(business__business_type__iexact=cat_param.strip())
        dark_city_ids = set(
            CityMarketplaceFlag.objects.filter(is_public=False).values_list('city_id', flat=True)
        )
        if dark_city_ids:
            filtered = queryset.exclude(outlet__city_id__in=dark_city_ids)
            if filtered.exists():
                queryset = filtered
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)
        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)
    @action(detail=True, methods=['get'])
    def rooms(self, request, pk=None):
        from apps.core.models import Room
        store = self.get_object()
        rooms = Room.objects.filter(store=store, is_active=True).order_by('name')
        return success_response([{"id": r.id, "name": r.name} for r in rooms], f"Rooms for {store.name}")
    @action(detail=True, methods=['get'])
    def menu(self, request, pk=None):
        from apps.core.models import StoreService, Service
        store = self.get_object()
        outlet = store.outlet if store.outlet_id else None
        store_group = outlet.store_group if (outlet and outlet.store_group_id) else None

        # Check for Phase 1 StoreService catalog (managed via StoreAdmin)
        store_services = None
        if store_group:
            store_services = StoreService.objects.filter(
                store_group=store_group
            ).select_related('canonical_service', 'canonical_service__category')
        elif outlet:
            store_services = StoreService.objects.filter(
                store_group__outlets=outlet
            ).select_related('canonical_service', 'canonical_service__category')

        if store_services and store_services.exists():
            # Exclude paused services (is_active_in_store=False)
            active_store_services = store_services.filter(is_active_in_store=True).order_by('name')
            categories_map = {}
            for ss in active_store_services:
                cat_name = "General"
                if ss.canonical_service and ss.canonical_service.category and ss.canonical_service.category.name:
                    cat_name = ss.canonical_service.category.name
                else:
                    leg_svc = Service.objects.filter(name__iexact=ss.name).select_related('category').first()
                    if leg_svc and leg_svc.category:
                        cat_name = leg_svc.category.name
                    else:
                        cat_name = ss.name

                if cat_name not in categories_map:
                    categories_map[cat_name] = {
                        "id": f"cat-{len(categories_map)+1}",
                        "name": cat_name,
                        "services": []
                    }
                categories_map[cat_name]["services"].append({
                    "id": str(ss.id),
                    "name": ss.name,
                    "price": (ss.default_price_paise or 0) / 100.0,
                    "duration_minutes": ss.duration_min or 45,
                    "category_name": cat_name,
                    "description": (ss.canonical_service.description if (ss.canonical_service and hasattr(ss.canonical_service, 'description')) else "") or "",
                    "is_premium_listing": False,
                    "is_active": True,
                    "is_active_in_store": True,
                })
            return success_response(list(categories_map.values()), f"Menu for {store.name}")

        # Fallback to legacy ServiceCategory & Service
        paused_names = set(StoreService.objects.filter(
            is_active_in_store=False
        ).values_list('name', flat=True))

        categories = ServiceCategory.objects.filter(
            business=store.business_id,
            is_active=True
        ).prefetch_related(
            Prefetch('services', queryset=Service.objects.filter(is_active=True).exclude(name__in=paused_names))
        )
        data = []
        for cat in categories:
            svcs = [
                s for s in cat.services.filter(is_active=True)
                if s.name not in paused_names
            ]
            if svcs:
                data.append({
                    "id": cat.id,
                    "name": cat.name,
                    "services": PublicServiceSerializer(svcs, many=True).data
                })
        return success_response(data, f"Menu for {store.name}")
    @action(detail=True, methods=['get'])
    def staff(self, request, pk=None):
        store = self.get_object()
        therapists = User.objects.filter(store=store, role=Role.THERAPIST, is_active=True).select_related('therapist_profile')
        data = [{
            "id": t.id,
            "name": t.get_full_name(),
            "specializations": getattr(getattr(t, 'therapist_profile', None), 'specializations', None) or None,
        } for t in therapists]
        return success_response(data, f"Staff for {store.name}")
    @action(detail=True, methods=['get'], url_path='phase1-menu')
    def phase1_menu(self, request, pk=None):
        from apps.core.models import StoreService
        store = self.get_object()
        if not store.outlet_id:
            return error_response("Online booking is not available for this location yet.", 404)
        services = StoreService.objects.filter(
            store_group=store.outlet.store_group_id, is_active_in_store=True
        ).select_related('canonical_service', 'canonical_service__category')
        return success_response(Phase1StoreServiceSerializer(services, many=True).data, f"Menu for {store.name}")
    @action(detail=True, methods=['get'], url_path='phase1-professionals')
    def phase1_professionals(self, request, pk=None):
        from django.db import models
        from apps.core.models import Professional, ProfessionalLinkStatus, StoreService
        store = self.get_object()
        if not store.outlet_id:
            return error_response("Online booking is not available for this location yet.", 404)
        qs = Professional.objects.filter(
            outlet_id=store.outlet_id
        ).filter(models.Q(link_status=ProfessionalLinkStatus.ACCEPTED) | models.Q(link_status=ProfessionalLinkStatus.INVITED))
        skill_tag = None
        service_id = request.query_params.get('service_id')
        if service_id:
            svc = StoreService.objects.filter(id=service_id).select_related('canonical_service').first()
            if svc and svc.canonical_service_id:
                skill_tag = svc.canonical_service.skill_tag
        if skill_tag:
            filtered_qs = qs.filter(skills__skill_tag=skill_tag)
            if filtered_qs.exists():
                qs = filtered_qs
        return success_response(Phase1ProfessionalSerializer(qs.distinct(), many=True).data)
    @action(detail=True, methods=['get'], url_path='phase1-availability')
    def phase1_availability(self, request, pk=None):
        import datetime
        from apps.core.models import StoreService
        from apps.store_erp.availability import compute_availability
        store = self.get_object()
        if not store.outlet_id:
            return error_response("Online booking is not available for this location yet.", 404)
        service_id = request.query_params.get('service_id')
        date_str = request.query_params.get('date')
        if not service_id or not date_str:
            return error_response("service_id and date are required", 400)
        try:
            the_date = datetime.date.fromisoformat(date_str)
        except ValueError:
            return error_response("date must be in YYYY-MM-DD format", 400)
        try:
            svc = StoreService.objects.get(id=service_id, store_group=store.outlet.store_group_id)
        except StoreService.DoesNotExist:
            return error_response("Service not found for this store.", 404)
        professional_id = request.query_params.get('professional_id')
        duration_min, slots = compute_availability(store.outlet, svc, the_date, professional_id)
        return success_response({
            "duration_min": duration_min,
            "slots": [
                {
                    "start": s["start"].isoformat(), "end": s["end"].isoformat(),
                    "professionals": [{"id": str(p.id), "display_name": p.display_name} for p in s["professionals"]],
                }
                for s in slots
            ],
        })
    @action(detail=True, methods=['post'], url_path='hold-slot')
    def hold_slot(self, request, pk=None):
        """Reserves a slot for ~8 minutes while a guest completes OTP + payment,
        so it can't be taken out from under them. See build guide section 6."""
        import datetime as dt
        from apps.core.models import StoreService
        from apps.store_erp.booking_engine import auto_assign_professional
        from apps.store_erp.availability import service_duration_and_buffers, bump_availability_version
        store = self.get_object()
        if not store.outlet_id:
            return error_response("Online booking is not available for this location yet.", 404)
        serializer = SlotHoldRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            svc = StoreService.objects.get(id=data['store_service_id'], store_group=store.outlet.store_group_id)
        except StoreService.DoesNotExist:
            return error_response("Service not found for this store.", 404)
        slot_start, slot_end = data['slot_start'], data['slot_end']
        if data.get('professional_id'):
            professional = Professional.objects.filter(id=data['professional_id'], outlet=store.outlet).first()
            if not professional:
                return error_response("Selected professional is not available at this outlet.", 404)
        else:
            professional = auto_assign_professional(store.outlet, svc, slot_start.date(), slot_start, slot_end)
        if not professional:
            return error_response("That time just went. Please pick another slot.", 409)
        conflict = SlotHold.objects.filter(
            professional=professional, status=SlotHoldStatus.HELD, expires_at__gt=timezone.now(),
            slot_start__lt=slot_end, slot_end__gt=slot_start,
        ).exists() or AppointmentSlot.objects.filter(
            professional=professional, status__in=[AppointmentSlotStatus.SCHEDULED, AppointmentSlotStatus.STARTED, AppointmentSlotStatus.DONE],
            slot_start__lt=slot_end, slot_end__gt=slot_start,
        ).exists()
        if conflict:
            return error_response("That time just went. Please pick another slot.", 409)
        _, _, _, _, resource_type = service_duration_and_buffers(svc, store.outlet)
        resource = None
        if resource_type != ResourceType.NONE:
            resource = Resource.objects.filter(outlet=store.outlet, resource_type=resource_type, is_bookable=True).first()
        hold = SlotHold.objects.create(
            outlet=store.outlet, store_service=svc, professional=professional, resource=resource,
            slot_start=slot_start, slot_end=slot_end, session_token=data['session_token'],
            expires_at=timezone.now() + dt.timedelta(minutes=8),
        )
        bump_availability_version(store.outlet_id)
        return success_response({
            "id": str(hold.id), "expires_at": hold.expires_at.isoformat(),
            "professional_id": str(professional.id), "professional_name": professional.display_name,
        }, "Slot held", 201)
    @action(detail=True, methods=['post'], url_path='release-hold')
    def release_hold(self, request, pk=None):
        from apps.store_erp.availability import bump_availability_version
        hold = SlotHold.objects.filter(
            id=request.data.get('hold_id'), session_token=request.data.get('session_token'), status=SlotHoldStatus.HELD,
        ).first()
        if hold:
            hold.status = SlotHoldStatus.RELEASED
            hold.save(update_fields=['status'])
            bump_availability_version(hold.outlet_id)
        return success_response(None, "Released")
    @action(detail=True, methods=['post'], url_path='create-payment-order', permission_classes=[IsAuthenticated, IsCustomer])
    def create_payment_order(self, request, pk=None):
        """Raises a Razorpay order for a Phase1 booking. Amount is always
        computed server-side from StoreService pricing (build guide rule:
        no client-side price computation) — the client only tells us which
        service and, optionally, which held slot it's paying for."""
        from apps.core.models import StoreService, GlobalCustomer, normalize_e164
        from apps.store_erp.availability import service_price_paise
        from .payments import create_order, PaymentsNotConfigured
        from django.conf import settings
        store = self.get_object()
        if not store.outlet_id:
            return error_response("Online booking is not available for this location yet.", 404)
        serializer = CreatePaymentOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            svc = StoreService.objects.get(id=data['store_service_id'], store_group=store.outlet.store_group_id)
        except StoreService.DoesNotExist:
            return error_response("Service not found for this store.", 404)
        hold = None
        hold_id = data.get('hold_id')
        if hold_id:
            hold = SlotHold.objects.filter(id=hold_id, status=SlotHoldStatus.HELD, expires_at__gt=timezone.now()).first()
            if not hold:
                return error_response("Your hold expired. Please pick another slot.", 409)
        total_amount_paise = service_price_paise(svc, store.outlet)
        payment_type = data.get('payment_type', 'full')
        if payment_type == 'deposit':
            amount_paise = (total_amount_paise * svc.deposit_percentage) // 100
        else:
            amount_paise = total_amount_paise
        try:
            order = create_order(amount_paise, receipt=str(hold_id or svc.id), notes={
                "store_service_id": str(svc.id), "store_id": str(store.id), "payment_type": payment_type,
            })
        except PaymentsNotConfigured as e:
            return error_response(str(e), 503)
        user = request.user
        cust_defaults = _clean_customer_defaults(user)
        if user.phone:
            customer, created = GlobalCustomer.objects.get_or_create(
                phone_e164=normalize_e164(user.phone), defaults=cust_defaults
            )
        else:
            customer, created = GlobalCustomer.objects.get_or_create(email=user.email, defaults=cust_defaults)
        if not created and (not customer.name or '@' in customer.name or customer.name.startswith('+') or customer.name.isdigit() or customer.name == 'Valued Customer'):
            customer.name = cust_defaults['name']
            customer.save(update_fields=['name'])
        payment = OnlinePayment.objects.create(
            hold=hold, store_service=svc, customer=customer, payment_type=payment_type,
            amount_paise=amount_paise, total_amount_paise=total_amount_paise, gateway_order_id=order['id'],
        )
        return success_response({
            "order_id": order['id'], "amount": amount_paise, "total_amount": total_amount_paise,
            "balance_due": total_amount_paise - amount_paise, "payment_type": payment_type, "currency": "INR",
            "key_id": settings.RAZORPAY_KEY_ID, "payment_id": str(payment.id),
        }, "Payment order created", 201)
    @action(detail=True, methods=['post'], url_path='phase1-book', permission_classes=[IsAuthenticated, IsCustomer])
    def phase1_book(self, request, pk=None):
        from decimal import Decimal
        from django.db import transaction
        from apps.core.models import GlobalCustomer, Booking, BookingStatus, BookingSource, normalize_e164, StoreService
        from apps.store_erp.booking_engine import confirm_booking, BookingConflictError, BookingEngineError
        from apps.store_erp.availability import bump_availability_version, service_price_paise
        from .payments import verify_payment, refund_payment, PaymentsNotConfigured, PaymentVerificationError
        store = self.get_object()
        if not store.outlet_id:
            return error_response("Online booking is not available for this location yet.", 404)
        serializer = Phase1BookingRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        slot_start = serializer.validated_data['slot_start']
        slot_end = serializer.validated_data['slot_end']
        pay_with_wallet = serializer.validated_data.get('pay_with_wallet', False)
        wallet = None
        if pay_with_wallet:
            try:
                store_service_for_price = StoreService.objects.get(
                    id=serializer.validated_data['store_service_id'], store_group=store.outlet.store_group
                )
            except StoreService.DoesNotExist:
                return error_response("Service not found for this store.", 404)
            expected_price_paise = service_price_paise(store_service_for_price, store.outlet)
            wallet, _ = Wallet.objects.get_or_create(customer=request.user)
            wallet_balance_paise = int(wallet.balance * 100)
            if wallet_balance_paise < expected_price_paise:
                return error_response(
                    f"Insufficient wallet balance. You have ₹{wallet.balance}, this booking costs ₹{expected_price_paise / 100:.2f}.",
                    402,
                )
        hold = None
        hold_id = serializer.validated_data.get('hold_id')
        if hold_id:
            hold = SlotHold.objects.filter(
                id=hold_id, status=SlotHoldStatus.HELD, expires_at__gt=timezone.now(),
                store_service_id=serializer.validated_data['store_service_id'],
                slot_start=slot_start, slot_end=slot_end,
            ).first()
            if not hold:
                return success_response({
                    "conflict": True, "conflicts": [],
                }, "Your hold expired. Please pick another slot.", 200)
        online_payment = None
        razorpay_order_id = serializer.validated_data.get('razorpay_order_id')
        if razorpay_order_id:
            online_payment = OnlinePayment.objects.filter(
                gateway_order_id=razorpay_order_id, status=OnlinePaymentStatus.CREATED,
            ).first()
            if not online_payment:
                return error_response("Payment not found or already used.", 409)
            try:
                verify_payment(
                    razorpay_order_id,
                    serializer.validated_data.get('razorpay_payment_id'),
                    serializer.validated_data.get('razorpay_signature'),
                )
            except PaymentsNotConfigured as e:
                return error_response(str(e), 503)
            except PaymentVerificationError as e:
                online_payment.status = OnlinePaymentStatus.FAILED
                online_payment.save(update_fields=['status'])
                return error_response(str(e), 402)
            online_payment.status = OnlinePaymentStatus.CAPTURED
            online_payment.gateway_payment_id = serializer.validated_data.get('razorpay_payment_id')
            online_payment.gateway_signature = serializer.validated_data.get('razorpay_signature')
            online_payment.confirmed_at = timezone.now()
            online_payment.save(update_fields=['status', 'gateway_payment_id', 'gateway_signature', 'confirmed_at'])
        user = request.user
        cust_defaults = _clean_customer_defaults(user)
        if user.phone:
            customer, created = GlobalCustomer.objects.get_or_create(
                phone_e164=normalize_e164(user.phone), defaults=cust_defaults
            )
        else:
            customer, created = GlobalCustomer.objects.get_or_create(email=user.email, defaults=cust_defaults)
        if not created and (not customer.name or '@' in customer.name or customer.name.startswith('+') or customer.name.isdigit() or customer.name == 'Valued Customer'):
            customer.name = cust_defaults['name']
            customer.save(update_fields=['name'])
        booking = Booking.objects.create(
            outlet_id=store.outlet_id, customer=customer, source=BookingSource.ONLINE,
            status=BookingStatus.DRAFT, booking_start=slot_start, booking_end=slot_end,
            is_home_service=serializer.validated_data.get('is_home_service', False),
            service_address=serializer.validated_data.get('service_address') or None,
        )
        slot_request = {
            'store_service_id': str(serializer.validated_data['store_service_id']),
            'slot_start': slot_start, 'slot_end': slot_end,
        }
        if hold and hold.professional_id:
            slot_request['professional_id'] = str(hold.professional_id)
        elif serializer.validated_data.get('professional_id'):
            slot_request['professional_id'] = str(serializer.validated_data['professional_id'])
        try:
            created_slots = confirm_booking(booking, [slot_request], actor=None)
        except BookingConflictError as e:
            if online_payment:
                try:
                    refund_payment(online_payment.gateway_payment_id)
                    online_payment.status = OnlinePaymentStatus.REFUNDED
                except Exception:
                    pass
                else:
                    online_payment.save(update_fields=['status'])
            return success_response({
                "conflict": True, "conflicts": e.conflicts,
            }, "That time just got booked. Please pick another slot.", 200)
        except BookingEngineError as e:
            return error_response(str(e), 400)
        if pay_with_wallet and wallet:
            total_paise = sum(s.price_paise for s in created_slots)
            with transaction.atomic():
                wallet.balance -= Decimal(total_paise) / 100
                wallet.save(update_fields=['balance'])
                WalletTransaction.objects.create(
                    wallet=wallet, transaction_type='DEBIT', amount=Decimal(total_paise) / 100,
                    description=f"Booking payment - {booking.booking_code or booking.id}",
                )
        if online_payment:
            online_payment.booking = booking
            online_payment.save(update_fields=['booking'])
        if hold:
            hold.status = SlotHoldStatus.CONVERTED
            hold.customer = customer
            hold.save(update_fields=['status', 'customer'])
            bump_availability_version(store.outlet_id)
        booking.refresh_from_db()
        from zoneinfo import ZoneInfo
        from apps.core.notifications import send_expo_push_notification, notify_user
        when = booking.booking_start.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d %b, %I:%M %p")
        if user.expo_push_token:
            send_expo_push_notification(
                user.expo_push_token, "Booking confirmed",
                f"You're booked at {store.name} on {when}.",
                data={"booking_id": str(booking.id)},
            )
        for slot in booking.slots.select_related('professional__user_account__user', 'store_service'):
            professional_user = getattr(getattr(slot.professional, 'user_account', None), 'user', None)
            if professional_user:
                notify_user(
                    professional_user, "New booking",
                    f"{customer.name} booked {slot.store_service.name} on {when}.",
                    notif_type='APPOINTMENT_BOOKED', data={"booking_id": str(booking.id)},
                )
        return success_response({
            "id": str(booking.id), "status": booking.status,
            "booking_start": booking.booking_start.isoformat(), "booking_end": booking.booking_end.isoformat(),
        }, "Booking confirmed", 201)
    @action(detail=True, methods=['get'])
    def reviews(self, request, pk=None):
        store = self.get_object()
        reviews = Review.objects.filter(store=store, status='APPROVED').order_by('-created_at')
        serializer = PublicReviewSerializer(reviews, many=True)
        return success_response(serializer.data, f"Reviews for {store.name}")
    @action(detail=True, methods=['get'])
    def availability(self, request, pk=None):
        store = self.get_object()
        date_str = request.query_params.get('date')
        if not date_str:
            return Response({"error": "date query parameter is required (YYYY-MM-DD)"}, status=400)
        return success_response({"available_slots": ["09:00", "10:00", "11:30", "14:00"]}, f"Available slots for {store.name} on {date_str}")
class CustomerProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = CustomerProfileSerializer
    permission_classes = [IsAuthenticated, IsCustomer]
    def get_object(self):
        return self.request.user
class CustomerWalletView(generics.RetrieveAPIView):
    serializer_class = CustomerWalletSerializer
    permission_classes = [IsAuthenticated, IsCustomer]
    def get_object(self):
        wallet, created = Wallet.objects.get_or_create(customer=self.request.user)
        return wallet
REFERRAL_REWARD_POINTS = 100
def _referral_code_for(user_id):
    return f"NB{user_id:X}"
def _user_id_from_referral_code(code):
    code = (code or '').strip().upper()
    if not code.startswith('NB'):
        return None
    try:
        return int(code[2:], 16)
    except ValueError:
        return None
class ReferralView(APIView):
    permission_classes = [IsAuthenticated, IsCustomer]
    def get(self, request):
        user = request.user
        referrals = Referral.objects.filter(referrer=user)
        total_points = sum(r.reward_points_awarded for r in referrals)
        was_referred = Referral.objects.filter(referred_user=user).exists()
        return success_response({
            "referral_code": _referral_code_for(user.id),
            "total_referred": referrals.count(),
            "total_points_earned": total_points,
            "was_referred": was_referred,
        })
    def post(self, request):
        code = request.data.get('code')
        referrer_id = _user_id_from_referral_code(code)
        if not referrer_id:
            return error_response("Invalid referral code", 400)
        if referrer_id == request.user.id:
            return error_response("You can't use your own referral code", 400)
        referrer = User.objects.filter(id=referrer_id, role=Role.CUSTOMER).first()
        if not referrer:
            return error_response("Referral code not found", 404)
        if Referral.objects.filter(referred_user=request.user).exists():
            return error_response("You've already used a referral code", 400)
        Referral.objects.create(
            referrer=referrer, referred_user=request.user,
            reward_points_awarded=REFERRAL_REWARD_POINTS,
        )
        referrer.loyalty_points += REFERRAL_REWARD_POINTS
        referrer.save(update_fields=['loyalty_points'])
        return success_response({"reward_points_awarded": REFERRAL_REWARD_POINTS}, "Referral applied successfully")
LOYALTY_POINTS_PER_RUPEE = 10
LOYALTY_REDEEM_BLOCK = 500
class LoyaltyRedeemView(APIView):
    permission_classes = [IsAuthenticated, IsCustomer]
    def post(self, request):
        from decimal import Decimal
        from django.db import transaction
        try:
            points = int(request.data.get('points'))
        except (TypeError, ValueError):
            return error_response("points must be a whole number", 400)
        if points <= 0 or points % LOYALTY_REDEEM_BLOCK != 0:
            return error_response(f"You can redeem in blocks of {LOYALTY_REDEEM_BLOCK} points", 400)
        user = request.user
        if user.loyalty_points < points:
            return error_response("You don't have enough points for that", 400)
        amount = Decimal(points) / LOYALTY_POINTS_PER_RUPEE
        with transaction.atomic():
            user.loyalty_points -= points
            user.save(update_fields=['loyalty_points'])
            wallet, _ = Wallet.objects.get_or_create(customer=user)
            wallet.balance += amount
            wallet.save()
            WalletTransaction.objects.create(
                wallet=wallet, transaction_type='CREDIT', amount=amount,
                description=f"Redeemed {points} loyalty points",
            )
        return success_response({
            "points_redeemed": points, "amount_credited": str(amount),
            "remaining_points": user.loyalty_points, "wallet_balance": str(wallet.balance),
        }, "Points redeemed to your wallet")
class CustomerMembershipViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CustomerMembershipSerializer
    permission_classes = [IsAuthenticated, IsCustomer]
    def get_queryset(self):
        return CustomerMembership.objects.filter(customer=self.request.user)

class PublicMembershipTierViewSet(viewsets.ReadOnlyModelViewSet):
    from apps.store_erp.serializers import MembershipTierSerializer
    serializer_class = MembershipTierSerializer
    permission_classes = [AllowAny]
    queryset = MembershipTier.objects.filter(is_active=True).order_by('price')

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def purchase(self, request, pk=None):
        tier = self.get_object()
        import datetime
        end_date = datetime.date.today() + datetime.timedelta(days=tier.duration_days)
        membership, _ = CustomerMembership.objects.update_or_create(
            customer=request.user,
            tier=tier,
            defaults={
                'end_date': end_date,
                'is_active': True,
                'is_frozen': False,
            }
        )
        return success_response({
            "id": str(membership.id),
            "tier_id": tier.id,
            "tier_name": tier.name,
            "discount_percentage": float(tier.discount_percentage),
            "valid_until": str(end_date),
            "status": "ACTIVE"
        }, f"Subscribed to {tier.name} successfully!")
class CustomerAppointmentViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerAppointmentSerializer
    permission_classes = [IsAuthenticated, IsCustomer]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['status', 'store']
    ordering = ['-start_time']
    def get_queryset(self):
        return Appointment.objects.filter(customer=self.request.user)
    def perform_create(self, serializer):
        serializer.save(customer=self.request.user)
    @action(detail=True, methods=['post'])
    def reschedule(self, request, pk=None):
        from apps.core.models import AppointmentStatus
        appointment = self.get_object()
        if appointment.status not in (AppointmentStatus.BOOKED, AppointmentStatus.RESCHEDULE_REQUESTED):
            return error_response("Only booked appointments can be rescheduled.", 400)
        new_start = request.data.get('start_time')
        if not new_start:
            return error_response("start_time is required.", 400)
        from django.utils.dateparse import parse_datetime
        new_start_dt = parse_datetime(new_start)
        if not new_start_dt:
            return error_response("start_time must be a valid ISO datetime.", 400)
        duration = appointment.end_time - appointment.start_time
        appointment.start_time = new_start_dt
        appointment.end_time = new_start_dt + duration
        appointment.save(update_fields=['start_time', 'end_time'])
        return success_response({
            "id": str(appointment.id),
            "start_time": appointment.start_time.isoformat(),
            "end_time": appointment.end_time.isoformat(),
        }, "Appointment rescheduled.")
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        from apps.core.models import AppointmentStatus
        appointment = self.get_object()
        if appointment.status in (AppointmentStatus.COMPLETED, AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW):
            return error_response(f"Cannot cancel an appointment that is already {appointment.status.lower()}.", 400)
        appointment.status = AppointmentStatus.CANCELLED
        appointment.save(update_fields=['status'])
        return success_response(None, "Appointment cancelled.")
    @action(detail=True, methods=['post'])
    def tip(self, request, pk=None):
        from django.db import transaction
        from decimal import Decimal
        appointment = self.get_object()
        amount_str = request.data.get('amount')
        therapist_id = request.data.get('therapist_id')
        if not amount_str:
            return Response({"error": "amount is required"}, status=400)
        amount = Decimal(amount_str)
        if therapist_id:
            therapist = User.objects.filter(id=therapist_id).first()
        else:
            first_item = appointment.items.first()
            therapist = first_item.assigned_staff if first_item else None
        if not therapist:
            return Response({"error": "No therapist found for this appointment to tip."}, status=400)
        invoice = Invoice.objects.filter(appointment=appointment).first()
        with transaction.atomic():
            tip = Tip.objects.create(
                invoice=invoice,
                amount=amount
            )
            therapist_wallet, _ = Wallet.objects.get_or_create(customer=therapist)
            therapist_wallet.balance += amount
            therapist_wallet.save()
            WalletTransaction.objects.create(
                wallet=therapist_wallet,
                transaction_type='CREDIT',
                amount=amount,
                description=f"Tip from {request.user.get_full_name()} for Appointment #{appointment.id}"
            )
        return success_response({
            "appointment_id": appointment.id,
            "therapist": therapist.get_full_name(),
            "tip_amount": amount
        }, "Tip successfully sent to therapist's wallet!")
class GiftCardViewSet(viewsets.ModelViewSet):
    serializer_class = GiftCardSerializer
    permission_classes = [IsAuthenticated, IsCustomer]
    def get_queryset(self):
        return GiftCard.objects.filter(purchaser=self.request.user)
    def perform_create(self, serializer):
        import random, string
        from datetime import timedelta
        code = None
        while not code or GiftCard.objects.filter(code=code).exists():
            code = 'GIFT-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        initial_value = serializer.validated_data.get('initial_value', 0)
        serializer.save(
            purchaser=self.request.user, code=code,
            current_balance=initial_value,
            expiry_date=timezone.now().date() + timedelta(days=365),
        )
    @action(detail=False, methods=['post'])
    def redeem(self, request):
        from django.db import transaction
        from apps.core.models import Wallet, WalletTransaction
        code = (request.data.get('code') or '').strip().upper()
        if not code:
            return error_response("A gift card code is required", 400)
        gift_card = GiftCard.objects.filter(code=code).first()
        if not gift_card:
            return error_response("Invalid gift card code", 404)
        if not gift_card.is_active:
            return error_response("This gift card is no longer active", 400)
        if gift_card.expiry_date < timezone.now().date():
            return error_response("This gift card has expired", 400)
        if gift_card.current_balance <= 0:
            return error_response("This gift card has already been fully redeemed", 400)
        with transaction.atomic():
            amount = gift_card.current_balance
            wallet, _ = Wallet.objects.get_or_create(customer=request.user)
            wallet.balance += amount
            wallet.save()
            WalletTransaction.objects.create(
                wallet=wallet, transaction_type='CREDIT', amount=amount,
                description=f"Redeemed gift card {gift_card.code}",
            )
            gift_card.current_balance = 0
            gift_card.is_active = False
            gift_card.save()
        return success_response(
            {"amount_credited": str(amount), "wallet_balance": str(wallet.balance)},
            "Gift card redeemed successfully"
        )
class CustomerPackageViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerPackageSerializer
    permission_classes = [IsAuthenticated, IsCustomer]
    def get_queryset(self):
        return CustomerPackage.objects.filter(customer=self.request.user)
    def perform_create(self, serializer):
        serializer.save(customer=self.request.user)
class CustomerInvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CustomerInvoiceSerializer
    permission_classes = [IsAuthenticated, IsCustomer]
    def get_queryset(self):
        return Invoice.objects.filter(appointment__customer=self.request.user).order_by('-created_at')
class FavoriteTherapistViewSet(viewsets.ModelViewSet):
    serializer_class = FavoriteTherapistSerializer
    permission_classes = [IsAuthenticated, IsCustomer]
    def get_queryset(self):
        return FavoriteTherapist.objects.filter(customer=self.request.user).order_by('-created_at')
    def perform_create(self, serializer):
        serializer.save(customer=self.request.user)
class StoreFavouriteViewSet(viewsets.ModelViewSet):
    """Saved salons — distinct from FavoriteTherapistViewSet, which favourites
    a therapist login User, not a store."""
    serializer_class = CustomerFavouriteSerializer
    permission_classes = [IsAuthenticated, IsCustomer]
    def _resolve_customer(self):
        user = self.request.user
        cust_defaults = _clean_customer_defaults(user)
        if user.phone:
            customer, created = GlobalCustomer.objects.get_or_create(
                phone_e164=normalize_e164(user.phone), defaults=cust_defaults
            )
        else:
            customer, created = GlobalCustomer.objects.get_or_create(email=user.email, defaults=cust_defaults)
        if not created and (not customer.name or '@' in customer.name or customer.name.startswith('+') or customer.name.isdigit() or customer.name == 'Valued Customer'):
            customer.name = cust_defaults['name']
            customer.save(update_fields=['name'])
        return customer
    def get_queryset(self):
        return CustomerFavourite.objects.filter(customer=self._resolve_customer()).select_related('store', 'professional_account')
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['customer'] = self._resolve_customer()
        return context
    def perform_create(self, serializer):
        serializer.save(customer=self._resolve_customer())
class CustomerNotificationViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerNotificationSerializer
    permission_classes = [IsAuthenticated, IsCustomer]
    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)
    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        self.get_queryset().update(is_read=True)
        return success_response(None, "All notifications marked as read")
    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.is_read = True
        notification.save()
        return success_response(None, "Notification marked as read")
class CustomerConversationViewSet(viewsets.ModelViewSet):
    serializer_class = ConversationSerializer
    permission_classes = [IsAuthenticated, IsCustomer]
    def get_queryset(self):
        return Conversation.objects.filter(customer=self.request.user)
    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx
    def create(self, request, *args, **kwargs):
        therapist_id = request.data.get('therapist_id')
        therapist = None
        if therapist_id:
            try:
                t_int = int(str(therapist_id).replace('staff-', '').replace('therapist-', '').strip())
                therapist = User.objects.filter(id=t_int, role=Role.THERAPIST).first()
            except (ValueError, TypeError):
                pass
            if not therapist:
                try:
                    import uuid as _u
                    p_uuid = _u.UUID(str(therapist_id))
                    from apps.core.models import Professional
                    prof = Professional.objects.filter(id=p_uuid).select_related('user_account__user').first()
                    if prof and prof.user_account and prof.user_account.user:
                        therapist = prof.user_account.user
                except Exception:
                    pass
            if not therapist:
                therapist = User.objects.filter(role=Role.THERAPIST, is_active=True).first()
        else:
            therapist = User.objects.filter(role=Role.THERAPIST, is_active=True).first()

        if not therapist:
            from apps.core.models import Professional
            prof = Professional.objects.filter(user_account__user__isnull=False).first()
            if prof and prof.user_account and prof.user_account.user:
                therapist = prof.user_account.user

        if not therapist:
            therapist = User.objects.filter(is_staff=True, is_active=True).first() or User.objects.filter(is_active=True).exclude(id=request.user.id).first()

        if not therapist:
            return error_response("No specialist is available to chat right now.", 404)
        convo, created = Conversation.objects.get_or_create(customer=request.user, therapist=therapist)
        initial_msg = (request.data.get('content') or request.data.get('message') or '').strip()
        if initial_msg:
            ChatMessage.objects.create(conversation=convo, sender=request.user, content=initial_msg)
            from apps.core.models import Notification
            Notification.objects.create(
                user=convo.therapist,
                title=f"New message from {request.user.get_full_name() or 'Customer'}",
                message=initial_msg[:120],
                type='NEW_MESSAGE',
            )
        return success_response(self.get_serializer(convo).data, "Conversation ready", 201 if created else 200)
    @action(detail=True, methods=['get', 'post'])
    def messages(self, request, pk=None):
        convo = self.get_object()
        if request.method == 'POST':
            content = (request.data.get('content') or '').strip()
            if not content:
                return error_response("content is required.", 400)
            msg = ChatMessage.objects.create(conversation=convo, sender=request.user, content=content)
            from apps.core.models import Notification
            Notification.objects.create(
                user=convo.therapist,
                title=f"New message from {request.user.get_full_name() or 'Customer'}",
                message=content[:120],
                type='NEW_MESSAGE',
            )
            from apps.core.notifications import notify_user
            notify_user(
                convo.therapist, f"New message from {request.user.get_full_name() or 'Customer'}",
                content[:120], notif_type='NEW_MESSAGE', data={"conversation_id": str(convo.id)},
            )
            store = getattr(convo.therapist, 'store', None)
            if not store and getattr(convo.therapist, 'outlet', None):
                store = convo.therapist.outlet.legacy_stores.first()
            if store:
                for mgr in store.users.filter(role__in=[Role.STORE_MANAGER, Role.STORE_ADMIN]):
                    notify_user(
                        mgr, f"Customer {request.user.get_full_name()} to {convo.therapist.get_full_name()}",
                        content[:120], notif_type='NEW_MESSAGE', data={"conversation_id": str(convo.id)}
                    )
            return success_response(ChatMessageSerializer(msg, context={'request': request}).data, "Sent", 201)
        convo.messages.exclude(sender=request.user).update(is_read=True)
        msgs = convo.messages.select_related('sender')
        return success_response(ChatMessageSerializer(msgs, many=True, context={'request': request}).data)
class CustomerReviewViewSet(viewsets.ReadOnlyModelViewSet):
    """Reviews the logged-in customer has written (see CustomerBookingViewSet.review to create one)."""
    serializer_class = CustomerReviewSerializer
    permission_classes = [IsAuthenticated, IsCustomer]
    def get_queryset(self):
        user = self.request.user
        customer = None
        if user.phone:
            customer = GlobalCustomer.objects.filter(phone_e164=normalize_e164(user.phone)).first()
        if not customer and user.email:
            customer = GlobalCustomer.objects.filter(email=user.email).first()
        if not customer:
            return ProfessionalReview.objects.none()
        return ProfessionalReview.objects.filter(customer=customer).select_related('store_group', 'professional_account').order_by('-created_at')
class PublicServiceViewSet(viewsets.ReadOnlyModelViewSet):
    def get_queryset(self):
        from django.db.models import Count
        return Service.objects.filter(is_active=True).annotate(
            booking_count=Count('appointmentitem')
        ).order_by('-booking_count')[:10]
    serializer_class = PublicServiceSerializer
    permission_classes = [AllowAny]
class PublicCouponViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PublicCouponSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        from django.utils import timezone
        from django.db.models import Q
        now = timezone.now()
        qs = Coupon.objects.filter(is_active=True, end_date__gte=now).order_by('-created_at')
        store_id = self.request.query_params.get('store_id') or self.request.query_params.get('store')
        if store_id:
            cleaned_id = str(store_id).replace('salon-', '').replace('store-', '').strip()
            if cleaned_id.isdigit():
                qs = qs.filter(Q(store_id=int(cleaned_id)) | Q(store__isnull=True))
            else:
                qs = qs.filter(Q(store__slug__iexact=cleaned_id) | Q(store__name__icontains=cleaned_id) | Q(store__isnull=True))

        city_param = (self.request.query_params.get('city') or '').strip().lower()
        if city_param and city_param not in ['all', 'all cities']:
            if 'chennai' in city_param:
                qs = qs.filter(
                    Q(store__isnull=True) |
                    Q(store__outlet__city__name__iexact='Chennai') |
                    Q(store__address__icontains='Chennai') |
                    Q(store__outlet__address_line__icontains='Chennai')
                )
            elif 'bengaluru' in city_param or 'bangalore' in city_param:
                qs = qs.filter(
                    Q(store__isnull=True) |
                    Q(store__outlet__city__name__iexact='Bengaluru') |
                    Q(store__address__icontains='Bengaluru') |
                    Q(store__address__icontains='Bangalore') |
                    Q(store__outlet__address_line__icontains='Bengaluru') |
                    (Q(store__isnull=False) & ~Q(store__address__icontains='chennai') & ~Q(store__outlet__city__name__iexact='Chennai') & ~Q(store__address__icontains='mumbai') & ~Q(store__address__icontains='delhi') & ~Q(store__address__icontains='hyderabad'))
                )
            elif 'mumbai' in city_param:
                qs = qs.filter(
                    Q(store__isnull=True) |
                    Q(store__outlet__city__name__iexact='Mumbai') |
                    Q(store__address__icontains='Mumbai') |
                    Q(store__outlet__address_line__icontains='Mumbai')
                )
            elif 'delhi' in city_param:
                qs = qs.filter(
                    Q(store__isnull=True) |
                    Q(store__outlet__city__name__iexact='Delhi') |
                    Q(store__address__icontains='Delhi') |
                    Q(store__outlet__address_line__icontains='Delhi')
                )
            elif 'hyderabad' in city_param:
                qs = qs.filter(
                    Q(store__isnull=True) |
                    Q(store__outlet__city__name__iexact='Hyderabad') |
                    Q(store__address__icontains='Hyderabad') |
                    Q(store__outlet__address_line__icontains='Hyderabad')
                )
            else:
                qs = qs.filter(
                    Q(store__isnull=True) |
                    Q(store__outlet__city__name__iexact=city_param) |
                    Q(store__address__icontains=city_param) |
                    Q(store__outlet__address_line__icontains=city_param)
                )
        return qs

    @action(detail=False, methods=['post'], url_path='validate', permission_classes=[AllowAny])
    def validate_coupon(self, request):
        from django.utils import timezone
        from django.db.models import Q
        now = timezone.now()

        code = str(request.data.get('code') or '').strip().upper()
        if not code:
            return Response({"success": False, "message": "Please enter a coupon code."}, status=status.HTTP_400_BAD_REQUEST)

        coupon = Coupon.objects.filter(code__iexact=code).first()
        if not coupon:
            return Response({"success": False, "message": f"Coupon code '{code}' does not exist."}, status=status.HTTP_400_BAD_REQUEST)

        if not coupon.is_active:
            return Response({"success": False, "message": f"Coupon '{coupon.code}' is no longer active."}, status=status.HTTP_400_BAD_REQUEST)

        if coupon.start_date and coupon.start_date > now:
            return Response({"success": False, "message": f"Coupon '{coupon.code}' is not valid until {coupon.start_date.strftime('%d %b %Y')}."}, status=status.HTTP_400_BAD_REQUEST)

        if coupon.end_date and coupon.end_date < now:
            return Response({"success": False, "message": f"Coupon '{coupon.code}' expired on {coupon.end_date.strftime('%d %b %Y')}."}, status=status.HTTP_400_BAD_REQUEST)

        if coupon.usage_limit and coupon.used_count >= coupon.usage_limit:
            return Response({"success": False, "message": f"Coupon '{coupon.code}' usage limit has been reached."}, status=status.HTTP_400_BAD_REQUEST)

        # Check store association if the coupon belongs to a specific store
        store_param = request.data.get('store_id') or request.data.get('store')
        city_param = (request.data.get('city') or '').strip().lower()

        if coupon.store_id and store_param:
            cleaned_id = str(store_param).replace('salon-', '').replace('store-', '').strip()
            target_store = None
            if cleaned_id.isdigit():
                target_store = Store.objects.filter(id=int(cleaned_id)).first()
            if not target_store:
                target_store = Store.objects.filter(Q(slug=cleaned_id) | Q(name__iexact=cleaned_id)).first()

            # If target_store is found and does not match coupon's store
            if target_store and target_store.id != coupon.store_id:
                store_name = coupon.store.name if coupon.store else "another salon"
                return Response({
                    "success": False,
                    "message": f"Coupon '{coupon.code}' is only valid at {store_name}."
                }, status=status.HTTP_400_BAD_REQUEST)

        # Check city compatibility
        if coupon.store:
            coupon_city = ""
            if coupon.store.outlet and coupon.store.outlet.city:
                coupon_city = coupon.store.outlet.city.name.lower()
            elif 'chennai' in (coupon.store.address or '').lower():
                coupon_city = 'chennai'
            elif 'bengaluru' in (coupon.store.address or '').lower() or 'bangalore' in (coupon.store.address or '').lower():
                coupon_city = 'bengaluru'

            if city_param and coupon_city and city_param not in ['all', 'all cities']:
                if (city_param == 'chennai' and coupon_city != 'chennai') or (city_param == 'bengaluru' and coupon_city != 'bengaluru'):
                    return Response({
                        "success": False,
                        "message": f"Coupon '{coupon.code}' is only valid in {coupon_city.capitalize()}."
                    }, status=status.HTTP_400_BAD_REQUEST)

        # Calculate discount preview if amount/subtotal provided
        subtotal_val = request.data.get('subtotal') or request.data.get('amount')
        discount_amount = 0
        if subtotal_val is not None:
            try:
                subtotal = float(subtotal_val)
                d_val = float(coupon.discount_value)
                if coupon.discount_type == 'PERCENTAGE':
                    pct_discount = round((subtotal * d_val) / 100, 2)
                    if coupon.maximum_discount:
                        discount_amount = min(pct_discount, float(coupon.maximum_discount))
                    else:
                        discount_amount = pct_discount
                else:
                    discount_amount = min(subtotal, d_val)
            except (ValueError, TypeError):
                pass

        serializer = PublicCouponSerializer(coupon)
        coupon_data = dict(serializer.data)
        coupon_data['discount_amount'] = discount_amount
        return Response({
            "success": True,
            "message": f"Coupon '{coupon.code}' applied successfully!",
            "coupon": coupon_data
        }, status=status.HTTP_200_OK)
class PublicTherapistViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PublicTherapistSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        from django.db.models import Count, Q
        qs = User.objects.filter(role=Role.THERAPIST, is_active=True).annotate(
            follower_count=Count('favorited_by')
        )
        city_param = (self.request.query_params.get('city') or '').strip().lower()
        if city_param and city_param not in ['all', 'all cities']:
            if 'chennai' in city_param:
                qs = qs.filter(
                    Q(store__outlet__city__name__iexact='Chennai') |
                    Q(store__address__icontains='Chennai') |
                    Q(outlet__city__name__iexact='Chennai') |
                    Q(outlet__address_line__icontains='Chennai')
                )
            elif 'bengaluru' in city_param or 'bangalore' in city_param:
                qs = qs.filter(
                    Q(store__outlet__city__name__iexact='Bengaluru') |
                    Q(store__address__icontains='Bengaluru') |
                    Q(store__address__icontains='Bangalore') |
                    Q(outlet__city__name__iexact='Bengaluru') |
                    Q(outlet__address_line__icontains='Bengaluru') |
                    (Q(store__isnull=False) & ~Q(store__address__icontains='chennai') & ~Q(store__outlet__city__name__iexact='Chennai') & ~Q(store__address__icontains='mumbai') & ~Q(store__address__icontains='delhi') & ~Q(store__address__icontains='hyderabad'))
                )
            elif 'mumbai' in city_param:
                qs = qs.filter(
                    Q(store__outlet__city__name__iexact='Mumbai') |
                    Q(store__address__icontains='Mumbai') |
                    Q(outlet__city__name__iexact='Mumbai')
                )
            elif 'delhi' in city_param:
                qs = qs.filter(
                    Q(store__outlet__city__name__iexact='Delhi') |
                    Q(store__address__icontains='Delhi') |
                    Q(outlet__city__name__iexact='Delhi')
                )
            elif 'hyderabad' in city_param:
                qs = qs.filter(
                    Q(store__outlet__city__name__iexact='Hyderabad') |
                    Q(store__address__icontains='Hyderabad') |
                    Q(outlet__city__name__iexact='Hyderabad')
                )
            else:
                qs = qs.filter(
                    Q(store__outlet__city__name__iexact=city_param) |
                    Q(store__address__icontains=city_param) |
                    Q(outlet__city__name__iexact=city_param)
                )
        return qs.order_by('-follower_count')[:10]

    def list(self, request, *args, **kwargs):
        from django.db.models import Q
        city_param = (request.query_params.get('city') or '').strip().lower()
        users = list(self.get_queryset())
        data = list(self.get_serializer(users, many=True).data)

        # Complement with active Professionals from this city if fewer than 4
        if city_param and city_param not in ['all', 'all cities']:
            from apps.core.models import Professional
            profs_qs = Professional.objects.filter(deleted_at__isnull=True, is_bookable=True).select_related('outlet', 'outlet__city')
            if 'chennai' in city_param:
                profs_qs = profs_qs.filter(
                    Q(outlet__city__name__iexact='Chennai') |
                    Q(outlet__address_line__icontains='Chennai')
                )
            elif 'bengaluru' in city_param or 'bangalore' in city_param:
                profs_qs = profs_qs.filter(
                    Q(outlet__city__name__iexact='Bengaluru') |
                    Q(outlet__address_line__icontains='Bengaluru')
                )
            else:
                profs_qs = profs_qs.filter(
                    Q(outlet__city__name__icontains=city_param) |
                    Q(outlet__address_line__icontains=city_param)
                )

            existing_names = {str(d.get('name') or '').lower() for d in data}
            for p in profs_qs[:6]:
                name = p.display_name or "Specialist"
                if name.lower() not in existing_names:
                    p_city = p.outlet.city.name if p.outlet and p.outlet.city else city_param.capitalize()
                    data.append({
                        'id': str(p.id),
                        'first_name': name.split(' ')[0],
                        'last_name': ' '.join(name.split(' ')[1:]) if ' ' in name else '',
                        'name': name,
                        'city': p_city,
                        'store_name': p.outlet.name if p.outlet else '',
                        'role': getattr(p, 'display_role', None) or 'Top Rated',
                    })
                    existing_names.add(name.lower())

        return Response(data)
class CustomerBookingViewSet(viewsets.ModelViewSet):
    """Phase1 (GlobalCustomer/Booking) bookings for the logged-in customer, with
    actions to create, tip a professional directly, and to review a completed booking."""
    serializer_class = CustomerBookingSerializer
    permission_classes = [IsAuthenticated, IsCustomer]
    def get_queryset(self):
        customer = self._get_global_customer()
        if not customer:
            return Booking.objects.none()
        return Booking.objects.filter(customer=customer).select_related('outlet').prefetch_related('slots__professional', 'slots__store_service')
    def _get_global_customer(self):
        user = self.request.user
        if user.phone:
            customer = GlobalCustomer.objects.filter(phone_e164=normalize_e164(user.phone)).first()
            if customer:
                return customer
        if user.email:
            return GlobalCustomer.objects.filter(email=user.email).first()
        return None

    def create(self, request, *args, **kwargs):
        from datetime import timedelta, datetime
        from django.utils.dateparse import parse_datetime
        from django.db import transaction
        from apps.core.models import (
            GlobalCustomer, Booking, BookingStatus, BookingSource, normalize_e164,
            Store, StoreService, AppointmentSlot, AppointmentSlotStatus, Professional, Outlet, StoreGroup, CanonicalService
        )
        import uuid as _uuid

        try:
            user = request.user
            customer = None
            cust_name_req = (request.data.get('customer_name') or request.data.get('name') or user.get_full_name() or '').strip()
            if '@' in cust_name_req or cust_name_req.startswith('+') or cust_name_req.isdigit():
                cust_name_req = ""
            default_cust_name = _clean_customer_defaults(user, cust_name_req)['name']

            if getattr(user, 'phone', None):
                norm_phone = normalize_e164(user.phone)
                customer = GlobalCustomer.objects.filter(phone_e164=norm_phone).first()
                if not customer:
                    customer = GlobalCustomer.objects.create(
                        phone_e164=norm_phone,
                        name=default_cust_name,
                        email=user.email or None,
                    )
                elif cust_name_req or not customer.name or '@' in customer.name or customer.name.startswith('+') or customer.name.isdigit() or customer.name == "Valued Customer":
                    customer.name = default_cust_name
                    customer.save(update_fields=['name'])
            elif getattr(user, 'email', None):
                customer = GlobalCustomer.objects.filter(email=user.email).first()
                if not customer:
                    customer = GlobalCustomer.objects.create(
                        email=user.email,
                        name=default_cust_name,
                    )
                elif cust_name_req or not customer.name or '@' in customer.name or customer.name.startswith('+') or customer.name.isdigit() or customer.name == "Valued Customer":
                    customer.name = default_cust_name
                    customer.save(update_fields=['name'])
            else:
                customer = GlobalCustomer.objects.create(
                    name=default_cust_name
                )

            # Resolve Store
            store_id = request.data.get('store_id')
            store = None
            if store_id:
                cleaned_id = str(store_id).replace('salon-', '').replace('store-', '').strip()
                if cleaned_id.isdigit():
                    store = Store.objects.filter(id=int(cleaned_id)).first()
                if not store:
                    try:
                        import uuid as _u
                        u_val = _u.UUID(cleaned_id)
                        store = Store.objects.filter(outlet_id=u_val).first() or Store.objects.filter(business_id=u_val).first()
                    except Exception:
                        pass
                if not store:
                    store = Store.objects.filter(name__icontains=cleaned_id).first()

            if not store:
                store = Store.objects.filter(status='ACTIVE', outlet__isnull=False).first() or Store.objects.first()

            outlet = (store.outlet if store and store.outlet else None) or Outlet.objects.filter(status='active').first() or Outlet.objects.first()
            if not outlet:
                sg, _ = StoreGroup.objects.get_or_create(name="Default Store Group", defaults={"slug": "default-store-group"})
                outlet, _ = Outlet.objects.get_or_create(name="Default Outlet", store_group=sg, defaults={"slug": "default-outlet", "status": "active"})

            # Resolve services list from payload
            services_list = request.data.get('services') or request.data.get('items') or []
            req_name = str(request.data.get('service_name') or '').strip()
            if not req_name and isinstance(services_list, list) and len(services_list) > 0:
                first_it_name = services_list[0].get('name') or services_list[0].get('service_name')
                if first_it_name:
                    req_name = str(first_it_name).strip()

            # Resolve primary service safely
            service_id = request.data.get('service_id')
            svc = None
            if service_id:
                cleaned_svc = str(service_id).replace('svc-', '').strip()
                if cleaned_svc.isdigit():
                    from apps.core.models import Service
                    legacy_svc = Service.objects.filter(id=int(cleaned_svc)).first()
                    if legacy_svc:
                        if outlet and outlet.store_group:
                            svc = StoreService.objects.filter(store_group=outlet.store_group, name__iexact=legacy_svc.name).first()
                        if not svc:
                            svc = StoreService.objects.filter(name__iexact=legacy_svc.name).first()
                        if not svc and outlet and outlet.store_group:
                            canonical = CanonicalService.objects.first()
                            svc = StoreService.objects.create(
                                store_group=outlet.store_group,
                                canonical_service=canonical,
                                name=legacy_svc.name,
                                default_price_paise=int(round(float(legacy_svc.price or 500) * 100)),
                                duration_min=int(legacy_svc.duration_minutes or 45),
                                is_active_in_store=True,
                            )
                else:
                    try:
                        val = _uuid.UUID(cleaned_svc)
                        svc = StoreService.objects.filter(id=val).first()
                    except (ValueError, TypeError, Exception):
                        pass

            if not svc and req_name:
                if outlet and outlet.store_group:
                    svc = StoreService.objects.filter(store_group=outlet.store_group, name__iexact=req_name).first() or StoreService.objects.filter(store_group=outlet.store_group, name__icontains=req_name).first()
                if not svc:
                    svc = StoreService.objects.filter(name__iexact=req_name).first() or StoreService.objects.filter(name__icontains=req_name).first()

            if not svc and req_name:
                canonical = CanonicalService.objects.first()
                sg = (outlet.store_group if outlet and outlet.store_group else None) or StoreGroup.objects.first()
                svc = StoreService.objects.create(
                    store_group=sg,
                    canonical_service=canonical,
                    name=req_name,
                    default_price_paise=int(round(float(request.data.get('amount') or 500) * 100)),
                    duration_min=int(request.data.get('duration_minutes') or 45),
                    is_active_in_store=True,
                )

            if not svc and outlet and outlet.store_group:
                svc = StoreService.objects.filter(store_group=outlet.store_group, is_active_in_store=True).first() or StoreService.objects.filter(store_group=outlet.store_group).first()

            if not svc:
                svc = StoreService.objects.filter(is_active_in_store=True).first() or StoreService.objects.first()

            if not svc:
                canonical = CanonicalService.objects.first()
                sg = outlet.store_group if (outlet and outlet.store_group) else StoreGroup.objects.first()
                svc = StoreService.objects.create(
                    store_group=sg,
                    canonical_service=canonical,
                    name=req_name or "Salon Service",
                    default_price_paise=int(round(float(request.data.get('amount') or 500) * 100)),
                    duration_min=int(request.data.get('duration_minutes') or 45),
                    is_active_in_store=True,
                )

            if not svc:
                return Response(
                    {"error": "This venue has not published its service catalog for online booking yet. Please select a venue with available services."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Slot start parsing in IST (Asia/Kolkata)
            import zoneinfo
            kolkata_tz = zoneinfo.ZoneInfo('Asia/Kolkata')
            raw_start = request.data.get('slot_start')
            slot_start = None
            if raw_start:
                try:
                    parsed_dt = parse_datetime(str(raw_start))
                    if parsed_dt:
                        if timezone.is_naive(parsed_dt):
                            slot_start = parsed_dt.replace(tzinfo=kolkata_tz)
                        else:
                            slot_start = parsed_dt.astimezone(kolkata_tz)
                except Exception:
                    pass

            if not slot_start and request.data.get('slot_date') and request.data.get('slot_time'):
                t_str = str(request.data['slot_time']).strip()
                date_str = str(request.data['slot_date']).strip()
                for fmt in ["%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M%p"]:
                    try:
                        dt = datetime.strptime(f"{date_str} {t_str}", fmt)
                        slot_start = dt.replace(tzinfo=kolkata_tz)
                        break
                    except Exception:
                        continue
                if not slot_start:
                    try:
                        dt = datetime.strptime(f"{date_str} 11:30", "%Y-%m-%d %H:%M")
                        slot_start = dt.replace(tzinfo=kolkata_tz)
                    except Exception:
                        pass

            if not slot_start:
                slot_start = timezone.now().astimezone(kolkata_tz) + timedelta(hours=2)

            # QA-05: Prevent booking elapsed/past time slots
            if slot_start < timezone.now() - timedelta(minutes=5):
                return Response(
                    {"error": "Cannot book an appointment slot in the past. Please select an upcoming date and time."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # QA-06: Prevent duplicate concurrent/exact customer bookings
            existing_duplicate = Booking.objects.filter(
                customer=customer,
                outlet=outlet,
                booking_start=slot_start,
                status__in=[BookingStatus.CONFIRMED, BookingStatus.IN_SERVICE, BookingStatus.DRAFT]
            ).first()
            if existing_duplicate:
                return Response(
                    {"error": f"You already have a confirmed appointment at this venue scheduled for {slot_start.strftime('%d %b, %I:%M %p')}. To avoid duplicate charges, please choose a different time."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Pre-calculate total duration across all services so booking_end accommodates all slots
            services_list = request.data.get('services') or request.data.get('items') or []
            if isinstance(services_list, list) and len(services_list) > 0:
                total_duration = sum(int(it.get('duration_minutes') or it.get('duration') or 30) for it in services_list)
            else:
                total_duration = int(request.data.get('duration_minutes') or getattr(svc, 'duration_min', 45) or 45)

            total_duration = max(15, total_duration)
            slot_end = slot_start + timedelta(minutes=total_duration)

            req_amt = request.data.get('amount')
            if req_amt is not None and str(req_amt).strip() != '':
                try:
                    price_paise = int(round(float(req_amt) * 100))
                except (ValueError, TypeError):
                    price_paise = int(svc.default_price_paise) if svc else 50000
            else:
                price_paise = int(svc.default_price_paise) if svc else 50000

            # Resolve professional safely
            professional_id = request.data.get('professional_id')
            prof = None
            if professional_id:
                try:
                    p_uuid = _uuid.UUID(str(professional_id))
                    prof = Professional.objects.filter(id=p_uuid, outlet=outlet, is_bookable=True).first()
                    if not prof:
                        prof = Professional.objects.filter(id=p_uuid).first()
                except Exception:
                    prof = None
            if not prof:
                prof = Professional.objects.filter(outlet=outlet, is_bookable=True).first() if outlet else None

            is_home = bool(request.data.get('is_home_service', False))
            service_addr = str(request.data.get('service_address') or request.data.get('address') or '').strip()
            if is_home and not service_addr:
                service_addr = f"Home Service — {customer.name if customer else 'Customer'} Residence"

            with transaction.atomic():
                booking = Booking.objects.create(
                    outlet=outlet,
                    customer=customer,
                    source=BookingSource.ONLINE,
                    status=BookingStatus.CONFIRMED,
                    booking_start=slot_start,
                    booking_end=slot_end,
                    is_home_service=is_home,
                    service_address=service_addr or None,
                    notes=request.data.get('notes') or (f"Services: {req_name}" if req_name else None),
                )

                if isinstance(services_list, list) and len(services_list) > 1:
                    current_start = slot_start
                    for item in services_list:
                        item_id = str(item.get('id') or item.get('service_id') or '').replace('svc-', '').strip()
                        item_name = str(item.get('name') or item.get('service_name') or '').strip()
                        item_svc = None
                        if item_id:
                            if item_id.isdigit():
                                from apps.core.models import Service
                                legacy_svc = Service.objects.filter(id=int(item_id)).first()
                                if legacy_svc:
                                    if not item_name:
                                        item_name = legacy_svc.name
                                    if outlet and outlet.store_group:
                                        item_svc = StoreService.objects.filter(store_group=outlet.store_group, name__iexact=legacy_svc.name).first()
                                    if not item_svc:
                                        item_svc = StoreService.objects.filter(name__iexact=legacy_svc.name).first()
                            else:
                                try:
                                    item_svc = StoreService.objects.filter(id=_uuid.UUID(item_id)).first()
                                except Exception:
                                    pass
                        if not item_svc and item_name:
                            if outlet and outlet.store_group:
                                item_svc = StoreService.objects.filter(store_group=outlet.store_group, name__iexact=item_name).first() or StoreService.objects.filter(store_group=outlet.store_group, name__icontains=item_name).first()
                            if not item_svc:
                                item_svc = StoreService.objects.filter(name__iexact=item_name).first() or StoreService.objects.filter(name__icontains=item_name).first()

                        item_dur = int(item.get('duration') or item.get('duration_minutes') or 30)
                        item_price = int(round(float(item.get('price') or 0) * 100))

                        if not item_svc and item_name:
                            canonical = CanonicalService.objects.first()
                            sg = (outlet.store_group if outlet and outlet.store_group else None) or StoreGroup.objects.first()
                            item_svc = StoreService.objects.create(
                                store_group=sg,
                                canonical_service=canonical,
                                name=item_name,
                                default_price_paise=item_price if item_price > 0 else 50000,
                                duration_min=item_dur,
                                is_active_in_store=True,
                            )

                        item_end = current_start + timedelta(minutes=item_dur)
                        AppointmentSlot.objects.create(
                            booking=booking,
                            store_service=item_svc or svc,
                            professional=prof,
                            slot_start=current_start,
                            slot_end=item_end,
                            price_paise=item_price if item_price > 0 else (price_paise // len(services_list)),
                            status=AppointmentSlotStatus.SCHEDULED,
                        )
                        current_start = item_end
                    if booking.booking_end < current_start:
                        booking.booking_end = current_start
                        booking.save(update_fields=['booking_end'])
                else:
                    AppointmentSlot.objects.create(
                        booking=booking,
                        store_service=svc,
                        professional=prof,
                        slot_start=slot_start,
                        slot_end=slot_end,
                        price_paise=price_paise,
                        status=AppointmentSlotStatus.SCHEDULED,
                    )

                # Auto-create Invoice so bill immediately shows in StoreAdmin and Therapist views
                try:
                    from apps.core.models import (
                        Invoice, InvoiceStatus, InvoiceLine, InvoiceLineType, Payment, PaymentMethod
                    )
                    inv_store = store or (outlet.legacy_stores.first() if outlet else None) or Store.objects.first()
                    if inv_store:
                        payment_mode_raw = str(request.data.get('payment_method', '')).lower()
                        is_paid = payment_mode_raw in ['online', 'upi', 'paid']
                        inv_status = InvoiceStatus.PAID if is_paid else InvoiceStatus.UNPAID

                        req_subtotal = request.data.get('subtotal')
                        req_discount = request.data.get('discount_amount')
                        req_total = request.data.get('amount')

                        sub_paise = int(round(float(req_subtotal if req_subtotal is not None else (price_paise / 100)) * 100))
                        disc_paise = int(round(float(req_discount if req_discount is not None else 0) * 100))
                        tot_paise = int(round(float(req_total if req_total is not None else (price_paise / 100)) * 100))
                        if tot_paise <= 0 and sub_paise > 0:
                            tot_paise = max(0, sub_paise - disc_paise)

                        invoice = Invoice.objects.create(
                            invoice_number=f"INV-{_uuid.uuid4().hex[:6].upper()}",
                            store=inv_store,
                            outlet=outlet,
                            booking=booking,
                            global_customer=customer,
                            customer=user if user.is_authenticated else None,
                            subtotal_paise=sub_paise,
                            discount_amount_paise=disc_paise,
                            grand_total_paise=tot_paise,
                            status=inv_status,
                        )

                        if isinstance(services_list, list) and len(services_list) > 1:
                            for s_item in services_list:
                                s_id = str(s_item.get('id') or s_item.get('service_id') or '').replace('svc-', '').strip()
                                s_name = str(s_item.get('name') or s_item.get('service_name') or '').strip()
                                s_svc = None
                                if s_id:
                                    try:
                                        s_svc = StoreService.objects.filter(id=_uuid.UUID(s_id)).first()
                                    except Exception:
                                        pass
                                if not s_svc and s_name:
                                    if outlet and outlet.store_group:
                                        s_svc = StoreService.objects.filter(store_group=outlet.store_group, name__iexact=s_name).first() or StoreService.objects.filter(store_group=outlet.store_group, name__icontains=s_name).first()
                                    if not s_svc:
                                        s_svc = StoreService.objects.filter(name__iexact=s_name).first() or StoreService.objects.filter(name__icontains=s_name).first()
                                s_price = int(round(float(s_item.get('price') or 0) * 100))
                                line_amt = s_price if s_price > 0 else (sub_paise // len(services_list))
                                InvoiceLine.objects.create(
                                    invoice=invoice,
                                    store_service=s_svc or svc,
                                    professional=prof,
                                    quantity=1,
                                    line_type=InvoiceLineType.SERVICE,
                                    unit_price_paise=line_amt,
                                    total_paise=line_amt,
                                )
                        else:
                            InvoiceLine.objects.create(
                                invoice=invoice,
                                store_service=svc,
                                professional=prof,
                                quantity=1,
                                line_type=InvoiceLineType.SERVICE,
                                unit_price_paise=sub_paise,
                                total_paise=sub_paise,
                            )

                        if is_paid:
                            Payment.objects.create(
                                invoice=invoice,
                                method=PaymentMethod.UPI,
                                amount_paise=tot_paise,
                                transaction_reference=f"PAY-{_uuid.uuid4().hex[:8].upper()}"
                            )
                except Exception as inv_err:
                    logger.warning("Could not auto-create invoice for booking %s: %s", booking.id, inv_err)

                # Increment coupon used_count if a coupon code was applied
                coupon_code = request.data.get('coupon_code')
                if coupon_code:
                    try:
                        from django.db.models import F
                        Coupon.objects.filter(code__iexact=str(coupon_code).strip()).update(used_count=F('used_count') + 1)
                    except Exception as coup_err:
                        logger.warning("Could not increment coupon count for code %s: %s", coupon_code, coup_err)

            booking.refresh_from_db()
            return success_response(CustomerBookingSerializer(booking).data, "Appointment booked successfully.", status_code=201)
        except Exception as e:
            logger.exception("Booking creation error: %s", e)
            return Response(
                {"error": f"Booking could not be confirmed: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        from apps.core.models import BookingStatus, AppointmentSlotStatus, SlotHold, SlotHoldStatus
        from apps.store_erp.availability import bump_availability_version
        booking = self.get_object()
        if booking.status in (BookingStatus.COMPLETED, BookingStatus.CANCELLED, BookingStatus.NO_SHOW):
            return error_response(f"Cannot cancel a booking that is already {booking.status}.", 400)
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.save(update_fields=['status', 'cancelled_at'])
        booking.slots.exclude(status=AppointmentSlotStatus.DONE).update(status=AppointmentSlotStatus.CANCELLED)
        SlotHold.objects.filter(outlet=booking.outlet, slot_start__lt=booking.booking_end, slot_end__gt=booking.booking_start, status=SlotHoldStatus.HELD).update(status=SlotHoldStatus.RELEASED)
        bump_availability_version(booking.outlet_id)
        return success_response(None, "Booking cancelled.")
    @action(detail=True, methods=['post'])
    def reschedule(self, request, pk=None):
        from django.utils.dateparse import parse_datetime
        from apps.core.models import BookingStatus, AppointmentSlotStatus
        from apps.store_erp.booking_engine import reschedule_slot, BookingConflictError, BookingEngineError
        booking = self.get_object()
        if booking.status != BookingStatus.CONFIRMED:
            return error_response(f"Cannot reschedule a booking that is {booking.status}.", 400)
        new_start = parse_datetime(request.data.get('slot_start') or '')
        if not new_start:
            return error_response("A valid slot_start is required", 400)
        slot = booking.slots.exclude(status=AppointmentSlotStatus.CANCELLED).order_by('slot_start').first()
        if not slot:
            return error_response("This booking has no active slot to reschedule", 400)
        try:
            reschedule_slot(slot, new_start, actor=request.user)
        except BookingConflictError:
            return error_response("That time is no longer available. Please pick another slot.", 409)
        except BookingEngineError as e:
            return error_response(str(e), 400)
        booking.refresh_from_db()
        return success_response(CustomerBookingSerializer(booking).data, "Booking rescheduled")
    @action(detail=True, methods=['post'])
    def tip(self, request, pk=None):
        from urllib.parse import quote
        from apps.core.models import (
            Professional, PayoutDestination, PayoutDestinationType, PayoutVerificationStatus,
            ProfessionalTip, ProfessionalTipMethod, ProfessionalTipStatus,
        )
        booking = self.get_object()
        serializer = BookingTipRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        amount = serializer.validated_data['amount']
        professional_id = serializer.validated_data['professional_id']
        professional = Professional.objects.filter(id=professional_id).select_related('user_account').first()
        if not professional or not professional.user_account_id:
            return error_response("This professional is not set up to receive tips yet.", 400)
        slot = booking.slots.filter(professional_id=professional_id).first()
        if not slot:
            return error_response("This professional did not perform a service in this booking.", 400)
        destination = PayoutDestination.objects.filter(
            professional_account=professional.user_account_id, type=PayoutDestinationType.UPI_VPA,
            verification_status=PayoutVerificationStatus.VERIFIED, is_active=True
        ).first()
        if not destination or not destination.vpa:
            return error_response("This professional hasn't set up a verified UPI payout method yet.", 400)
        customer = self._get_global_customer()
        amount_paise = int(amount * 100)
        tip = ProfessionalTip.objects.create(
            booking=booking, appointment_slot=slot, professional_account=professional.user_account,
            customer=customer, store_group_id=booking.outlet.store_group_id,
            amount_paise=amount_paise, method=ProfessionalTipMethod.UPI_DEEPLINK,
            status=ProfessionalTipStatus.INITIATED,
        )
        payee_name = destination.holder_name or professional.user_account.name
        deep_link = f"upi://pay?pa={quote(destination.vpa)}&pn={quote(payee_name)}&am={amount}&cu=INR&tn=Tip"
        if professional.user_account.user_id:
            from apps.core.notifications import notify_user
            notify_user(
                professional.user_account.user, "Tip on its way",
                f"{customer.name} is sending you a tip of ₹{amount}. Confirm it in Earnings once received.",
                notif_type='TIP_RECEIVED', data={"tip_id": str(tip.id)},
            )
        return success_response({
            "tip_id": str(tip.id),
            "status": tip.status,
            "amount_paise": tip.amount_paise,
            "vpa": destination.vpa,
            "payee_name": payee_name,
            "upi_deeplink": deep_link,
        }, "Tip initiated. Complete payment via your UPI app.", 201)
    @action(detail=True, methods=['post'])
    def review(self, request, pk=None):
        from apps.core.models import BookingStatus, ProfessionalReview, GlobalCustomer, normalize_e164
        booking = self.get_object()
        if booking.status != BookingStatus.COMPLETED:
            return error_response("You can only review a completed booking.", 400)
        serializer = BookingReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        customer = self._get_global_customer() or booking.customer
        if not customer and request.user.is_authenticated:
            user = request.user
            customer, _ = GlobalCustomer.objects.get_or_create(
                phone_e164=normalize_e164(user.phone) if user.phone else "+919999999999",
                defaults={"name": user.get_full_name() or user.first_name or "Valued Client", "email": user.email}
            )

        professional_id = data.get('professional_id')
        slot = None
        if professional_id:
            try:
                import uuid as _u
                slot = booking.slots.filter(professional_id=_u.UUID(str(professional_id))).select_related('professional').first()
            except Exception:
                slot = booking.slots.filter(professional_id=professional_id).select_related('professional').first()
        if not slot:
            slot = booking.slots.exclude(professional__isnull=True).select_related('professional').first()

        professional_account = None
        if slot and slot.professional_id and slot.professional.user_account_id:
            professional_account = slot.professional.user_account

        existing_review = ProfessionalReview.objects.filter(booking=booking).first()
        if existing_review:
            existing_review.store_rating = data['store_rating']
            existing_review.professional_rating = data.get('professional_rating') or data['store_rating']
            existing_review.comment = data.get('comment') or ""
            if professional_account:
                existing_review.professional_account = professional_account
            existing_review.save()
            review = existing_review
        else:
            review = ProfessionalReview.objects.create(
                booking=booking,
                customer=customer,
                store_group=booking.outlet.store_group,
                professional_account=professional_account,
                store_rating=data['store_rating'],
                professional_rating=data.get('professional_rating') or data['store_rating'],
                comment=data.get('comment') or "",
                media_url=data.get('media_url'),
            )

        # Also sync to legacy/staff Review model so the review immediately appears in TherapistWeb & StoreAdmin
        try:
            from apps.core.models import Review, Store, User
            from django.db.models import Q
            th_user = None
            if slot and slot.professional:
                if slot.professional.user_account and slot.professional.user_account.user:
                    th_user = slot.professional.user_account.user
                elif hasattr(slot.professional, 'user') and slot.professional.user:
                    th_user = slot.professional.user
                elif slot.professional.phone_e164:
                    th_user = User.objects.filter(phone=slot.professional.phone_e164).first()
                elif slot.professional.email:
                    th_user = User.objects.filter(email__iexact=slot.professional.email).first()

            if not th_user:
                th_name = data.get('therapist_name') or request.data.get('therapist_name')
                if not th_name and booking.notes and 'Stylist:' in booking.notes:
                    try:
                        th_name = booking.notes.split('Stylist:')[1].split('\n')[0].strip()
                    except Exception:
                        pass
                if th_name:
                    first_part = th_name.split()[0] if th_name else ""
                    th_user = User.objects.filter(
                        Q(first_name__iexact=th_name) |
                        Q(username__iexact=th_name) |
                        Q(first_name__icontains=first_part)
                    ).filter(role__in=['THERAPIST', 'STAFF', 'STORE_ADMIN']).first()

            store_obj = booking.outlet.legacy_stores.first() if (booking.outlet and hasattr(booking.outlet, 'legacy_stores')) else Store.objects.first()
            if not th_user and store_obj:
                th_user = User.objects.filter(store=store_obj, role='THERAPIST').first()

            if store_obj:
                cust_disp_name = (customer.name if customer and customer.name else request.user.get_full_name()) or "Customer"
                rev_rating = data.get('professional_rating') or data['store_rating']
                rev_comment = data.get('comment') or ""

                existing_rev = None
                if th_user:
                    existing_rev = Review.objects.filter(store=store_obj, customer_name=cust_disp_name, therapist=th_user).order_by('-created_at').first()
                else:
                    existing_rev = Review.objects.filter(store=store_obj, customer_name=cust_disp_name).order_by('-created_at').first()

                if existing_rev:
                    existing_rev.rating = rev_rating
                    existing_rev.comment = rev_comment
                    existing_rev.status = 'APPROVED'
                    if th_user:
                        existing_rev.therapist = th_user
                    existing_rev.save()
                else:
                    Review.objects.create(
                        store=store_obj,
                        customer_name=cust_disp_name,
                        therapist=th_user,
                        customer_email=getattr(customer, 'email', None) or request.user.email,
                        rating=rev_rating,
                        comment=rev_comment,
                        status='APPROVED',
                    )
        except Exception as rev_err:
            logger.warning("Could not sync review to store Review model: %s", rev_err)

        if professional_account and professional_account.user_id:
            from apps.core.notifications import notify_user
            stars = review.professional_rating or review.store_rating
            cust_name = customer.name if customer and customer.name else "Client"
            notify_user(
                professional_account.user, "New review",
                f"{cust_name} left you a {stars}★ review.",
                notif_type='NEW_REVIEW', data={"review_id": str(review.id)},
            )
        return success_response({
            "id": str(review.id),
            "store_rating": review.store_rating,
            "professional_rating": review.professional_rating,
            "comment": review.comment,
            "created_at": review.created_at.isoformat(),
        }, "Thanks for your review!", 201)
