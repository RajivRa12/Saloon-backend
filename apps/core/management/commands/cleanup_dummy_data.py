import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.core.models import (
    Store, StoreGroup, Outlet, ServiceCategory, Service,
    Business, Brand, City, Zone, StorePublicProfile, CityMarketplaceFlag
)

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Removes old dummy/mock stores and ensures clean real stores, store groups, and services are active in Bengaluru and Chennai."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Starting database cleanup of dummy/mock data..."))

        # 1. Target dummy stores to delete
        DUMMY_STORE_NAMES = [
            "Bodycraft Luxury Spa",
            "Green Trends Unisex Styling",
            "NearbyMe Partner Studio (POS Branch)",
            "Lumière Salon & Spa",
            "Serendipity Med-Spa",
            "Meghavi Luxury Wellness",
            "Truefitt & Hill",
            "World Spa",
        ]

        deleted_stores_count = 0
        for name in DUMMY_STORE_NAMES:
            for s in Store.objects.filter(name__icontains=name):
                self.stdout.write(f"Deleting dummy store: {s.name} (id={s.id})")
                s.delete()
                deleted_stores_count += 1

        # Also delete old dummy store groups that aren't the real ones
        KEEP_GROUP_NAMES = [
            "The New Look Men’s Saloon Group",
            "Roots Mens Salon Alpha Group",
            "The New Look Mens Saloon Group",
            "Roots Mens Salon Alpha",
        ]

        for sg in StoreGroup.objects.all():
            if not any(k.lower() in sg.name.lower() for k in KEEP_GROUP_NAMES):
                self.stdout.write(f"Deleting dummy store group: {sg.name}")
                Outlet.objects.filter(store_group=sg).delete()
                sg.delete()

        self.stdout.write(self.style.SUCCESS(f"✔ Deleted {deleted_stores_count} old dummy stores."))

        # Clear old dummy admin audit logs
        from django.contrib.admin.models import LogEntry
        LogEntry.objects.all().delete()
        self.stdout.write(self.style.SUCCESS("✔ Cleaned historical dummy admin log entries."))

        # 2. Setup Cities, Zones & Enable Marketplace Flags (Bengaluru & Chennai)
        cities_config = [
            ("Bengaluru", "Karnataka", ["JP Nagar", "Indiranagar", "Koramangala", "HSR Layout", "Whitefield", "Lavelle Road"]),
            ("Chennai", "Tamil Nadu", ["Nungambakkam", "Alwarpet", "Anna Nagar", "Adyar", "T. Nagar"]),
        ]

        city_map = {}
        zone_map = {}

        for c_name, c_state, z_list in cities_config:
            city_obj, _ = City.objects.get_or_create(
                name=c_name,
                defaults={"state": c_state, "is_active": True}
            )
            if not city_obj.is_active:
                city_obj.is_active = True
                city_obj.save()
            city_map[c_name] = city_obj

            CityMarketplaceFlag.objects.update_or_create(
                city=city_obj,
                defaults={
                    "is_public": True,
                    "min_store_threshold": 1,
                    "enabled_at": timezone.now(),
                }
            )

            for z_name in z_list:
                z, _ = Zone.objects.get_or_create(city=city_obj, name=z_name, defaults={"is_active": True})
                zone_map[f"{c_name}:{z_name}"] = z

        working_hours_default = {
            "mon": "09:00-21:00",
            "tue": "09:00-21:00",
            "wed": "09:00-21:00",
            "thu": "09:00-21:00",
            "fri": "09:00-21:00",
            "sat": "09:00-21:00",
            "sun": "09:00-21:00",
        }

        # 3. Setup The New Look Men’s Saloon Group
        sg_newlook, _ = StoreGroup.objects.get_or_create(
            name="The New Look Men’s Saloon Group",
            defaults={
                "owner_name": "Salon Owner",
                "owner_phone": "+919731212730",
                "owner_email": "owner@newlooksalon.in",
                "status": "active",
                "business_type": "salon",
            }
        )
        sg_newlook.status = "active"
        sg_newlook.save()

        biz_newlook, _ = Business.objects.get_or_create(
            name="The New Look Men’s Saloon Group",
            defaults={
                "business_type": "SALON",
                "email": "owner@newlooksalon.in",
                "phone": "+919731212730",
                "address": "JP Nagar 7th Phase, Bengaluru",
                "state": "Karnataka",
                "city": "Bengaluru",
                "status": "APPROVED",
            }
        )
        brand_newlook, _ = Brand.objects.get_or_create(
            name="The New Look Men’s Saloon",
            business=biz_newlook,
            defaults={"status": "APPROVED"}
        )

        # 3A. New Look - Bengaluru Outlet & Store
        outlet_newlook_blr, _ = Outlet.objects.get_or_create(
            store_group=sg_newlook,
            name="The New Look Men’s Saloon – JP Nagar",
            defaults={
                "city": city_map["Bengaluru"],
                "zone": zone_map.get("Bengaluru:JP Nagar"),
                "address_line": "JP Nagar 7th Phase, Bengaluru",
                "pincode": "560078",
                "phone": "+919731212730",
                "status": "active",
                "opening_time": "09:00:00",
                "closing_time": "21:00:00",
                "invoice_prefix": "NL01",
                "lat": 12.9063,
                "lng": 77.5857,
            }
        )
        outlet_newlook_blr.city = city_map["Bengaluru"]
        outlet_newlook_blr.status = "active"
        outlet_newlook_blr.save()

        store_newlook_blr, _ = Store.objects.get_or_create(
            name="The New Look Men’s Saloon",
            defaults={
                "business": biz_newlook,
                "brand": brand_newlook,
                "outlet": outlet_newlook_blr,
                "contact_number": "+919731212730",
                "address": "JP Nagar 7th Phase, Bengaluru",
                "status": "ACTIVE",
                "working_hours": working_hours_default,
                "is_premium_listing": True,
            }
        )
        store_newlook_blr.outlet = outlet_newlook_blr
        store_newlook_blr.status = "ACTIVE"
        store_newlook_blr.working_hours = working_hours_default
        store_newlook_blr.save()

        StorePublicProfile.objects.update_or_create(
            store=store_newlook_blr,
            defaults={
                "slug": "the-new-look-mens-saloon",
                "about": "Premier grooming destination for modern men. Expert haircuts, styling, beard detailing and head massages in JP Nagar, Bengaluru.",
                "is_microsite_live": True,
                "marketplace_public": True,
            }
        )

        # 3B. New Look - Chennai Outlet & Store
        outlet_newlook_chn, _ = Outlet.objects.get_or_create(
            store_group=sg_newlook,
            name="The New Look Men’s Saloon – Anna Nagar",
            defaults={
                "city": city_map["Chennai"],
                "zone": zone_map.get("Chennai:Anna Nagar"),
                "address_line": "2nd Avenue, Anna Nagar, Chennai",
                "pincode": "600040",
                "phone": "+919731212730",
                "status": "active",
                "opening_time": "09:00:00",
                "closing_time": "21:00:00",
                "invoice_prefix": "NL02",
                "lat": 13.0850,
                "lng": 80.2101,
            }
        )
        outlet_newlook_chn.city = city_map["Chennai"]
        outlet_newlook_chn.status = "active"
        outlet_newlook_chn.save()

        store_newlook_chn, _ = Store.objects.get_or_create(
            name="The New Look Men’s Saloon (Anna Nagar)",
            defaults={
                "business": biz_newlook,
                "brand": brand_newlook,
                "outlet": outlet_newlook_chn,
                "contact_number": "+919731212730",
                "address": "2nd Avenue, Anna Nagar, Chennai",
                "status": "ACTIVE",
                "working_hours": working_hours_default,
                "is_premium_listing": True,
            }
        )
        store_newlook_chn.outlet = outlet_newlook_chn
        store_newlook_chn.status = "ACTIVE"
        store_newlook_chn.working_hours = working_hours_default
        store_newlook_chn.save()

        StorePublicProfile.objects.update_or_create(
            store=store_newlook_chn,
            defaults={
                "slug": "the-new-look-mens-saloon-chennai",
                "about": "Top-tier gentlemen's haircuts, beard contouring, facials and hair spa in Anna Nagar, Chennai.",
                "is_microsite_live": True,
                "marketplace_public": True,
            }
        )

        # 4. Setup Roots Mens Salon Alpha Group
        sg_roots, _ = StoreGroup.objects.get_or_create(
            name="Roots Mens Salon Alpha Group",
            defaults={
                "owner_name": "Roots Management",
                "owner_phone": "+917021795120",
                "owner_email": "contact@rootssalon.in",
                "status": "active",
                "business_type": "salon",
            }
        )
        sg_roots.status = "active"
        sg_roots.save()

        biz_roots, _ = Business.objects.get_or_create(
            name="Roots Mens Salon Alpha Group",
            defaults={
                "business_type": "SALON",
                "email": "contact@rootssalon.in",
                "phone": "+917021795120",
                "address": "Indiranagar 100ft Road, Bengaluru",
                "state": "Karnataka",
                "city": "Bengaluru",
                "status": "APPROVED",
            }
        )
        brand_roots, _ = Brand.objects.get_or_create(
            name="Roots Mens Salon Alpha",
            business=biz_roots,
            defaults={"status": "APPROVED"}
        )

        # 4A. Roots - Bengaluru Outlet & Store
        outlet_roots_blr, _ = Outlet.objects.get_or_create(
            store_group=sg_roots,
            name="Roots Men’s Salon – Alpha",
            defaults={
                "city": city_map["Bengaluru"],
                "zone": zone_map.get("Bengaluru:Indiranagar"),
                "address_line": "Indiranagar 100ft Road, Bengaluru",
                "pincode": "560038",
                "phone": "+917021795120",
                "status": "active",
                "opening_time": "09:00:00",
                "closing_time": "21:00:00",
                "invoice_prefix": "RT01",
                "lat": 12.9784,
                "lng": 77.6408,
            }
        )
        outlet_roots_blr.city = city_map["Bengaluru"]
        outlet_roots_blr.status = "active"
        outlet_roots_blr.save()

        store_roots_blr, _ = Store.objects.get_or_create(
            name="Roots Mens Salon Alpha",
            defaults={
                "business": biz_roots,
                "brand": brand_roots,
                "outlet": outlet_roots_blr,
                "contact_number": "+917021795120",
                "address": "Indiranagar 100ft Road, Bengaluru",
                "status": "ACTIVE",
                "working_hours": working_hours_default,
                "is_premium_listing": True,
            }
        )
        store_roots_blr.outlet = outlet_roots_blr
        store_roots_blr.status = "ACTIVE"
        store_roots_blr.working_hours = working_hours_default
        store_roots_blr.save()

        StorePublicProfile.objects.update_or_create(
            store=store_roots_blr,
            defaults={
                "slug": "roots-mens-salon-alpha",
                "about": "Bespoke gentlemen's grooming experience in Indiranagar. Premium fades, classic shaves, revitalizing hair spa and facials.",
                "is_microsite_live": True,
                "marketplace_public": True,
            }
        )

        # 4B. Roots - Chennai Outlet & Store
        outlet_roots_chn, _ = Outlet.objects.get_or_create(
            store_group=sg_roots,
            name="Roots Men’s Salon – Nungambakkam",
            defaults={
                "city": city_map["Chennai"],
                "zone": zone_map.get("Chennai:Nungambakkam"),
                "address_line": "Nungambakkam High Road, Chennai",
                "pincode": "600034",
                "phone": "+919840256789",
                "status": "active",
                "opening_time": "09:00:00",
                "closing_time": "21:00:00",
                "invoice_prefix": "RT02",
                "lat": 13.0604,
                "lng": 80.2443,
            }
        )
        outlet_roots_chn.city = city_map["Chennai"]
        outlet_roots_chn.status = "active"
        outlet_roots_chn.save()

        store_roots_chn, _ = Store.objects.get_or_create(
            name="Roots Men’s Salon (Nungambakkam)",
            defaults={
                "business": biz_roots,
                "brand": brand_roots,
                "outlet": outlet_roots_chn,
                "contact_number": "+919840256789",
                "address": "Nungambakkam High Road, Chennai",
                "status": "ACTIVE",
                "working_hours": working_hours_default,
                "is_premium_listing": True,
            }
        )
        store_roots_chn.outlet = outlet_roots_chn
        store_roots_chn.status = "ACTIVE"
        store_roots_chn.working_hours = working_hours_default
        store_roots_chn.save()

        StorePublicProfile.objects.update_or_create(
            store=store_roots_chn,
            defaults={
                "slug": "roots-mens-salon-chennai",
                "about": "Signature grooming salon in Nungambakkam, Chennai. Precision haircuts, organic beard therapy, detox facials.",
                "is_microsite_live": True,
                "marketplace_public": True,
            }
        )

        # 5. Clean Services Setup for New Look
        NEWLOOK_SERVICES = [
            ("Normal Haircut", 250.00, 30),
            ("Stylish Haircut", 350.00, 35),
            ("Beard Trim", 100.00, 15),
            ("Clean Shave", 150.00, 20),
            ("Hair Wash", 150.00, 15),
            ("Head Massage", 300.00, 30),
            ("Hair Spa", 350.00, 45),
            ("Hair Colour", 1000.00, 60),
            ("Haircut + Beard", 250.00, 45),
        ]

        for s_name, price, dur in NEWLOOK_SERVICES:
            cat, _ = ServiceCategory.objects.get_or_create(
                name=s_name,
                business=biz_newlook,
                defaults={"is_active": True}
            )
            svc, _ = Service.objects.get_or_create(
                name=s_name,
                category=cat,
                store_group=sg_newlook,
                defaults={
                    "price": price,
                    "duration_minutes": dur,
                    "is_active": True,
                }
            )
            svc.price = price
            svc.duration_minutes = dur
            svc.is_active = True
            svc.store_group = sg_newlook
            svc.save()

        # Clean Services Setup for Roots
        ROOTS_SERVICES = [
            ("Normal Haircut", 300.00, 30),
            ("Stylish Haircut", 450.00, 40),
            ("Beard Trim", 150.00, 20),
            ("Clean Shave", 200.00, 20),
            ("Hair Spa", 600.00, 45),
            ("Head Massage", 400.00, 30),
            ("Haircut + Beard", 400.00, 45),
        ]

        for s_name, price, dur in ROOTS_SERVICES:
            cat, _ = ServiceCategory.objects.get_or_create(
                name=s_name,
                business=biz_roots,
                defaults={"is_active": True}
            )
            svc, _ = Service.objects.get_or_create(
                name=s_name,
                category=cat,
                store_group=sg_roots,
                defaults={
                    "price": price,
                    "duration_minutes": dur,
                    "is_active": True,
                }
            )
            svc.price = price
            svc.duration_minutes = dur
            svc.is_active = True
            svc.store_group = sg_roots
            svc.save()

        self.stdout.write(self.style.SUCCESS("✔ Clean stores, outlets, categories, and services in Bengaluru & Chennai synchronized successfully!"))
