from rest_framework import serializers
from driverService.models import Driver, UserInfo, VerificationCode

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserInfo
        fields = ['phone']

class DriverSerializer(serializers.ModelSerializer):
    assigned_users = UserSerializer(many=True, read_only=True)

    class Meta:
        model = Driver
        fields = '__all__'

class VerificationCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationCode
        fields = '__all__'



