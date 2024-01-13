import csv
import json
import random
import requests
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.timezone import make_aware
from django.db.models import F, Q
import jwt
from django.db import connections, transaction
from django.views.decorators.cache import cache_page
from rest_framework.views import APIView
from django.db.utils import OperationalError, IntegrityError
from django.core.exceptions import ObjectDoesNotExist
from django.http import JsonResponse, HttpRequest
from rest_framework.decorators import api_view, parser_classes
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from rest_framework import status
from .serializers import CancelRideSerializer, RescheduleRideSerializer

from driverService import models
from driverService.models import Driver, Customer, DriverVerificationCode, DriverRide, Copassenger
from driverService.serializers import DriverSerializer, DriverVerificationCodeSerializer, DriverRideSerializer, CustomerSerializer, CopassengerSerializer
from django_ratelimit.decorators import ratelimit
from datetime import datetime, timedelta
from django.conf import settings
from django.utils import timezone
from django.core.cache import cache
from driverService.serializers import CustomerSerializer

@api_view(['GET'])
def awake(request):
    response_data = {'message': 'I am awake'}
    return Response(response_data, status=200)
@api_view(['GET'])
def get_drivers(request, phone):
    drivers = get_object_or_404(Driver, phone= phone)
    serializer = DriverSerializer(drivers)
    return Response(serializer.data)

@ratelimit(key='ip', rate='5/m', block=True)
@api_view(['POST'])
def create_driver(request):
    data = request.data
    existing_driver = Driver.objects.filter(phone=data['phone']).first()
    if existing_driver:
        return Response({'error': 'Driver with this phone number already exists.'}, status=status.HTTP_400_BAD_REQUEST)

    serializer = DriverSerializer(data=data)

    if serializer.is_valid():
        serializer.save()
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
'''
DriverApp UI will use this API for driver verification using authorisation technique.
'''
@api_view(['GET'])
def get_driver_details(request):
    authorization_header = request.headers.get('Authorization')
    if not authorization_header or len(authorization_header.split()) < 2:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    token = authorization_header.split(' ')[1]

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
'''
This API will join all the relevant tables of customerAppBackend service 
and project it on the admin dashboard making it easy for our 
Ops team to work on the existing customer data.
'''
@api_view(['GET'])
def get_customer_details(request):
    try:
        with connections['default'].cursor() as cursor:
            query = """
            SELECT DISTINCT ON (users_rides_detail.ride_date_time)
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
    users_rides_detail.id AS customer_ride_id,
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

            '''
            Convert rows to a list of dictionaries.
            '''
            result = [
                dict(zip([column[0] for column in cursor.description], row))
                for row in rows
            ]
            '''
            Returns result as JSON
            '''
            return JsonResponse({"status": "success", "data": {"upcoming_customers": result}})
    except OperationalError as e:
        return JsonResponse({"status": "error", "message": str(e)})
'''
This API will fetch the data from upload file the one that will 
be pushed from admin dashboard and will ingest all the driver 
related informations into the tables driverride, customer and co_passengers.
'''

@api_view(['POST'])
def form_upload_response(request):
    if 'csv_file' not in request.FILES:
        return Response({"error": "CSV file is missing"}, status=status.HTTP_400_BAD_REQUEST)

    csv_file = request.FILES['csv_file'].read().decode('utf-8').splitlines()
    reader = csv.DictReader(csv_file)

    ride_details = []

    for row in reader:
        ride_date_time = row.get('ride_date_time', '')
        driver_id = row.get('driver', '')
        ride_type = row.get('ride_type', '')
        customer_id = row.get('customer_id', '')
        drop_priority = int(row.get('drop_priority', '')) if row.get('drop_priority', '') else None
        co_passenger = row.get('co_passenger', '') or None
        customer_ride_id = row.get('customer_ride_id', '')
        customer_ride_status = row.get('ride_status', '')
        customer_name = row.get('customer_name', '')
        customer_pickup_address = row.get('pickup_address', '')
        customer_drop_address = row.get('drop_address', '')

        ride_details.append({
            "ride_date_time": ride_date_time,
            "driver_id": driver_id,
            "ride_type": ride_type,
            "customers": [
                {
                    "customer_id": customer_id,
                    "drop_priority": drop_priority,
                    "co_passenger": co_passenger,
                    "customer_ride_id": customer_ride_id,
                    "customer_ride_status":customer_ride_status,
                    "customer_name":customer_name,
                    "customer_pickup_address":customer_pickup_address,
                    "customer_drop_address":customer_drop_address

                }
            ]
        })

    response_data = {
        "ride_details": ride_details
    }
    print(response_data)

    for ride_detail in ride_details:
        driver_id = ride_detail['driver_id']
        ride_type = ride_detail['ride_type']
        ride_date_time = make_aware(datetime.strptime(ride_detail['ride_date_time'], "%Y-%m-%d %H:%M:%S"))

        for customers in ride_detail['customers']:
            customer_id = customers['customer_id']

            print(f"Processing ride_detail: {ride_detail}")

            driver, created = Driver.objects.get_or_create(driver_id=driver_id)

            existing_ride = DriverRide.objects.filter(
                ride_type=ride_type,
                ride_date_time=ride_date_time,
                driver=driver,
                customer_id = customer_id
            ).first()

            ride = None

            if existing_ride and existing_ride.customer_id == customer_id:
                existing_ride.ride_date_time = ride_date_time
                existing_ride.save()


            elif not existing_ride:

                ride = DriverRide.objects.create(

                    ride_type=ride_type,

                    ride_date_time=ride_date_time,

                    driver=driver,

                    customer_id=customer_id
                )

            for customer_detail in ride_detail['customers']:
                customer_id = customer_detail['customer_id']
                drop_priority = customer_detail['drop_priority']
                co_passenger = customer_detail['co_passenger']
                customer_ride_id = customer_detail.get('customer_ride_id', None)
                customer_ride_status = customer_detail.get('customer_ride_status', None)
                customer_name = customer_detail.get('customer_name', None)
                customer_pickup_address = customer_detail.get('customer_pickup_address', None)
                customer_drop_address = customer_detail.get('customer_drop_address', None)

                customer_exists = Customer.objects.filter(
                    customer_id=customer_id,
                    driver=driver,
                    ride_date_time__date=ride_date_time.date(),
                    customer_ride_id=customer_ride_id,
                    customer_ride_status = customer_ride_status,
                    name = customer_name,
                    pickup_address = customer_pickup_address,
                    drop_address = customer_drop_address
                ).first()

                copassenger_exists = Copassenger.objects.filter(
                    co_passenger__customer_id=customer_id,
                    ride=ride
                ).exists()

                if customer_exists or copassenger_exists:
                    print("The records already exist in the system")
                    customer_exists.ride_date_time = ride_date_time
                    customer_exists.save()
                else:
                    customer, created = Customer.objects.get_or_create(
                        customer_id=customer_id,
                        driver=driver,
                        ride_date_time=ride_date_time,
                        customer_ride_id=customer_ride_id,
                        customer_ride_status = customer_ride_status,
                        name= customer_name,
                        pickup_address=customer_pickup_address,
                        drop_address=customer_drop_address
                    )

                    if created or (drop_priority is not None and customer.drop_priority is None):
                        customer.drop_priority = drop_priority
                        customer.save()

                        if co_passenger:
                            co_passenger, created = Copassenger.objects.get_or_create(
                                co_passenger=customer,
                                ride=ride
                            )

    return Response(response_data, status=status.HTTP_201_CREATED)

'''
This API will be syncing the driver_info
 and customer_ride_date_time info for all Private rides with the customerApp service.
'''
@api_view(['GET'])
@cache_page(60 * 20)
def get_upcoming_private_rides(request, driver_id):

    '''
    Caching all private rides info with the driverAppBackend for interval of 20 min.
    '''
    cache_key = f'upcoming_private_rides_{driver_id}'
    cached_result = cache.get(cache_key)
    if cached_result:
        return JsonResponse({"status": "success", "data": {"upcoming_private_rides": cached_result}})


    try:
        driver = get_object_or_404(Driver, driver_id=driver_id)

        with connections['default'].cursor() as cursor:
            query = """
                    SELECT DISTINCT ON (customer.ride_date_time, customer.driver_id)
    driver.name as driver_name,
    driver.phone as driver_phone,
    usersInfo.phone_number AS user_phone,
    usersInfo.name as user_name,
    usersInfo.id AS user_id,
    customer.ride_date_time,
    customer.driver_id,
    customer.drop_priority,
    driverRide.ride_type,
    customer.customer_ride_id as customer_ride_id,
    userRides.ride_status,
    userRides.drop_address_type,
    userRides.drop_address,
    userRides.pickup_address_type,
    userRides.pickup_address,
    driverRide.ride_id,
    CASE
        WHEN EXTRACT(DOW FROM customer.ride_date_time) = 0 THEN 'Sunday'
        WHEN EXTRACT(DOW FROM customer.ride_date_time) = 1 THEN 'Monday'
        WHEN EXTRACT(DOW FROM customer.ride_date_time) = 2 THEN 'Tuesday'
        WHEN EXTRACT(DOW FROM customer.ride_date_time) = 3 THEN 'Wednesday'
        WHEN EXTRACT(DOW FROM customer.ride_date_time) = 4 THEN 'Thursday'
        WHEN EXTRACT(DOW FROM customer.ride_date_time) = 5 THEN 'Friday'
        WHEN EXTRACT(DOW FROM customer.ride_date_time) = 6 THEN 'Saturday'
        ELSE 'Unknown'
    END AS day_of_week
FROM
    "driverService_customer" AS customer
JOIN
    "driverService_driverride" AS driverRide
ON
    customer.ride_date_time = driverRide.ride_date_time AND customer.driver_id = driverRide.driver_id
JOIN
    "driverService_driver" AS driver
ON
    driver.driver_id = driverRide.driver_id
JOIN
    users AS usersInfo
ON
    usersInfo.id = customer.customer_id
JOIN
    users_rides_detail AS userRides
ON
    usersInfo.id = userRides.user_id
WHERE
    userRides.ride_status = 'Upcoming' AND ride_type = 'Private' AND driverRide.driver_id = %s
ORDER BY
    customer.ride_date_time, customer.driver_id, customer.ride_date_time DESC;
                    """
            cursor.execute(query, [driver_id])
            rows = cursor.fetchall()

            result = [
                dict(zip([column[0] for column in cursor.description], row))
                for row in rows
            ]

            pairs = []
            for i in range(len(result)):
                pair = [result[i]]
                pairs.append(pair)

            for pair in pairs:
                for row in pair:
                    # print(row)
                    driver_phone = row['driver_phone']
                    ride_date_time = row['ride_date_time'].strftime('%Y-%m-%d %H:%M:%S')
                    user_id = row['user_id']
                    customer_ride_id = row['customer_ride_id']
                    # print(driver_phone, ride_date_time, user_id, customer_ride_id)
                    reschedule_ride(customer_ride_id, ride_date_time)
                    update_customer_sharing_rides(customer_ride_id, driver_phone)
                    cache.set(cache_key, result, timeout=300)

            return JsonResponse({"status": "success", "data": {"upcoming_private_rides": pairs}})

    except OperationalError as e:
        return JsonResponse({"status": "error", "message": str(e)})

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)})
'''
This API will be syncing the driver_info
 and customer_ride_date_time info for all Sharing rides with the customerApp service.
'''
@api_view(['GET'])
@cache_page(60 * 20)
def get_upcoming_sharing_rides(request, driver_id):
    '''
        Caching all Sharing rides info with the driverAppBackend for interval of 20 min.
    '''
    cache_key = f'upcoming_sharing_rides_{driver_id}'
    cached_result = cache.get(cache_key)
    if cached_result:
        return JsonResponse({"status": "success", "data": {"upcoming_sharing_rides": cached_result}})

    try:
        driver = Driver.objects.get(driver_id=driver_id)
    except Driver.DoesNotExist:
        return JsonResponse({"status": "error", "message": f"Driver with ID {driver_id} does not exist in the system"})

    try:
        with connections['default'].cursor() as cursor:
            query = """
                    SELECT DISTINCT ON (customer.ride_date_time, customer.driver_id)
    driver.name as driver_name,
    driver.phone as driver_phone,
    usersInfo.phone_number AS user_phone,
    usersInfo.name as user_name,
    usersInfo.id AS user_id,
    customer.ride_date_time,
    customer.driver_id,
    customer.drop_priority,
    driverRide.ride_type,
    customer.customer_ride_id as customer_ride_id,
    userRides.ride_status,
    userRides.drop_address_type,
    userRides.drop_address,
    userRides.pickup_address_type,
    userRides.pickup_address,
    driverRide.ride_id,
    CASE
        WHEN EXTRACT(DOW FROM customer.ride_date_time) = 0 THEN 'Sunday'
        WHEN EXTRACT(DOW FROM customer.ride_date_time) = 1 THEN 'Monday'
        WHEN EXTRACT(DOW FROM customer.ride_date_time) = 2 THEN 'Tuesday'
        WHEN EXTRACT(DOW FROM customer.ride_date_time) = 3 THEN 'Wednesday'
        WHEN EXTRACT(DOW FROM customer.ride_date_time) = 4 THEN 'Thursday'
        WHEN EXTRACT(DOW FROM customer.ride_date_time) = 5 THEN 'Friday'
        WHEN EXTRACT(DOW FROM customer.ride_date_time) = 6 THEN 'Saturday'
        ELSE 'Unknown'
    END AS day_of_week
FROM
    "driverService_customer" AS customer
JOIN
    "driverService_driverride" AS driverRide
ON
    customer.ride_date_time = driverRide.ride_date_time AND customer.driver_id = driverRide.driver_id
JOIN
    "driverService_driver" AS driver
ON
    driver.driver_id = driverRide.driver_id
JOIN
    users AS usersInfo
ON
    usersInfo.id = customer.customer_id
JOIN
    users_rides_detail AS userRides
ON
    usersInfo.id = userRides.user_id
WHERE
    userRides.ride_status = 'Upcoming' AND ride_type = 'Sharing' AND driverRide.driver_id = %s
ORDER BY
    customer.ride_date_time, customer.driver_id, customer.ride_date_time DESC;
                    """
            cursor.execute(query, [driver_id])
            rows = cursor.fetchall()

            result = [
                dict(zip([column[0] for column in cursor.description], row))
                for row in rows
            ]

            pairs = []
            for i in range(0, len(result), 2):
                if i + 1 < len(result):
                    pair = [result[i], result[i + 1]]
                    pairs.append(pair)

            for pair in pairs:
                for row in pair:
                    #print(row)
                    driver_phone = row['driver_phone']
                    ride_date_time = row['ride_date_time'].strftime('%Y-%m-%d %H:%M:%S')
                    user_id = row['user_id']
                    customer_ride_id = row['customer_ride_id']
                    print(customer_ride_id, driver_phone)
                    #reschedule_ride(customer_ride_id, ride_date_time)
                    #update_customer_sharing_rides(customer_ride_id, driver_phone)
                    cache.set(cache_key, result, timeout=300)

            return JsonResponse({"status": "success", "data": {"upcoming_sharing_rides": pairs}})

    except OperationalError as e:
        return JsonResponse({"status": "error", "message": str(e)})

def reschedule_ride(customer_ride_id, ride_date_time):

    url = f'https://fast-o4qh.onrender.com/reschedule_ride/'

    payload = json.dumps({
  "ride_id": customer_ride_id,
  "new_datetime": ride_date_time
})
    print(payload)

    headers = {
        'accept': 'application/json',
        'Content-Type': 'application/json'
    }

    try:
        response = requests.put(url, headers=headers, data=payload)
        response.raise_for_status()  # Raises HTTPError for bad responses
        print(response.status_code)
        print(response.text)
    except requests.exceptions.RequestException as e:
        print(f"Error making reschedule request: {e}")

def update_customer_sharing_rides(customer_ride_id, driver_phone):
    update_url = f'https://fast-o4qh.onrender.com/edit_ride_driver_phone/{customer_ride_id}?driver_phone={driver_phone}'
    print(update_url)

    try:
        response = requests.put(update_url)
        '''
        Raise HTTPError for bad responses.
        '''
        response.raise_for_status()
        json_response = response.json()
        print(json_response)
    except requests.exceptions.RequestException as e:
        print(f"Error updating customer sharing rides table: {e}")

@api_view(['POST'])
def start_private_ride(request):

    try:
        customer_ride_id = request.data.get('customer_ride_id')
        driver_id = request.data.get('driver_id')

        with transaction.atomic():
            valid_ride = Customer.objects.select_for_update().filter(
                customer_ride_id=customer_ride_id,
                driver_id=driver_id,
                customer_ride_status='Upcoming',
                driver__driverride__ride_type='Private'
            ).first()

            if not valid_ride:
                return Response({"status": "error", "message": "Invalid customer_ride_id or driver_id"},
                                status=status.HTTP_400_BAD_REQUEST)

            '''
            Call the helper function to update the customerApp's users_rides_detail table
            by updating the ride-status as Ongoing.
            '''
            update_result = map_driver_customer_app_ride_status(customer_ride_id, 'Ongoing')
            print(update_result)

            if update_result.get('status_code') == 200:
                '''
                If the update is successful, proceed with marking the Driver ride as ongoing in the driverService Customer table.
                '''
                valid_ride.customer_ride_status = 'Ongoing'
                valid_ride.save()

                return Response({"status": "success", "message": "Ride started successfully"}, status=status.HTTP_200_OK)
            else:
                '''
                If the update fails, return an error response.
                '''
                return Response({"status": "error", "message": "Failed to update customer app ride status"},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@cache_page(60 * 20)
def fetch_private_customer_rides(request, driver_id):
    '''
            Caching all private rides info with the driverAppBackend for interval of 20 min.
    '''
    cache_key = f'private_customer_rides_{driver_id}'
    cached_result = cache.get(cache_key)
    if cached_result:
        return JsonResponse({"status": "success", "data": {"private_customer_rides_": cached_result}})

    private_queryset = Customer.objects.select_related('driver', 'driver__driverride').filter(
        Q(drop_priority__isnull=True, driver__driverride__ride_type='Private', customer_ride_status='Upcoming', driver_id=driver_id)
    ).values(
        customer_name_info=F('name'),
        customer_id_info=F('customer_id'),
        customer_ride_datetime=F('ride_date_time'),
        driver_phone_info=F('driver__phone'),
        driver_id_info=F('driver_id'),
        customer_drop_priority_info=F('drop_priority'),
        driver_ride_type_info=F('driver__driverride__ride_type'),
        customer_ride_id_info=F('customer_ride_id'),
        customer_ride_status_info=F('customer_ride_status'),
        customer_pickup_address_info=F('pickup_address'),
        customer_drop_address_info=F('drop_address'),
    ).order_by('ride_date_time').distinct()

    '''
    Appended each private_rides in each Nested lists.
    '''

    pairs = []
    for i in range(len(private_queryset)):
        pair = [private_queryset[i]]
        pairs.append(pair)

        customer_ride_id_info = private_queryset[i]['customer_ride_id_info']
        customer_ride_datetime = private_queryset[i]['customer_ride_datetime']
        driver_phone = private_queryset[i]['driver_phone_info']

        customer_ride_datetime_str = DjangoJSONEncoder().default(customer_ride_datetime)

        reschedule_ride(customer_ride_id_info, customer_ride_datetime_str)
        update_customer_sharing_rides(customer_ride_id_info, driver_phone)
        cache.set(cache_key, pairs, timeout=300)

    return Response(pairs, status=status.HTTP_200_OK)
@api_view(['POST'])
def start_sharing_ride(request):

    try:
        customer_ride_id = request.data.get('customer_ride_id')
        driver_id = request.data.get('driver_id')

        with transaction.atomic():
            valid_ride = Customer.objects.select_for_update().filter(
                customer_ride_id=customer_ride_id,
                driver_id=driver_id,
                customer_ride_status='Upcoming',
                driver__driverride__ride_type='Sharing'
            ).first()

            if not valid_ride:
                return Response({"status": "error", "message": "Invalid customer_ride_id or driver_id"},
                                status=status.HTTP_400_BAD_REQUEST)

            '''
            Call the helper function to update the customerApp's users_rides_detail table
            by updating the ride-status as Ongoing.
            '''
            update_result = map_driver_customer_app_ride_status(customer_ride_id, 'Ongoing')
            print(update_result)

            if update_result.get('status_code') == 200:
                '''
                If the update is successful, proceed with marking the Driver ride as ongoing in the driverService Customer table.
                '''
                valid_ride.customer_ride_status = 'Ongoing'
                valid_ride.save()

                return Response({"status": "success", "message": "Ride started successfully"}, status=status.HTTP_200_OK)
            else:
                '''
                If the update fails, return an error response.
                '''
                return Response({"status": "error", "message": "Failed to update customer app ride status"},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
@api_view(['GET'])
@cache_page(60 * 20)
def fetch_sharing_customer_rides(request, driver_id):
    '''
    Caching all sharing rides info with the driverAppBackend for interval of 20 min.
    '''
    cache_key = f'sharing_customer_rides_{driver_id}'
    cached_result = cache.get(cache_key)
    if cached_result:
        return JsonResponse({"status": "success", "data": {"sharing_customer_rides": cached_result}})


    sharing_queryset = Customer.objects.select_related('driver', 'driver__driverride').filter(
        Q(drop_priority__isnull=False, driver__driverride__ride_type='Sharing', customer_ride_status='Upcoming', driver_id=driver_id)
    ).values(
        customer_name_info=F('name'),
        customer_id_info=F('customer_id'),
        customer_ride_datetime=F('ride_date_time'),
        driver_id_info=F('driver_id'),
        customer_drop_priority_info=F('drop_priority'),
        driver_ride_type_info=F('driver__driverride__ride_type'),
        driver_phone_info= F('driver__phone'),
        customer_ride_id_info=F('customer_ride_id'),
        customer_ride_status_info=F('customer_ride_status'),
        customer_pickup_address_info=F('pickup_address'),
        customer_drop_address_info=F('drop_address'),
    ).order_by('ride_date_time').distinct()

    pairs = []
    for i in range(0, len(sharing_queryset), 2):
        if i + 1 < len(sharing_queryset):
            pair = [sharing_queryset[i], sharing_queryset[i + 1]]
            pairs.append(pair)

            customer_ride_id_info = sharing_queryset[i]['customer_ride_id_info']
            customer_ride_datetime = sharing_queryset[i]['customer_ride_datetime']
            driver_phone = sharing_queryset[i]['driver_phone_info']

            customer_ride_datetime_str = DjangoJSONEncoder().default(customer_ride_datetime)

            reschedule_ride(customer_ride_id_info, customer_ride_datetime_str)
            update_customer_sharing_rides(customer_ride_id_info, driver_phone)
            cache.set(cache_key, pairs, timeout=300)

    return Response(pairs, status=status.HTTP_200_OK)
@api_view(['POST'])
def end_private_ride(request):
    try:
        customer_ride_id = request.data.get('customer_ride_id')
        driver_id = request.data.get('driver_id')

        with transaction.atomic():
            valid_ride = Customer.objects.select_for_update().filter(
                customer_ride_id=customer_ride_id,
                driver_id=driver_id,
                customer_ride_status='Ongoing',
                driver__driverride__ride_type='Private'
            ).first()

            if not valid_ride:
                return Response({"status": "error", "message": "Invalid customer_ride_id or driver_id"},
                                status=status.HTTP_400_BAD_REQUEST)

            '''
            Call the helper function to update the customerApp's users_rides_detail table
            by updating the ride-status as Ongoing.
            '''
            update_result = map_driver_customer_app_ride_status(customer_ride_id, 'Completed')
            print(update_result)

            if update_result.get('status_code') == 200:
                '''
                If the update is successful, proceed with marking the Driver ride as ongoing in the driverService Customer table.
                '''
                valid_ride.customer_ride_status = 'Completed'
                valid_ride.save()

                return Response({"status": "success", "message": "Ride started successfully"}, status=status.HTTP_200_OK)
            else:
                '''
                If the update fails, return an error response.
                '''
                return Response({"status": "error", "message": "Failed to update customer app ride status"},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
@api_view(['POST'])
def end_sharing_ride(request):
    try:
        customer_ride_id = request.data.get('customer_ride_id')
        driver_id = request.data.get('driver_id')

        with transaction.atomic():
            valid_ride = Customer.objects.select_for_update().filter(
                customer_ride_id=customer_ride_id,
                driver_id=driver_id,
                customer_ride_status='Ongoing',
                driver__driverride__ride_type='Sharing'
            ).first()

            if not valid_ride:
                return Response({"status": "error", "message": "Invalid customer_ride_id or driver_id"},
                                status=status.HTTP_400_BAD_REQUEST)

            '''
            Call the helper function to update the customerApp's users_rides_detail table
            by updating the ride-status as Ongoing.
            '''
            update_result = map_driver_customer_app_ride_status(customer_ride_id, 'Completed')
            print(update_result)

            if update_result.get('status_code') == 200:
                '''
                If the update is successful, proceed with marking the Driver ride as ongoing in the driverService Customer table.
                '''
                valid_ride.customer_ride_status = 'Completed'
                valid_ride.save()

                return Response({"status": "success", "message": "Ride started successfully"},
                                status=status.HTTP_200_OK)
            else:
                '''
                If the update fails, return an error response.
                '''
                return Response({"status": "error", "message": "Failed to update customer app ride status"},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def map_driver_customer_app_ride_status(ride_id, new_status):

    url = f'https://fast-o4qh.onrender.com/updateRideStatus?ride_id={ride_id}'
    headers = {
        'accept': 'application/json',
        'Content-Type': 'application/json',
    }
    data = {
        'newStatus': new_status,
    }

    try:
        response = requests.put(url, headers=headers, json=data)
        response.raise_for_status()

        '''
        Including the status code in the response dictionary.
        '''
        result = {
            "status": "success",
            "status_code": response.status_code,
            "data": response.json()
        }
        return result
    except requests.exceptions.RequestException as e:
        '''
        Include the status code in the response dictionary.
        '''
        result = {
            "status": "error",
            "status_code": getattr(e.response, 'status_code', None),
            "message": str(e),
        }
        return result


@api_view(['POST'])
def cancel_customer_ride(request):
    serializer = CancelRideSerializer(data=request.data)
    if serializer.is_valid():
        customer_ride_id = serializer.validated_data['customer_ride_id']
        customers = Customer.objects.filter(customer_ride_id=customer_ride_id)

        if customers.exists():
            '''
            To cancel all rides with the given customer_ride_id.
            '''
            for customer in customers:
                customer.customer_ride_status = 'Cancelled'
                customer.save()

            return Response({'status': 'Rides Cancelled'}, status=status.HTTP_200_OK)
        else:
            return Response({'error': 'No customers found with the specified ride_id'},
                            status=status.HTTP_404_NOT_FOUND)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
def reschedule_customer_ride(request):
    serializer = RescheduleRideSerializer(data=request.data)
    if serializer.is_valid():
        customer_ride_id = serializer.validated_data['customer_ride_id']
        new_datetime = serializer.validated_data['ride_date_time']
        customers = Customer.objects.filter(customer_ride_id=customer_ride_id)

        if customers.exists():
            for customer in customers:
                customer.ride_date_time = new_datetime
                customer.save()

        return Response({'status': 'Ride Rescheduled'}, status=status.HTTP_200_OK)
    else:
        return Response({'error': 'Customer with specified ride_id not found'}, status=status.HTTP_404_NOT_FOUND)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
def fetch_all_ongoing_customer_rides(request, driver_id):

    ongoing_queryset = Customer.objects.select_related('driver', 'driver__driverride').filter(
        Q(drop_priority__isnull=True, driver__driverride__ride_type='Private', customer_ride_status='Ongoing',
          driver_id=driver_id) |
        Q(drop_priority__isnull=False, driver__driverride__ride_type='Sharing', customer_ride_status='Ongoing',
          driver_id=driver_id)
    ).values(
        customer_name_info=F('name'),
        customer_id_info=F('customer_id'),
        customer_ride_datetime=F('ride_date_time'),
        driver_phone_info=F('driver__phone'),
        driver_id_info=F('driver_id'),
        customer_drop_priority_info=F('drop_priority'),
        driver_ride_type_info=F('driver__driverride__ride_type'),
        customer_ride_id_info=F('customer_ride_id'),
        customer_ride_status_info=F('customer_ride_status'),
        customer_pickup_address_info=F('pickup_address'),
        customer_drop_address_info=F('drop_address'),
    ).order_by('ride_date_time').distinct('customer_ride_id')

    pairs = []
    for i in range(len(ongoing_queryset)):
        pair = [ongoing_queryset[i]]
        pairs.append(pair)

    return Response(pairs, status=status.HTTP_200_OK)


