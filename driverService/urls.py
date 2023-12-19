from django.urls import path
from . import views

urlpatterns = [
    path('fetchDrivers/<int:driver_id>/', views.get_drivers, name='get-drivers'),
    path('createDrivers/', views.create_driver, name='create-driver'),
    path('awake/', views.awake, name='awake'),
]