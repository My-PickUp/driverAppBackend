import random
from venv import logger

import jwt
from django.db import connections
from django.db.utils import OperationalError
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
    expiration_time_threshold = timezone.now() - timedelta(minutes=1)
    print(f"Current time: {timezone.now()}, Expiration threshold: {expiration_time_threshold}")
    old_verification_codes = DriverVerificationCode.objects.filter(
        phone_number=phone_number,
        created_at__lte=expiration_time_threshold,
        status='active'
    )

    print(f"Old verification codes: {old_verification_codes}")
    old_verification_codes.update(status='expired')

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


def is_authenticated(token):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        return True
    except Exception as e:
        return False

@api_view(['GET'])
def get_driver_details(request):

    token = request.headers.get('Authorization').split(' ')[1]


    if not is_authenticated(token):
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        phone_number = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256']).get('phone')
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
@api_view(['PATCH'])
def update_customers_for_driver(request, driver_id):
    try:
        driver = Driver.objects.get(pk=driver_id)
    except Driver.DoesNotExist:
        return Response({'error': 'Driver not found'}, status=status.HTTP_404_NOT_FOUND)

    data = request.data
    assigned_user_phones = data.get('assigned_users', [])

    assigned_users = []
    for phone in assigned_user_phones:
        user, created = UserInfo.objects.get_or_create(phone=phone)
        assigned_users.append(user)

    assigned_users_list = list(assigned_users)


    driver.assigned_users.set(assigned_users_list)

    driver.save()

    serializer = DriverSerializer(driver)
    return Response(serializer.data, status=status.HTTP_200_OK)
@api_view(['GET'])
def get_customer_details(request):
    try:
        with connections['default'].cursor() as cursor:
            query = """
            SELECT
    CASE EXTRACT(DOW FROM users_rides_detail.ride_date_time)
        WHEN 0 THEN 'Sunday'
        WHEN 1 THEN 'Monday'
        WHEN 2 THEN 'Tuesday'
        WHEN 3 THEN 'Wednesday'
        WHEN 4 THEN 'Thursday'
        WHEN 5 THEN 'Friday'
        WHEN 6 THEN 'Saturday'
        ELSE 'Unknown Day'
    END AS day_of_week,
    users.id AS customer_id,
    users.name AS customer_name,
    users_rides_detail.pickup_address_type,
    users_rides_detail.pickup_address,
    users_rides_detail.drop_address_type,
    users_rides_detail.drop_address,
    users_rides_detail.ride_status,
    users_rides_detail.ride_date_time
FROM
    users
JOIN
    users_subscription ON users.id = users_subscription.user_id
JOIN
    users_rides_detail ON users_rides_detail.user_id = users.id
WHERE
    users_rides_detail.ride_status = 'Upcoming'
ORDER BY
    users_rides_detail.ride_date_time;

            """
            cursor.execute(query)
            rows = cursor.fetchall()

            # Convert rows to a list of dictionaries.
            result = [
                dict(zip([column[0] for column in cursor.description], row))
                for row in rows
            ]
            # Returns result as JSON
            return JsonResponse({"status": "success", "data": {"upcoming_customers": result}})
    except OperationalError as e:
        return JsonResponse({"status": "error", "message": str(e)})



















