from django.urls import path
from . import views

urlpatterns = [
    path('fetchDrivers/<str:phone>/', views.get_drivers, name='get-drivers'),
    path('createDrivers/', views.create_driver, name='create-driver'),
    path('generateOtp/', views.generate_otp, name='generate-otp'),
    path('verifyOtp/', views.verify_otp, name='verify-otp'),
    #path('deleteExpiredOtp/<str:phone>/', views.delete_expired_otp, name='delete-expired-otp'),
    path('awake/', views.awake, name='awake'),
]