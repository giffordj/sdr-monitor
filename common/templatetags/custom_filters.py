from django import template
from django.utils.translation import get_language

register = template.Library()


@register.filter
def humanize_field(value):
    try:
        return str(value).replace("_", " ").replace("-", " ").strip().capitalize()
    except (ValueError, TypeError):
        return value


@register.filter
def m(value):
    try:
        return f"{round(value)} m"
    except (ValueError, TypeError):
        return value


@register.filter
def km(value):
    try:
        return f"{value / 1000:.2f} km"
    except (ValueError, TypeError):
        return value


@register.filter
def kmh(value):
    try:
        return f"{value * 3600 / 1000:.2f} km/h"
    except (ValueError, TypeError):
        return value


@register.filter
def duration(value):
    if value is not None:
        days = value.days
        hours, remainder = divmod(value.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        language = get_language()
        if language == "pl":
            return "{}d {:02d}g {:02d}m {:02d}s".format(days, hours, minutes, seconds)
        else:
            return "{}d {:02d}h {:02d}m {:02d}s".format(days, hours, minutes, seconds)
    return ""


@register.filter
def seconds(value):
    if value is None:
        return ""
    else:
        return "{} s".format(value.seconds)


@register.filter
def duration_limit(value):
    if value is not None:
        days = value.days
        hours, remainder = divmod(value.seconds, 3600)
        language = get_language()
        if language == "pl":
            return "{}d {:02d}g".format(days, hours)
        else:
            return "{}d {:02d}h".format(days, hours)
    return ""


@register.filter
def battery(value):
    if value is not None:
        return "{} %".format(value)
    else:
        return ""


@register.simple_tag(takes_context=True)
def url_with_param(context, key, value, delimiter=""):
    query = context["request"].GET.copy()
    if delimiter and key in query:
        values = query[key].split(delimiter)
        values = [value] + [v for v in values if v.replace("-", "") != value.replace("-", "")]
        query[key] = delimiter.join(values)
    else:
        query[key] = value
    return "?" + query.urlencode()
