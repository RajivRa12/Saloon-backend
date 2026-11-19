from rest_framework.permissions import BasePermission
from apps.core.models import Role

class IsCustomer(BasePermission):
    def has_permission(self, request, view):
        # Allow any authenticated user (customer, store owner testing customer flow, staff)
        return bool(request.user and request.user.is_authenticated)

