from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework_simplejwt.tokens import RefreshToken

class TestCalls(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="nguyen.hung", password="1234ABbcd!@", email="nguyen.hung@gmail.com")

    def test_call_register(self):
        data = {
            "username": "bao.binh",
            "password": "1234ABbcd!@",
            "email": "bao.binh@gmail.com",
            "first_name": "bao",
            "last_name": "binh"
        }

        response = self.client.post("/api/v1/auth/register/", data, content_type="application/json")

        self.assertEqual(response.status_code, 201)
        self.assertIn("username", response.json())
        self.assertIn("email", response.json())
        self.assertIn("first_name", response.json())
        self.assertIn("last_name", response.json())
        self.assertEqual(response.json().get("username"), "bao.binh")

    def test_call_login(self):
        data = {
            "username": "nguyen.hung",
            "password": "1234ABbcd!@"
        }

        response = self.client.post("/api/v1/auth/login/", data, content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
        self.assertIn("refresh", response.json())

    def test_call_refresh_token(self):
        refresh = RefreshToken.for_user(TestCalls.user)
        data = {
            "refresh": str(refresh),
        }

        response = self.client.post("/api/v1/auth/token/refresh/", data, content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
