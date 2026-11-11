import hashlib
import logging
import os
import random
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from apps.core.models import PhoneOTP, Role, normalize_e164
from .serializers import RegisterSerializer, UserSerializer
User = get_user_model()
logger = logging.getLogger(__name__)
class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = User.USERNAME_FIELD
    def validate(self, attrs):
        data = super().validate(attrs)
        serializer = UserSerializer(self.user)
        data['user'] = serializer.data
        return data
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['role'] = user.role
        token['email'] = user.email
        if user.brand:
            token['brand_id'] = str(user.brand.id)
        if user.store:
            token['store_id'] = str(user.store.id)
        return token
class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'
class ChangePasswordView(APIView):
    """Shared account action for any authenticated role (customer, staff,
    therapist) — distinct from apps.store_erp's ERP-scoped equivalent, which
    is gated to store-staff roles only."""
    permission_classes = [IsAuthenticated]
    def post(self, request):
        current_password = request.data.get('current_password')
        new_password = request.data.get('new_password')
        if not current_password or not new_password:
            return Response({"message": "current_password and new_password are required."}, status=400)
        if len(new_password) < 6:
            return Response({"message": "New password must be at least 6 characters."}, status=400)
        if not request.user.check_password(current_password):
            return Response({"message": "Current password is incorrect."}, status=400)
        request.user.set_password(new_password)
        request.user.save(update_fields=['password'])
        return Response({"message": "Password changed successfully."}, status=200)
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = (AllowAny,)
    serializer_class = RegisterSerializer
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        user_serializer = UserSerializer(user)
        return Response({
            "message": "User registered successfully",
            "user": user_serializer.data
        }, status=status.HTTP_201_CREATED)
OTP_TTL_MINUTES = 5
OTP_RESEND_COOLDOWN_SECONDS = 30
MAX_OTP_ATTEMPTS = 5
PILOT_MODE = os.environ.get('PILOT_MODE', 'True').lower() in ('true', '1', 'yes')
PILOT_DEMO_OTP = os.environ.get('PILOT_DEMO_OTP', '123456')

def _hash_otp(phone_e164, code):
    return hashlib.sha256(f"{phone_e164}:{code}:{settings.SECRET_KEY}".encode()).hexdigest()
class RequestOTPView(APIView):
    """Phone-is-the-account: no signup form, no password. Customer app rule 26."""
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp'
    def post(self, request):
        phone = request.data.get('phone')
        if not phone:
            return Response({"message": "phone is required."}, status=400)
        phone_e164 = normalize_e164(phone)
        recent = PhoneOTP.objects.filter(phone_e164=phone_e164).order_by('-created_at').first()
        if recent and (timezone.now() - recent.created_at) < timedelta(seconds=OTP_RESEND_COOLDOWN_SECONDS):
            wait = OTP_RESEND_COOLDOWN_SECONDS - int((timezone.now() - recent.created_at).total_seconds())
            return Response({"message": f"Please wait {wait}s before requesting another code."}, status=429)
        code = f"{random.randint(0, 999999):06d}"
        
        # In Pilot mode, any real customer phone number can log in with PILOT_DEMO_OTP (123456)
        # without requiring a paid SMS gateway. When PILOT_MODE=False, real SMS is dispatched.
        if PILOT_MODE:
            code = PILOT_DEMO_OTP

        PhoneOTP.objects.create(
            phone_e164=phone_e164,
            code_hash=_hash_otp(phone_e164, code),
            expires_at=timezone.now() + timedelta(minutes=OTP_TTL_MINUTES),
        )

        payload = {"phone": phone_e164, "expires_in": OTP_TTL_MINUTES * 60}

        if PILOT_MODE:
            if settings.DEBUG:
                payload["dev_otp"] = code
            return Response(payload, status=200)

        from .sms import send_otp_sms, SMSNotConfigured, SMSDeliveryError
        try:
            send_otp_sms(phone_e164, code)
        except SMSNotConfigured:
            if settings.DEBUG:
                print(f"[OTP DEV] {phone_e164} -> {code} (expires in {OTP_TTL_MINUTES}m)")
                payload["dev_otp"] = code
                return Response(payload, status=200)
            logger.error("SMS service is not configured in production.")
            return Response({"message": "SMS delivery service is not configured. Please contact support."}, status=503)
        except SMSDeliveryError as e:
            if settings.DEBUG:
                print(f"[SMS FAILED DEV] Falling back to dev_otp in DEBUG mode. Error: {e}")
                payload["dev_otp"] = code
                return Response(payload, status=200)
            logger.error(f"Failed to send SMS to {phone_e164}: {e}")
            return Response({"message": "Failed to deliver OTP SMS. Please try again in a moment."}, status=502)

        return Response(payload, status=200)
class VerifyOTPView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'
    def post(self, request):
        phone = request.data.get('phone')
        code = (request.data.get('code') or request.data.get('otp') or '').strip()
        if not phone or not code:
            return Response({"message": "phone and code are required."}, status=400)
        phone_e164 = normalize_e164(phone)
        otp = PhoneOTP.objects.filter(phone_e164=phone_e164, is_used=False).order_by('-created_at').first()
        if not otp or otp.expires_at < timezone.now():
            return Response({"message": "That code has expired. Request a new one."}, status=400)
        if otp.attempts >= MAX_OTP_ATTEMPTS:
            return Response({"message": "Too many attempts. Request a new code."}, status=400)
        if otp.code_hash != _hash_otp(phone_e164, code):
            otp.attempts += 1
            otp.save(update_fields=['attempts'])
            return Response({"message": "Incorrect code."}, status=400)
        otp.is_used = True
        otp.save(update_fields=['is_used'])
        user = User.objects.filter(phone=phone_e164, role=Role.CUSTOMER).first()
        created = False
        if not user:
            user = User.objects.create(
                phone=phone_e164, role=Role.CUSTOMER,
                email=f"{phone_e164.lstrip('+')}@phone.nearbyme.local",
                username=phone_e164,
            )
            user.set_unusable_password()
            user.save()
            created = True
        refresh = RefreshToken.for_user(user)
        refresh['role'] = user.role
        refresh['email'] = user.email
        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": UserSerializer(user).data,
            "is_new_user": created,
        }, status=200)
