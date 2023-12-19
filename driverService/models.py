from django.db import models

class Driver(models.Model):
    driver_id = models.AutoField(primary_key = True)
    driver_status = models.CharField(max_length = 12, default='default_value_here')
    current_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    current_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    assigned_users = models.ManyToManyField('UserInfo', blank=True)
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=12)
    vehicle_number = models.CharField(max_length=20)
    vehicle_model = models.CharField(max_length=255)
    track_url = models.URLField(null=True, blank=True)



class UserInfo(models.Model):
    phone = models.CharField(max_length=12)

class VerificationCode(models.Model):
    phone_number = models.CharField(max_length=12, null=False)
    code = models.CharField(max_length=6, null=False)
    created_at = models.DateTimeField(auto_now_add=True)
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('expired', 'Expired'),
    ]
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')











