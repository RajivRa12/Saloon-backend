import os
from datetime import time
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.core.models import (
    Business, BusinessType, BusinessStatus,
    Brand, BrandStatus,
    Store, StoreStatus,
    StoreGroup, StoreGroupStatus, StoreGroupType,
    Outlet, City, Zone,
    ServiceCategory, Service,
    StoreService, CanonicalService, ServiceCategoryPhase1,
    Professional, ProfessionalShift, ProfessionalLinkStatus,
    StaffAvailability, Role, normalize_e164
)

User = get_user_model()

class Command(BaseCommand):
    help = "Sets up or updates a complete live pilot salon (Store, Outlet, Categories, Services, Staff, Shifts, Store Manager)."

    def add_arguments(self, parser):
        parser.add_argument('--name', type=str, default='NearbyMe Signature Studio', help='Store Name')
        parser.add_argument('--phone', type=str, default='+919845012345', help='Store Phone')
        parser.add_argument('--address', type=str, default='100ft Road, Indiranagar, Bengaluru', help='Store Address')
        parser.add_argument('--city', type=str, default='Bengaluru', help='City Name')
        parser.add_argument('--zone', type=str, default='Indiranagar', help='Commercial Zone')
        parser.add_argument('--manager-email', type=str, default='manager@nearbyme.com', help='Store Manager Login Email')
        parser.add_argument('--manager-pass', type=str, default='password123', help='Store Manager Password')

    def handle(self, *args, **options):
        store_name = options['name']
        phone = options['phone']
        address = options['address']
        city_name = options['city']
        zone_name = options['zone']
        mgr_email = options['manager_email']
        mgr_pass = options['manager_pass']

        self.stdout.write(self.style.NOTICE(f"Setting up pilot salon: '{store_name}' in {city_name}..."))

        # 1. City & Zone
        city, _ = City.objects.get_or_create(name=city_name, defaults={'state': 'Karnataka', 'is_active': True})
        zone, _ = Zone.objects.get_or_create(city=city, name=zone_name, defaults={'is_active': True})

        # 2. Business & Brand
        from django.utils.text import slugify
        biz_slug = slugify(store_name)
        business, _ = Business.objects.get_or_create(
            name=f"{store_name} Group",
            defaults={
                'business_type': BusinessType.SALON,
                'status': BusinessStatus.ACTIVE,
                'email': f"{biz_slug}@nearbyme.com",
                'phone': phone
            }
        )
        brand, _ = Brand.objects.get_or_create(
            business=business,
            name=store_name,
            defaults={'status': BrandStatus.ACTIVE}
        )

        # 3. StoreGroup & Outlet (Phase 1)
        sg, _ = StoreGroup.objects.get_or_create(
            name=store_name,
            defaults={
                'legal_name': f"{store_name} Pvt Ltd",
                'business_type': StoreGroupType.BOTH,
                'status': StoreGroupStatus.ACTIVE,
                'owner_name': 'Pilot Salon Partner',
                'owner_phone': phone,
                'owner_email': mgr_email,
            }
        )
        outlet, _ = Outlet.objects.get_or_create(
            store_group=sg,
            name=f"{store_name} ({zone_name})",
            defaults={
                'city': city,
                'zone': zone,
                'address_line': address,
                'pincode': '560038',
                'phone': phone,
                'status': 'active',
                'opening_time': '09:00:00',
                'closing_time': '21:00:00',
            }
        )

        # 4. Store (Legacy + Bridge to Outlet)
        working_hours = {
            "mon": "09:00-21:00", "tue": "09:00-21:00", "wed": "09:00-21:00",
            "thu": "09:00-21:00", "fri": "09:00-21:00", "sat": "09:00-21:00", "sun": "09:00-21:00"
        }
        store, _ = Store.objects.get_or_create(
            name=store_name,
            defaults={
                'business': business,
                'brand': brand,
                'outlet': outlet,
                'address': address,
                'contact_number': phone,
                'email': mgr_email,
                'working_hours': working_hours,
                'status': StoreStatus.ACTIVE,
                'is_premium_listing': True,
            }
        )
        if store.outlet_id != outlet.id or store.status != StoreStatus.ACTIVE:
            store.outlet = outlet
            store.status = StoreStatus.ACTIVE
            store.address = address
            store.contact_number = phone
            store.working_hours = working_hours
            store.save()

        # 5. Service Categories & Real Services
        services_data = [
            ("Hair & Styling", [
                ("Men's Precision Haircut", 30, 450, "Full precision scissor trim, styling & hair wash."),
                ("Beard Sculpting & Trim", 20, 250, "Line-up, hot towel conditioning & beard oil styling."),
                ("Women's Signature Blowdry & Style", 45, 950, "Shampoo, deep conditioning and radiant blowout."),
                ("Global Hair Colouring (L'Oreal)", 90, 2800, "Ammonia-free vibrant full-coverage hair color."),
            ]),
            ("Skin & Facials", [
                ("Hydrating Glow Brightening Facial", 45, 1200, "Deep pore cleansing, fruit mask and hydration serum."),
                ("Express Anti-Tan Detan Therapy", 30, 650, "Instant tan removal & soothing aloe-vera massage."),
            ]),
            ("Massage & Spa", [
                ("Stress Relief Head & Shoulder Massage", 30, 500, "Warm herbal oil acupressure therapy."),
                ("Swedish Full Body Relaxation Massage", 60, 2200, "Full body calming massage for muscle tension."),
                ("Deep Tissue Rejuvenation Spa", 90, 2800, "Therapeutic firm pressure session with essential oils."),
                ("Luxury Foot Reflexology & Pedicure", 45, 750, "Dead skin scrub, massage and nail cuticle care."),
            ])
        ]

        total_svcs = 0
        from django.utils.text import slugify
        for cat_name, items in services_data:
            cat, _ = ServiceCategory.objects.get_or_create(business=business, name=cat_name, defaults={'is_active': True})
            cat_p1, _ = ServiceCategoryPhase1.objects.get_or_create(
                slug=slugify(cat_name),
                defaults={'name': cat_name, 'applies_to': 'both'}
            )
            for s_name, duration, price, desc in items:
                svc, _ = Service.objects.get_or_create(
                    category=cat,
                    name=s_name,
                    defaults={'duration_minutes': duration, 'price': price, 'is_active': True}
                )
                from django.utils.text import slugify
                svc_slug = slugify(s_name)
                canon, _ = CanonicalService.objects.get_or_create(
                    slug=svc_slug,
                    defaults={'category': cat_p1, 'name': s_name, 'default_duration_min': duration, 'skill_tag': cat_name.lower().replace(' ', '_')}
                )
                StoreService.objects.get_or_create(
                    store_group=sg,
                    canonical_service=canon,
                    name=s_name,
                    defaults={
                        'default_price_paise': price * 100,
                        'duration_min': duration,
                        'is_active_in_store': True
                    }
                )
                total_svcs += 1

        self.stdout.write(self.style.SUCCESS(f"✔ Added {len(services_data)} Categories and {total_svcs} Services."))

        # 6. Staff / Therapists
        staff_data = [
            ("Anita", "Sharma", "anita.therapist@nearbyme.in", "+919845011111"),
            ("Vikram", "Singh", "vikram.therapist@nearbyme.in", "+919845022222"),
        ]

        for first, last, s_email, s_phone in staff_data:
            u, _ = User.objects.get_or_create(
                email=s_email,
                defaults={
                    'username': s_email,
                    'first_name': first,
                    'last_name': last,
                    'phone': s_phone,
                    'role': Role.THERAPIST,
                    'store': store,
                    'brand': brand,
                    'is_active': True,
                }
            )
            u.set_password('password123')
            u.store = store
            u.save()

            # Create ProfessionalAccount & Professional link
            from apps.core.models import ProfessionalAccount
            prof_acc, _ = ProfessionalAccount.objects.get_or_create(
                user=u,
                defaults={'name': f"{first} {last}", 'phone_e164': normalize_e164(s_phone)}
            )
            prof, _ = Professional.objects.get_or_create(
                outlet=outlet,
                email=s_email,
                defaults={
                    'display_name': f"{first} {last}",
                    'phone_e164': normalize_e164(s_phone),
                    'is_bookable': True,
                    'link_status': ProfessionalLinkStatus.ACCEPTED,
                    'user_account': prof_acc,
                    'store_group': sg,
                }
            )

            # Weekly Shifts (Monday to Sunday, 09:00 - 21:00)
            for day_idx in range(7):
                StaffAvailability.objects.get_or_create(
                    staff=u,
                    day_of_week=day_idx,
                    defaults={
                        'start_time': time(9, 0),
                        'end_time': time(21, 0),
                        'is_available': True
                    }
                )
                from django.utils import timezone
                ProfessionalShift.objects.get_or_create(
                    professional=prof,
                    outlet=outlet,
                    weekday=day_idx,
                    defaults={
                        'start_time': time(9, 0),
                        'end_time': time(21, 0),
                        'effective_from': timezone.now().date(),
                    }
                )

        self.stdout.write(self.style.SUCCESS(f"✔ Configured {len(staff_data)} Therapists with weekly shifts (Mon-Sun 09:00-21:00)."))

        # 7. Store Manager User
        mgr, _ = User.objects.get_or_create(
            email=mgr_email,
            defaults={
                'username': mgr_email,
                'first_name': 'Store',
                'last_name': 'Manager',
                'role': Role.STORE_ADMIN,
                'store': store,
                'brand': brand,
                'outlet': outlet,
                'is_active': True,
            }
        )
        mgr.set_password(mgr_pass)
        mgr.store = store
        mgr.brand = brand
        mgr.outlet = outlet
        mgr.role = Role.STORE_ADMIN
        mgr.save()

        self.stdout.write(self.style.SUCCESS(f"✔ Store Manager ready: {mgr_email} / {mgr_pass}"))
        self.stdout.write(self.style.SUCCESS("\n🎉 PILOT SALON SETUP COMPLETE!"))
        self.stdout.write(self.style.NOTICE(f"Store ID: {store.id} | Name: {store.name} | Outlet ID: {outlet.id}"))

