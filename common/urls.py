from django.urls import include, path
import common.views

urlpatterns = [
    path("language/<str:language>", common.views.language, name="language"),
]
