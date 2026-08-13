from datetime import timedelta
from django.utils import timezone
from rest_framework.permissions import BasePermission
from rest_framework.exceptions import AuthenticationFailed
from apps.core.models import Role, ImpersonationSession, ImpersonationSessionMode, Store
def check_impersonation_session(request, permission_obj):
    token_id = request.headers.get('X-Impersonation-Token') or request.META.get('HTTP_X_IMPERSONATION_TOKEN')
    if not token_id:
        return None
    try:
        session = ImpersonationSession.objects.get(id=token_id, ended_at__isnull=True)
    except (ImpersonationSession.DoesNotExist, ValueError):
        raise AuthenticationFailed("Impersonation session is invalid, expired, or has been terminated.")
    if (timezone.now() - session.started_at) > timedelta(minutes=60):
        session.ended_at = timezone.now()
        session.save(update_fields=['ended_at'])
        raise AuthenticationFailed("Impersonation session expired after 60 minutes.")
    if session.mode == ImpersonationSessionMode.READ_ONLY and request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
        permission_obj.message = "403 Forbidden: Read-only impersonation token rejects every write endpoint server-side."
        return False
    request.impersonation_session = session
    if request.user and request.user.is_authenticated:
        if not getattr(request.user, 'store_id', None) and not getattr(request.user, 'store', None):
            store_match = Store.objects.first()
            if store_match:
                request.user.store = store_match
                request.user.store_id = store_match.id
    return True
class IsStoreStaff(BasePermission):
    message = "You must be assigned to a Store to access the Store ERP."
    def has_permission(self, request, view):
        imp_status = check_impersonation_session(request, self)
        if imp_status is not None:
            return imp_status
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role in [Role.STORE_ADMIN, Role.RECEPTIONIST, Role.THERAPIST] and
            request.user.store_id is not None
        )
class IsOutletStaff(BasePermission):
    message = "You must be assigned to an Outlet to access the booking engine."
    def has_permission(self, request, view):
        imp_status = check_impersonation_session(request, self)
        if imp_status is not None:
            return imp_status
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role in [Role.STORE_ADMIN, Role.RECEPTIONIST, Role.THERAPIST] and
            request.user.outlet_id is not None
        )
class IsStoreManagerOrReceptionist(BasePermission):
    message = "You do not have permission to perform this administrative action."
    def has_permission(self, request, view):
        imp_status = check_impersonation_session(request, self)
        if imp_status is not None:
            return imp_status
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role in [Role.STORE_ADMIN, Role.RECEPTIONIST] and
            request.user.store_id is not None
        )
