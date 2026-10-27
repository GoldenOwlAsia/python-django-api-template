from django.contrib.auth import get_user_model
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt import serializers as jwt_serializers


class TokenRefreshSerializer(jwt_serializers.TokenRefreshSerializer):
    # simplejwt 5.5.1 answers 500 when the token's user was deleted. Drop this
    # class once a release includes the upstream fix (simplejwt PR #860).
    def validate(self, attrs):
        try:
            return super().validate(attrs)
        except get_user_model().DoesNotExist:
            raise AuthenticationFailed(
                self.error_messages["no_active_account"], "no_active_account"
            )
