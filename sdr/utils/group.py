from django.db.models import F
from sdr.models import *

# Modulation types offered when adding/editing a group. The list is combined
# with whatever the scanner has already produced, so new types show up too.
DEFAULT_MODULATIONS = ["AM", "FM", "NFM", "WFM", "USB", "LSB", "DSB", "CW"]


def get_modulation_choices():
    existing = set(Group.objects.values_list("modulation", flat=True).distinct())
    return sorted({m for m in (set(DEFAULT_MODULATIONS) | existing) if m})


def update_groups():
    Transmission.objects.update(group_id=get_default_group_id())
    for group in Group.objects.annotate(bandwidth=F("end_frequency") - F("begin_frequency")).order_by("-bandwidth").all():
        Transmission.objects.annotate(frequency=(F("begin_frequency") + F("end_frequency")) / 2).filter(
            frequency__gte=group.begin_frequency, frequency__lte=group.end_frequency
        ).update(group_id=group.id)
