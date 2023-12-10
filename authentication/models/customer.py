from django.contrib.auth.models import User
from django.db import models


# Create your models here.
class Customer(User):
    bio = models.TextField(verbose_name="Bio info", max_length=500, blank=True)
    birth_date = models.DateField(verbose_name="Birth date", null=True, blank=True)
    address = models.CharField(verbose_name="Address", max_length=30, blank=True)

    class Meta:
        db_table = "customer"
        verbose_name = "Customer"
        verbose_name_plural = "Customers"
