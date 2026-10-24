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

