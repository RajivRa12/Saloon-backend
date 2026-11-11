import datetime as dt
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.models import (
    Role, StoreGroup, StoreGroupStatus, StoreGroupType, City, Zone, Outlet, Store,
    ServiceCategoryPhase1, CanonicalService, StoreService, StoreServiceMarketplaceStatus,
    Professional, ProfessionalLinkStatus, ProfessionalSkill, ProfessionalShift, Resource, ResourceKind,
    GlobalCustomer, Booking, BookingStatus, AppointmentSlot, AppointmentSlotStatus,
    PhoneOTP, SlotHold, SlotHoldStatus
)

User = get_user_model()


class EndToEndIntegrationTestSuite(APITestCase):
    def setUp(self):
        self.city = City.objects.create(name="Bengaluru", state="Karnataka", is_active=True)
        self.zone = Zone.objects.create(city=self.city, name="Indiranagar", is_active=True)

        self.store_group = StoreGroup.objects.create(
            name="Serendipity Med-Spa",
            legal_name="Serendipity Skincare India Pvt Ltd",
            business_type=StoreGroupType.BOTH,
            status=StoreGroupStatus.ACTIVE,
            owner_name="Kabir Bedi",
            owner_email="kabir@serendipity.co.in",
            owner_phone="+919846901234",
        )
        self.outlet = Outlet.objects.create(
            store_group=self.store_group,
            name="Serendipity Studio - Indiranagar",
            address_line="100ft Road, Indiranagar",
            city=self.city,
            zone=self.zone,
            pincode="560038",
            phone="+919800000000",
            opening_time=dt.time(9, 0),
            closing_time=dt.time(21, 0),
            status='active',
        )
        self.store = Store.objects.create(
            name="NearbyMe Partner Studio (POS Branch)",
            outlet=self.outlet,
            status="ACTIVE",
            email="studio.pos@nearbyme.in",
            contact_number="+919800000000",
        )

        self.category, _ = ServiceCategoryPhase1.objects.get_or_create(
            slug="hair-styling-test",
            defaults={'name': "Hair Styling Test", 'is_active': True}
        )
        self.canonical_service, _ = CanonicalService.objects.get_or_create(
            slug="blow-dry-styling-test",
            defaults={
                'category': self.category,
                'name': "Blow Dry & Styling Test",
                'default_duration_min': 45,
                'buffer_before_min': 0,
                'buffer_after_min': 10,
                'resource_type': "chair",
                'gender_applicability': "women",
                'skill_tag': "stylist",
                'is_active': True,
            }
        )
        self.store_service, _ = StoreService.objects.get_or_create(
            store_group=self.store_group,
            canonical_service=self.canonical_service,
            defaults={
                'name': "Blow Dry & Styling Test",
                'default_price_paise': 150000,
                'duration_min': 45,
                'is_active_in_store': True,
                'marketplace_status': StoreServiceMarketplaceStatus.APPROVED,
            }
        )

        self.resource = Resource.objects.create(
            outlet=self.outlet,
            name="Styling Chair 1",
            resource_type=ResourceKind.CHAIR,
            capacity=1,
            is_bookable=True,
        )

        self.pro_user = User.objects.create_user(
            email="therapist.qa@nearbyme.in",
            password="password123",
            first_name="Rajiv",
            last_name="Therapist",
            role=Role.THERAPIST,
            store=self.store,
            phone="+919875647869",
        )
        self.professional = Professional.objects.create(
            store_group=self.store_group,
            outlet=self.outlet,
            display_name="Rajiv Therapist",
            display_role="Senior Stylist",
            email="therapist.qa@nearbyme.in",
            phone_e164="+919875647869",
            link_status=ProfessionalLinkStatus.INVITED,
            is_bookable=True,
        )
        ProfessionalSkill.objects.create(professional=self.professional, skill_tag="stylist")
        for day in range(7):
            ProfessionalShift.objects.create(
                professional=self.professional,
                outlet=self.outlet,
                weekday=day,
                start_time=dt.time(9, 0),
                end_time=dt.time(21, 0),
                effective_from=dt.date(2026, 1, 1),
            )

        self.customer1_user = User.objects.create_user(
            email="919999999999@phone.nearbyme.local",
            username="+919999999999",
            phone="+919999999999",
            role=Role.CUSTOMER,
        )
        self.customer2_user = User.objects.create_user(
            email="919876543210@phone.nearbyme.local",
            username="+919876543210",
            phone="+919876543210",
            role=Role.CUSTOMER,
        )

    def _jwt_for(self, user):
        refresh = RefreshToken.for_user(user)
        refresh['role'] = user.role
        refresh['email'] = user.email
        return str(refresh.access_token)

    def test_e2e_complete_booking_and_therapist_workflow(self):
        """End-to-End Test: Customer discovery -> Booking -> Therapist Schedule -> Start -> Complete"""
        cust1_token = self._jwt_for(self.customer1_user)
        pro_token = self._jwt_for(self.pro_user)

        res = self.client.get(
            f"/api/customer/stores/{self.store.id}/phase1-menu/",
            HTTP_AUTHORIZATION=f"Bearer {cust1_token}"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data['data']), 1)
        self.assertEqual(res.data['data'][0]['name'], "Blow Dry & Styling Test")

        target_date = timezone.now().date() + dt.timedelta(days=1)
        slot_start = timezone.make_aware(dt.datetime.combine(target_date, dt.time(10, 0)))
        slot_end = timezone.make_aware(dt.datetime.combine(target_date, dt.time(10, 45)))

        book_payload = {
            "store_service_id": str(self.store_service.id),
            "professional_id": str(self.professional.id),
            "slot_start": slot_start.isoformat(),
            "slot_end": slot_end.isoformat(),
            "pay_with_wallet": False,
        }
        book_res = self.client.post(
            f"/api/customer/stores/{self.store.id}/phase1-book/",
            book_payload,
            format='json',
            HTTP_AUTHORIZATION=f"Bearer {cust1_token}"
        )
        self.assertEqual(book_res.status_code, status.HTTP_201_CREATED)
        booking_id = book_res.data['data']['id']
        self.assertEqual(book_res.data['data']['status'], "confirmed")

        pro_profile = self.client.get(
            "/api/therapist/profile/",
            HTTP_AUTHORIZATION=f"Bearer {pro_token}"
        )
        self.assertEqual(pro_profile.status_code, status.HTTP_200_OK)

        self.professional.refresh_from_db()
        self.assertEqual(self.professional.link_status, ProfessionalLinkStatus.ACCEPTED)

        sched_res = self.client.get(
            "/api/therapist/schedule/?ordering=slot_start",
            HTTP_AUTHORIZATION=f"Bearer {pro_token}"
        )
        self.assertEqual(sched_res.status_code, status.HTTP_200_OK)
        slots = sched_res.data
        self.assertEqual(len(slots), 1)
        slot_id = slots[0]['id']
        self.assertEqual(str(slots[0]['booking']), str(booking_id))
        self.assertEqual(slots[0]['status'], "scheduled")

        start_res = self.client.post(
            f"/api/therapist/schedule/{slot_id}/start/",
            {'reason': 'Client arrived early'},
            format='json',
            HTTP_AUTHORIZATION=f"Bearer {pro_token}"
        )
        self.assertEqual(start_res.status_code, status.HTTP_200_OK)
        self.assertEqual(start_res.data['data']['status'], "started")

        booking = Booking.objects.get(id=booking_id)
        self.assertEqual(booking.status, BookingStatus.IN_SERVICE)

        complete_res = self.client.post(
            f"/api/therapist/schedule/{slot_id}/complete/",
            {'reason': 'Service completed normally'},
            format='json',
            HTTP_AUTHORIZATION=f"Bearer {pro_token}"
        )
        self.assertEqual(complete_res.status_code, status.HTTP_200_OK)
        self.assertEqual(complete_res.data['data']['status'], "done")

        booking.refresh_from_db()
        self.assertEqual(booking.status, BookingStatus.COMPLETED)

    def test_conflict_prevention_and_cancellation(self):
        """Test slot conflict prevention, booking cancellation, and schedule sync"""
        cust1_token = self._jwt_for(self.customer1_user)
        cust2_token = self._jwt_for(self.customer2_user)
        pro_token = self._jwt_for(self.pro_user)

        target_date = timezone.now().date() + dt.timedelta(days=2)
        slot_start = timezone.make_aware(dt.datetime.combine(target_date, dt.time(14, 0)))
        slot_end = timezone.make_aware(dt.datetime.combine(target_date, dt.time(14, 45)))

        book_res1 = self.client.post(
            f"/api/customer/stores/{self.store.id}/phase1-book/",
            {
                "store_service_id": str(self.store_service.id),
                "professional_id": str(self.professional.id),
                "slot_start": slot_start.isoformat(),
                "slot_end": slot_end.isoformat(),
            },
            format='json',
            HTTP_AUTHORIZATION=f"Bearer {cust1_token}"
        )
        self.assertEqual(book_res1.status_code, status.HTTP_201_CREATED)
        booking1_id = book_res1.data['data']['id']

        book_res2 = self.client.post(
            f"/api/customer/stores/{self.store.id}/phase1-book/",
            {
                "store_service_id": str(self.store_service.id),
                "professional_id": str(self.professional.id),
                "slot_start": slot_start.isoformat(),
                "slot_end": slot_end.isoformat(),
            },
            format='json',
            HTTP_AUTHORIZATION=f"Bearer {cust2_token}"
        )
        self.assertEqual(book_res2.status_code, status.HTTP_200_OK)
        self.assertTrue(book_res2.data['data']['conflict'])

        cancel_res = self.client.post(
            f"/api/customer/bookings/{booking1_id}/cancel/",
            HTTP_AUTHORIZATION=f"Bearer {cust1_token}"
        )
        self.assertEqual(cancel_res.status_code, status.HTTP_200_OK)

        booking1 = Booking.objects.get(id=booking1_id)
        self.assertEqual(booking1.status, BookingStatus.CANCELLED)
        self.assertTrue(all(s.status == AppointmentSlotStatus.CANCELLED for s in booking1.slots.all()))

        sched_res = self.client.get(
            "/api/therapist/schedule/?ordering=slot_start",
            HTTP_AUTHORIZATION=f"Bearer {pro_token}"
        )
        self.assertEqual(sched_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(sched_res.data), 0)

    def test_unauthorized_access_security(self):
        """Security: Role-based access control and unauthorized request rejection"""
        cust_token = self._jwt_for(self.customer1_user)

        res = self.client.get(
            "/api/therapist/schedule/",
            HTTP_AUTHORIZATION=f"Bearer {cust_token}"
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        res_anon = self.client.get("/api/therapist/schedule/")
        self.assertEqual(res_anon.status_code, status.HTTP_401_UNAUTHORIZED)
