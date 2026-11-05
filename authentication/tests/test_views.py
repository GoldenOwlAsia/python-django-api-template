from django.contrib.auth.models import User
from django.test import TestCase
from faker import Faker
from rest_framework_simplejwt.tokens import RefreshToken

fake = Faker()


class TestCalls(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = fake.password()
        cls.username = fake.profile()["username"]
        cls.email = fake.email()
        cls.customer = User.objects.create_user(
            username=cls.username,
            password=cls.password,
            email=cls.email,
        )

    def test_call_register(self):
        user_name = fake.profile()["username"]
        data = {
            "username": user_name,
            "password": fake.password(),
            "email": fake.email(),
        }

        response = self.client.post(
            "/api/v1/auth/register/", data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 201)
        self.assertIn("username", response.json())
        self.assertIn("email", response.json())
        self.assertEqual(response.json().get("username"), user_name)

    def test_call_login(self):
        data = {"username": TestCalls.username, "password": TestCalls.password}

        response = self.client.post(
            "/api/v1/auth/login/", data, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
        self.assertIn("refresh", response.json())

    def test_call_refresh_token(self):
        refresh = RefreshToken.for_user(TestCalls.customer)
        data = {
            "refresh": str(refresh),
        }

        response = self.client.post(
            "/api/v1/auth/token/refresh/", data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())

    def test_call_refresh_token_of_deleted_user(self):
        user = User.objects.create_user(
            username=fake.profile()["username"], password=fake.password()
        )
        refresh = RefreshToken.for_user(user)
        user.delete()

        response = self.client.post(
            "/api/v1/auth/token/refresh/",
            {"refresh": str(refresh)},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
