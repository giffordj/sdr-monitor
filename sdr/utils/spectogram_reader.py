from django.utils import timezone
from django.utils.timezone import make_aware
from humanize import naturalsize
from sdr.models import *
import base64
import json
import logging
import numpy as np
import re
import sdr.utils.device
import sdr.utils.file


class SpectrogramReader:
    def __init__(self):
        self.__logger = logging.getLogger("Spectrogram")
        # The device part is the scanner's alias, which may contain spaces and
        # even slashes ("NESDR VHF/UHF", "Blog V4 HF"). Capture the whole
        # remainder: the old [\w\.]+ truncated at the first space, so "Blog
        # V4 HF" was stored as device "Blog" (2026-10-15).
        self.__regex = re.compile("sdr/spectrogram/\\w+/(.+)")

    def get_device(self, name):
        # The scanner alias (raw_name) is the source of truth. Keep the display
        # name in sync so the panel's device list lines up with Settings >
        # Scanner (a stale row kept the old truncated name "Blog" after the
        # alias fix, so the devices looked unassociated).
        pretty = sdr.utils.device.convert_raw_to_name_to_pretty_name(name)
        device, created = Device.objects.get_or_create(raw_name=name, defaults={"name": pretty})
        if not created and device.name != pretty:
            Device.objects.filter(id=device.id).update(name=pretty)
            device.name = pretty
        return device

    def round_down_date(self, date):
        return date.replace(hour=0, minute=0, second=0, microsecond=0)

    def round_up_date(self, date):
        return date.replace(hour=23, minute=59, second=59, microsecond=999999)

    def check_spectrogram_integrity(self, s):
        y_size = np.frombuffer(s.labels, dtype=np.uint64).size
        x_size = (s.end_frequency - s.begin_frequency) // s.step_frequency + 1
        data = np.memmap(s.data_file.path, dtype=np.uint8, mode="r", shape=(y_size, x_size))
        self.__logger.info("total data shape: %s, size: %s" % (str(data.shape), naturalsize(data.size)))

    def append_spectrogram(self, device, dt, begin_frequency, end_frequency, step_frequency, data, source):
        begin_model_date = self.round_down_date(dt)
        end_model_date = self.round_up_date(dt)
        device = self.get_device(device)
        try:
            # Match the model's unique_together exactly - it does not include
            # source. Filtering on source made rows written under the previous
            # label invisible and the insert below then collided with the
            # unique index (IntegrityError, silent data loss - 2026-10-15).
            s = Spectrogram.objects.get(
                device=device,
                begin_frequency=begin_frequency,
                end_frequency=end_frequency,
                step_frequency=step_frequency,
                begin_model_date=begin_model_date,
                end_model_date=end_model_date,
            )
            if s.source != source:
                s.source = source
        except Spectrogram.DoesNotExist:
            f = (begin_frequency + end_frequency) // 2
            dir = "device_%d/spectrogram" % device.id
            (filename, filename_full) = sdr.utils.file.get_filename(dir, begin_model_date, "%s_%d_%d.bin" % (begin_model_date.strftime("%H_%M_%S"), f, step_frequency), True)
            s = Spectrogram.objects.create(
                device=device,
                begin_frequency=begin_frequency,
                end_frequency=end_frequency,
                step_frequency=step_frequency,
                begin_model_date=begin_model_date,
                end_model_date=end_model_date,
                begin_real_date=dt,
                end_real_date=dt,
                data_file=filename,
                source=source,
            )

        with open(s.data_file.path, "ab") as file:
            file.write(data)
        s.labels += np.array([int(dt.timestamp() * 1000)]).astype(np.uint64).tobytes()
        s.end_real_date = dt
        s.save()
        # self.check_spectrogram_integrity(s)

    def on_message(self, client, message):
        topic = message.topic
        m = self.__regex.match(topic)
        if m:
            device = m.group(1)
            message = json.loads(message.payload.decode("utf-8"))
            data = base64.b64decode(message["data"])
            source = message["source"]
            # The upstream scanner hard-codes "gain tester" as its source label
            # (the string is baked into /usr/bin/auto_sdr and cannot be
            # overridden through the config or CLI). The panel hides that
            # source unless the "gain tester data" setting is on, which hid
            # every live detection for days (2026-10-15). Store real scanner
            # data under a sane name instead.
            if source == "gain tester":
                source = "scanner"
            frequency = message["frequency"]
            sample_rate = message["sample_rate"]
            begin_frequency = frequency - sample_rate // 2
            end_frequency = frequency + sample_rate // 2
            step_frequency = sample_rate // len(data)
            dt = make_aware(timezone.datetime.fromtimestamp(message["time"] / 1000))
            self.__logger.info(
                f"source: {source}, device: {device}, frequency: {frequency}, sample_rate: {sample_rate}, step: {step_frequency}, datetime: {dt}, data size: {naturalsize(len(data))}"
            )
            self.append_spectrogram(m.group(1), dt, begin_frequency, end_frequency, step_frequency, data, source)
            return True
        return False
