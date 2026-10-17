from common.utils.type import *
from django import forms
from enum import Enum
from sdr.models import *


class AppSettingsKey(Enum):
    SPECTROGRAMS_TOTAL_SIZE_GB = ("spectrograms_total_size_gb", 0, int)
    SPECTROGRAMS_KEEP_COUNT = ("spectrograms_keep_count", 20, int)
    TRANSMISSIONS_TOTAL_SIZE_GB = ("transmissions_total_size_gb", 0, int)
    N2YO_API_KEY = ("n2yo_api_key", "", str)
    GAIN_TESTER_DATA_ENABLED = ("gain_tester_data_enabled", False, str_to_bool)
    AUTO_DELETE_NOISE = ("auto_delete_noise", False, str_to_bool)
    AUTO_DELETE_NOISE_LABELS = ("auto_delete_noise_labels", "Noise", str)
    TRANSMISSION_KEEP_RULES = ("transmission_keep_rules", "", str)

    def __init__(self, key: str, default, cast):
        self.key = key
        self.default = default
        self.cast = cast


class AppSettings:
    @staticmethod
    def get(setting: AppSettingsKey):
        try:
            obj = AppSetting.objects.get(key=setting.key)
            return setting.cast(obj.value)
        except AppSetting.DoesNotExist:
            return setting.default
        except (ValueError, TypeError):
            return setting.default

    @staticmethod
    def set(setting: AppSettingsKey, value):
        AppSetting.objects.update_or_create(key=setting.key, defaults={"value": str(value)})

    @staticmethod
    def noise_labels() -> list[str]:
        raw = AppSettings.get(AppSettingsKey.AUTO_DELETE_NOISE_LABELS)
        return [label.strip() for label in raw.split(",") if label.strip()]

    @staticmethod
    def keep_rules() -> dict:
        """Parse the per-class keep rules: comma-separated ``Class:seconds``.

        A transmission whose class name matches is kept (excluded from the
        automatic deletions) when its duration is longer than the given number
        of seconds. Unknown/garbage entries are ignored.
        """
        raw = AppSettings.get(AppSettingsKey.TRANSMISSION_KEEP_RULES)
        rules = {}
        for part in raw.replace("\n", ",").split(","):
            part = part.strip()
            if not part or ":" not in part:
                continue
            name, _, seconds = part.partition(":")
            name = name.strip()
            try:
                rules[name] = int(float(seconds.strip()))
            except (ValueError, TypeError):
                continue
        return rules

    @staticmethod
    def should_keep(name: str, duration_seconds: float, rules: dict = None) -> bool:
        """True if a transmission of class ``name`` and this duration is protected."""
        if rules is None:
            rules = AppSettings.keep_rules()
        return name in rules and duration_seconds > rules[name]


class AppSettingsForm(forms.Form):
    n2yo_api_key = forms.CharField(label="n2yo api key", max_length=255, required=False, help_text="get your key from https://n2yo.com/api/")
    spectrograms_total_size_gb = forms.IntegerField(label="Spectrograms size", help_text="keep only the last n GB of spectrograms, 0 for unlimited")
    transmissions_total_size_gb = forms.IntegerField(label="Transmissions size", help_text="keep only the last n GB of transmissions, 0 for unlimited")
    gain_tester_data_enabled = forms.BooleanField(label="Gain tester data", help_text="show spectrograms and transmissions in table view", required=False)
    
    

    def load_initial(self):
        self.initial = {
            AppSettingsKey.SPECTROGRAMS_TOTAL_SIZE_GB.key: AppSettings.get(AppSettingsKey.SPECTROGRAMS_TOTAL_SIZE_GB),
            AppSettingsKey.TRANSMISSIONS_TOTAL_SIZE_GB.key: AppSettings.get(AppSettingsKey.TRANSMISSIONS_TOTAL_SIZE_GB),
            AppSettingsKey.N2YO_API_KEY.key: AppSettings.get(AppSettingsKey.N2YO_API_KEY),
            AppSettingsKey.GAIN_TESTER_DATA_ENABLED.key: AppSettings.get(AppSettingsKey.GAIN_TESTER_DATA_ENABLED),
        }

    def save(self):
        data = self.cleaned_data
        AppSettings.set(AppSettingsKey.SPECTROGRAMS_TOTAL_SIZE_GB, data[AppSettingsKey.SPECTROGRAMS_TOTAL_SIZE_GB.key])
        AppSettings.set(AppSettingsKey.TRANSMISSIONS_TOTAL_SIZE_GB, data[AppSettingsKey.TRANSMISSIONS_TOTAL_SIZE_GB.key])
        AppSettings.set(AppSettingsKey.N2YO_API_KEY, data[AppSettingsKey.N2YO_API_KEY.key])
        AppSettings.set(AppSettingsKey.GAIN_TESTER_DATA_ENABLED, data[AppSettingsKey.GAIN_TESTER_DATA_ENABLED.key])
