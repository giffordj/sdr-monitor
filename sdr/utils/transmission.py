import logging

from sdr.models import Transmission


__logger = logging.getLogger("Transmission")


def delete_transmission(transmission: Transmission) -> None:
    """Delete a transmission together with its recording file.

    Django's model delete does not remove FileField data, so callers must go
    through here to actually reclaim disk space.
    """
    try:
        if transmission.data_file:
            transmission.data_file.delete(save=False)
    except Exception as e:
        __logger.warning("failed to remove transmission file %s: %s" % (transmission.id, e))
    transmission.delete()


def delete_transmissions(transmissions) -> int:
    """Delete an iterable/queryset of transmissions and their files."""
    count = 0
    for transmission in transmissions:
        delete_transmission(transmission)
        count += 1
    return count
