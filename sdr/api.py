"""JSON API for the scanner configuration UI.

Replaces the browser->MQTT path: the server reads/writes the scanner config file
and talks to the scanner over MQTT on the browser's behalf. No broker
credentials reach the page.
"""

import json
import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import permission_required
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_http_methods

from sdr.utils import scanner_config, scanner_mqtt
from sdr.utils.radio import radio_controller


__logger = logging.getLogger("Config")


@staff_member_required()
@permission_required("sdr.change_device", raise_exception=True)
@require_http_methods(["GET", "POST"])
def config(request):
    if request.method == "GET":
        return __get_config()
    return __save_config(request)


def __get_config() -> JsonResponse:
    on_disk = scanner_config.load()
    try:
        # Prefer the worker-maintained cache (no MQTT round-trip in the request
        # path); fall back to a live poll when the cache is missing.
        scanners = scanner_mqtt.read_cache(max_age=300.0)
        if not scanners:
            scanners = scanner_mqtt.get_status(timeout=2.0)
    except Exception as e:
        __logger.warning("live status failed: %s" % e)
        scanners = {}
    online = bool(scanners)
    if not online:
        # Fall back to the config file so the UI is editable with the scanner down.
        scanners = {"offline": scanner_config.offline_scanner(on_disk)}
    return JsonResponse({"online": online, "scanners": scanners, "config": on_disk})


def __save_config(request) -> JsonResponse:
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"success": False, "errors": ["Request body is not valid JSON."]}, status=400)

    scanner_id = payload.get("scanner_id") or "offline"
    scanner = payload.get("config")
    if not isinstance(scanner, dict):
        return JsonResponse({"success": False, "errors": ["Missing configuration."]}, status=400)

    validation = scanner_config.validate(scanner)
    if validation["errors"]:
        return JsonResponse({"success": False, "errors": validation["errors"], "warnings": validation["warnings"]}, status=400)

    cleaned = scanner_config.save(scanner)

    # Ask the running scanner to apply the change live (skip when we only have
    # the offline placeholder). Persisting already succeeded, so a failed apply
    # is reported but not fatal - the config is picked up on next scanner start.
    applied = False
    if scanner_id != "offline":
        try:
            scanner_mqtt.apply_config(scanner_id, scanner)
            applied = True
        except Exception as e:
            __logger.warning("failed to apply config to scanner %s: %s" % (scanner_id, e))

    return JsonResponse({"success": True, "applied": applied, "warnings": validation["warnings"], "config": cleaned})


@staff_member_required()
@permission_required("sdr.change_device", raise_exception=True)
@require_http_methods(["GET", "POST"])
def radio(request):
    if request.method == "GET":
        return JsonResponse(radio_controller.status())
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"success": False, "errors": ["Request body is not valid JSON."]}, status=400)

    action = payload.get("action")
    try:
        if action == "start":
            return JsonResponse(radio_controller.start(payload.get("mode", "AM"), int(payload.get("frequency", 10000000)), int(payload.get("gain", 0)), payload.get("device")))
        if action == "stop":
            return JsonResponse(radio_controller.stop())
        if action == "tune":
            gain = payload.get("gain")
            return JsonResponse(radio_controller.tune(payload.get("mode", "AM"), int(payload.get("frequency", 10000000)), int(gain) if gain is not None else None))
        if action == "record":
            return JsonResponse(radio_controller.set_record(bool(payload.get("on"))))
    except Exception as e:
        __logger.warning("radio action %s failed: %s" % (action, e))
        return JsonResponse({"success": False, "errors": [str(e)]}, status=500)
    return JsonResponse({"success": False, "errors": ["Unknown action."]}, status=400)


@staff_member_required()
@permission_required("sdr.change_device", raise_exception=True)
@require_http_methods(["GET", "POST"])
def scanner(request):
    if request.method == "GET":
        return JsonResponse(radio_controller.status())
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"success": False, "errors": ["Request body is not valid JSON."]}, status=400)
    action = payload.get("action")
    if action == "start":
        if radio_controller.status()["active"]:
            return JsonResponse({"success": False, "errors": ["Stop the radio before starting the scanner."]}, status=409)
        radio_controller.scanner_start()
    elif action == "stop":
        radio_controller.scanner_stop()
    else:
        return JsonResponse({"success": False, "errors": ["Unknown action."]}, status=400)
    return JsonResponse({"success": True, "status": radio_controller.status()})


@staff_member_required()
@permission_required("sdr.change_device", raise_exception=True)
def radio_stream(request):
    subscriber = radio_controller.subscribe()

    def stream():
        try:
            while True:
                chunk = subscriber.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            radio_controller.unsubscribe(subscriber)

    return StreamingHttpResponse(stream(), content_type="audio/mpeg")
