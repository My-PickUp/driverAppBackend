from rest_framework import serializers
from driverService.models import Driver, DriverVerificationCode, Customer

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = '__all__'

class DriverSerializer(serializers.ModelSerializer):
    class Meta:
        model = Driver
        fields = '__all__'

class DriverVerificationCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DriverVerificationCode
        fields = '__all__'





