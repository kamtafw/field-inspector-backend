from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    """
    Login endpoint for JWT authentication
    returns: JWT refresh and access tokens
    """
    email = request.data.get("email")
    password = request.data.get("password")

    if not email or not password:
        return Response({"error": "Email and password are required."}, status=status.HTTP_400_BAD_REQUEST)

    user = authenticate(request, email=email, password=password)

    if not user:
        return Response({"error": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

    refresh = RefreshToken.for_user(user)
    return Response(
        {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": {
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "role": getattr(user, "role", "inspector"),  # inspector as default role
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
