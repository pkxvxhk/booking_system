import calendar
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from .models import Booking

DAY_FREE = "free"
DAY_PARTIAL = "partial"
DAY_BUSY = "busy"


def month_bounds(month_start):
    first = month_start.replace(day=1)
    days_in_month = calendar.monthrange(first.year, first.month)[1]
    last = first.replace(day=days_in_month)
    return first, last


def aware_day_range(day):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    end = timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min), tz)
    return start, end


def merge_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def day_status(intervals, day_start, day_end):
    clipped = [
        (max(start, day_start), min(end, day_end))
        for start, end in intervals
        if start < day_end and end > day_start
    ]
    if not clipped:
        return DAY_FREE, []
    merged = merge_intervals(clipped)
    covered = sum((end - start).total_seconds() for start, end in merged)
    total = (day_end - day_start).total_seconds()
    status = DAY_BUSY if covered >= total else DAY_PARTIAL
    return status, merged


def build_month_calendar(rooms, month_start):
    first, last = month_bounds(month_start)
    range_start, _ = aware_day_range(first)
    _, range_end = aware_day_range(last)
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]

    room_list = list(rooms)
    bookings = (
        Booking.objects.active()
        .filter(room__in=room_list, start__lt=range_end, end__gt=range_start)
        .values_list("room_id", "start", "end")
    )
    intervals_by_room = {room.pk: [] for room in room_list}
    for room_id, start, end in bookings:
        intervals_by_room[room_id].append((start, end))

    rows = []
    for room in room_list:
        cells = []
        for day in days:
            day_start, day_end = aware_day_range(day)
            status, busy = day_status(intervals_by_room[room.pk], day_start, day_end)
            cells.append(
                {
                    "date": day,
                    "status": status,
                    "busy": [
                        (timezone.localtime(start), timezone.localtime(end))
                        for start, end in busy
                    ],
                }
            )
        rows.append({"room": room, "cells": cells})
    return {"days": days, "rows": rows, "first": first, "last": last}


def parse_month(value):
    if isinstance(value, date):
        return value.replace(day=1)
    return timezone.localdate().replace(day=1)


def shift_month(month_start, delta):
    year = month_start.year + (month_start.month - 1 + delta) // 12
    month = (month_start.month - 1 + delta) % 12 + 1
    return date(year, month, 1)
