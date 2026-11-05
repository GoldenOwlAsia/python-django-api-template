from django.db import models

# Create your models here.


class BaseModel(models.Model):
    created_at = models.DateTimeField(verbose_name="Created At", auto_now_add=True)
    updated_at = models.DateTimeField(verbose_name="Updated At", auto_now=True)

    class Meta:
        abstract = True
