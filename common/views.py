from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _


def load_settings(request):
    return {
        "LANGUAGES": settings.LANGUAGES,
        "TITLE_CLASS": settings.TITLE_CLASS,
    }


@login_required
def home(request):
    # Imported lazily so the home page does not pull in the heavy SDR stack
    # (gnuradio/numpy) at import time.
    from sdr.models import Device, GainTest, Group, Spectrogram, Transmission

    context = {
        "transmission_count": Transmission.objects.count(),
        "spectrogram_count": Spectrogram.objects.count(),
        "group_count": Group.objects.count(),
        "device_count": Device.objects.count(),
        "gain_test_count": GainTest.objects.count(),
        "recent_transmissions": Transmission.objects.select_related("device", "group", "audio_class").order_by("-begin_date")[:8],
        "recent_spectrograms": Spectrogram.objects.select_related("device").order_by("-begin_real_date")[:8],
        "latest_transmission": Transmission.objects.order_by("-begin_date").first(),
    }
    return render(request, "home.html", context)


def language(request, language):
    response = HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))
    if language in dict(settings.LANGUAGES):
        request.session["django_language"] = language
        response.set_cookie(
            settings.LANGUAGE_COOKIE_NAME,
            language,
            max_age=settings.LANGUAGE_COOKIE_AGE,
            path=settings.LANGUAGE_COOKIE_PATH,
            domain=settings.LANGUAGE_COOKIE_DOMAIN,
            secure=settings.LANGUAGE_COOKIE_SECURE,
            httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
            samesite=settings.LANGUAGE_COOKIE_SAMESITE,
        )
    return response
