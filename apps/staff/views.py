from rest_framework import viewsets, generics, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from apps.core.models import (
    User, Appointment, AppointmentItem, Commission, AppointmentStatus,
    CustomerNote, TherapistProfile, Announcement, TrainingVideo, TrainingCourse, Wallet,
    Notification, Attendance, AttendanceStatus, StaffTarget,
    Review, StaffIncentive, Conversation, ChatMessage, Payroll, LeaveRequest,
)
from .serializers import (
    TherapistProfileSerializer, TherapistAppointmentSerializer,
    TherapistCommissionSerializer, TherapistAppointmentItemSerializer,
    CustomerNoteSerializer, AnnouncementSerializer, TrainingVideoSerializer, TrainingCourseSerializer,
    StaffWalletSerializer, NotificationSerializer, TipSerializer,
    StaffTaskSerializer, TherapistSettingsSerializer, StaffChatMessageSerializer,
    TherapistReviewSerializer, StaffIncentiveSerializer,
    StaffPayrollSerializer, StaffLeaveRequestSerializer,
    TherapistConversationSerializer, TherapistChatMessageSerializer,
)
from .permissions import IsTherapist
def success_response(data, message="Success", status_code=200):
    return Response({"success": True, "message": message, "data": data}, status=status_code)
def error_response(message="Error", status_code=400):
    return Response({"success": False, "message": message, "data": None}, status=status_code)
class TherapistProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = TherapistProfileSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    def get_object(self):
        return self.request.user
    def perform_update(self, serializer):
        user = serializer.save()
        portfolio_data = self.request.data.get('portfolio')
        if portfolio_data:
            profile, _ = TherapistProfile.objects.get_or_create(user=user)
            if 'bio' in portfolio_data:
                profile.bio = portfolio_data['bio']
            if 'instagram_link' in portfolio_data:
                profile.instagram_link = portfolio_data['instagram_link']
            if 'specializations' in portfolio_data:
                profile.specializations = portfolio_data['specializations']
            if 'years_of_experience' in portfolio_data:
                profile.years_of_experience = portfolio_data['years_of_experience']
            if 'certificates' in portfolio_data:
                profile.certificates = portfolio_data['certificates']
            if 'awards' in portfolio_data:
                profile.awards = portfolio_data['awards']
            if 'languages' in portfolio_data:
                profile.languages = portfolio_data['languages']
            profile.save()
class TherapistAppointmentViewSet(viewsets.ModelViewSet):
    serializer_class = TherapistAppointmentSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['status']
    ordering = ['start_time']
    http_method_names = ['get', 'patch', 'post']
    def get_queryset(self):
        return Appointment.objects.filter(
            items__therapist=self.request.user
        ).distinct()
    def _update_status(self, request, pk, new_status, allowed_from=None, msg="Updated."):
        from decimal import Decimal
        from apps.core.models import Invoice, InvoiceLine
        appointment = self.get_object()
        if allowed_from and appointment.status not in allowed_from:
            return Response(
                {"success": False, "message": f"Cannot perform this action from status: {appointment.status}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        appointment.status = new_status
        if new_status == AppointmentStatus.COMPLETED:
            from django.utils import timezone as tz
            appointment.end_time = tz.now()
            appointment.save()
            invoice, inv_created = Invoice.objects.get_or_create(
                appointment=appointment,
                defaults={
                    'store': appointment.store,
                    'customer': appointment.customer,
                    'invoice_number': f'INV-{appointment.id}',
                    'subtotal_paise': 0,
                    'tax_amount_paise': 0,
                    'grand_total_paise': 0,
                    'status': 'PAID',
                }
            )
            subtotal = Decimal('0.00')
            for item in appointment.items.all():
                price = item.price or (item.service.price if item.service else Decimal('0.00'))
                inv_item, _ = InvoiceLine.objects.get_or_create(
                    invoice=invoice,
                    service=item.service,
                    defaults={
                        'quantity': 1,
                        'unit_price_paise': int(round(price * 100)),
                        'tax_rate': Decimal('0.00'),
                        'tax_amount_paise': 0,
                        'total_paise': int(round(price * 100)),
                    }
                )
                subtotal += price
                if item.therapist:
                    commission_rate = Decimal('0.40')
                    commission_amount = (price * commission_rate).quantize(Decimal('0.01'))
                    Commission.objects.get_or_create(
                        invoice_item=inv_item,
                        therapist=item.therapist,
                        defaults={
                            'store': appointment.store,
                            'amount': commission_amount,
                            'is_paid_out': False,
                        }
                    )
            invoice.subtotal_paise = int(round(subtotal * 100))
            invoice.grand_total_paise = int(round(subtotal * 100))
            invoice.save()
        else:
            appointment.save()
        return success_response(TherapistAppointmentSerializer(appointment).data, msg)
    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        appt = self.get_object()
        if appt.status not in [AppointmentStatus.BOOKED]:
            return Response({"success": False, "message": "Can only start BOOKED appointments."}, status=400)
        from django.utils import timezone as tz
        appt.notes = (appt.notes or '') + f'\n[Service started at {tz.now().strftime("%H:%M")}]'
        appt.status = 'CONFIRMED'
        appt.save()
        return success_response(TherapistAppointmentSerializer(appt).data, "Service started.")
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        return self._update_status(
            request, pk,
            AppointmentStatus.COMPLETED,
            allowed_from=['CONFIRMED', 'BOOKED'],
            msg="Appointment completed."
        )
    @action(detail=True, methods=['post'])
    def no_show(self, request, pk=None):
        return self._update_status(
            request, pk,
            AppointmentStatus.NO_SHOW,
            allowed_from=['BOOKED', 'CONFIRMED'],
            msg="Marked as no-show."
        )
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        return self._update_status(
            request, pk,
            AppointmentStatus.CANCELLED,
            allowed_from=['BOOKED', 'CONFIRMED'],
            msg="Appointment cancelled."
        )
    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        return self._update_status(
            request, pk,
            AppointmentStatus.PAUSED,
            allowed_from=['CONFIRMED', 'IN_PROGRESS'],
            msg="Appointment paused."
        )
    @action(detail=True, methods=['post'])
    def reschedule(self, request, pk=None):
        return self._update_status(
            request, pk,
            AppointmentStatus.RESCHEDULE_REQUESTED,
            allowed_from=['BOOKED'],
            msg="Reschedule requested."
        )
    @action(detail=True, methods=['patch'])
    def add_note(self, request, pk=None):
        appt = self.get_object()
        note = request.data.get('note', '')
        if note:
            from django.utils import timezone as tz
            appt.notes = (appt.notes or '') + f'\n[{tz.now().strftime("%d %b %H:%M")}] {note}'
            appt.save()
        return success_response(TherapistAppointmentSerializer(appt).data, "Note added.")
class TherapistAppointmentItemViewSet(viewsets.ModelViewSet):
    serializer_class = TherapistAppointmentItemSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    http_method_names = ['get', 'patch']
    def get_queryset(self):
        return AppointmentItem.objects.filter(therapist=self.request.user)
class TherapistCommissionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TherapistCommissionSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['is_paid_out']
    ordering = ['-created_at']
    def get_queryset(self):
        return Commission.objects.filter(therapist=self.request.user)
class CustomerNoteViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerNoteSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['customer']
    ordering = ['-created_at']
    def get_queryset(self):
        return CustomerNote.objects.filter(therapist=self.request.user)
    def perform_create(self, serializer):
        serializer.save(therapist=self.request.user)
class AnnouncementViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AnnouncementSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    def get_queryset(self):
        from django.db.models import Q
        store = self.request.user.store
        return Announcement.objects.filter(Q(store=store) | Q(store__isnull=True)).order_by('-created_at')
class TrainingVideoViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TrainingVideoSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    def get_queryset(self):
        return TrainingVideo.objects.filter(is_active=True).order_by('-created_at')
class TrainingCourseViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TrainingCourseSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    def get_queryset(self):
        return TrainingCourse.objects.filter(is_active=True)
class TherapistWalletView(generics.RetrieveAPIView):
    serializer_class = StaffWalletSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    def get_object(self):
        wallet, created = Wallet.objects.get_or_create(customer=self.request.user)
        return wallet
from django.utils import timezone
from django.db.models import Sum
from decimal import Decimal
from apps.core.models import BeforeAfterGallery, User
from .serializers import BeforeAfterGallerySerializer
class TherapistDashboardViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, IsTherapist]
    def list(self, request):
        therapist = request.user
        today = timezone.localtime().date()
        from django.db.models import Q
        from apps.core.models import AppointmentSlot, AppointmentSlotStatus
        today_appointments = AppointmentItem.objects.filter(therapist=therapist, appointment__start_time__date=today).count()
        today_appointments += AppointmentSlot.objects.filter(
            professional__user_account__user=therapist
        ).filter(
            Q(slot_start__date=today) | Q(actual_start_time__date=today) | Q(actual_end_time__date=today)
        ).count()

        upcoming_appointments = AppointmentItem.objects.filter(therapist=therapist, appointment__start_time__gte=timezone.now()).count()
        upcoming_appointments += AppointmentSlot.objects.filter(
            professional__user_account__user=therapist,
            status__in=['scheduled', 'started', 'confirmed', 'SCHEDULED', 'STARTED', 'CONFIRMED']
        ).count()

        today_commissions = Commission.objects.filter(therapist=therapist, created_at__date=today).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')

        # Add 30% stylist commission from completed AppointmentSlots today
        done_slots_today = AppointmentSlot.objects.filter(
            professional__user_account__user=therapist,
            status=AppointmentSlotStatus.DONE
        ).filter(
            Q(actual_end_time__date=today) | Q(slot_start__date=today)
        )
        for s in done_slots_today:
            price = Decimal(s.price_paise or 75000) / Decimal(100)
            today_commissions += price * Decimal('0.30')

        from apps.core.models import Tip
        today_tips = Tip.objects.filter(
            therapist=therapist,
            created_at__date=today
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        total_earnings_today = today_commissions + today_tips
        avg_rating = therapist.favorited_by.count()
        today_att = Attendance.objects.filter(staff=therapist, date=today).first()
        is_checked_in = bool(today_att and today_att.clock_in and not today_att.clock_out)
        profile, _ = TherapistProfile.objects.get_or_create(user=therapist)
        data = {
            "today_date": str(today),
            "today_appointments": today_appointments,
            "upcoming_bookings": upcoming_appointments,
            "earnings_today": {
                "commission": float(today_commissions),
                "tips": float(today_tips),
                "total": float(total_earnings_today)
            },
            "is_checked_in": is_checked_in,
            "availability_status": getattr(profile, 'availability_status', 'AVAILABLE'),
            "followers": avg_rating
        }
        return success_response(data, "Therapist dashboard generated")
class BeforeAfterGalleryViewSet(viewsets.ModelViewSet):
    serializer_class = BeforeAfterGallerySerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    def get_queryset(self):
        queryset = BeforeAfterGallery.objects.filter(therapist=self.request.user).order_by('-created_at')
        customer_id = self.request.query_params.get('customer')
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)
        return queryset
    def perform_create(self, serializer):
        serializer.save(therapist=self.request.user)
from apps.store_erp.serializers import CustomerCRMDataSerializer
class StaffCustomerCRMViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CustomerCRMDataSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    def get_queryset(self):
        customer_ids = AppointmentItem.objects.filter(
            therapist=self.request.user
        ).values_list('appointment__customer_id', flat=True).distinct()
        return User.objects.filter(id__in=customer_ids)

    def list(self, request, *args, **kwargs):
        clients_data = []
        try:
            legacy_qs = self.get_queryset()
            clients_data = list(CustomerCRMDataSerializer(legacy_qs, many=True).data)
        except Exception:
            clients_data = []

        from apps.core.models import AppointmentSlot, AppointmentSlotStatus, GlobalCustomer
        slots = AppointmentSlot.objects.filter(
            professional__user_account__user=self.request.user
        ).select_related('booking', 'booking__customer', 'store_service').order_by('-slot_start')

        seen_customer_ids = set()
        for slot in slots:
            booking = slot.booking
            if not booking or not booking.customer:
                continue
            cust = booking.customer
            if str(cust.id) in seen_customer_ids:
                continue
            seen_customer_ids.add(str(cust.id))

            cust_slots = [s for s in slots if s.booking and s.booking.customer_id == cust.id]
            total_visits = len(cust_slots)
            total_spend_paise = sum(s.price_paise or 0 for s in cust_slots if s.status == AppointmentSlotStatus.DONE)
            total_spend = total_spend_paise / 100.0
            avg_spend = (total_spend / total_visits) if total_visits > 0 else 0

            raw_name = cust.name or "Client"
            if raw_name.startswith("91") and "@phone.nearbyme.local" in raw_name:
                phone_raw = raw_name.replace("@phone.nearbyme.local", "")
                display_name = f"+91 {phone_raw[2:7]} {phone_raw[7:]}" if len(phone_raw) == 12 else f"Client ({phone_raw})"
            else:
                display_name = raw_name

            phone = cust.phone_e164 or ""
            parts = display_name.split(" ")
            first_name = parts[0]
            last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

            visits = []
            for s in cust_slots:
                visits.append({
                    'id': str(s.id),
                    'service_name': s.store_service.name if s.store_service else "Salon Service",
                    'date': s.slot_start.isoformat() if s.slot_start else None,
                    'price': (s.price_paise or 0) / 100,
                    'status': s.status,
                })

            clients_data.append({
                'id': str(cust.id),
                'first_name': first_name,
                'last_name': last_name,
                'name': display_name,
                'phone': phone or display_name,
                'total_visits': total_visits,
                'total_spend': total_spend,
                'average_spend': avg_spend,
                'formula': "Signature styling & grooming preference",
                'notes': booking.notes or "Regular salon client",
                'allergies': "None reported",
                'created_at': cust.created_at.isoformat() if cust.created_at else timezone.now().isoformat(),
                'visits': visits,
            })

        return success_response(clients_data, "Clients retrieved successfully")
class TherapistConversationViewSet(viewsets.ModelViewSet):
    serializer_class = TherapistConversationSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    http_method_names = ['get', 'post', 'head']

    def get_queryset(self):
        user = self.request.user
        from apps.core.models import Appointment, AppointmentSlot, Conversation, User, Role, ChatMessage
        try:
            cust_ids = set()
            for appt in Appointment.objects.filter(items__therapist=user, customer__isnull=False):
                cust_ids.add(appt.customer_id)
            for slot in AppointmentSlot.objects.filter(professional__user_account__user=user, booking__customer__isnull=False):
                cust_ids.add(slot.booking.customer_id)
            for cid in cust_ids:
                Conversation.objects.get_or_create(therapist=user, customer_id=cid)
        except Exception:
            pass
        return Conversation.objects.filter(therapist=user)

    def create(self, request, *args, **kwargs):
        customer_id = request.data.get('customer_id') or request.data.get('customer')
        if not customer_id:
            return error_response("customer_id is required.", 400)
        from apps.core.models import Conversation, ChatMessage
        convo, created = Conversation.objects.get_or_create(
            therapist=request.user,
            customer_id=customer_id
        )
        first_msg = (request.data.get('message') or request.data.get('content') or '').strip()
        if first_msg:
            ChatMessage.objects.create(conversation=convo, sender=request.user, content=first_msg)
        return success_response(TherapistConversationSerializer(convo, context={'request': request}).data, "Conversation ready", 201 if created else 200)

    @action(detail=True, methods=['get', 'post'])
    def messages(self, request, pk=None):
        convo = self.get_object()
        if request.method == 'POST':
            content = (request.data.get('content') or '').strip()
            if not content:
                return error_response("content is required.", 400)
            msg = ChatMessage.objects.create(conversation=convo, sender=request.user, content=content)
            from apps.core.notifications import notify_user
            notify_user(
                convo.customer, f"New message from {request.user.get_full_name() or 'your therapist'}",
                content[:120], notif_type='NEW_MESSAGE', data={"conversation_id": str(convo.id)},
            )
            return success_response(TherapistChatMessageSerializer(msg, context={'request': request}).data, "Sent", 201)
        convo.messages.exclude(sender=request.user).update(is_read=True)
        msgs = convo.messages.select_related('sender')
        return success_response(TherapistChatMessageSerializer(msgs, many=True, context={'request': request}).data)
class NotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
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
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['store'] = self.request.user.store
        return context
    def get_object(self):
        user = super().get_object()
        user.total_visits = 0
        user.total_spend = Decimal('0.00')
        user.average_spend = Decimal('0.00')
        user.outstanding_balance = Decimal('0.00')
        user.favorite_therapist_name = self.request.user.get_full_name()
        return user
class TherapistTipViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TipSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    filter_backends = [OrderingFilter]
    ordering = ['-created_at']
    def get_queryset(self):
        from apps.core.models import Tip
        return Tip.objects.filter(therapist=self.request.user).select_related('invoice', 'invoice__customer')
class AttendanceView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsTherapist]
    def get(self, request):
        from django.utils import timezone
        today = timezone.localtime().date()
        store = request.user.store
        profile, _ = TherapistProfile.objects.get_or_create(user=request.user)
        if store:
            record = Attendance.objects.filter(staff=request.user, date=today).first()
            clock_in  = record.clock_in if record else None
            clock_out = record.clock_out if record else None
            att_status = record.status if record else None
        else:
            clock_in = clock_out = att_status = None
        is_checked_in = bool(clock_in and not clock_out)
        return Response({
            'clock_in': clock_in,
            'clock_out': clock_out,
            'status': att_status,
            'is_checked_in': is_checked_in,
            'availability_status': getattr(profile, 'availability_status', 'AVAILABLE'),
        })
    def post(self, request):
        from django.utils import timezone
        from apps.core.models import Professional, Role
        from apps.core.notifications import notify_user
        action_type = request.data.get('action')
        today = timezone.localtime().date()
        store = request.user.store
        profile, _ = TherapistProfile.objects.get_or_create(user=request.user)
        prof = Professional.objects.filter(user_account__user=request.user).first()
        staff_name = request.user.get_full_name() or request.user.first_name or "Stylist"

        if action_type == 'status':
            new_status = request.data.get('availability_status', 'AVAILABLE')
            profile.availability_status = new_status
            profile.save()
            if prof:
                prof.is_bookable = (new_status == 'AVAILABLE')
                prof.save(update_fields=['is_bookable'])
            return Response({
                'availability_status': new_status,
                'is_bookable': prof.is_bookable if prof else True
            })

        if not store:
            return Response({'error': 'No store assigned to your account. Please contact your manager.'}, status=400)

        record, _ = Attendance.objects.get_or_create(
            staff=request.user, date=today,
            defaults={'store': store, 'status': AttendanceStatus.PRESENT}
        )

        if action_type == 'check_in':
            record.clock_in = timezone.now()
            record.clock_out = None
            record.status = AttendanceStatus.PRESENT
            record.save()
            profile.availability_status = 'AVAILABLE'
            profile.save()
            if prof:
                prof.is_bookable = True
                prof.save(update_fields=['is_bookable'])

            # Send in-app notification to store managers / receptionists
            managers = User.objects.filter(store=store, role__in=[Role.STORE_ADMIN, Role.RECEPTIONIST])
            for m in managers:
                notify_user(
                    m,
                    f"Staff Checked In: {staff_name}",
                    f"{staff_name} has checked in at {store.name} and is now available for appointments.",
                    notif_type='SYSTEM',
                    data={'type': 'staff_check_in', 'staff_id': str(request.user.id)}
                )

        elif action_type == 'check_out':
            record.clock_out = timezone.now()
            record.save()
            profile.availability_status = 'OFF_DUTY'
            profile.save()

            # Send in-app notification to store managers / receptionists
            managers = User.objects.filter(store=store, role__in=[Role.STORE_ADMIN, Role.RECEPTIONIST])
            for m in managers:
                notify_user(
                    m,
                    f"Staff Checked Out: {staff_name}",
                    f"{staff_name} has checked out from {store.name} and is now offline.",
                    notif_type='SYSTEM',
                    data={'type': 'staff_check_out', 'staff_id': str(request.user.id)}
                )

        is_checked_in = bool(record.clock_in and not record.clock_out)
        return Response({
            'clock_in': record.clock_in,
            'clock_out': record.clock_out,
            'status': record.status,
            'is_checked_in': is_checked_in,
            'availability_status': getattr(profile, 'availability_status', 'AVAILABLE'),
        })
class StaffTargetView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsTherapist]
    def get(self, request):
        from django.utils import timezone
        from django.db.models import Sum
        from decimal import Decimal
        therapist = request.user
        today = timezone.localtime().date()
        month_str = today.strftime('%m-%Y')
        target = StaffTarget.objects.filter(staff=therapist, month_year=month_str).first()
        monthly_commission = Commission.objects.filter(
            therapist=therapist,
            created_at__year=today.year,
            created_at__month=today.month
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        revenue_target = target.revenue_target if target else Decimal('0.00')
        percentage = float((monthly_commission / revenue_target * 100) if revenue_target > 0 else 0)
        return Response({
            'month': month_str,
            'revenue_target': revenue_target,
            'achieved': monthly_commission,
            'percentage': round(min(percentage, 100), 1),
        })
class LeaderboardView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsTherapist]
    def get(self, request):
        from django.utils import timezone
        from django.db.models import Sum, Count
        from decimal import Decimal
        from apps.core.models import Tip, AppointmentSlot, AppointmentSlotStatus
        today = timezone.localtime().date()
        store = request.user.store
        month_year = today.strftime('%m-%Y')
        therapists = list(User.objects.filter(store=store, role='THERAPIST')) if store else []
        if request.user not in therapists:
            therapists.append(request.user)
        board = []
        for t in therapists:
            comm = Commission.objects.filter(
                therapist=t,
                created_at__year=today.year,
                created_at__month=today.month
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            tips = Tip.objects.filter(
                therapist=t,
                created_at__year=today.year,
                created_at__month=today.month
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            appts = AppointmentItem.objects.filter(
                therapist=t,
                appointment__status='COMPLETED',
                appointment__start_time__year=today.year,
                appointment__start_time__month=today.month,
            ).count()
            appts += AppointmentSlot.objects.filter(
                professional__user_account__user=t,
                status=AppointmentSlotStatus.DONE
            ).count()
            repeat = AppointmentItem.objects.filter(
                therapist=t,
                appointment__status='COMPLETED',
            ).values('appointment__customer').annotate(n=Count('appointment__customer')).filter(n__gt=1).count()
            points = (appts * 150) + int(comm)
            badge = "🌱 Newcomer"
            if points >= 4000 or appts >= 50:
                badge = "🥇 Master Stylist"
            elif points >= 2500 or appts >= 25:
                badge = "🥈 Star Stylist"
            elif points >= 1000 or appts >= 10:
                badge = "🥉 Elite Specialist"
            elif points >= 500:
                badge = "💪 Pro Specialist"

            board.append({
                'id': t.id,
                'name': t.get_full_name() or t.first_name or t.email,
                'outlet': t.store.name if t.store else (request.user.store.name if request.user.store else "Roots Men’s Salon"),
                'commission': float(comm),
                'tips': float(tips),
                'total': float(comm + tips),
                'completed': appts,
                'points': f"{points:,} pts",
                'badge': badge,
                'is_me': t.id == request.user.id,
            })
        board.sort(key=lambda x: (x['total'], x['completed']), reverse=True)
        for i, item in enumerate(board):
            item['rank'] = i + 1
        return Response({'month': month_year, 'board': board})
class EarningsSummaryView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsTherapist]
    def get(self, request):
        from django.utils import timezone
        from django.db.models import Sum
        from datetime import timedelta
        from decimal import Decimal
        from apps.core.models import Tip
        therapist = request.user
        period = request.query_params.get('period', 'today')
        today = timezone.localtime().date()
        if period == 'week':
            start = today - timedelta(days=today.weekday())
            end = today
        elif period == 'month':
            start = today.replace(day=1)
            end = today
        else:
            start = today
            end = today
        commissions = Commission.objects.filter(
            therapist=therapist,
            created_at__date__range=[start, end]
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        tips = Tip.objects.filter(
            therapist=therapist,
            created_at__date__range=[start, end]
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        completed_appts = AppointmentItem.objects.filter(
            therapist=therapist,
            appointment__status='COMPLETED',
            appointment__start_time__date__range=[start, end]
        ).count()
        unpaid_commissions = Commission.objects.filter(
            therapist=therapist,
            is_paid_out=False
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        return Response({
            'period': period,
            'start': str(start),
            'end': str(end),
            'commission': commissions,
            'tips': tips,
            'total': commissions + tips,
            'completed_services': completed_appts,
            'pending_payout': unpaid_commissions,
        })
class StaffStatsView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsTherapist]
    def get(self, request):
        from django.db.models import Sum, Count, Avg
        from decimal import Decimal
        from apps.core.models import Review, AppointmentSlot, AppointmentSlotStatus
        therapist = request.user
        store = therapist.store
        total_completed = AppointmentItem.objects.filter(
            therapist=therapist,
            appointment__status='COMPLETED'
        ).count()
        total_completed += AppointmentSlot.objects.filter(
            professional__user_account__user=therapist,
            status=AppointmentSlotStatus.DONE
        ).count()
        total_booked = AppointmentItem.objects.filter(
            therapist=therapist,
            appointment__status__in=['COMPLETED', 'CANCELLED', 'NO_SHOW']
        ).count()
        total_booked += AppointmentSlot.objects.filter(
            professional__user_account__user=therapist
        ).count()
        completion_rate = round((total_completed / total_booked * 100) if total_booked > 0 else 0)
        repeat_customers = AppointmentItem.objects.filter(
            therapist=therapist,
            appointment__status='COMPLETED',
            appointment__customer__isnull=False
        ).values('appointment__customer').annotate(
            n=Count('appointment__customer')
        ).filter(n__gt=1).count()
        followers = therapist.favorited_by.count()
        avg_rating_data = Review.objects.filter(
            store=store,
            status='APPROVED'
        ).aggregate(avg=Avg('rating'))
        avg_rating = round(float(avg_rating_data['avg'] or 4.8), 1)
        total_tips = Commission.objects.filter(
            therapist=therapist
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        badge = 'Rising Star'
        if total_completed >= 500 or completion_rate >= 95:
            badge = '🏆 Elite'
        elif total_completed >= 200 or completion_rate >= 90:
            badge = '⭐ Expert'
        elif total_completed >= 100 or completion_rate >= 80:
            badge = '💪 Pro'
        elif total_completed >= 50:
            badge = '🌟 Rising Star'
        else:
            badge = '🌱 Newcomer'
        return Response({
            'total_completed': total_completed,
            'completion_rate': completion_rate,
            'repeat_customers': repeat_customers,
            'followers': followers,
            'avg_rating': avg_rating,
            'total_tips': total_tips,
            'performance_badge': badge,
        })
from apps.core.models import StaffTask, TherapistSettings, StaffChatMessage
class StaffTaskViewSet(viewsets.ModelViewSet):
    serializer_class = StaffTaskSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    def get_queryset(self):
        return StaffTask.objects.filter(therapist=self.request.user)
    def perform_create(self, serializer):
        serializer.save(therapist=self.request.user)
class TherapistSettingsView(generics.RetrieveUpdateAPIView):
    serializer_class = TherapistSettingsSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    def get_object(self):
        settings, _ = TherapistSettings.objects.get_or_create(user=self.request.user)
        return settings
class StaffChatViewSet(viewsets.ModelViewSet):
    serializer_class = StaffChatMessageSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    def get_queryset(self):
        return StaffChatMessage.objects.all()[:50]
    def perform_create(self, serializer):
        serializer.save(sender=self.request.user)
class AIDailySuggestionView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsTherapist]
    def get(self, request, *args, **kwargs):
        from django.utils import timezone
        from django.db.models import Q
        from apps.core.models import AppointmentSlot
        today = timezone.localdate()
        appts = Appointment.objects.filter(
            items__therapist=request.user,
            start_time__date=today
        ).distinct().count()
        appts += AppointmentSlot.objects.filter(
            professional__user_account__user=request.user
        ).filter(
            Q(slot_start__date=today) | Q(actual_start_time__date=today)
        ).count()
        if appts == 0:
            text = "Good day! Your schedule is clear today. Stay prepared for new walk-ins and bookings!"
        else:
            text = f"Good day! You have {appts} scheduled appointment{'s' if appts != 1 else ''} today. Give every client an exceptional experience!"
        return Response({"suggestion": text, "updated_at": "Just now"})
class CustomerAIRecommendationView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsTherapist]
    def get(self, request, pk=None, *args, **kwargs):
        return Response({
            "treatments": ["Hydrating Facial (Recommended)", "LED Therapy"],
            "products": ["Vitamin C Serum", "SPF 50 Moisturizer"],
            "rationale": "Client has a history of dry skin and recently mentioned sensitivity."
        })
class TherapistReviewViewSet(viewsets.ModelViewSet):
    serializer_class = TherapistReviewSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = ['created_at', 'rating']
    ordering = ['-created_at']
    def get_queryset(self):
        return Review.objects.filter(therapist=self.request.user)
    @action(detail=True, methods=['post', 'patch'])
    def reply(self, request, pk=None):
        review = self.get_object()
        reply_text = request.data.get('reply_text')
        if not reply_text:
            return Response({"error": "reply_text is required"}, status=status.HTTP_400_BAD_REQUEST)
        from django.utils import timezone
        review.reply_text = reply_text
        review.replied_at = timezone.now()
        review.save()
        return Response(self.get_serializer(review).data)
class StaffIncentiveViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StaffIncentiveSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    filter_backends = [OrderingFilter]
    ordering_fields = ['created_at', 'amount']
    ordering = ['-created_at']
    def get_queryset(self):
        return StaffIncentive.objects.filter(staff=self.request.user)
class StaffPayrollViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StaffPayrollSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    filter_backends = [OrderingFilter]
    ordering = ['-processed_at']
    def get_queryset(self):
        return Payroll.objects.filter(staff=self.request.user)
class StaffLeaveRequestViewSet(viewsets.ModelViewSet):
    serializer_class = StaffLeaveRequestSerializer
    permission_classes = [IsAuthenticated, IsTherapist]
    http_method_names = ['get', 'post', 'delete', 'head']
    filter_backends = [OrderingFilter]
    ordering = ['-start_date']

    def get_queryset(self):
        return LeaveRequest.objects.filter(staff=self.request.user)

    def perform_create(self, serializer):
        user = self.request.user
        store = user.store
        if not store and user.outlet:
            store = user.outlet.store
        if not store:
            from apps.core.models import Store
            store = Store.objects.first()
        outlet = user.outlet or (store.outlets.first() if store and hasattr(store, 'outlets') else None)
        leave = serializer.save(staff=user, store=store, outlet=outlet)

        try:
            from apps.core.notifications import notify_user
            from apps.core.models import Role
            staff_name = user.get_full_name() or user.first_name or "Stylist"
            managers = User.objects.filter(store=store, role__in=[Role.STORE_MANAGER, Role.STORE_OWNER, Role.MASTER_ADMIN])
            for mgr in managers:
                notify_user(
                    user=mgr,
                    title="🌴 New Leave Request",
                    body=f"{staff_name} requested leave from {leave.start_date} to {leave.end_date}: {leave.reason[:50]}.",
                    notification_type="SYSTEM",
                    data={"leave_id": str(leave.id), "staff_id": str(user.id)}
                )
        except Exception:
            pass

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.status != 'PENDING':
            return Response({"error": "Only pending leave requests can be cancelled."}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

