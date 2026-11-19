from rest_framework import serializers
from django.contrib.auth import get_user_model
User = get_user_model()
class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6, style={'input_type': 'password'})
    class Meta:
        model = User
        fields = ('id', 'email', 'password', 'first_name', 'last_name', 'role')
        read_only_fields = ('id', 'role')
    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value
    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            role='CUSTOMER'
        )
        return user
class UserSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    outlet_name = serializers.CharField(source='outlet.name', read_only=True)
    outlet_id = serializers.SerializerMethodField()

    def get_outlet_id(self, obj):
        if getattr(obj, 'outlet_id', None):
            return str(obj.outlet_id)
        if getattr(obj, 'store', None) and getattr(obj.store, 'outlet_id', None):
            return str(obj.store.outlet_id)
        from apps.core.models import Store, Outlet
        st = getattr(obj, 'store', None) or Store.objects.first()
        if st and st.outlet_id:
            return str(st.outlet_id)
        first_out = Outlet.objects.first()
        return str(first_out.id) if first_out else None

    class Meta:
        model = User
        fields = ('id', 'email', 'first_name', 'last_name', 'role', 'brand_id', 'store_id', 'outlet_id', 'store_name', 'outlet_name')
