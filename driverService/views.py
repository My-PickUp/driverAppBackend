from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from rest_framework import status
from driverService.models import Driver, UserInfo
from driverService.serializers import DriverSerializer
from django_ratelimit.decorators import ratelimit
from driverService.serializers import UserSerializer

@api_view(['GET'])
def awake(request):
    response_data = {'message': 'I am awake'}
    return Response(response_data, status=200)
@api_view(['GET'])
@ratelimit(key='ip', rate='5/m', block=True)
def get_drivers(request, phone):
    drivers = get_object_or_404(Driver, phone= phone)
    serializer = DriverSerializer(drivers)
    return Response(serializer.data)

@ratelimit(key='ip', rate='5/m', block=True)
@api_view(['POST'])
def create_driver(request):
    data = request.data
    assigned_user_phones = data.pop('assigned_users', [])
    existing_driver = Driver.objects.filter(phone=data['phone']).first()
    if existing_driver:
        return Response({'error': 'Driver with this phone number already exists.'}, status=status.HTTP_400_BAD_REQUEST)
    assigned_users = []
    for phone in assigned_user_phones:
        user, created = UserInfo.objects.get_or_create(phone=phone)
        assigned_users.append(user)
    serializer = DriverSerializer(data=data)

    if serializer.is_valid():
        driver_instance = serializer.save()
        driver_instance.assigned_users.set(assigned_users)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)







