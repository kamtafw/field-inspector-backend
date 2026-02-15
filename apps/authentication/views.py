from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.db import IntegrityError
import re

from .models import User


def generate_email(first_name: str, last_name: str) -> tuple[str, str]:
    """
    Generate email from first and last name
    Format firstname.lastname@vantage.com

    Returns: (base_email, final_email)
    """
    first = re.sub(r"[^a-z0-9]", "", first_name.lower().strip())
    last = re.sub(r"[^a-z0-9]", "", last_name.lower().strip())

    if not first or not last:
        raise ValueError("First name and last name must contain valid characters")

    base_email = f"{first}.{last}@vantage.com"
    return base_email, base_email


def generate_unique_email(first_name: str, last_name: str) -> str:
    """
    Generate unique email, adding numbers if needed
    Examples:
    - john.doe@vantage.com
    - john.doe2@vantage.com
    - john.doe3@vantage.com
    """
    base_email, current_email = generate_email(first_name, last_name)

    if not User.objects.filter(email=current_email).exists():
        return current_email

    counter = 2
    base_without_domain = base_email.split("@")[0]

    while counter < 100:
        current_email = f"{base_without_domain}{counter}@vantage.com"

        if not User.objects.filter(email=current_email).exists():
            return current_email

        counter += 1

    import time

    timestamp = int(time.time())
    return f"{base_without_domain}{timestamp}@vantage.com"


@api_view(["POST"])
@permission_classes([AllowAny])
def signup_view(request):
    """
    Signup endpoint with auto-generated email

    POST /api/auth/signup/
    {
        "first_name": "John",
        "last_name": "Doe",
        "password": "securepassword123"
    }

    Returns:
    {
        "access": "jwt_token",
        "refresh": "jwt_token",
        "user": {
            "id": "uuid",
            "email": "john.doe@vantage.com",
            "first_name": "John",
            "last_name": "Doe",
            "role": "inspector"
        }
    }
    """
    first_name = request.data.get("first_name", "").strip()
    last_name = request.data.get("last_name", "").strip()
    password = request.data.get("password")

    if not first_name:
        return Response({"error": "First name is required"}, status=status.HTTP_400_BAD_REQUEST)

    if not last_name:
        return Response({"error": "Last name is required"}, status=status.HTTP_400_BAD_REQUEST)

    if not password:
        return Response({"error": "Password is required"}, status=status.HTTP_400_BAD_REQUEST)

    if len(password) < 8:
        return Response({"error": "Password must be at least 8 characters"}, status=status.HTTP_400_BAD_REQUEST)

    # generate unique email
    try:
        email = generate_unique_email(first_name, last_name)
    except ValueError as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    # create user
    try:
        user = User.objects.create_user(
            email=email,
            password=password,
            first_name=first_name.title(),
            last_name=last_name.title(),
            role="inspector",
        )

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "role": user.role,
                },
            },
            status=status.HTTP_201_CREATED,
        )
    except IntegrityError:
        return Response({"error": "An account with this name already exists. Please contact support."}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({"error": f"Signup failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    """
    Login endpoint for JWT authentication
    returns: JWT refresh and access tokens
    """
    email = request.data.get("email").strip()
    password = request.data.get("password")

    if not email or not password:
        return Response({"error": "Email and password are required"}, status=status.HTTP_400_BAD_REQUEST)

    user = authenticate(request, email=email, password=password)

    if not user:
        return Response({"error": "Invalid email or password"}, status=status.HTTP_401_UNAUTHORIZED)

    refresh = RefreshToken.for_user(user)
    return Response(
        {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": {
                "id": str(user.id),
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "role": getattr(user, "role", "inspector"),
            },
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    refresh_token = request.data.get("refresh") or request.COOKIES.get("refresh_token")

    if refresh_token is None:
        return Response({"error": "No refresh token provided."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        token = RefreshToken(refresh_token)
        token.blacklist()

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    response = Response(status=204)
    response.delete_cookie("refresh_token")

    return response
