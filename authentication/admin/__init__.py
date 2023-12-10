from django.contrib import admin

from authentication.models import *

from .customer_admin import CustomerAdmin

register_list = (
    (
        Customer,
        CustomerAdmin,
    ),
)

for register_item in register_list:
    admin.site.register(*register_item)
