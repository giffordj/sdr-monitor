#!/bin/bash
# ============================================================================
# Rebuild and redeploy the sdr-hub container from this checkout.
#
#   bash scripts/deploy.sh
#
# 1. git pull
# 2. ensure compose.yml Authelia env (trust 127.0.0.1, group 'admins',
#    AUTHELIA_ALL_STAFF=1, INFO logs)
# 3. docker build
# 4. docker compose up -d --force-recreate
# 5. collectstatic + verify
#
# Paths can be overridden:
#   SDR_SRC    (default: this repo checkout)
#   SDR_DEPLOY (default: /home/docker/sdr-hub)
#   SDR_IMAGE  (default: sdr-hub:patched)
# Env knobs: PULL=0 skip pull, NOCACHE=1 build --no-cache
# ============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${SDR_SRC:-$(dirname "$SCRIPT_DIR")}"
DEPLOY="${SDR_DEPLOY:-/home/docker/sdr-hub}"
IMAGE="${SDR_IMAGE:-sdr-hub:patched}"
COMPOSE="$DEPLOY/compose.yml"

echo "=================================================================="
echo " sdr-hub deploy  $(date '+%Y-%m-%d %H:%M:%S')"
echo " src=$SRC  deploy=$DEPLOY  image=$IMAGE"
echo "=================================================================="

if [ "${PULL:-1}" = "1" ]; then
    echo ">> git pull"
    git -C "$SRC" pull --ff-only || echo "!! pull failed - continuing with current tree"
else
    echo ">> pull skipped (PULL=0)"
fi
echo ">> source commit: $(git -C "$SRC" log --oneline -1)"

if [ -f "$COMPOSE" ]; then
    echo ">> ensuring compose.yml Authelia env"
    cp "$COMPOSE" "$COMPOSE.bak.$(date +%Y%m%d%H%M%S)"
    python3 - "$COMPOSE" <<'PY'
import re, sys
p = sys.argv[1]
s = open(p).read()

def setline(s, key, val):
    pat = re.compile(r'(?m)^(\s*)- ' + re.escape(key) + r'=.*$')
    if pat.search(s):
        return pat.sub(lambda m: m.group(1) + '- ' + key + '=' + val, s)
    anchor = re.search(r'(?m)^(\s*)- AUTHELIA_[A-Z_]+=.*$', s)
    if anchor:
        indent = re.match(r'(\s*)', anchor.group(0)).group(1)
        return s[:anchor.end()] + '\n' + indent + '- ' + key + '=' + val + s[anchor.end():]
    sys.exit("!! could not find where to insert " + key)

for key, val in [
    ('AUTHELIA_TRUSTED_PROXIES', '127.0.0.1'),
    ('AUTHELIA_ADMIN_GROUPS', 'admins'),
    ('AUTHELIA_ALL_STAFF', '1'),
    ('DJANGO_LOG_LEVEL', 'INFO'),
]:
    s = setline(s, key, val)
open(p, 'w').write(s)
print("compose env updated")
PY
    grep -nE 'AUTHELIA_|DJANGO_LOG_LEVEL' "$COMPOSE"
else
    echo "!! $COMPOSE not found, skipping env patch"
fi

echo ">> docker build $IMAGE"
cd "$SRC"
if [ "${NOCACHE:-0}" = "1" ]; then
    docker build --no-cache -t "$IMAGE" .
else
    docker build -t "$IMAGE" .
fi

echo ">> docker compose up -d --force-recreate"
cd "$DEPLOY"
docker compose up -d --force-recreate

echo ">> waiting for startup"
sleep 12
docker ps --filter name=sdr-hub --format 'container: {{.Status}}'

echo ">> collectstatic"
docker exec sdr-hub /app/manage.py collectstatic --no-input 2>&1 | tail -3 || echo "!! collectstatic failed"


echo ">> verifying image contents"
docker exec sdr-hub grep -q 'display: none' /app/common/templates/generic/theme.html \
    && echo "  theme watermark hidden : OK" || echo "  theme watermark hidden : MISSING"
docker exec sdr-hub grep -q 'theme-toggle' /app/templates/generic/main.html \
    && echo "  dark-mode toggle       : OK" || echo "  dark-mode toggle       : MISSING"
docker exec sdr-hub test -f /app/common/auth.py \
    && echo "  authelia backend       : OK" || echo "  authelia backend       : MISSING"

echo ">> effective settings"
docker exec sdr-hub sh -c "cd /app && python3 -c \"
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','monitor.settings')
django.setup()
from django.conf import settings
print('   enabled      :', settings.AUTHELIA_AUTH_ENABLED)
print('   admin_groups :', settings.AUTHELIA_ADMIN_GROUPS)
print('   all_staff    :', getattr(settings,'AUTHELIA_ALL_STAFF',None))
print('   trusted      :', settings.AUTHELIA_TRUSTED_PROXIES)
\""

echo
echo "DONE. Hard-refresh (Ctrl-Shift-R). Run scripts/doctor.sh to health-check."
