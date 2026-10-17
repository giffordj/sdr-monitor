from sdr.utils.cleaner import Cleaner
from sdr.utils.reader import Reader
import argparse
import logging
import monitor.settings as settings
import shlex
import time


def run(*args):
    parser = argparse.ArgumentParser(description="Set worker config")
    parser.add_argument("-r", "--reader", help="enable reader", action="store_true")
    parser.add_argument("-clr", "--cleaner", help="enable cleaner", action="store_true")
    parser.add_argument("-cls", "--classifier", help="enable classifier", action="store_true")
    args = parser.parse_args(shlex.split(args[0] if len(args) else ""))

    # Guard against the zero-retention trap: with both budgets at 0 GB the panel
    # silently discards everything the scanner sends (hit 2026-10-15).
    try:
        from sdr.app_settings import AppSettings, AppSettingsKey
        log = logging.getLogger("Worker")
        for key, label in ((AppSettingsKey.SPECTROGRAMS_TOTAL_SIZE_GB, "spectrograms"),
                           (AppSettingsKey.TRANSMISSIONS_TOTAL_SIZE_GB, "transmissions")):
            try:
                size = int(AppSettings.get(key))
            except (TypeError, ValueError):
                size = -1
            if size <= 0:
                log.warning("%s retention is %d GB - scanner data will be discarded (Settings > Retention)" % (label, size))
    except Exception as e:
        logging.getLogger("Worker").warning("retention check failed: %s" % e)

    threads = []
    if args.reader:
        threads.append(Reader(settings.MQTT))
    if args.cleaner:
        threads.append(Cleaner())
    if args.classifier:
        try:
            from sdr.utils.classifier_controller import ClassifierController

            threads.append(ClassifierController())
        except Exception as e:
            logging.getLogger("Worker").warning("exception: %s" % e)

    for t in threads:
        t.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        for t in threads:
            t.stop()

    for t in threads:
        t.join()
