from django.urls import path
import common.views_account
import django.contrib.auth.views

urlpatterns = [
    path("", common.views_account.account, name="account"),
    path(
        "login/", django.contrib.auth.views.LoginView.as_view(template_name="account/login.html", authentication_form=common.views_account.CustomAuthenticationForm), name="login"
    ),
    path("logout/", django.contrib.auth.views.LogoutView.as_view(), name="logout"),
    path("password/change/", django.contrib.auth.views.PasswordChangeView.as_view(template_name="account/password_change.html"), name="password_change"),
    path("password/change/done/", django.contrib.auth.views.PasswordChangeDoneView.as_view(template_name="account/password_change_done.html"), name="password_change_done"),
    path(
        "password/reset/complete/",
        django.contrib.auth.views.PasswordResetCompleteView.as_view(template_name="account/password_reset_complete.html"),
        name="password_reset_complete",
    ),
    path(
        "password/reset/confirm/<uidb64>/<token>/",
        django.contrib.auth.views.PasswordResetConfirmView.as_view(template_name="account/password_reset_confirm.html"),
        name="password_reset_confirm",
    ),
    path("password/reset/done/", django.contrib.auth.views.PasswordResetDoneView.as_view(template_name="account/password_reset_done.html"), name="password_reset_done"),
    path("password/reset/", django.contrib.auth.views.PasswordResetView.as_view(template_name="account/password_reset.html"), name="password_reset"),
]
