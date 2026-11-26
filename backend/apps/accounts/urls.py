from django.urls import path

from .views import LoginView, LogoutView, SessionView

urlpatterns = [
    path("auth/session/", SessionView.as_view(), name="auth-session"),
    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
]
