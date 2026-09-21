import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.core.models import User, CustomerProfile, Coupon, Store
from django.utils import timezone
from datetime import timedelta

# Create dummy customer
user, _ = User.objects.get_or_create(email="customer@nearbyme.com", defaults={"username": "customer@nearbyme.com", "first_name": "Test", "last_name": "Customer", "phone_number": "1234567890"})
if _:
    user.set_password("password123")
    user.save()
profile, _ = CustomerProfile.objects.get_or_create(user=user)

# Create a coupon
store = Store.objects.first()
if store:
    Coupon.objects.get_or_create(
        code="WELCOME20",
        defaults={
            "store": store,
            "discount_type": "PERCENTAGE",
            "discount_value": 20.0,
            "is_active": True,
            "start_date": timezone.now(),
            "end_date": timezone.now() + timedelta(days=30)
        }
    )
print("Customer seed complete! User: customer@nearbyme.com / password123")
