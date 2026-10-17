"""Server-side MQTT bridge to the scanner.

The browser used to talk to the broker directly (exposing the broker password to
the page). Instead the Django server performs the two operations the UI needs:

* ``get_status()``  - ask the scanner to publish its status/config (best effort;
  returns ``{}`` when the scanner or broker is unavailable).
* ``apply_config()`` - push a new configuration to the running scanner so it
  takes effect without a container restart.

The broker inside the container only listens for websockets on ``:9001``; the
shared ``common.utils.mqtt`` client already handles the ``ws://`` URL.
"""

import json
import logging
import os
import time

import common.utils.mqtt
import monitor.settings


__logger = logging.getLogger("ScannerMQTT")

STATUS_TOPIC = "sdr/status/+"
LIST_TOPIC = "sdr/list"


def _client(client_id: str):
    mqtt = monitor.settings.MQTT
    return common.utils.mqtt.get_client(mqtt["url"], mqtt["user"], mqtt["password"], client_id)


def get_status(timeout: float = 2.0) -> dict:
    """Publish ``sdr/list`` and collect ``sdr/status/+`` replies for a moment."""
    result: dict = {}
    try:
        client = _client("sdr-config-status")

        def on_message(_client, _userdata, message):
            parts = message.topic.split("/")
            if len(parts) >= 3 and parts[1] == "status":
                try:
                    result[parts[2]] = json.loads(message.payload.decode("utf-8"))
                except (ValueError, UnicodeDecodeError) as e:
                    __logger.warning("invalid status payload on %s: %s" % (message.topic, e))

        client.on_message = on_message
        client.subscribe(STATUS_TOPIC)
        client.loop_start()
        time.sleep(0.3)
        client.publish(LIST_TOPIC)
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.05)
        client.loop_stop()
        client.disconnect()
    except Exception as e:
        __logger.warning("failed to read scanner status: %s" % e)
    return result


# ---------------------------------------------------------------------------
# Scanner status cache
#
# get_status() costs a full MQTT round-trip (2-3 s). The status page used to
# pay that on every render (and it self-refreshes every 30 s), and the config
# page paid it on every load. Instead, the worker keeps a fresh copy on disk
# (Reader refreshes it every 15 s) and the web process reads that file.
# ---------------------------------------------------------------------------
CACHE_FILE = os.path.join(monitor.settings.BASE_DIR, "data", "scanner_status.json")


def write_cache(data: dict) -> None:
    """Store the last scanner status for fast, MQTT-free page renders."""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        tmp = "%s.%d.tmp" % (CACHE_FILE, os.getpid())
        with open(tmp, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, CACHE_FILE)
    except OSError as e:
        __logger.warning("failed to write status cache: %s" % e)


def read_cache(max_age: float = 300.0) -> dict:
    """Return the cached status when it is fresh enough, else {}."""
    try:
        if time.time() - os.path.getmtime(CACHE_FILE) > max_age:
            return {}
        with open(CACHE_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def cache_age() -> float | None:
    """Age of the cached status in seconds, or None when there is no cache."""
    try:
        return time.time() - os.path.getmtime(CACHE_FILE)
    except OSError:
        return None


def apply_config(scanner_id: str, config: dict) -> None:
    """Push a configuration to the running scanner (raises on failure)."""
    client = _client("sdr-config-apply")
    client.loop_start()
    try:
        time.sleep(0.3)
        client.publish("sdr/config/%s" % scanner_id, json.dumps(config))
        time.sleep(0.5)
    finally:
        client.loop_stop()
        client.disconnect()
