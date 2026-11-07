from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import Booking, Room


def build_absolute_url(path, request=None):
    if request is not None:
        return request.build_absolute_uri(path)
    return f"{settings.SITE_URL.rstrip('/')}{path}"


def send_confirmation_email(booking, request=None):
    confirm_url = build_absolute_url(
        reverse("booking:booking_confirm_email", args=[booking.confirmation_token]),
        request,
    )
    detail_url = build_absolute_url(
        reverse("booking:booking_detail", args=[booking.confirmation_token]),
        request,
    )
    subject = f"Підтвердіть бронювання #{booking.pk}"
    message = (
        f"Вітаємо, {booking.name}!\n\n"
        f"Ви створили бронювання:\n"
        f"Кімната/місце: {booking.room}\n"
        f"Початок: {timezone.localtime(booking.start):%d.%m.%Y %H:%M}\n"
        f"Завершення: {timezone.localtime(booking.end):%d.%m.%Y %H:%M}\n"
        f"Кількість гостей: {booking.guests}\n"
        f"Вартість: {booking.total_price}\n\n"
        f"Щоб підтвердити бронювання, перейдіть за посиланням:\n{confirm_url}\n\n"
        f"Переглянути або скасувати бронювання:\n{detail_url}\n"
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [booking.email])


def send_status_email(booking, request=None):
    detail_url = build_absolute_url(
        reverse("booking:booking_detail", args=[booking.confirmation_token]),
        request,
    )
    subject = f"Статус бронювання #{booking.pk}: {booking.get_status_display()}"
    message = (
        f"Вітаємо, {booking.name}!\n\n"
        f"Статус вашого бронювання змінено на: {booking.get_status_display()}.\n\n"
        f"Кімната/місце: {booking.room}\n"
        f"Початок: {timezone.localtime(booking.start):%d.%m.%Y %H:%M}\n"
        f"Завершення: {timezone.localtime(booking.end):%d.%m.%Y %H:%M}\n\n"
        f"Деталі: {detail_url}\n"
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [booking.email])


def create_booking(*, room, user, name, email, start, end, guests, request=None):
    with transaction.atomic():
        locked_room = Room.objects.select_for_update().get(pk=room.pk)
        booking = Booking(
            room=locked_room,
            user=user if user is not None and user.is_authenticated else None,
            name=name,
            email=email,
            start=start,
            end=end,
            guests=guests,
        )
        booking.full_clean()
        booking.save()
    send_confirmation_email(booking, request)
    return booking


def change_status(booking, new_status, request=None, notify=True):
    if booking.status == new_status:
        return booking
    with transaction.atomic():
        Room.objects.select_for_update().get(pk=booking.room_id)
        if new_status in Booking.BLOCKING_STATUSES and not booking.room.is_available(
            booking.start, booking.end, exclude_booking_id=booking.pk
        ):
            raise ValidationError("Обраний період уже зайнятий іншим бронюванням.")
        booking.status = new_status
        booking.save(update_fields=["status", "updated_at"])
    if notify:
        send_status_email(booking, request)
    return booking


def check_availability(room, start, end, exclude_booking_id=None):
    conflicts = Booking.objects.overlapping(room, start, end)
    if exclude_booking_id is not None:
        conflicts = conflicts.exclude(pk=exclude_booking_id)
    probe = Booking(room=room, start=start, end=end)
    return {
        "available": not conflicts.exists(),
        "price": str(probe.calculate_price()),
        "conflicts": [
            {
                "start": timezone.localtime(b.start).isoformat(),
                "end": timezone.localtime(b.end).isoformat(),
                "status": b.status,
            }
            for b in conflicts.order_by("start")
        ],
    }
