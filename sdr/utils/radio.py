"""Live shortwave radio ("SDR Monitor" receiver), backed by an RTL-SDR dongle.

Two deployment modes:

- **Single dongle (default):** the scanner owns the RTL-SDR. Starting the radio
  stops ``sdr_scanner`` (via supervisord) so the dongle is free, and the scanner
  is started again when the radio stops.
- **Dual dongle** (``SDR_RADIO_KEEP_SCANNER=1`` + ``SDR_RADIO_DEVICE=<index>``):
  the radio is pinned to its own dongle (e.g. RTL-SDR Blog V4 in slot 1) and the
  scanner keeps scanning on the other one — no hand-off at all.
- **Pause-and-borrow** (``SDR_RADIO_PAUSE_SERIAL=<serial>``): the radio dongle
  *also* scans (e.g. the V4 over the shortwave bands). Starting the radio
  disables that device in the scanner config live (over MQTT), uses the dongle
  for listening, and re-enables it on stop — the other dongle never stops
  scanning. This is what destiny runs.

Dongles with a real HF upconverter (Blog V4) should set
``SDR_RADIO_HF_UPCONVERTER=1``: direct sampling (``-E direct2``) is skipped and
HF comes in much stronger.

One gunicorn worker runs this module, so the controller is a module-level
singleton. The audio is fanned out to HTTP streaming clients and optionally
recorded to disk (and registered as a Transmission).
"""

import json
import logging
import os
import queue
import subprocess
import threading
import time

import numpy as np
from django.utils import timezone

import monitor.settings
from sdr.models import Transmission, get_default_audio_class_id, get_default_device_id, get_default_group_id
from sdr.utils import scanner_config, scanner_mqtt


logger = logging.getLogger("Radio")

SUPERVISOR = ["supervisorctl", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
SCANNER_PROGRAM = "sdr_scanner"
SAMPLE_RATE = 48000
READ_SIZE = 8192
# Below this the tuner needs direct sampling (HF/MW/shortwave). Requires an
# HF-capable dongle (e.g. RTL-SDR Blog V4); the Nooelec SMArt v5 falls back to
# poor-sensitivity direct sampling.
HF_DIRECT_HZ = 24000000
# Dual-dongle support: pin the radio to a specific rtl_fm device index (0-9)
# so the scanner can keep running on the other dongle. Empty = default device.
RADIO_DEVICE = os.environ.get("SDR_RADIO_DEVICE", "").strip()
# The Blog V4 has a real HF upconverter: direct sampling is ~4x weaker there,
# so skip -E direct2 when this is set.
HF_UPCONVERTER = os.environ.get("SDR_RADIO_HF_UPCONVERTER", "") not in ("", "0")
# Keep the scanner running while the radio plays (only safe with a dedicated
# radio dongle — otherwise the scanner owns the one the radio needs).
KEEP_SCANNER = os.environ.get("SDR_RADIO_KEEP_SCANNER", "") not in ("", "0")
# Pause-and-borrow mode: serial of the dongle that both scans and (when the
# radio is active) is temporarily disabled in the scanner config so rtl_fm can
# use it. Requires SDR_RADIO_DEVICE to point at the same dongle.
PAUSE_SERIAL = os.environ.get("SDR_RADIO_PAUSE_SERIAL", "").strip()


def _parse_radio_devices() -> list:
    """Dongles the radio may pick from, in rtl-sdr enumeration order.

    SDR_RADIO_DEVICES is a JSON list:
        [{"index": 0, "serial": "66687725", "label": "NESDR VHF/UHF", "hf": false}, ...]
    Without it the legacy single-device configuration is used.
    """
    raw = os.environ.get("SDR_RADIO_DEVICES", "").strip()
    devices = []
    if raw:
        try:
            for entry in json.loads(raw):
                devices.append({
                    "index": int(entry.get("index", 0)),
                    "serial": str(entry.get("serial", "")),
                    "label": str(entry.get("label") or ("device %s" % entry.get("index", 0))),
                    "hf": bool(entry.get("hf", False)),
                })
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning("invalid SDR_RADIO_DEVICES: %s" % e)
            devices = []
    if not devices and (RADIO_DEVICE or PAUSE_SERIAL):
        devices.append({
            "index": int(RADIO_DEVICE or 0),
            "serial": PAUSE_SERIAL,
            "label": "radio dongle",
            "hf": HF_UPCONVERTER,
        })
    return devices


RADIO_DEVICES = _parse_radio_devices()
# rtl_fm -M mode -> our UI name
MODES = ("AM", "USB", "LSB", "FM", "WFM")
# rtl_fm -M names. NB: broadcast FM is "wbfm" (not "wfm"), which expands to
# -s 170k -r 32k -E deemp in rtl_fm.
RTLSDR_MODES = {"AM": "am", "USB": "usb", "LSB": "lsb", "FM": "fm", "WFM": "wbfm"}


class RadioController:
    def __init__(self):
        self.__lock = threading.Lock()
        self.__rf = None
        self.__lame = None
        self.__pcm_thread = None
        self.__mp3_thread = None
        self.__subscribers: set[queue.Queue] = set()
        self.__active = False
        self.__mode = "AM"
        self.__frequency = 10000000
        self.__gain = 0
        self.__rms = 0.0
        self.__record = False
        self.__record_file = None
        self.__record_begin = None
        self.__record_started = None
        self.__device = None

    # -- devices --------------------------------------------------------------
    def __pick_device(self, serial: str | None) -> dict | None:
        """Resolve a requested device serial to an entry of RADIO_DEVICES."""
        for device in RADIO_DEVICES:
            if serial and device["serial"] == serial:
                return device
        for device in RADIO_DEVICES:
            if PAUSE_SERIAL and device["serial"] == PAUSE_SERIAL:
                return device
        return RADIO_DEVICES[0] if RADIO_DEVICES else None

    def __device_serial(self) -> str:
        if self.__device:
            return self.__device["serial"]
        return PAUSE_SERIAL

    def __device_index(self) -> str:
        if self.__device:
            return str(self.__device["index"])
        return RADIO_DEVICE

    def __device_hf(self) -> bool:
        if self.__device:
            return bool(self.__device["hf"])
        return HF_UPCONVERTER

    # -- status ---------------------------------------------------------------
    def status(self) -> dict:
        return {
            "active": self.__active,
            "mode": self.__mode,
            "frequency": self.__frequency,
            "gain": self.__gain,
            "rms": round(self.__rms, 5),
            "record": self.__record,
            "listeners": len(self.__subscribers),
            "scanner": self.__scanner_state(),
            "devices": RADIO_DEVICES,
            "device": self.__device_serial(),
        }

    # -- control --------------------------------------------------------------
    def start(self, mode: str, frequency: int, gain: int = 0, serial: str | None = None) -> dict:
        with self.__lock:
            if self.__active:
                # Switching dongles needs a full restart; the UI stops first.
                self.__retune(mode, frequency, gain)
                return self.status()
            device = self.__pick_device(serial)
            if device:
                self.__device = device
            self.__mode = mode if mode in MODES else "AM"
            self.__frequency = int(frequency)
            self.__gain = int(gain)
            if self.__device_serial():
                # Borrow the dongle: disable it in the scanner (live) and give
                # the scanner a moment to release it, then open it with rtl_fm.
                self.__set_device_enabled(False)
                time.sleep(2.5)
            elif not KEEP_SCANNER:
                self.__stop_scanner()
            self.__start_pipeline_retry()
            self.__active = True
        return self.status()

    def tune(self, mode: str, frequency: int, gain: int = None) -> dict:
        with self.__lock:
            if not self.__active:
                return self.start(mode, frequency, gain or 0)
            self.__retune(mode, frequency, gain)
        return self.status()

    def stop(self) -> dict:
        with self.__lock:
            if self.__active:
                self.__stop_pipeline(end_subscribers=True)
                self.__finalize_recording()
                self.__active = False
            else:
                self.__end_subscribers()
            if self.__device_serial():
                # Give the borrowed dongle back to the scanner.
                self.__set_device_enabled(True)
            elif not KEEP_SCANNER:
                self.__start_scanner()
        return self.status()

    def set_record(self, on: bool) -> dict:
        with self.__lock:
            if on and not self.__record and self.__active:
                self.__start_recording()
            elif not on and self.__record:
                self.__finalize_recording()
        return self.status()

    # -- streaming ------------------------------------------------------------
    def scanner_start(self) -> None:
        self.__start_scanner()

    def scanner_stop(self) -> None:
        self.__stop_scanner()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=200)
        self.__subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        self.__subscribers.discard(q)

    # -- pipeline -------------------------------------------------------------
    def __retune(self, mode: str, frequency: int, gain: int) -> None:
        self.__mode = mode if mode in MODES else self.__mode
        self.__frequency = int(frequency)
        self.__gain = int(gain) if gain is not None else self.__gain
        self.__stop_pipeline()
        self.__start_pipeline()

    def __start_pipeline(self) -> None:
        rf_cmd = ["rtl_fm"]
        device_index = self.__device_index()
        if device_index:
            # Pin to a specific dongle (e.g. "1" = Blog V4) so the scanner keeps
            # the other one while the radio is live.
            rf_cmd += ["-d", device_index]
        rf_cmd += ["-M", RTLSDR_MODES.get(self.__mode, "am"), "-f", str(self.__frequency)]
        if self.__frequency < HF_DIRECT_HZ and not self.__device_hf():
            # HF/MW/shortwave: direct sampling (Q branch). Skipped on dongles
            # with a real HF upconverter (Blog V4) where it's much weaker.
            rf_cmd += ["-E", "direct2"]
        # -g defaults to automatic; only force it when the user picked a gain.
        if self.__gain and self.__gain > 0:
            rf_cmd += ["-g", str(self.__gain)]
        if self.__mode == "WFM":
            # wbfm has its own preset rates (tuner 170k, audio 32k); do not
            # override -s, or the broadcast signal is too wide to demodulate.
            out_rate = 32000
        else:
            out_rate = SAMPLE_RATE
            rf_cmd += ["-s", str(out_rate), "-r", str(out_rate)]
        rf_cmd += ["-"]
        # lame reads raw 16-bit mono PCM at out_rate and writes MP3 to stdout.
        lame_cmd = ["lame", "-r", "-s", str(out_rate // 1000), "-m", "m", "-b", "128", "--quiet", "-", "-"]
        logger.info("starting radio: %s" % " ".join(rf_cmd))
        self.__rf = subprocess.Popen(rf_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self.__lame = subprocess.Popen(lame_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self.__pcm_thread = threading.Thread(target=self.__pump_pcm, daemon=True)
        self.__mp3_thread = threading.Thread(target=self.__pump_mp3, daemon=True)
        self.__pcm_thread.start()
        self.__mp3_thread.start()

    def __start_pipeline_retry(self, attempts: int = 4) -> None:
        """Start rtl_fm, retrying if it exits immediately (dongle still busy)."""
        for attempt in range(1, attempts + 1):
            self.__start_pipeline()
            time.sleep(1.2)
            if self.__rf is not None and self.__rf.poll() is None:
                return
            logger.warning("rtl_fm exited early (attempt %d/%d) — retrying" % (attempt, attempts))
            self.__stop_pipeline()
            time.sleep(1.5)
        logger.error("could not start rtl_fm after %d attempts" % attempts)

    def __stop_pipeline(self, end_subscribers: bool = False) -> None:
        for proc in (self.__rf, self.__lame):
            if proc is None:
                continue
            try:
                proc.terminate()
            except Exception:
                pass
        # Reap the children, otherwise terminated rtl_fm/lame become zombies.
        for proc in (self.__rf, self.__lame):
            if proc is None:
                continue
            try:
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except Exception:
                    pass
        self.__rf = None
        self.__lame = None
        if end_subscribers:
            self.__end_subscribers()

    def __end_subscribers(self) -> None:
        # Sentinel per subscriber so the streaming responses finish instead of
        # blocking forever on get() after the pipeline is gone.
        for q in list(self.__subscribers):
            try:
                q.put_nowait(None)
            except queue.Full:
                pass
        self.__subscribers.clear()

    def __pump_pcm(self) -> None:
        rf = self.__rf
        lame = self.__lame
        if rf is None or lame is None:
            return
        try:
            while True:
                chunk = rf.stdout.read(READ_SIZE)
                if not chunk:
                    break
                self.__rms = self.__compute_rms(chunk)
                lame.stdin.write(chunk)
        except (BrokenPipeError, ValueError, OSError):
            pass
        finally:
            try:
                lame.stdin.close()
            except Exception:
                pass

    def __pump_mp3(self) -> None:
        lame = self.__lame
        if lame is None:
            return
        try:
            while True:
                data = lame.stdout.read(READ_SIZE)
                if not data:
                    break
                if self.__record and self.__record_file:
                    try:
                        self.__record_file.write(data)
                    except Exception as e:
                        logger.warning("record write failed: %s" % e)
                for q in list(self.__subscribers):
                    try:
                        q.put_nowait(data)
                    except queue.Full:
                        pass
        except (ValueError, OSError):
            pass

    @staticmethod
    def __compute_rms(chunk: bytes) -> float:
        try:
            samples = np.frombuffer(chunk, dtype="<i2").astype(np.float32)
            if samples.size == 0:
                return 0.0
            return float(np.sqrt(np.mean(np.square(samples))) / 32768.0)
        except Exception:
            return 0.0

    # -- scanner handoff ------------------------------------------------------
    def __scanner_state(self) -> str:
        try:
            out = subprocess.run(SUPERVISOR + ["status", SCANNER_PROGRAM], capture_output=True, text=True, timeout=10).stdout
            return out.split()[1] if out else "UNKNOWN"
        except Exception:
            return "UNKNOWN"

    def __set_device_enabled(self, enabled: bool) -> None:
        """Enable/disable the borrow dongle in the scanner config (live)."""
        serial = self.__device_serial()
        if not serial:
            return
        try:
            config = scanner_config.load()
        except Exception as e:
            logger.warning("could not load scanner config: %s" % e)
            return
        changed = False
        for device in config.get("devices", []):
            if str(device.get("serial", "")) == serial and bool(device.get("enabled")) != enabled:
                device["enabled"] = enabled
                changed = True
        if not changed:
            return
        try:
            scanner_config.save(config)
        except Exception as e:
            logger.warning("could not save scanner config: %s" % e)
            return
        try:
            scanners = scanner_mqtt.get_status(timeout=2.0)
        except Exception as e:
            logger.warning("scanner status failed: %s" % e)
            scanners = {}
        for scanner_id in scanners:
            try:
                scanner_mqtt.apply_config(scanner_id, config)
            except Exception as e:
                logger.warning("could not apply scanner config: %s" % e)
        logger.info("scanner device %s enabled=%s" % (serial, enabled))

    def __stop_scanner(self) -> None:
        logger.info("stopping scanner to free the RTL-SDR")
        subprocess.run(SUPERVISOR + ["stop", SCANNER_PROGRAM], capture_output=True, timeout=30)
        deadline = time.time() + 15
        while time.time() < deadline and self.__scanner_state() not in ("STOPPED", "EXITED", "FATAL", "UNKNOWN"):
            time.sleep(0.5)
        time.sleep(1)

    def __start_scanner(self) -> None:
        logger.info("starting scanner")
        subprocess.run(SUPERVISOR + ["start", SCANNER_PROGRAM], capture_output=True, timeout=30)

    # -- recording ------------------------------------------------------------
    def __start_recording(self) -> None:
        self.__record_begin = timezone.now()
        self.__record_started = time.time()
        rel_dir = os.path.join("transmission", timezone.now().strftime("%Y-%m-%d"))
        full_dir = os.path.join(monitor.settings.MEDIA_ROOT, rel_dir)
        os.makedirs(full_dir, exist_ok=True)
        name = "radio_%d_%s.mp3" % (self.__frequency, timezone.now().strftime("%Y%m%d_%H%M%S"))
        self.__record_path = os.path.join(rel_dir, name)
        self.__record_file = open(os.path.join(monitor.settings.MEDIA_ROOT, self.__record_path), "wb")
        self.__record = True
        logger.info("recording to %s" % self.__record_path)

    def __finalize_recording(self) -> None:
        if not self.__record:
            return
        self.__record = False
        try:
            if self.__record_file:
                self.__record_file.close()
        except Exception:
            pass
        self.__record_file = None
        if not self.__record_path:
            return
        try:
            transmission = Transmission(
                begin_frequency=self.__frequency,
                end_frequency=self.__frequency,
                begin_date=self.__record_begin or timezone.now(),
                end_date=timezone.now(),
                sample_size=SAMPLE_RATE,
                data_type="audio",
                audio_class_id=get_default_audio_class_id(),
                group_id=get_default_group_id(),
                device_id=get_default_device_id(),
                source="radio",
            )
            transmission.data_file.name = self.__record_path
            transmission.save()
            logger.info("saved recording %s as transmission %d" % (self.__record_path, transmission.id))
        except Exception as e:
            logger.warning("failed to register recording: %s" % e)
        finally:
            self.__record_path = None
            self.__record_begin = None


radio_controller = RadioController()
