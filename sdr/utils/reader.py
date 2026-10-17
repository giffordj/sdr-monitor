from sdr.utils import scanner_config, scanner_mqtt
from sdr.utils.gain_tester_controller import GainTesterController
from sdr.utils.scheduler import Scheduler
from sdr.utils.spectogram_reader import SpectrogramReader
from sdr.utils.transmission_reader import TransmissionReader
import common.utils.mqtt
import django.db
import json
import logging
import threading
import time


class Reader(threading.Thread):
    def __init__(self, config):
        threading.Thread.__init__(self)
        self.__logger = logging.getLogger("Reader")

        self.__parsers = []
        self.__parsers.append(SpectrogramReader())
        self.__parsers.append(TransmissionReader())
        self.__parsers.append(Scheduler())
        self.__parsers.append(GainTesterController())

        self.__client = common.utils.mqtt.get_client(config["url"], config["user"], config["password"], "sdr-monitor", self)
        self.__client.on_connect = Reader.on_connect
        self.__client.on_message = Reader.on_message

    def run(self):
        threading.Thread(target=self.__status_refresher, daemon=True).start()
        self.__client.loop_forever()

    def __status_refresher(self):
        """Keep a cached scanner status for the web UI.

        The web process must not block on MQTT round-trips (the status page
        stalled ~2.4 s per render before this cache, 2026-10-17).
        """
        while True:
            try:
                status = scanner_mqtt.get_status(timeout=3.0)
                if status:
                    scanner_mqtt.write_cache(status)
            except Exception as e:
                self.__logger.warning("status refresh failed: %s" % e)
            time.sleep(15)

    def stop(self):
        for parser in self.__parsers:
            try:
                parser.stop()
            except Exception as e:
                self.__logger.warning("failed to stop parser: %s" % e)
        self.__client.disconnect()

    def on_connect(client, userdata, flags, rc):
        self = userdata
        self.__logger.info("connected")
        # Multi-level wildcards: aliases can contain slashes ("NESDR VHF/UHF"),
        # which makes the topic deeper than +/+ matches - the broker silently
        # dropped those messages entirely (2026-10-15).
        self.__client.subscribe("sdr/spectrogram/#")
        self.__client.subscribe("sdr/transmission/#")
        self.__client.subscribe("sdr/scheduler/+/+/get")
        self.__client.subscribe("sdr/gain_test/+/+/start")
        self.__client.subscribe("sdr/gain_test/+/+/stop")
        self.__client.subscribe("sdr/gain_test/+/+/get_status")
        self.sweep_stale_gain_tests()

    def sweep_stale_gain_tests(self):
        """Un-wedge scanner state left over from a dead gain test.

        A gain test is owned by an in-process thread. If the app restarts while
        one is running, the scanner keeps scanning the test's live config with
        nobody left to send "stop" - it sat that way for days on 2026-10-15
        (transmissions silently stopped). On every (re)connect, stop any test on
        each known scanner/device and re-apply our on-disk config so normal
        scanning resumes. Runs in a daemon thread so the MQTT loop is not
        blocked.
        """
        def sweep():
            time.sleep(3)
            try:
                scanners = scanner_mqtt.get_status(timeout=3.0)
            except Exception as e:
                self.__logger.warning("stale gain test sweep: status failed: %s" % e)
                return
            scanner_mqtt.write_cache(scanners)
            config = None
            try:
                config = scanner_config.load()
            except Exception as e:
                self.__logger.warning("stale gain test sweep: config load failed: %s" % e)
            for scanner_id, status in (scanners or {}).items():
                devices = []
                status_config = status.get("config") if isinstance(status, dict) else None
                for dev in (status_config or config or {}).get("devices", []):
                    serial = dev.get("serial")
                    driver = dev.get("driver", "rtlsdr")
                    if serial:
                        devices.append("%s_%s" % (driver, serial))
                for device in devices:
                    self.__client.publish("sdr/gain_test/%s/%s/stop" % (scanner_id, device), "")
                    self.__logger.info("stopped stale gain test (if any): %s/%s" % (scanner_id, device))
                if config:
                    self.__client.publish("sdr/config/%s" % scanner_id, json.dumps(config))
                    self.__logger.info("re-applied on-disk config to scanner %s" % scanner_id)
        threading.Thread(target=sweep, daemon=True).start()

    def on_message(client, userdata, message):
        self = userdata
        django.db.reset_queries()
        django.db.close_old_connections()
        for parser in self.__parsers:
            try:
                if parser.on_message(client, message):
                    return True
            except django.db.OperationalError:
                self.__logger.warning("reset db connection")
                django.db.connection.close()
            except Exception as e:
                self.__logger.warning("exception: %s" % e)
        self.__logger.warning("can not parse, topic: %s" % (message.topic))
