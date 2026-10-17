from sdr.app_settings import *
from sdr.models import *
from sdr.utils.transmission import delete_transmissions
import logging
import monitor.settings
import os
import threading
import time


class Cleaner(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.__is_runnig = True
        self.__last_clear_timestamp = 0.0
        self.__clear_interval = 60 * 60
        self.__logger = logging.getLogger("Cleaner")
        self.__spectrograms_total_size_gb = AppSettings.get(AppSettingsKey.SPECTROGRAMS_TOTAL_SIZE_GB)
        self.__spectrograms_keep_count = AppSettings.get(AppSettingsKey.SPECTROGRAMS_KEEP_COUNT)
        self.__transmissions_total_size_gb = AppSettings.get(AppSettingsKey.TRANSMISSIONS_TOTAL_SIZE_GB)
        self.__auto_delete_noise = AppSettings.get(AppSettingsKey.AUTO_DELETE_NOISE)
        self.__noise_labels = AppSettings.noise_labels()
        self.__keep_rules = AppSettings.keep_rules()

    def run(self):
        while self.__is_runnig:
            now = time.time()
            if self.__last_clear_timestamp + self.__clear_interval < now:
                self.__last_clear_timestamp = now
                try:
                    self.__spectrograms_total_size_gb = AppSettings.get(AppSettingsKey.SPECTROGRAMS_TOTAL_SIZE_GB)
                    self.__spectrograms_keep_count = AppSettings.get(AppSettingsKey.SPECTROGRAMS_KEEP_COUNT)
                    self.__transmissions_total_size_gb = AppSettings.get(AppSettingsKey.TRANSMISSIONS_TOTAL_SIZE_GB)
                    self.__auto_delete_noise = AppSettings.get(AppSettingsKey.AUTO_DELETE_NOISE)
                    self.__noise_labels = AppSettings.noise_labels()
                    self.__keep_rules = AppSettings.keep_rules()
                    if 0 < self.__spectrograms_total_size_gb:
                        self.__remove_spectrograms()
                    if 0 < self.__spectrograms_keep_count:
                        self.__remove_spectrograms_by_count()
                    if 0 < self.__transmissions_total_size_gb:
                        self.__remove_transmissions()
                    if self.__auto_delete_noise:
                        self.__remove_noise_transmissions()
                    self.__remove_old_image_cache()
                except Exception as e:
                    self.__logger.warning("exception: %s" % e)
            time.sleep(1)

    def stop(self):
        self.__is_runnig = False

    def __remove_old_image_cache(self, days: int = 3):
        """Prune the rendered spectrogram image cache (views.spectrogram_data)."""
        path = os.path.join(monitor.settings.BASE_DIR, "data", "image_cache")
        if not os.path.isdir(path):
            return
        cutoff = time.time() - days * 86400
        removed = 0
        for name in os.listdir(path):
            full = os.path.join(path, name)
            try:
                if os.path.isfile(full) and os.path.getmtime(full) < cutoff:
                    os.remove(full)
                    removed += 1
            except OSError:
                continue
        if removed:
            self.__logger.info("removed %d old cached spectrogram images" % removed)

    def __delete_spectrograms(self, objects):
        for s in Spectrogram.objects.filter(id__in=objects):
            try:
                s.data_file.delete(save=False)
            except Exception as e:
                self.__logger.warning("failed to remove spectrogram file %d: %s" % (s.id, e))
        Spectrogram.objects.filter(id__in=objects).delete()

    def __remove_spectrograms_by_count(self):
        keep = self.__spectrograms_keep_count
        objects = list(Spectrogram.objects.order_by("-begin_real_date").values_list("id", flat=True)[keep:])
        if not objects:
            return
        self.__logger.info("removing %d spectrograms, keeping last %d" % (len(objects), keep))
        self.__delete_spectrograms(objects)

    def __remove_spectrograms(self):
        removed = 0
        total_size = 0
        max_size = self.__spectrograms_total_size_gb * 1024 * 1024 * 1024
        objects = []
        for s in Spectrogram.objects.order_by("-begin_real_date"):
            try:
                total_size += s.data_file.size
                if max_size < total_size:
                    removed += 1
                    objects.append(s.id)
                    self.__logger.debug("removing spectrogram: %d, %s" % (s.id, s.begin_real_date))
            except FileNotFoundError:
                removed += 1
                objects.append(s.id)
                self.__logger.debug("removing spectrogram: %d, %s" % (s.id, s.begin_real_date))

        self.__logger.info("spectrograms max size: %.2f GB, current size: %.2f GB" % (self.__spectrograms_total_size_gb, total_size / 1024 / 1024 / 1024))
        self.__delete_spectrograms(objects)
        self.__logger.info("removed last %d spectrograms" % removed)

    def __remove_transmissions(self):
        removed = 0
        total_size = 0
        max_size = self.__transmissions_total_size_gb * 1024 * 1024 * 1024
        objects = []
        for t in Transmission.objects.order_by("-begin_date").select_related("audio_class"):
            if AppSettings.should_keep(t.audio_class.name, t.duration().total_seconds(), self.__keep_rules):
                continue
            try:
                total_size += t.data_file.size
                if max_size < total_size:
                    removed += 1
                    objects.append(t.id)
                    self.__logger.debug("removing transmission: %d, %s" % (t.id, t.begin_date))
            except FileNotFoundError:
                removed += 1
                objects.append(t.id)
                self.__logger.debug("removing transmission: %d, %s" % (t.id, t.begin_date))

        self.__logger.info("transmissions max size: %.2f GB, current size: %.2f" % (self.__transmissions_total_size_gb, total_size / 1024 / 1024 / 1024))
        delete_transmissions(Transmission.objects.filter(id__in=objects))
        self.__logger.info("removed last %d transmissions" % removed)

    def __remove_noise_transmissions(self):
        if not self.__noise_labels:
            return
        candidates = Transmission.objects.filter(audio_class__name__in=self.__noise_labels).select_related("audio_class")
        delete_ids = [
            t.id
            for t in candidates
            if not AppSettings.should_keep(t.audio_class.name, t.duration().total_seconds(), self.__keep_rules)
        ]
        if not delete_ids:
            return
        kept = candidates.count() - len(delete_ids)
        self.__logger.info(
            "auto-deleting %d noise transmissions (classes: %s)%s"
            % (len(delete_ids), ", ".join(self.__noise_labels), ", kept %d via keep rules" % kept if kept else "")
        )
        delete_transmissions(Transmission.objects.filter(id__in=delete_ids))
