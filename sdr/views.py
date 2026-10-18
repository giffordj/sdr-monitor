from common.helpers import *
from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import F, Count, Min, Max
from django.db.models.functions import TruncSecond, TruncDate, Length
from django.http import Http404
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.utils.timezone import localtime
from django.views.decorators.http import require_POST
from sdr.app_settings import *
from sdr.models import *
from sdr.signals import *
import common.helpers
import common.utils.files
import common.utils.filters
import logging
import monitor.settings
import os
import numpy as np
import sdr.drawer
import sdr.utils.group
import sdr.utils.scanner_mqtt
import sdr.utils.satellites
import sdr.utils.transmission
import uuid


PAGE_SIZE_DEFAULT = 100
PAGE_SIZE_MAX = 1000


def get_page_size(request):
    try:
        value = int(request.GET.get("page_size", PAGE_SIZE_DEFAULT))
    except (TypeError, ValueError):
        return PAGE_SIZE_DEFAULT
    if value < 1:
        return PAGE_SIZE_DEFAULT
    return min(value, PAGE_SIZE_MAX)


def get_download_filename(name, id, extension, dt):
    return "%s%d_%s.%s" % (name, id, localtime(dt).strftime("%Y%m%d_%H%M%S"), extension)


def get_download_raw_iq_filename(name, id, type, extension, frequency, sample_rate, dt):
    return "%s%d_%s_%d_%d_%s.%s" % (name, id, localtime(dt).strftime("%Y%m%d_%H%M%S"), frequency, sample_rate, type, extension)


def mhz_to_hz(value):
    return int(round(float(str(value).strip().replace(",", ".")) * 1000000))


def convert_frequency_filters(request, fields):
    params = request.GET.copy()
    converted = False
    for field in fields:
        for suffix in ("", "__gte", "__lte", "__gt", "__lt"):
            key = field + suffix
            value = params.get(key)
            if not value:
                continue
            # Supports plain values and natural expressions ("1-10", ">2").
            hz = common.utils.filters.mhz_expression_to_hz(value)
            if hz is None:
                continue
            params[key] = hz
            converted = True
    if converted:
        request.GET = params


@login_required()
@permission_required("sdr.view_spectrogram", raise_exception=True)
def spectrograms(request):
    if AppSettings.get(AppSettingsKey.GAIN_TESTER_DATA_ENABLED):
        items = Spectrogram.objects
    else:
        items = Spectrogram.objects.exclude(source="gain tester")
    items = items.select_related("device").annotate(
        device_name=F("device__name"),
        datetime=F("end_real_date"),
        date=TruncDate("begin_model_date"),
        samples=Length("labels") / 8,
        sample_rate=F("end_frequency") - F("begin_frequency"),
        frequency=F("begin_frequency") + (F("end_frequency") - F("begin_frequency")) / 2,
        duration=TruncSecond("end_real_date") - TruncSecond("begin_real_date"),
    )
    options_lists = common.utils.filters.get_options_lists(request, items, ["device_name", "source"])
    items = common.utils.filters.filter(request, items)
    items = common.utils.filters.order_by(request, items, ["-datetime", "frequency", "device_name"])
    page_size = get_page_size(request)
    items = Paginator(items, page_size).get_page(request.GET.get("page"))
    context = {
        "items": items,
        "spectrograms_keep_count": AppSettings.get(AppSettingsKey.SPECTROGRAMS_KEEP_COUNT),
    }
    return render(request, "spectrograms.html", dict(context, **options_lists))


@login_required()
@permission_required("sdr.view_spectrogram", raise_exception=True)
def spectrogram(request, spectrogram_id):
    mode = request.GET.get("mode", "static")
    spectrogram = get_object_or_404(
        Spectrogram.objects.annotate(
            samples=Length("labels") / 8,
            sample_rate=F("end_frequency") - F("begin_frequency"),
            frequency=F("begin_frequency") + (F("end_frequency") - F("begin_frequency")) / 2,
            duration=TruncSecond("end_real_date") - TruncSecond("begin_real_date"),
        ),
        id=spectrogram_id,
    )
    return render(request, "spectrogram.html", {"spectrogram": spectrogram, "mode": mode})


@login_required()
@permission_required("sdr.view_spectrogram", raise_exception=True)
def spectrogram_data(request, spectrogram_id):
    format = request.GET.get("format", "image")
    s = get_object_or_404(Spectrogram, id=spectrogram_id)
    if format == "image":
        data_type = request.GET.get("data", "")
        # Cache the rendered image: drawing costs ~0.5 s CPU and several MB per
        # request, and the pages load the same rows over and over. The key
        # includes the labels/data sizes, so a row that grows gets a new file;
        # the worker prunes files older than a few days (see Cleaner).
        image_cache_dir = os.path.join(monitor.settings.BASE_DIR, "data", "image_cache")
        os.makedirs(image_cache_dir, exist_ok=True)
        cached_filename = os.path.join(image_cache_dir, "%s_%s_%s_%s.jpg" % (
            s.id, data_type or "full", len(s.labels), s.data_file.size))
        if not os.path.exists(cached_filename):
            y_labels = np.frombuffer(s.labels, dtype=np.uint64)
            y_size = y_labels.size
            x_size = s.data_file.file.size // y_size
            data = np.memmap(s.data_file.path, dtype=np.int8, mode="r", shape=(y_size, x_size))

            kwargs = {"draw_frequency": False, "draw_power": False, "draw_time": False, "draw_data": False}
            if data_type == "left":
                kwargs["draw_time"] = True
            elif data_type == "top":
                kwargs["draw_power"] = True
                kwargs["draw_frequency"] = True
            elif data_type == "main":
                kwargs["draw_data"] = True
            else:
                kwargs = {}

            # Render to a .jpg temp name (OpenImageIO picks the format from the
            # extension), then atomically move it into the cache.
            tmp_filename = "%s.%s.jpg" % (cached_filename[:-4], uuid.uuid4().hex)
            drawer = sdr.drawer.Drawer(frequency_labels_count=(s.end_frequency - s.begin_frequency) // 200000, **kwargs)
            drawer.draw_spectrogram(data, tmp_filename, x_size, y_size, s.begin_frequency, s.end_frequency, y_labels)
            os.replace(tmp_filename, cached_filename)
        return file_response(cached_filename, get_download_filename("spectrogram", s.id, "jpg", s.begin_real_date), remove=False)
    elif format == "raw":
        filename = get_download_filename("spectrogram", s.id, "raw", s.begin_real_date)
        return redirect_file_response(filename, s.data_file.url)
    raise Http404()


@login_required()
@permission_required("sdr.view_transmission", raise_exception=True)
def transmissions(request):
    if AppSettings.get(AppSettingsKey.GAIN_TESTER_DATA_ENABLED):
        items = Transmission.objects
    else:
        items = Transmission.objects.exclude(source="gain tester")
    items = (
        items.select_related("device")
        .select_related("group")
        .annotate(
            device_name=F("device__name"),
            group_name=F("group__name"),
            modulation=F("group__modulation"),
            datetime=F("begin_date"),
            duration=TruncSecond("end_date") - TruncSecond("begin_date"),
            frequency=F("begin_frequency") + (F("end_frequency") - F("begin_frequency")) / 2,
            class_name=F("audio_class__name"),
            class_subname=F("audio_class__subname"),
        )
    )
    options_lists = common.utils.filters.get_options_lists(request, items, ["device_name", "modulation", "group_name", "class_name"])
    items = common.utils.filters.filter(request, items)
    items = common.utils.filters.order_by(request, items, ["-datetime", "frequency"])
    page_size = get_page_size(request)
    items = Paginator(items, page_size).get_page(request.GET.get("page"))
    return render(request, "transmissions.html", dict({"items": items}, **options_lists))


@login_required()
@permission_required("sdr.view_transmission", raise_exception=True)
def transmission(request, transmission_id):
    transmission = get_object_or_404(
        Transmission.objects.annotate(
            duration=TruncSecond("end_date") - TruncSecond("begin_date"),
            sample_rate=F("end_frequency") - F("begin_frequency"),
            frequency=F("begin_frequency") + (F("end_frequency") - F("begin_frequency")) / 2,
        ),
        id=transmission_id,
    )
    return render(request, "transmission.html", {"transmission": transmission})


@login_required()
@permission_required("sdr.view_transmission", raise_exception=True)
def transmission_data(request, transmission_id):
    format = request.GET.get("format")
    t = get_object_or_404(Transmission, id=transmission_id)
    data = np.memmap(t.data_file.path, dtype=np.uint8, mode="r")
    sample_rate = t.end_frequency - t.begin_frequency
    if format == "spectrogram":
        filename = get_download_filename("transmission", t.id, "jpg", t.begin_date)
        data = make_spectrogram(data, sample_rate)
        drawer = sdr.drawer.Drawer(frequency_labels_count=8, draw_time=False, draw_power=True, text_size=16, text_stroke=2, min_width=1024)
        drawer.draw_spectrogram(data, filename, data.shape[1], data.shape[0], t.begin_frequency, t.end_frequency, list(range(data.shape[0])))
        return file_response(filename)
    elif format == "gqrx":
        filename = get_download_raw_iq_filename("transmission", t.id, "fc", "raw", t.middle_frequency(), sample_rate, t.begin_date)
        return streaming_file_response(filename, convert_uint8_to_float32_stream(t.data_file.path), t.data_file.size * 4)
    elif format == "raw_wav":
        filename = get_download_filename("transmission", t.id, "wav", t.begin_date)
        header = wav_header_from_cu8_pcm16(t.data_file.path, sample_rate)
        return streaming_file_response(filename, wav_stream_from_cu8_pcm16(t.data_file.path, sample_rate), len(header) + t.data_file.size * 2)
    elif format == "raw":
        filename = get_download_filename("transmission", t.id, "bin", t.begin_date)
        return redirect_file_response(filename, t.data_file.url)
    elif t.group.modulation in ["FM", "AM"]:
        filename = get_download_filename("transmission", t.id, "wav", t.begin_date)
        sdr.signals.decode_audio(t.data_file.path, filename, t.group.modulation, sample_rate)
        return file_response(filename)
    raise Http404()


@staff_member_required()
@permission_required("sdr.change_group", raise_exception=True)
def groups(request):
    convert_frequency_filters(request, ["begin_frequency", "end_frequency"])
    items = Group.objects.annotate(bandwidth=F("end_frequency") - F("begin_frequency"), transmissions_count=Count("transmission"))
    options_lists = common.utils.filters.get_options_lists(request, items, ["name", "modulation"])
    items = common.utils.filters.filter(request, items)
    items = common.utils.filters.order_by(request, items, ["begin_frequency", "-bandwidth"])
    page_size = get_page_size(request)
    items = Paginator(items, page_size).get_page(request.GET.get("page"))
    context = {"items": items, "modulation_choices": sdr.utils.group.get_modulation_choices()}
    return render(request, "groups.html", dict(context, **options_lists))


@staff_member_required()
@permission_required("sdr.change_group", raise_exception=True)
def update_groups(request):
    sdr.utils.group.update_groups()


@staff_member_required()
@permission_required("sdr.change_group", raise_exception=True)
@require_POST
def add_group(request):
    try:
        name, begin_frequency, end_frequency, modulation = parse_group_form(request)
        Group.objects.get_or_create(name=name, begin_frequency=begin_frequency, end_frequency=end_frequency, modulation=modulation)
        sdr.utils.group.update_groups()
        messages.success(request, "Success!")
    except Exception as e:
        logging.getLogger("Group").exception("failed to add group")
        messages.error(request, "Error: %s" % e)
    return redirect("sdr_groups")


def parse_group_form(request):
    name = request.POST["name"].strip()
    if not name:
        raise ValueError("Name is required.")
    begin_frequency = mhz_to_hz(request.POST["begin_frequency"])
    end_frequency = mhz_to_hz(request.POST["end_frequency"])
    if begin_frequency > end_frequency:
        raise ValueError("Begin frequency must not exceed end frequency.")
    modulation = request.POST["modulation"]
    return name, begin_frequency, end_frequency, modulation


@staff_member_required()
@permission_required("sdr.change_group", raise_exception=True)
@require_POST
def edit_group(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    try:
        name, begin_frequency, end_frequency, modulation = parse_group_form(request)
        group.name = name
        group.begin_frequency = begin_frequency
        group.end_frequency = end_frequency
        group.modulation = modulation
        group.save()
        sdr.utils.group.update_groups()
        messages.success(request, "Group updated.")
    except Exception as e:
        logging.getLogger("Group").exception("failed to edit group %s", group_id)
        messages.error(request, "Error: %s" % e)
    return redirect("sdr_groups")


@staff_member_required()
@permission_required("sdr.change_group", raise_exception=True)
@require_POST
def delete_group(request, group_id):
    try:
        default_group_id = get_default_group_id()
        if int(group_id) == default_group_id:
            messages.error(request, "Can not delete Default group!")
        else:
            Group.objects.get(id=group_id).transmission_set.update(group_id=default_group_id)
            Group.objects.filter(id=group_id).delete()
            sdr.utils.group.update_groups()
            messages.success(request, "Success!")
    except Exception as e:
        logging.getLogger("Group").exception("failed to delete group %s", group_id)
        messages.error(request, "Error: %s" % e)
    return redirect("sdr_groups")


@staff_member_required()
@permission_required("sdr.change_device", raise_exception=True)
def config(request):
    # Configuration is loaded/saved through sdr/api.py (server-side); the page no
    # longer receives MQTT credentials.
    return render(request, "config.html")


@login_required()
@permission_required("sdr.view_transmission", raise_exception=True)
def radio(request):
    return render(request, "radio.html")


@staff_member_required()
def logs(request):
    """Panel-native log viewer (staff): tail of the selected log file."""
    import datetime

    log_dir = monitor.settings.LOG_DIR
    files = []
    if log_dir and os.path.isdir(log_dir):
        for name in os.listdir(log_dir):
            path = os.path.join(log_dir, name)
            if os.path.isfile(path):
                stat = os.stat(path)
                files.append({
                    "name": name,
                    "size": stat.st_size,
                    "mtime": datetime.datetime.fromtimestamp(stat.st_mtime),
                })
        files.sort(key=lambda item: item["mtime"], reverse=True)
    selected = request.GET.get("file", "")
    if not selected and files:
        selected = files[0]["name"]
    content = ""
    if selected and log_dir:
        path = os.path.join(log_dir, os.path.basename(selected))
        if os.path.isfile(path):
            with open(path, "rb") as file:
                file.seek(max(0, os.path.getsize(path) - 200 * 1024))
                text = file.read().decode("utf-8", "replace")
            content = "\n".join(text.splitlines()[-2000:])
    return render(request, "logs.html", {"files": files, "selected": selected, "content": content})


@staff_member_required()
def support_bundle(request):
    """One support bundle: logs, scanner config/status and versions."""
    import hashlib
    import io
    import json
    import platform
    import tarfile
    import tempfile
    import time
    import django
    import sdr.utils.scanner_config
    from django.http import FileResponse
    from django.utils import timezone

    def sha256(path):
        try:
            with open(path, "rb") as file:
                return hashlib.sha256(file.read()).hexdigest()
        except OSError:
            return "n/a"

    status = {}
    try:
        status = sdr.utils.scanner_mqtt.get_status(timeout=4) or {}
    except Exception:
        status = {}
    if not status:
        try:
            status = sdr.utils.scanner_mqtt.read_cache() or {}
        except Exception:
            status = {}

    scanner_versions = ", ".join(
        "%s=%s" % (scanner_id, scanner.get("version")) for scanner_id, scanner in status.items()
    )
    versions = "\n".join([
        "date: %s" % timezone.now().isoformat(),
        "hostname: %s" % platform.node(),
        "platform: %s" % platform.platform(),
        "python: %s" % platform.python_version(),
        "django: %s" % django.get_version(),
        "scanner: %s" % (scanner_versions or "unknown"),
        "requirements.lock sha256: %s" % sha256(os.path.join(monitor.settings.BASE_DIR, "requirements.lock")),
    ]) + "\n"
    readme = """SDR Monitor support bundle

logs/                  panel and scanner logs
scanner/config.json    scanner configuration
scanner/status.json    scanner status (devices, ranges, version)
versions.txt           panel/scanner versions and build info

No database, static assets or secrets are included.
"""

    buffer = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024, mode="w+b")
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        log_dir = monitor.settings.LOG_DIR
        if log_dir and os.path.isdir(log_dir):
            tar.add(log_dir, arcname="logs")
        config_path = sdr.utils.scanner_config.CONFIG_PATH
        if os.path.isfile(config_path):
            tar.add(config_path, arcname="scanner/config.json")
        for name, data in (
            ("scanner/status.json", json.dumps(status, indent=2, sort_keys=True)),
            ("versions.txt", versions),
            ("README.txt", readme),
        ):
            payload = data.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mtime = time.time()
            tar.addfile(info, io.BytesIO(payload))
    buffer.seek(0)
    filename = "support-%s.tar.gz" % timezone.now().strftime("%Y%m%d-%H%M%S")
    return FileResponse(buffer, as_attachment=True, filename=filename)


class SatellitesForm(forms.Form):
    latitude = forms.FloatField()
    longitude = forms.FloatField()
    altitude = forms.FloatField()
    satellites = forms.CharField()

    def clean_satellites(self):
        try:
            raw = self.cleaned_data["satellites"]
            satellites = []
            for satellite in raw.split(","):
                if satellite.strip():
                    data = satellite.split(";")
                    satellites.append({"id": data[0], "name": data[1]})
            return satellites
        except ValueError:
            raise forms.ValidationError("Invalid satellites")


@login_required()
def satellites(request):
    is_json = common.helpers.is_json_request(request)
    form = SatellitesForm(request.GET)
    if form.is_valid():
        reader = sdr.utils.satellites.SatellitesFlightReader(
            form.cleaned_data["latitude"],
            form.cleaned_data["longitude"],
            form.cleaned_data["altitude"],
            True,
        )
        flights = reader.get_visible_satellites_flights(
            [
                {
                    "id": satellite["id"],
                    "name": satellite["name"],
                    "frequency": 0,
                    "bandwidth": 0,
                    "modulation": "",
                }
                for satellite in form.cleaned_data["satellites"]
            ],
            is_json,
        )
    else:
        flights = []

    if is_json:
        return JsonResponse(flights, safe=False)
    else:
        return render(request, "flights.html", {"flights": flights})


@staff_member_required()
def gain_tester(request):
    return render(request, "gain_tester.html", {"mqtt": monitor.settings.MQTT})


@login_required()
def gain_tests(request):
    items = GainTest.objects.all()
    items = common.utils.filters.filter(request, items)
    items = common.utils.filters.order_by(request, items, ["-datetime", "name"])
    page_size = get_page_size(request)
    items = Paginator(items, page_size).get_page(request.GET.get("page"))
    return render(request, "gain_tests.html", {"items": items})


@login_required()
def gain_test(request, gain_test_id):
    gain_test = get_object_or_404(GainTest, id=gain_test_id)
    devices = Device.objects.filter(name__startswith=gain_test.device_prefix)
    spectrograms = Spectrogram.objects.filter(device__in=devices).select_related("device").order_by("begin_real_date")
    real_date = Spectrogram.objects.filter(device__in=devices).aggregate(begin_real_date=Min("begin_real_date"), end_real_date=Max("end_real_date"))
    if len(spectrograms) == 0:
        raise Http404()
    spectrogram = spectrograms[0]
    return render(request, "gain_test.html", {"name": gain_test.name, "gain_test_id": gain_test.id, "spectrogram": spectrogram, "spectrograms": spectrograms} | real_date)


@staff_member_required()
@permission_required("sdr.delete_gaintest", raise_exception=True)
@require_POST
def delete_gain_test(request, gain_test_id):
    gain_test = get_object_or_404(GainTest, id=gain_test_id)
    try:
        gain_test.delete()
        messages.success(request, "Gain test deleted.")
    except Exception:
        logging.getLogger("GainTest").exception("failed to delete gain test %s", gain_test_id)
        messages.error(request, "Could not delete gain test.")
    return redirect("sdr_gain_tests")


@login_required()
def scanning_status(request):
    from datetime import timedelta
    from django.utils.timezone import now

    now_dt = now()
    hour_ago = now_dt - timedelta(hours=1)

    def age_str(value):
        if value is None:
            return None
        seconds = max(0, int((now_dt - value).total_seconds()))
        if seconds < 90:
            return "%d s ago" % seconds
        if seconds < 5400:
            return "%d min ago" % (seconds // 60)
        if seconds < 172800:
            return "%d h %d min ago" % (seconds // 3600, (seconds % 3600) // 60)
        return "%d days ago" % (seconds // 86400)

    def status_of(value):
        if value is None:
            return "badge bg-secondary", "never"
        seconds = (now_dt - value).total_seconds()
        if seconds <= 600:
            return "badge bg-success", "live"
        if seconds <= 3600:
            return "badge bg-warning text-dark", "stale"
        return "badge bg-danger", "silent"

    def device_stats(device):
        row = {
            "name": device.raw_name if device else "",
            "last_spec": None,
            "last_spec_age": None,
            "last_trans": None,
            "last_trans_age": None,
            "spec_1h": 0,
            "trans_1h": 0,
            "badge": "badge bg-secondary",
            "status": "never",
        }
        if device is None:
            return row
        last_spec = Spectrogram.objects.filter(device=device).order_by("-end_real_date").first()
        last_trans = Transmission.objects.filter(device=device).order_by("-begin_date").first()
        row["spec_1h"] = Spectrogram.objects.filter(device=device, end_real_date__gte=hour_ago).count()
        row["trans_1h"] = Transmission.objects.filter(device=device, begin_date__gte=hour_ago).count()
        if last_spec:
            row["last_spec"] = last_spec.end_real_date
            row["last_spec_age"] = age_str(last_spec.end_real_date)
        if last_trans:
            row["last_trans"] = last_trans.begin_date
            row["last_trans_age"] = age_str(last_trans.begin_date)
        row["badge"], row["status"] = status_of(max([d for d in (row["last_spec"], row["last_trans"]) if d], default=None))
        return row

    def fmt_rate(value):
        try:
            return "%.2f MS/s" % (float(value) / 1000000)
        except (TypeError, ValueError):
            return "-"

    def fmt_gains(gains):
        values = []
        for gain in gains or []:
            if gain.get("name") is not None and gain.get("value") is not None:
                values.append("%s %.1f dB" % (gain["name"], gain["value"]))
        return ", ".join(values) if values else "-"

    def fmt_ranges(ranges):
        ranges = ranges or []
        try:
            span = sum(max(0, item.get("stop", 0) - item.get("start", 0)) for item in ranges) / 1000000
        except (TypeError, AttributeError):
            return "%d" % len(ranges)
        return "%d (%.1f MHz)" % (len(ranges), span)

    status = sdr.utils.scanner_mqtt.read_cache(max_age=300.0)
    status_age = sdr.utils.scanner_mqtt.cache_age() if status else None
    if not status:
        status = sdr.utils.scanner_mqtt.get_status(timeout=2.0)
        status_age = None
    scanners = []
    for scanner_id, scanner in status.items():
        devices = []
        for status_device in scanner.get("devices", []):
            alias = status_device.get("alias") or ""
            device = Device.objects.filter(raw_name=alias).first() or Device.objects.filter(name=alias).first()
            row = device_stats(device)
            row.update({
                "alias": alias or "-",
                "driver": status_device.get("driver") or "-",
                "serial": status_device.get("serial") or "-",
                "connected": bool(status_device.get("connected")),
                "enabled": bool(status_device.get("enabled")),
                "sample_rate": fmt_rate(status_device.get("sample_rate")),
                "gains": fmt_gains(status_device.get("gains")),
                "ranges": fmt_ranges(status_device.get("ranges")),
            })
            devices.append(row)
        scanners.append({"id": scanner_id, "label": (" + ".join(row["alias"] for row in devices if row.get("alias") and row["alias"] != "-") or "scanner #%s" % scanner_id), "version": scanner.get("version", "-"), "workers": scanner.get("workers", "-"), "devices": devices})
    db_devices = [device_stats(device) for device in Device.objects.order_by("id")]
    db_devices = [row for row in db_devices if row["last_spec"] or row["last_trans"]]
    status_age_text = "live (requested now)" if status_age is None else "cached %d s ago" % max(0, int(status_age))
    return render(request, "scanning_status.html", {"scanners": scanners, "db_devices": db_devices, "server_time": now_dt, "status_age_text": status_age_text})


@staff_member_required()
def settings(request):
    if request.method == "POST":
        form = AppSettingsForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Settings updated successfully!")
            return redirect("sdr_settings")
    else:
        form = AppSettingsForm()
        form.load_initial()
    return render(request, "app_settings.html", {"form": form})


@staff_member_required()
def keep_rules(request):
    """Transmission retention: auto-delete noise classes + per-class keep rules."""
    current = AppSettings.keep_rules()
    auto_delete = AppSettings.get(AppSettingsKey.AUTO_DELETE_NOISE)
    noise_labels = AppSettings.get(AppSettingsKey.AUTO_DELETE_NOISE_LABELS)
    if request.method == "POST":
        rules = {}
        index = 0
        while True:
            name = request.POST.get("name_%d" % index)
            if name is None:
                break
            raw = (request.POST.get("seconds_%d" % index) or "").strip()
            if raw:
                try:
                    seconds = int(float(raw))
                    if seconds >= 0:
                        rules[name] = seconds
                except (ValueError, TypeError):
                    pass
            index += 1
        value = ",".join("%s:%d" % (name, rules[name]) for name in rules)
        AppSettings.set(AppSettingsKey.TRANSMISSION_KEEP_RULES, value)
        AppSettings.set(AppSettingsKey.AUTO_DELETE_NOISE, "true" if request.POST.get("auto_delete_noise") else "false")
        AppSettings.set(AppSettingsKey.AUTO_DELETE_NOISE_LABELS, (request.POST.get("auto_delete_noise_labels") or "").strip())
        messages.success(request, "Retention settings updated.")
        return redirect("sdr_keep_rules")

    class_names = set(AudioClass.objects.values_list("name", flat=True).distinct())
    class_names |= set(current.keys())
    rows = [
        {"name": name, "seconds": current.get(name, "")}
        for name in sorted(class_names, key=lambda s: s.lower())
    ]
    return render(request, "keep_rules.html", {
        "rows": rows,
        "auto_delete_noise": auto_delete,
        "auto_delete_noise_labels": noise_labels,
    })


@staff_member_required()
@permission_required("sdr.delete_transmission", raise_exception=True)
@require_POST
def delete_transmission(request, transmission_id):
    transmission = get_object_or_404(Transmission, id=transmission_id)
    try:
        sdr.utils.transmission.delete_transmission(transmission)
        messages.success(request, "Transmission deleted.")
    except Exception:
        logging.getLogger("Transmission").exception("failed to delete transmission %s", transmission_id)
        messages.error(request, "Could not delete transmission.")
    return redirect("sdr_transmissions")


@staff_member_required()
@permission_required("sdr.delete_spectrogram", raise_exception=True)
@require_POST
def delete_spectrogram(request, spectrogram_id):
    spectrogram = get_object_or_404(Spectrogram, id=spectrogram_id)
    try:
        spectrogram.delete()
        messages.success(request, "Spectrogram deleted.")
    except Exception:
        logging.getLogger("Spectrogram").exception("failed to delete spectrogram %s", spectrogram_id)
        messages.error(request, "Could not delete spectrogram.")
    return redirect("sdr_spectrograms")


@staff_member_required()
@permission_required("sdr.delete_transmission", raise_exception=True)
@require_POST
def delete_transmissions_by_class(request):
    class_name = request.POST.get("class_name", "")
    if not class_name:
        messages.error(request, "No class selected.")
        return redirect("sdr_transmissions")
    try:
        count = sdr.utils.transmission.delete_transmissions(Transmission.objects.filter(audio_class__name=class_name))
        messages.success(request, "Deleted %d transmissions of class '%s'." % (count, class_name))
    except Exception:
        logging.getLogger("Transmission").exception("failed to delete transmissions of class %s", class_name)
        messages.error(request, "Could not delete transmissions of class '%s'." % class_name)
    return redirect("sdr_transmissions")


@staff_member_required()
@permission_required("sdr.delete_transmission", raise_exception=True)
@require_POST
def delete_all_transmissions(request):
    try:
        count = sdr.utils.transmission.delete_transmissions(Transmission.objects.all())
        messages.success(request, "Deleted all %d transmissions." % count)
    except Exception:
        logging.getLogger("Transmission").exception("failed to delete all transmissions")
        messages.error(request, "Could not delete transmissions.")
    return redirect("sdr_transmissions")


@staff_member_required()
@require_POST
def update_spectrograms_keep_count(request):
    try:
        count = max(0, int(request.POST.get("spectrograms_keep_count", "0")))
    except (TypeError, ValueError):
        messages.error(request, "Invalid number.")
        return redirect("sdr_spectrograms")
    AppSettings.set(AppSettingsKey.SPECTROGRAMS_KEEP_COUNT, count)
    messages.success(request, "Keeping the last %d spectrograms (0 keeps all)." % count)
    return redirect("sdr_spectrograms")


@staff_member_required()
@permission_required("sdr.delete_spectrogram", raise_exception=True)
@require_POST
def delete_all_spectrograms(request):
    try:
        count, _ = Spectrogram.objects.all().delete()
        messages.success(request, "Deleted all %d spectrograms." % count)
    except Exception:
        logging.getLogger("Spectrogram").exception("failed to delete all spectrograms")
        messages.error(request, "Could not delete spectrograms.")
    return redirect("sdr_spectrograms")
