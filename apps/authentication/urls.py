from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import signup_view, login_view, logout_view

urlpatterns = [
    path("signup/", signup_view, name="signup"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("refresh/", TokenRefreshView.as_view(), name="token_refresh"),
]
