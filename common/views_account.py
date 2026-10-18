from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _


class CustomAuthenticationForm(AuthenticationForm):
    username = forms.CharField(label=_("USERNAME OR EMAIL"))


@login_required
def account(request):
    return render(request, "account/account.html")
