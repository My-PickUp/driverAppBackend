from rest_framework import serializers
from driverService.models import Driver, UserInfo

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserInfo
        fields = ['phone']

class DriverSerializer(serializers.ModelSerializer):
    assigned_users = UserSerializer(many=True, read_only=True)

    class Meta:
        model = Driver
        fields = '__all__'
