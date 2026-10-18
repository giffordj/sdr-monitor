import ipaddress
import logging

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login
from django.contrib.auth.backends import ModelBackend

logger = logging.getLogger("Authelia")


def get_header(request, setting_name):
    meta_key = getattr(settings, setting_name, "")
    if not meta_key:
        return ""
    return request.META.get(meta_key, "")


def parse_groups(value):
    return [group.strip() for group in value.replace(";", ",").split(",") if group.strip()]


class AutheliaBackend(ModelBackend):
    def authenticate(self, request, remote_user=None, remote_groups=None, remote_email="", remote_name="", **kwargs):
        if not remote_user:
            return None

        username = remote_user.strip()[:150]
        if not username:
            return None

        UserModel = get_user_model()
        groups = set(remote_groups or [])
        is_admin = bool(groups & set(getattr(settings, "AUTHELIA_ADMIN_GROUPS", [])))
        if getattr(settings, "AUTHELIA_ALL_STAFF", False):
            is_admin = True
        logger.info("authelia auth: user=%s groups=%s admin=%s", username, sorted(groups), is_admin)

        user = UserModel.objects.filter(username=username).first()
        created = user is None
        if created:
            user = UserModel(username=username)
            user.set_unusable_password()

        update_fields = []
        if remote_email and user.email != remote_email:
            user.email = remote_email
            update_fields.append("email")
        if remote_name:
            first_name, _, last_name = remote_name.partition(" ")
            if user.first_name != first_name:
                user.first_name = first_name
                update_fields.append("first_name")
            if user.last_name != last_name:
                user.last_name = last_name
                update_fields.append("last_name")
        if user.is_staff != is_admin:
            user.is_staff = is_admin
            update_fields.append("is_staff")
        if user.is_superuser != is_admin:
            user.is_superuser = is_admin
            update_fields.append("is_superuser")

        if created:
            user.save()
            logger.info("created user from authelia: %s", username)
        elif update_fields:
            user.save(update_fields=update_fields)
        return user

    def get_user(self, user_id):
        UserModel = get_user_model()
        try:
            return UserModel.objects.get(pk=user_id)
        except UserModel.DoesNotExist:
            return None


class AutheliaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, "AUTHELIA_AUTH_ENABLED", False):
            self.authenticate_request(request)
        return self.get_response(request)

    def authenticate_request(self, request):
        if not self.is_trusted(request):
            logger.warning("ignoring authelia headers from untrusted remote address: %s", request.META.get("REMOTE_ADDR"))
            return

        username = get_header(request, "AUTHELIA_USER_HEADER").strip()
        if not username:
            return

        user = authenticate(
            request,
            remote_user=username,
            remote_groups=parse_groups(get_header(request, "AUTHELIA_GROUPS_HEADER")),
            remote_email=get_header(request, "AUTHELIA_EMAIL_HEADER").strip(),
            remote_name=get_header(request, "AUTHELIA_NAME_HEADER").strip(),
        )
        if user is None:
            return
        if request.user.is_authenticated and request.user.username == user.username:
            return
        login(request, user)
        logger.info("logged in user from authelia: %s", username)

    def is_trusted(self, request):
        trusted_proxies = getattr(settings, "AUTHELIA_TRUSTED_PROXIES", [])
        if not trusted_proxies:
            return True
        try:
            remote = ipaddress.ip_address(request.META.get("REMOTE_ADDR", ""))
        except ValueError:
            return False
        for entry in trusted_proxies:
            try:
                if "/" in entry:
                    if remote in ipaddress.ip_network(entry, strict=False):
                        return True
                elif remote == ipaddress.ip_address(entry):
                    return True
            except ValueError:
                logger.warning("invalid AUTHELIA_TRUSTED_PROXIES entry: %s", entry)
        return False
