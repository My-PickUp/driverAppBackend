from django.urls import path
from driverService import views

urlpatterns = [
    path('fetchDrivers/<str:phone>/', views.get_drivers, name='get-drivers'),
    path('createDrivers/', views.create_driver, name='create-driver'),
    path('generateOtp/', views.generate_otp, name='generate-otp'),
    path('verifyOtp/', views.verify_otp, name='verify-otp'),
    path('getDriverDetails/', views.get_driver_details, name='get-driver-details'),
    path('getCustomerDetails/',views.get_customer_details, name='get-upcoming-rides'),
    path('rideDetailsUpload/', views.form_upload_response, name='ride-details-upload'),
    path('cancelCustomerRide/', views.cancel_customer_ride, name='cancel-customer-ride'),
    path('customerRideReschedule/', views.reschedule_customer_ride, name='reschedule-customer-ride'),
    path('updateCustomerDriver/<int:customer_ride_id>/', views.update_customer_driver, name='update-customer-driver'),
    path('endRide/', views.end_ride, name='end-ride'),
    path('startRide/', views.start_ride, name='start-ride'),
    path('fetchOngoingPrivateCustomers/<int:driver_id>/', views.fetch_all_ongoing_private_customer_rides, name='fetch-all-ongoing-private-customer-rides'),
    path('fetchOngoingSharingCustomers/<int:driver_id>/', views.fetch_all_ongoing_sharing_customer_rides, name='fetch-all-ongoing-sharing-customer-rides'),
    path('fetchCustomerRides/<int:driver_id>/', views.fetch_customer_rides, name='fetch-customer-rides'),
    path('awake/', views.awake, name='awake'),
]