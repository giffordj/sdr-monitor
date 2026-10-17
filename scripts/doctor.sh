#!/bin/bash
# ============================================================================
# One-shot health check for the sdr-hub deployment. Read-only.
#   bash scripts/doctor.sh
# Paths can be overridden with SDR_SRC / SDR_DEPLOY.
# ============================================================================
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${SDR_SRC:-$(dirname "$SCRIPT_DIR")}"
DEPLOY="${SDR_DEPLOY:-/home/docker/sdr-hub}"

echo "================ DEPLOYED COMMIT ================"
git -C "$SRC" log --oneline -1 2>&1
git -C "$SRC" status -sb 2>&1 | head -1

echo
echo "================ CONTAINER ================"
docker ps --filter name=sdr-hub --format '{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>&1


echo
echo "================ APP PROCESSES ================"
docker exec sdr-hub sh -c 'ps -eo args | grep -E "nginx|gunicorn|auto_sdr|monitor_worker" | grep -v grep' 2>&1

echo
echo "================ AUTH SETTINGS ================"
docker exec sdr-hub sh -c "cd /app && python3 -c \"
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','monitor.settings')
django.setup()
from django.conf import settings
print('enabled      :', settings.AUTHELIA_AUTH_ENABLED)
print('admin_groups :', settings.AUTHELIA_ADMIN_GROUPS)
print('all_staff    :', getattr(settings,'AUTHELIA_ALL_STAFF',None))
print('trusted      :', settings.AUTHELIA_TRUSTED_PROXIES)
\"" 2>&1 | sed 's/^/  /'

echo
echo "================ FILTER (HTTP) ================"
docker exec sdr-hub python3 -c '
import re, urllib.request
def get(path):
    req = urllib.request.Request("http://127.0.0.1:8000" + path, headers={"Remote-User": "giffordj"})
    return urllib.request.urlopen(req, timeout=20).read().decode()
html = get("/sdr/transmissions/")
print("  form=\"filters\" count :", html.count("form=\"filters\""))
for label, path in [
    ("unfiltered", "/sdr/transmissions/"),
    ("modulation=AM", "/sdr/transmissions/?modulation__icontains=AM"),
    ("class=Noise", "/sdr/transmissions/?class_name__icontains=Noise"),
]:
    m = re.search(r"Transmissions: \d+", get(path))
    print("  %-14s: %s" % (label, m.group(0) if m else "?"))
' 2>&1

echo
echo "================ CLASSIFIER ================"
docker exec sdr-hub sh -c 'cd /app && python3 -c "
import os, django
os.environ.setdefault(\"DJANGO_SETTINGS_MODULE\",\"monitor.settings\")
django.setup()
from django.utils import timezone
from sdr.models import Transmission, get_default_audio_class_id
try:
    from sdr.utils.sound_classifier import SoundClassifier
    SoundClassifier()
    print(\"  init        : OK\")
except Exception as e:
    print(\"  init        : FAILED\", type(e).__name__, e)
default_id = get_default_audio_class_id()
pending = Transmission.objects.filter(end_date__lt=timezone.now()-timezone.timedelta(seconds=10), audio_class_id=default_id).count()
print(\"  pending     :\", pending, \"(default class, >10s old)\")
"' 2>&1

echo
echo "================ RECENT ERRORS ================"
docker exec sdr-hub sh -c 'grep -iE "error|exception|traceback" /var/log/sdr/sdr_monitor_worker.log 2>/dev/null | tail -10' 2>&1
docker logs --tail 15 sdr-hub 2>&1 | grep -iE "error|exception|segfault|exit" || echo "  (no recent container errors)"

echo
echo "DONE"
