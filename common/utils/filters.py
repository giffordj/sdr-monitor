import datetime
import re

from django.core.exceptions import FieldError
from django.db.models import (
    BigIntegerField,
    DecimalField,
    DurationField,
    FloatField,
    IntegerField,
    PositiveBigIntegerField,
    PositiveIntegerField,
    SmallIntegerField,
)

NUMBER_FIELD_TYPES = (
    IntegerField,
    BigIntegerField,
    PositiveIntegerField,
    PositiveBigIntegerField,
    SmallIntegerField,
    FloatField,
    DecimalField,
)

# Matches a single natural-language numeric filter, e.g. "5", ">5", ">=5",
# "<5", "<=5", "=5", "1-10", "1..10" or "1 to 10".
RANGE_RE = re.compile(
    r"^\s*(?P<op>>=|<=|>|<|=)?\s*(?P<low>-?\d+(?:\.\d+)?)"
    r"\s*(?:(?:\.\.|-|to)\s*(?P<high>-?\d+(?:\.\d+)?))?\s*$",
    re.IGNORECASE,
)


def parse_numeric_expression(value):
    """Return a list of (lookup, raw_value) pairs, or None if not an expression."""
    match = RANGE_RE.match(str(value))
    if not match:
        return None
    op = match.group("op")
    low = match.group("low")
    high = match.group("high")
    if op in (">", ">="):
        return [("gt" if op == ">" else "gte", low)]
    if op in ("<", "<="):
        return [("lt" if op == "<" else "lte", low)]
    if op == "=":
        return [("exact", low)]
    if high is not None:
        return [("gte", low), ("lte", high)]
    return [("exact", low)]


def mhz_expression_to_hz(value):
    """Convert a MHz numeric expression ("1-10", ">2") to the same form in Hz."""
    match = RANGE_RE.match(str(value))
    if not match:
        return None
    op = match.group("op") or ""
    low = int(round(float(match.group("low")) * 1000000))
    high = match.group("high")
    if high is not None:
        return "%d-%d" % (low, int(round(float(high) * 1000000)))
    return "%s%d" % (op, low)


def get_fields(qs):
    fields = {}
    for field in qs.model._meta.get_fields():
        if field.concrete and not field.many_to_many and not field.one_to_many:
            fields[field.name] = field
    for key, annotation in qs.query.annotations.items():
        fields[key] = annotation.output_field
    return fields


def get_options_lists(request, qs, keys):
    options_lists = {}
    for key in keys:
        options = qs.values_list(key, flat=True).distinct().order_by(key)
        options_lists[key + "_options"] = sorted(list(options))
    return options_lists


def filter(request, qs):
    fields = get_fields(qs)
    for key, value in request.GET.items():
        if not value:
            continue
        base = key.split("__")[0]
        field = fields.get(base)
        if field is None:
            continue
        is_duration = isinstance(field, DurationField)
        is_number = isinstance(field, NUMBER_FIELD_TYPES)

        # Natural-language range on a bare field name: "5", ">5", "1-10"...
        if "__" not in key and (is_number or is_duration):
            expression = parse_numeric_expression(value)
            if expression is not None:
                for lookup, raw in expression:
                    lookup_key = base if lookup == "exact" else base + "__" + lookup
                    try:
                        if is_duration:
                            raw = datetime.timedelta(seconds=int(float(raw)))
                        qs = qs.filter(**{lookup_key: raw})
                    except (FieldError, ValueError, TypeError):
                        continue
                continue

        lookup_value = value
        if is_duration:
            try:
                lookup_value = datetime.timedelta(seconds=int(value))
            except (TypeError, ValueError):
                continue
        # Skip individual invalid lookups (e.g. ?field__bogus=1) instead of
        # raising FieldError and returning a 500; valid filters still apply.
        try:
            qs = qs.filter(**{key: lookup_value})
        except (FieldError, ValueError, TypeError):
            continue
    return qs


def order_by(request, qs, default=None):
    default = default or []
    fields = get_fields(qs)
    order_by_fields = []
    order_by_param = request.GET.get("order_by")
    if order_by_param:
        for field in order_by_param.split(","):
            field_name = field.lstrip("-").split("__")[0]
            if field_name in fields:
                order_by_fields.append(field)
    order_by_fields.extend(default)
    try:
        return qs.order_by(*order_by_fields)
    except (FieldError, ValueError):
        return qs.order_by(*default)
