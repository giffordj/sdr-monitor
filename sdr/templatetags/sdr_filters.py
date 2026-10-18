from django import template
import humanize

register = template.Library()


def append(str, unit, value, current_unit):
    if value == 0:
        return (str, unit)
    else:
        if str == "":
            return ("%d" % value, current_unit)
        else:
            return ("%s.%03d" % (str, value), unit)


def frequency(value, force_segment=None):
    try:
        value = int(value)
        if value == 0:
            return "0 Hz"
        (str, unit) = ("", "")
        (str, unit) = append(str, unit, value // 1000000000, "GHz")
        (str, unit) = append(str, unit, (value // 1000000) % 1000, "MHz")
        (str, unit) = append(str, unit, (value // 1000) % 1000, "kHz")
        (str, unit) = append(str, unit, value % 1000, "Hz")
        return "%s %s" % (str, unit)
    except (TypeError, ValueError):
        return value


def to_mhz(value):
    try:
        return ("%.6f" % (int(value) / 1000000)).rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return value


def natural_size(value):
    return humanize.naturalsize(value, True)


def big_number(value):
    return humanize.intcomma(value).replace(",", " ")


# Frequency bands for the list pages. First match wins, so specific bands are
# listed before the generic HF/VHF/UHF ranges. Each entry: (low, high, name, tone)
BAND_RANGES = (
    (162400000, 162550000, "NOAA weather", "info"),
    (118000000, 137000000, "Airband", "info"),
    (144000000, 148000000, "2m", "success"),
    (420000000, 450000000, "70cm", "success"),
    (450000000, 470000000, "UHF", "warning"),
    (88000000, 108000000, "FM broadcast", "warning"),
    (148000000, 174000000, "VHF high", "info"),
    (174000000, 420000000, "VHF/UHF", "secondary"),
    (470000000, 1000000000, "UHF", "warning"),
    (1000000000, 10 ** 12, "SHF", "secondary"),
    (5900000, 6200000, "49m", "success"),
    (7200000, 7400000, "41m", "success"),
    (9400000, 9900000, "31m", "success"),
    (11600000, 12100000, "25m", "success"),
    (13700000, 13900000, "22m", "success"),
    (15100000, 15800000, "19m", "success"),
    (1800000, 2000000, "160m", "success"),
    (3500000, 4000000, "80m", "success"),
    (7000000, 7300000, "40m", "success"),
    (10100000, 10150000, "30m", "success"),
    (14000000, 14350000, "20m", "success"),
    (18068000, 18168000, "17m", "success"),
    (21000000, 21450000, "15m", "success"),
    (24890000, 24990000, "12m", "success"),
    (28000000, 29700000, "10m", "success"),
    (1700000, 30000000, "HF", "success"),
    (300000, 1700000, "MW", "warning"),
    (0, 300000, "LF", "secondary"),
)


def _band_entry(value):
    try:
        hz = int(value)
    except (TypeError, ValueError):
        return None
    for low, high, name, tone in BAND_RANGES:
        if low <= hz <= high:
            return (name, tone)
    return None


def band(value):
    entry = _band_entry(value)
    return entry[0] if entry else "\u2014"


def band_tone(value):
    entry = _band_entry(value)
    return entry[1] if entry else "secondary"


register.filter("band", band)
register.filter("band_tone", band_tone)
register.filter("frequency", frequency)
register.filter("to_mhz", to_mhz)
register.filter("natural_size", natural_size)
register.filter("big_number", big_number)
