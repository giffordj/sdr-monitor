"""Server-side access to the scanner configuration file.

The scanner (`auto_sdr`) is started with ``--config <BASE_DIR>/data/config.json``
and reads it at startup. The web UI used to edit this configuration by talking to
the MQTT broker directly from the browser; instead the Django server now owns the
file: it reads it (so the UI works even when the scanner is down), validates it,
writes it back (with a backup), and asks the running scanner to apply it over
MQTT. See ``sdr/api.py`` and ``sdr/utils/scanner_mqtt.py``.
"""

import copy
import json
import logging
import os
import shutil

import monitor.settings


__logger = logging.getLogger("ScannerConfig")

CONFIG_PATH = os.path.join(monitor.settings.BASE_DIR, "data", "config.json")
BACKUP_PATH = CONFIG_PATH + ".bak"

# The scanner splits each scanned range into ~1 MHz windows and builds one GNU
# Radio processing chain per window. Too many windows overloads the SDR/USB and
# makes auto_sdr overflow or crash, so warn above this many. Kept in sync with
# the estimate in sdr/static/js/config.js and the scanner's splitRanges().
MAX_SCAN_PROCESSORS = 35

# Fields owned by the configuration file. Capability fields reported by the
# running scanner (connected, driver, sample_rates, gain min/max/step) are
# stripped before writing.
DEVICE_CONFIG_FIELDS = (
    "alias",
    "crontabs",
    "enabled",
    "gains",
    "ranges",
    "sample_rate",
    "satellites",
    "serial",
    "start_recording_level",
    "stop_recording_level",
)
TOP_LEVEL_CONFIG_FIELDS = ("devices", "ignored_frequencies", "output", "position", "recording", "version", "workers")


def load() -> dict:
    """Return the on-disk scanner configuration (empty dict if absent/corrupt)."""
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as e:
        __logger.warning("failed to read %s: %s" % (CONFIG_PATH, e))
        return {}


def clean_config(config: dict) -> dict:
    """Drop capability-only fields so we persist a valid scanner config."""
    result = {key: copy.deepcopy(config[key]) for key in TOP_LEVEL_CONFIG_FIELDS if key in config}
    devices = []
    for device in config.get("devices", []):
        devices.append({key: copy.deepcopy(device[key]) for key in DEVICE_CONFIG_FIELDS if key in device})
    result["devices"] = devices
    return result


def save(config: dict) -> dict:
    """Atomically write the configuration, keeping a single .bak of the kernel."""
    cleaned = clean_config(config)
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    if os.path.exists(CONFIG_PATH):
        try:
            shutil.copyfile(CONFIG_PATH, BACKUP_PATH)
        except OSError as e:
            __logger.warning("failed to back up %s: %s" % (CONFIG_PATH, e))
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cleaned, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, CONFIG_PATH)
    return cleaned


def _split_sample_rate(sample_rate: int) -> int:
    """Mirror the scanner's getRangeSplitSampleRate()."""
    if sample_rate >= 10000000:
        return (sample_rate // 1000000) * 1000000
    if sample_rate >= 1000000:
        return (sample_rate // 500000) * 500000
    if sample_rate >= 100000:
        return (sample_rate // 100000) * 100000
    return sample_rate


def _count_processors(device: dict) -> tuple[int, list[int]]:
    split = _split_sample_rate(int(device.get("sample_rate") or 0))
    total = 0
    invalid = []
    for index, scan_range in enumerate(device.get("ranges", [])):
        start = scan_range.get("start", 0)
        stop = scan_range.get("stop", 0)
        if not start < stop:
            invalid.append(index + 1)
        elif stop - start <= split:
            total += 1
        else:
            total += -(-(stop - start) // split)  # ceil division
    return total, invalid


def validate(config: dict) -> dict:
    """Return {"errors": [...], "warnings": [...]} for a configuration."""
    errors = []
    warnings = []
    devices = config.get("devices")
    if not isinstance(devices, list) or not devices:
        errors.append("At least one SDR device is required.")
        return {"errors": errors, "warnings": warnings}
    for index, device in enumerate(devices):
        label = "device #%d (%s)" % (index + 1, device.get("serial", "?"))
        try:
            int(device.get("sample_rate") or 0)
        except (TypeError, ValueError):
            errors.append("%s: invalid sample rate" % label)
            continue
        total, invalid = _count_processors(device)
        if invalid:
            errors.append("%s: scanned range(s) %s have start >= stop" % (label, ", ".join(str(i) for i in invalid)))
        if total > MAX_SCAN_PROCESSORS:
            warnings.append("%s: %d scan windows (safe limit %d) may overload the SDR" % (label, total, MAX_SCAN_PROCESSORS))
    return {"errors": errors, "warnings": warnings}


def offline_scanner(config: dict) -> dict:
    """Build a scanner-shaped object from the config file for the offline UI."""
    scanner = copy.deepcopy(config) if config else {"devices": [], "ignored_frequencies": []}
    scanner.setdefault("ignored_frequencies", [])
    for device in scanner.get("devices", []):
        device["connected"] = False
        device.setdefault("alias", "")
        device.setdefault("driver", "")
        device.setdefault("sample_rates", [device.get("sample_rate")])
        device.setdefault("satellites", [])
        device.setdefault("crontabs", [])
        for gain in device.get("gains", []):
            gain.setdefault("min", "")
            gain.setdefault("max", "")
            gain.setdefault("step", "")
    return scanner
