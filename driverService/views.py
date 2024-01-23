import csv
import json
import random
from concurrent.futures import ThreadPoolExecutor
from django.db.utils import IntegrityError
from django.db import connection
import threading
import requests
from django.core.serializers.json import DjangoJSONEncoder
from django.template.response import ContentNotRenderedError
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

ongoing_sharing_rides_list = []

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
def manage_driver(request):
    if request.method == 'POST':
        data = request.data

        if 'driver_id' in data:
            driver_id = data.get('driver_id')

            try:
                driver = Driver.objects.get(driver_id= driver_id)
            except Driver.DoesNotExist:
                return Response({'error': 'Driver not found.'}, status=status.HTTP_404_NOT_FOUND)

            '''
            Toggle the driver status (active to inactive and vice versa.
            '''
            driver_status = data.get('driver_status', '').capitalize()
            if driver_status in ['Active', 'Inactive']:
                driver.driver_status = driver_status

            '''
            Reshuffle vehicle number.
            '''
            if 'vehicle_number' in data:
                vehicle_number = data.get('vehicle_number')
                driver.vehicle_number = vehicle_number

            driver.save()

            serializer = DriverSerializer(driver)
            return Response(serializer.data, status=status.HTTP_200_OK)

        else:
            existing_driver = Driver.objects.filter(phone=data['phone']).first()
            if existing_driver:
                return Response({'error': 'Driver with this phone number already exists.'},
                                status=status.HTTP_400_BAD_REQUEST)

            serializer = DriverSerializer(data=data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response({'error': 'Invalid request method.'}, status=status.HTTP_400_BAD_REQUEST)

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
    users.phone_number AS customer_phone,
    users.name AS customer_name,
    users_addresses_pickup.latitude AS customer_lat_pickup,
    users_addresses_pickup.longitude AS customer_lon_pickup,
    users_addresses_drop.latitude AS customer_lat_drop,
    users_addresses_drop.longitude AS customer_lon_drop,
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
JOIN
    users_addresses AS users_addresses_pickup ON users_addresses_pickup.phone_number = users.phone_number
    AND users_rides_detail.pickup_address_type = users_addresses_pickup.address_type
JOIN
    users_addresses AS users_addresses_drop ON users_addresses_drop.phone_number = users.phone_number
    AND users_rides_detail.drop_address_type = users_addresses_drop.address_type
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
        customer_phone = row.get('customer_phone', '')
        customer_lat_pickup = row.get('customer_lat_pickup', '')
        customer_lon_pickup = row.get('customer_lon_pickup', '')
        customer_lat_drop = row.get('customer_lat_drop', '')
        customer_lon_drop = row.get('customer_lon_drop', '')

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
                    "customer_drop_address":customer_drop_address,
                    "customer_phone": customer_phone,
                    "customer_lat_pickup": customer_lat_pickup,
                    "customer_lon_pickup": customer_lon_pickup,
                    "customer_lat_drop": customer_lat_drop,
                    "customer_lon_drop": customer_lon_drop

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
            customer_ride_id = customers['customer_ride_id']

            print(f"Processing ride_detail: {ride_detail}")

            driver, created = Driver.objects.get_or_create(driver_id=driver_id)

            existing_ride = DriverRide.objects.filter(
                ride_type=ride_type,
                ride_date_time=ride_date_time,
                driver=driver,
                customer_id = customer_id,
                customer_ride_id = customer_ride_id
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

                    customer_id=customer_id,

                    customer_ride_id = customer_ride_id
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
                customer_phone = customer_detail.get('customer_phone', None)

                customer_exists = Customer.objects.filter(
                    customer_id=customer_id,
                    driver=driver,
                    ride_date_time__date=ride_date_time.date(),
                    customer_ride_id=customer_ride_id,
                    customer_ride_status = customer_ride_status,
                    name = customer_name,
                    phone = customer_phone,
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
                        phone = customer_phone,
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


def reschedule_ride(customer_ride_id, ride_date_time):

    url = f'https://customer-mypickup.souvikmondal.live/reschedule_ride/'

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
    update_url = f'https://customer-mypickup.souvikmondal.live/edit_ride_driver_phone/{customer_ride_id}?driver_phone={driver_phone}'
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

def map_driver_customer_app_ride_status(ride_id, new_status):

    url = f'https://customer-mypickup.souvikmondal.live/updateRideStatus?ride_id={ride_id}'
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

def reschedule_and_update(customer_ride_id_info, customer_ride_datetime_str, driver_phone, ride_status):
    reschedule_ride(customer_ride_id_info, customer_ride_datetime_str)
    update_customer_sharing_rides(customer_ride_id_info, driver_phone)
    map_driver_customer_app_ride_status(customer_ride_id_info, ride_status)


'''
 If n is the total number of private rides and m is the total number of sharing rides, 
 and assuming the processing of each ride takes O(1) time
 The overall time complexity would be O(n + m).
 
'''
@api_view(['GET'])
def fetch_customer_rides(request, driver_id):

    private_queryset = Customer.objects.select_related('driver', 'driver__driverride').filter(
        Q(drop_priority__isnull=True, driver__driverride__ride_type='Private', customer_ride_status='Upcoming', driver_id=driver_id)
    ).values(
        customer_name_info=F('name'),
        customer_id_info=F('customer_id'),
        customer_phone_info=F('phone'),
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

    sharing_queryset = Customer.objects.select_related('driver', 'driver__driverride').filter(
        Q(drop_priority__isnull=False, driver__driverride__ride_type='Sharing', customer_ride_status='Upcoming', driver_id=driver_id) |
        Q(drop_priority__isnull=False, driver__driverride__ride_type='Sharing', customer_ride_status='Ongoing', driver_id=driver_id) |
        Q(drop_priority__isnull=False, driver__driverride__ride_type='Sharing', customer_ride_status='Completed',
        driver_id=driver_id) |
        Q(drop_priority__isnull=False, driver__driverride__ride_type='Sharing', customer_ride_status='Cancelled',
        driver_id=driver_id)
    ).values(
        customer_name_info=F('name'),
        customer_id_info=F('customer_id'),
        customer_phone_info=F('phone'),
        customer_ride_datetime=F('ride_date_time'),
        driver_id_info=F('driver_id'),
        customer_drop_priority_info=F('drop_priority'),
        driver_ride_type_info=F('driver__driverride__ride_type'),
        driver_phone_info=F('driver__phone'),
        customer_ride_id_info=F('customer_ride_id'),
        customer_ride_status_info=F('customer_ride_status'),
        customer_pickup_address_info=F('pickup_address'),
        customer_drop_address_info=F('drop_address'),
    ).order_by('ride_date_time').distinct()

    pairs = []

    with ThreadPoolExecutor() as executor:
        futures = []

        '''
        Processing private rides.
        '''
        for i in range(len(private_queryset)):
            pair = [private_queryset[i]]
            pairs.append(pair)

            customer_ride_id_info = private_queryset[i]['customer_ride_id_info']
            customer_ride_datetime = private_queryset[i]['customer_ride_datetime']
            driver_phone = private_queryset[i]['driver_phone_info']
            ride_status = private_queryset[i]['customer_ride_status_info']

            customer_ride_datetime_str = DjangoJSONEncoder().default(customer_ride_datetime)

            future = executor.submit(
                reschedule_and_update,
                customer_ride_id_info,
                customer_ride_datetime_str,
                driver_phone,
                ride_status
            )
            futures.append(future)
            print(f"Private Ride - Task submitted - Iteration {i + 1}, Customer Ride ID: {customer_ride_id_info}")

        '''
        Processing sharing rides.
        '''
        for i in range(0, len(sharing_queryset), 2):
            if i + 1 < len(sharing_queryset):
                pair = [sharing_queryset[i], sharing_queryset[i + 1]]
                pairs.append(pair)

                customer_ride_id_info_1 = sharing_queryset[i]['customer_ride_id_info']
                customer_ride_datetime_1 = sharing_queryset[i]['customer_ride_datetime']
                driver_phone_1 = sharing_queryset[i]['driver_phone_info']
                ride_status_1 = sharing_queryset[i]['customer_ride_status_info']

                customer_ride_datetime_str_1 = DjangoJSONEncoder().default(customer_ride_datetime_1)

                customer_ride_id_info_2 = sharing_queryset[i + 1]['customer_ride_id_info']
                customer_ride_datetime_2 = sharing_queryset[i + 1]['customer_ride_datetime']
                driver_phone_2 = sharing_queryset[i + 1]['driver_phone_info']
                ride_status_2 = sharing_queryset[i + 1]['customer_ride_status_info']

                customer_ride_datetime_str_2 = DjangoJSONEncoder().default(customer_ride_datetime_2)

                future_1 = executor.submit(
                    reschedule_and_update,
                    customer_ride_id_info_1,
                    customer_ride_datetime_str_1,
                    driver_phone_1,
                    ride_status_1
                )
                futures.append(future_1)

                future_2 = executor.submit(
                    reschedule_and_update,
                    customer_ride_id_info_2,
                    customer_ride_datetime_str_2,
                    driver_phone_2,
                    ride_status_2
                )
                futures.append(future_2)

                print(
                    f"Sharing Ride - Task submitted - Iteration {i + 1}, Customer Ride ID 1: {customer_ride_id_info_1}, Customer Ride ID 2: {customer_ride_id_info_2}")

    '''
    Wait for all submitted tasks to complete.
    '''
    for future in futures:
        result = future.result()
        print(f"Task completed - Result: {result}")

    global ongoing_sharing_rides_list
    ongoing_sharing_rides_list = pairs

    return Response(pairs, status=status.HTTP_200_OK)

@api_view(['GET'])
def fetch_all_ongoing_sharing_customer_rides(request, driver_id):

    global ongoing_sharing_rides_list

    try:
        ongoing_sharing_rides_list = validate_and_update_status(ongoing_sharing_rides_list, driver_id)
        ongoing_sharing_rides_list = remove_completed_rides(ongoing_sharing_rides_list, driver_id)
        ongoing_sharing_rides_list = remove_cancelled_rides(ongoing_sharing_rides_list, driver_id)

    except ContentNotRenderedError:
        return JsonResponse({'error': 'Content not rendered, please render it using the API fetchCustomerRides'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    new_pair = processingPairs(ongoing_sharing_rides_list, driver_id)

    return Response(new_pair, status=status.HTTP_200_OK)

def validate_and_update_status(rides_list, driver_id):


    flattened_rides_list = sum(rides_list, [])

    for ride in flattened_rides_list:
        if not isinstance(ride, dict):
            continue

        customer_ride_id = ride.get("customer_ride_id_info")
        try:
            '''
            Fetch the ride from the database.
            '''
            customer_ride = Customer.objects.get(customer_ride_id=customer_ride_id, driver_id=driver_id)

            '''
            Update the status in the list based on the fetched ride status.
            '''
            ride["customer_ride_status_info"] = customer_ride.customer_ride_status


        except Customer.DoesNotExist:
            '''
            Handle the case where the ride is not found.
            '''
            return JsonResponse({"error": "Customer does not exist"}, status=status.HTTP_404_NOT_FOUND)

    return rides_list

def remove_completed_rides(rides_list, driver_id):
    rides_to_remove = []
    flattened_rides_list = []

    for pair in rides_list:
        flattened_rides_list.extend(pair)

    for i, ride in enumerate(flattened_rides_list):
        if not isinstance(ride, dict):
            continue

        customer_ride_id = ride.get("customer_ride_id_info")
        try:
            '''
            Fetch the ride from the database.
            '''
            customer_ride = Customer.objects.get(customer_ride_id=customer_ride_id, driver_id=driver_id)

            '''
            If status is "Completed," mark this pair for removal.
            '''
            ride["customer_ride_status_info"] = customer_ride.customer_ride_status
            if customer_ride.customer_ride_status == "Completed":
                rides_to_remove.append(i)

        except Customer.DoesNotExist:
            '''
            Handle the case where the ride is not found.
            '''
            return JsonResponse({"error": "Customer does not exist"}, status=status.HTTP_404_NOT_FOUND)

    '''
    Remove pairs marked for removal in reverse order to avoid index issues.
    '''
    for i in reversed(rides_to_remove):
        flattened_rides_list.pop(i)

    '''
    Convert the modified list back to the original structure
    '''
    rides_list = [flattened_rides_list[i:i + 2] for i in range(0, len(flattened_rides_list), 2)]

    return rides_list

def remove_cancelled_rides(rides_list, driver_id):
    rides_to_remove = []
    flattened_rides_list = []

    for pair in rides_list:
        flattened_rides_list.extend(pair)

    for i, ride in enumerate(flattened_rides_list):
        if not isinstance(ride, dict):
            continue

        customer_ride_id = ride.get("customer_ride_id_info")
        try:
            '''
            Fetch the ride from the database.
            '''
            customer_ride = Customer.objects.get(customer_ride_id=customer_ride_id, driver_id=driver_id)

            '''
            If status is "Cancelled," mark this pair for removal.
            '''
            ride["customer_ride_status_info"] = customer_ride.customer_ride_status
            if customer_ride.customer_ride_status == "Cancelled":
                rides_to_remove.append(i)

        except Customer.DoesNotExist:
            '''
            Handle the case where the ride is not found.
            '''
            return JsonResponse({"error": "Customer does not exist"}, status=status.HTTP_404_NOT_FOUND)

    '''
    Remove pairs marked for removal in reverse order to avoid index issues.
    '''
    for i in reversed(rides_to_remove):
        flattened_rides_list.pop(i)

    '''
    Convert the modified list back to the original structure
    '''
    rides_list = [flattened_rides_list[i:i + 2] for i in range(0, len(flattened_rides_list), 2)]

    return rides_list

def processingPairs(ongoing_sharing_rides_list, driver_id):
    new_ongoing_pair = []

    flattened_list = sum(ongoing_sharing_rides_list, [])

    for pair in flattened_list:
        if not isinstance(pair, dict):
            continue

        if pair.get("driver_ride_type_info") == 'Sharing' and pair.get("driver_id_info") == driver_id:
            new_ongoing_pair.append({"customer_name_info": pair.get("customer_name_info"),
                                     "customer_id_info": pair.get("customer_id_info"),
                                     "customer_phone_info": pair.get("customer_phone_info"),
                                     "customer_ride_datetime": pair.get("customer_ride_datetime"),
                                     "driver_phone_info": pair.get("driver_phone_info"),
                                     "driver_id_info": pair.get("driver_id_info"),
                                     "customer_drop_priority_info":pair.get("customer_drop_priority_info"),
                                     "driver_ride_type_info": pair.get("driver_ride_type_info"),
                                     "customer_ride_id_info": pair.get("customer_ride_id_info"),
                                     "customer_ride_status_info": pair.get("customer_ride_status_info"),
                                     "customer_pickup_address_info": pair.get("customer_pickup_address_info"),
                                     "customer_drop_address_info": pair.get("customer_drop_address_info")})
    return new_ongoing_pair



@api_view(['POST'])
def start_ride(request):
    try:
        customer_ride_id = request.data.get('customer_ride_id')
        driver_id = request.data.get('driver_id')
        ride_type = request.data.get('ride_type')

        with transaction.atomic():
            valid_ride = Customer.objects.select_for_update().filter(
                customer_ride_id=customer_ride_id,
                driver_id=driver_id,
                customer_ride_status='Upcoming',
                driver__driverride__ride_type=ride_type
            ).first()

            if not valid_ride:
                return Response({"status": "error", "message": "Invalid customer_ride_id, driver_id, or ride_type"},
                                status=status.HTTP_400_BAD_REQUEST)

            update_result = map_driver_customer_app_ride_status(customer_ride_id, 'Ongoing')

            if update_result.get('status_code') == 200:
                valid_ride.customer_ride_status = 'Ongoing'
                valid_ride.save()

                return Response({"status": "success", "message": "Ride started successfully"},
                                status=status.HTTP_200_OK)
            else:
                return Response({"status": "error", "message": "Failed to update customer app ride status"},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except IntegrityError as e:
        transaction.set_rollback(True)
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
def end_ride(request):
    try:
        customer_ride_id = request.data.get('customer_ride_id')
        driver_id = request.data.get('driver_id')
        ride_type = request.data.get('ride_type')

        with transaction.atomic():
            valid_ride = Customer.objects.select_for_update().filter(
                customer_ride_id=customer_ride_id,
                driver_id=driver_id,
                customer_ride_status='Ongoing',
                driver__driverride__ride_type=ride_type
            ).first()

            if not valid_ride:
                return Response({"status": "error", "message": "Invalid customer_ride_id, driver_id, or ride_type"},
                                status=status.HTTP_400_BAD_REQUEST)

            update_result = map_driver_customer_app_ride_status(customer_ride_id, 'Completed')

            if update_result.get('status_code') == 200:
                valid_ride.customer_ride_status = 'Completed'
                valid_ride.save()

                return Response({"status": "success", "message": "Ride ended successfully"},
                                status=status.HTTP_200_OK)
            else:
                return Response({"status": "error", "message": "Failed to update customer app ride status"},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except IntegrityError as e:
        transaction.set_rollback(True)
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
def cancel_customer_ride(request):
    serializer = CancelRideSerializer(data=request.data)
    if serializer.is_valid():
        customer_ride_ids = serializer.validated_data.get('customer_ride_ids', [])

        customers = Customer.objects.filter(customer_ride_id__in=customer_ride_ids)

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
def fetch_all_ongoing_private_customer_rides(request, driver_id):

    ongoing_queryset = Customer.objects.select_related('driver', 'driver__driverride').filter(
        Q(drop_priority__isnull=True, driver__driverride__ride_type='Private', customer_ride_status='Ongoing',
          driver_id=driver_id)
    ).values(
        customer_name_info=F('name'),
        customer_id_info=F('customer_id'),
        customer_ride_datetime=F('ride_date_time'),
        customer_phone_info=F('phone'),
        driver_phone_info=F('driver__phone'),
        driver_id_info=F('driver_id'),
        customer_drop_priority_info=F('drop_priority'),
        driver_ride_type_info=F('driver__driverride__ride_type'),
        customer_ride_id_info=F('customer_ride_id'),
        customer_ride_status_info=F('customer_ride_status'),
        customer_pickup_address_info=F('pickup_address'),
        customer_drop_address_info=F('drop_address'),
    ).order_by('ride_date_time').distinct()

    pairs = []
    for i in range(len(ongoing_queryset)):
        pair = [ongoing_queryset[i]]
        pairs.append(pair)

    return Response(pairs, status=status.HTTP_200_OK)

@api_view(['PUT'])
def update_customer_driver(request, customer_ride_id):
    try:
        customer = Customer.objects.get(customer_ride_id=customer_ride_id)
    except Customer.DoesNotExist:
        return Response({'error': 'Customer not found with the specified customer_ride_id'},
                        status=status.HTTP_404_NOT_FOUND)

    if request.method == 'PUT':
        '''
        Including only the driver_id field for partial updates.
        '''
        serializer = CustomerSerializer(customer, data={'driver_id': request.data.get('driver_id')}, partial=True)
        if serializer.is_valid():
            serializer.save()

            '''
            Update the related driver in Customer table.
            '''
            new_driver_id = request.data.get('driver_id')
            if new_driver_id is not None:
                customer.driver_id = new_driver_id
                customer.save()

                '''
                Update the driver_id in the DriverRide table.
                '''
                try:
                    driver_ride = DriverRide.objects.get(customer_ride_id=customer.customer_ride_id)
                    driver_ride.driver_id = new_driver_id
                    driver_ride.save()
                except DriverRide.DoesNotExist:
                    '''
                    Handle the case where DriverRide entry doesn't exist for the given customer
                    '''
                    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            return Response({'status': 'Customer driver_id updated successfully'},
                            status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)







