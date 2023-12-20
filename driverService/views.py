import random
from venv import logger

import jwt
from django.core.exceptions import ObjectDoesNotExist
from django.http import JsonResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from rest_framework import status
from driverService.models import Driver, UserInfo, DriverVerificationCode
from driverService.serializers import DriverSerializer, DriverVerificationCodeSerializer
from django_ratelimit.decorators import ratelimit
from datetime import datetime, timedelta
from django.conf import settings
from django.utils import timezone
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
@api_view(['POST'])
def generate_otp(request):
    phone_number = request.data.get('phone')
    driver = Driver.objects.filter(phone=phone_number).first()
    if not driver:
        return Response({'error':'Driver is not found with this phone number.'}, status=status.HTTP_404_NOT_FOUND)

    otp = ''.join(random.choices('0123456789', k=6))
    verification_code = DriverVerificationCode.objects.create(
        phone_number=phone_number,
        code=otp,
        created_at=timezone.now(),
        status='active'
    )

    serializer = DriverVerificationCodeSerializer(verification_code)
    return Response(serializer.data, status=status.HTTP_201_CREATED)

@api_view(['POST'])
def verify_otp(request):
    phone_number = request.data.get('phone')
    entered_code = request.data.get('code')

    driver = Driver.objects.filter(phone=phone_number).first()
    if not driver:
        return Response({'error':'Driver is not found with this phone number.'}, status=status.HTTP_404_NOT_FOUND)

    verification_code = DriverVerificationCode.objects.filter(
        phone_number = phone_number,
        code = entered_code,
        status = 'active'
    ).first()

    if not verification_code:
        return Response({'error':'Invalid OTP'}, status=status.HTTP_401_UNAUTHORIZED)
    verification_code.status = 'expired'
    verification_code.save()


    access_token_expires = timezone.now() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = jwt.encode({'phone':phone_number, 'exp':access_token_expires}
                              ,settings.SECRET_KEY, algorithm='HS256')

    return Response({'access_token': access_token}, status=status.HTTP_200_OK)


def is_authenticated(token, phone_number):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        return payload.get('phone') == phone_number
    except Exception as e:
        return False


@api_view(['GET'])
def get_driver_details(request):
    phone_number = request.headers.get('phone')
    token = request.headers.get('Authorization').split(' ')[1]


    if not is_authenticated(token, phone_number):
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        driver = Driver.objects.get(phone=phone_number)
    except ObjectDoesNotExist:
        return JsonResponse({'error': 'Driver not found'}, status=404)

    driver_details = {
        'driver_id': driver.driver_id,
        'driver_status': driver.driver_status,
        'name': driver.name,
        'phone': driver.phone,
        'vehicle_number': driver.vehicle_number,
        'vehicle_model': driver.vehicle_model,
        'track_url': driver.track_url,
    }

    return JsonResponse(driver_details, status=200)



















