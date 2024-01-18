from rest_framework import serializers
from driverService.models import Driver, DriverVerificationCode, Customer, DriverRide, Copassenger

class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = '__all__'

class CancelRideSerializer(serializers.Serializer):
    customer_ride_ids = serializers.ListField(child=serializers.IntegerField(), required=False)

class DriverSerializer(serializers.ModelSerializer):
    class Meta:
        model = Driver
        fields = '__all__'

class DriverVerificationCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DriverVerificationCode
        fields = '__all__'


class DriverRideSerializer(serializers.ModelSerializer):
    class Meta:
        model = DriverRide
        fields = '__all__'

class CopassengerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Copassenger
        fields = '__all__'

class RescheduleRideSerializer(serializers.Serializer):

    customer_ride_id = serializers.IntegerField()
    ride_date_time = serializers.DateTimeField()











