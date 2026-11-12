from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.text import slugify
from .models import Store, StorePublicProfile
@receiver(post_save, sender=Store)
def create_store_public_profile(sender, instance, created, **kwargs):
    """Every store gets a microsite the moment it exists — legacy Store has
    no separate approval gate (StoreStatus defaults to ACTIVE on creation),
    so 'the moment it's approved' is 'the moment it's created' here. See
    customer-app-build-guide.pdf section 2."""
    if not created or hasattr(instance, 'public_profile'):
        return
    base_slug = slugify(instance.name) or f"store-{instance.id}"
    slug = base_slug
    suffix = 2
    while StorePublicProfile.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    StorePublicProfile.objects.create(store=instance, slug=slug)

@receiver(post_save, sender=Store)
def auto_provision_store_infrastructure(sender, instance, created, **kwargs):
    """When a Store is created without an Outlet or Business, auto-provision
    the underlying StoreGroup, Outlet, Business, and Brand so that admins
    only need to create a Store directly without needing to manually configure 4 extra tables."""
    if not created:
        return
    try:
        from .models import (
            Business, BusinessType, BusinessStatus, Brand, BrandStatus,
            StoreGroup, StoreGroupStatus, StoreGroupType, Outlet, City, Zone,
            PlatformSubscriptionPlan, StoreSubscription
        )
        from django.utils.text import slugify
        from django.utils import timezone
        from datetime import timedelta

        updated_fields = []
        
        # 1. Business & Brand
        if not instance.business_id:
            biz_name = f"{instance.name} Group"
            biz, _ = Business.objects.get_or_create(
                name=biz_name,
                defaults={
                    'business_type': BusinessType.SALON,
                    'status': BusinessStatus.ACTIVE,
                    'email': instance.email or f"{slugify(instance.name)}@nearbyme.local",
                    'phone': instance.contact_number or "+919876543210"
                }
            )
            instance.business = biz
            updated_fields.append('business')

        if not instance.brand_id and instance.business:
            brand, _ = Brand.objects.get_or_create(
                business=instance.business,
                name=instance.name,
                defaults={'status': BrandStatus.ACTIVE}
            )
            instance.brand = brand
            updated_fields.append('brand')

        # 2. StoreGroup & Outlet
        if not instance.outlet_id:
            sg, _ = StoreGroup.objects.get_or_create(
                name=instance.name,
                defaults={
                    'legal_name': f"{instance.name} Pvt Ltd",
                    'business_type': StoreGroupType.BOTH,
                    'status': StoreGroupStatus.ACTIVE,
                    'owner_name': 'Salon Partner',
                    'owner_phone': instance.contact_number or '+919876543210',
                    'owner_email': instance.email or f"{slugify(instance.name)}@nearbyme.local",
                }
            )
            
            city = City.objects.filter(name__iexact='Bengaluru').first() or City.objects.first()
            zone = Zone.objects.filter(city=city).first() if city else None
            
            outlet, _ = Outlet.objects.get_or_create(
                store_group=sg,
                name=instance.name,
                defaults={
                    'city': city,
                    'zone': zone,
                    'address_line': instance.address or 'City Center',
                    'pincode': '560001',
                    'phone': instance.contact_number or '+919876543210',
                    'status': 'active',
                    'opening_time': '09:00:00',
                    'closing_time': '21:00:00',
                }
            )
            instance.outlet = outlet
            updated_fields.append('outlet')

        if updated_fields:
            instance.save(update_fields=updated_fields)

        # 3. Store Subscription (Pro Plan so Store Admin never gets 403)
        if not hasattr(instance, 'platform_subscription'):
            plan, _ = PlatformSubscriptionPlan.objects.get_or_create(
                name='Soft Launch Unlimited Partner',
                defaults={
                    'monthly_price': 0,
                    'commission_percent': 0,
                    'includes_crm': True,
                    'includes_analytics': True,
                    'includes_ai_assistant': True,
                    'includes_premium_listing': True,
                    'is_active': True,
                }
            )
            StoreSubscription.objects.get_or_create(
                store=instance,
                defaults={
                    'plan': plan,
                    'status': 'ACTIVE',
                    'current_period_end': timezone.now() + timedelta(days=365),
                }
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Failed to auto-provision store infrastructure: %s", e)

from .models import Service

@receiver(post_save, sender=Service)
def auto_sync_service_to_store_service(sender, instance, created, **kwargs):
    """When a Service is added in Django admin, automatically mirror it to StoreService
    so both legacy menu and Phase1 booking engine work seamlessly."""
    try:
        from .models import StoreService, StoreGroup, Store
        store_group = instance.store_group
        if not store_group and instance.category and instance.category.business:
            store = Store.objects.filter(business=instance.category.business).first()
            if store and store.outlet and store.outlet.store_group:
                store_group = store.outlet.store_group
            else:
                store_group = StoreGroup.objects.filter(name=instance.category.business.name).first()
        if not store_group:
            store_group = StoreGroup.objects.first()

        if store_group:
            price_paise = int(round(float(instance.price or 0) * 100))
            StoreService.objects.update_or_create(
                store_group=store_group,
                name=instance.name,
                defaults={
                    'default_price_paise': price_paise if price_paise > 0 else 50000,
                    'duration_min': instance.duration_minutes or 30,
                    'is_active_in_store': instance.is_active,
                }
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Failed to sync service to store service: %s", e)

from django.contrib.admin.models import LogEntry

@receiver(post_save, sender=LogEntry)
def mirror_admin_log_to_audit_log(sender, instance, created, **kwargs):
    """Mirror Django admin actions (add, change, delete) into the universal AuditLog table (DJ-04)."""
    if not created:
        return
    try:
        from .models import AuditLog
        content_type = instance.content_type
        model_name = content_type.model if content_type else "unknown"
        if model_name.lower() in ("auditlog", "session", "logentry"):
            return

        action_map = {
            1: "django_admin_create",
            2: "django_admin_update",
            3: "django_admin_delete",
        }
        action = action_map.get(instance.action_flag, "django_admin_action")
        user = instance.user
        actor_id = str(user.id) if user else "system"
        actor_label = (user.get_full_name() or user.email) if user else "System Admin"

        AuditLog.objects.create(
            actor_id=actor_id,
            actor_type="internal_user",
            action=action,
            entity_type=model_name,
            entity_id=str(instance.object_id),
            before=None,
            after={
                "object_repr": instance.object_repr,
                "change_message": instance.get_change_message(),
                "actor": actor_label,
                "source": "django_admin",
            },
        )
    except Exception:
        pass




