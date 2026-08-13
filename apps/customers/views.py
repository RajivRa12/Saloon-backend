from rest_framework import viewsets, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from django.db.models import Prefetch
from apps.core.models import (
    Store, ServiceCategory, Service, User, Role,
    Appointment, Wallet, CustomerMembership, Review,
    GiftCard, CustomerPackage, FavoriteTherapist, Invoice, Coupon, Tip, WalletTransaction
)
from .serializers import (
    PublicStoreSerializer, PublicServiceCategorySerializer,
    PublicReviewSerializer, CustomerProfileSerializer,
    CustomerWalletSerializer, CustomerMembershipSerializer,
    CustomerAppointmentSerializer, GiftCardSerializer,
    CustomerPackageSerializer,
    FavoriteTherapistSerializer, CustomerInvoiceSerializer,
    PublicServiceSerializer, PublicCouponSerializer, PublicTherapistSerializer,
    Phase1StoreServiceSerializer, Phase1ProfessionalSerializer, Phase1BookingRequestSerializer
)
from .permissions import IsCustomer
def success_response(data, message="Success", status_code=200):
    return Response({"success": True, "message": message, "data": data}, status=status_code)
def error_response(message="Error", status_code=400):
    return Response({"success": False, "message": message, "data": None}, status=status_code)
class PublicStoreViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Store.objects.filter(status='ACTIVE')
    serializer_class = PublicStoreSerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['brand', 'business__business_type']
    search_fields = ['name', 'address', 'location']
    ordering = ['name']
    @action(detail=True, methods=['get'])
    def menu(self, request, pk=None):
        store = self.get_object()
        categories = ServiceCategory.objects.filter(
            store=store,
            is_active=True
        ).prefetch_related(
            Prefetch('services', queryset=Service.objects.filter(is_active=True))
        )
        serializer = PublicServiceCategorySerializer(categories, many=True)
        return success_response(serializer.data, f"Menu for {store.name}")
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
        from apps.core.models import Professional, ProfessionalLinkStatus, StoreService
        store = self.get_object()
        if not store.outlet_id:
            return error_response("Online booking is not available for this location yet.", 404)
        qs = Professional.objects.filter(outlet_id=store.outlet_id, is_bookable=True, link_status=ProfessionalLinkStatus.ACCEPTED)
        skill_tag = None
        service_id = request.query_params.get('service_id')
        if service_id:
            svc = StoreService.objects.filter(id=service_id).select_related('canonical_service').first()
            if svc and svc.canonical_service_id:
                skill_tag = svc.canonical_service.skill_tag
        if skill_tag:
            qs = qs.filter(skills__skill_tag=skill_tag)
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
    @action(detail=True, methods=['post'], url_path='phase1-book', permission_classes=[IsAuthenticated, IsCustomer])
    def phase1_book(self, request, pk=None):
        from apps.core.models import GlobalCustomer, Booking, BookingStatus, BookingSource, normalize_e164
        from apps.store_erp.booking_engine import confirm_booking, BookingConflictError, BookingEngineError
        store = self.get_object()
        if not store.outlet_id:
            return error_response("Online booking is not available for this location yet.", 404)
        serializer = Phase1BookingRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        slot_start = serializer.validated_data['slot_start']
        slot_end = serializer.validated_data['slot_end']
        user = request.user
        if user.phone:
            customer, _ = GlobalCustomer.objects.get_or_create(
                phone_e164=normalize_e164(user.phone), defaults={'name': user.get_full_name() or user.email, 'email': user.email}
            )
        else:
            customer, _ = GlobalCustomer.objects.get_or_create(email=user.email, defaults={'name': user.get_full_name() or user.email})
        booking = Booking.objects.create(
            outlet_id=store.outlet_id, customer=customer, source=BookingSource.ONLINE,
            status=BookingStatus.DRAFT, booking_start=slot_start, booking_end=slot_end,
        )
        slot_request = {
            'store_service_id': str(serializer.validated_data['store_service_id']),
            'slot_start': slot_start, 'slot_end': slot_end,
        }
        if serializer.validated_data.get('professional_id'):
            slot_request['professional_id'] = str(serializer.validated_data['professional_id'])
        try:
            confirm_booking(booking, [slot_request], actor=None)
        except BookingConflictError as e:
            return success_response({
                "conflict": True, "conflicts": e.conflicts,
            }, "That time just got booked. Please pick another slot.", 200)
        except BookingEngineError as e:
            return error_response(str(e), 400)
        booking.refresh_from_db()
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
class CustomerMembershipViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CustomerMembershipSerializer
    permission_classes = [IsAuthenticated, IsCustomer]
    def get_queryset(self):
        return CustomerMembership.objects.filter(customer=self.request.user)
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
        serializer.save(purchaser=self.request.user)
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
class PublicServiceViewSet(viewsets.ReadOnlyModelViewSet):
    def get_queryset(self):
        from django.db.models import Count
        return Service.objects.filter(is_active=True).annotate(
            booking_count=Count('appointmentitem')
        ).order_by('-booking_count')[:10]
    serializer_class = PublicServiceSerializer
    permission_classes = [AllowAny]
class PublicCouponViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Coupon.objects.filter(is_active=True).order_by('-created_at')
    serializer_class = PublicCouponSerializer
    permission_classes = [AllowAny]
class PublicTherapistViewSet(viewsets.ReadOnlyModelViewSet):
    def get_queryset(self):
        from django.db.models import Count
        return User.objects.filter(role=Role.THERAPIST, is_active=True).annotate(
            follower_count=Count('favorited_by')
        ).order_by('-follower_count')[:10]
    serializer_class = PublicTherapistSerializer
    permission_classes = [AllowAny]
