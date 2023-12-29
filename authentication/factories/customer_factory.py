from faker import Faker
from authentication.models import Customer
import factory

fake = Faker()

class CustomerFactory(factory.django.DjangoModelFactory):
    username =  fake.profile()['username']
    password = fake.password()
    email = fake.email()
    bio = fake.text()
    birth_date = fake.date_object()
    address = fake.address()

    class Meta:
        model = Customer
