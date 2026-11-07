import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone


class RoomType(models.Model):
    name = models.CharField("Назва", max_length=100, unique=True)
    description = models.TextField("Опис", blank=True)

    class Meta:
        verbose_name = "Тип кімнати/місця"
        verbose_name_plural = "Типи кімнат/місць"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Feature(models.Model):
    name = models.CharField("Назва", max_length=100, unique=True)

    class Meta:
        verbose_name = "Особливість"
        verbose_name_plural = "Особливості"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Room(models.Model):
    name = models.CharField("Назва", max_length=150)
    room_type = models.ForeignKey(
        RoomType,
        on_delete=models.PROTECT,
        related_name="rooms",
        verbose_name="Тип",
    )
    description = models.TextField("Опис", blank=True)
    capacity = models.PositiveIntegerField("Вмістимість")
    price_per_hour = models.DecimalField("Ціна за годину", max_digits=10, decimal_places=2)
    features = models.ManyToManyField(
        Feature,
        blank=True,
        related_name="rooms",
        verbose_name="Особливості",
    )
    is_active = models.BooleanField("Доступна для бронювання", default=True)

    class Meta:
        verbose_name = "Кімната/місце"
        verbose_name_plural = "Кімнати/місця"
        ordering = ["room_type__name", "name"]

    def __str__(self):
        return f"{self.name} ({self.room_type})"

    def get_absolute_url(self):
        return reverse("booking:room_detail", args=[self.pk])

    def is_available(self, start, end, exclude_booking_id=None):
        qs = Booking.objects.overlapping(self, start, end)
        if exclude_booking_id is not None:
            qs = qs.exclude(pk=exclude_booking_id)
        return not qs.exists()


class BookingQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status__in=Booking.BLOCKING_STATUSES)

    def overlapping(self, room, start, end):
        return self.active().filter(room=room, start__lt=end, end__gt=start)


class Booking(models.Model):
    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Очікує підтвердження"),
        (STATUS_CONFIRMED, "Підтверджено"),
        (STATUS_CANCELLED, "Скасовано"),
    ]
    BLOCKING_STATUSES = [STATUS_PENDING, STATUS_CONFIRMED]

    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name="bookings",
        verbose_name="Кімната/місце",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bookings",
        verbose_name="Користувач",
    )
    name = models.CharField("Ім'я", max_length=150)
    email = models.EmailField("Електронна пошта")
    start = models.DateTimeField("Початок")
    end = models.DateTimeField("Завершення")
    guests = models.PositiveIntegerField("Кількість гостей", default=1)
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    email_confirmed = models.BooleanField("Підтверджено через e-mail", default=False)
    confirmation_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    total_price = models.DecimalField("Вартість", max_digits=12, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField("Створено", auto_now_add=True)
    updated_at = models.DateTimeField("Оновлено", auto_now=True)

    objects = BookingQuerySet.as_manager()

    class Meta:
        verbose_name = "Бронювання"
        verbose_name_plural = "Бронювання"
        ordering = ["-start"]
        indexes = [models.Index(fields=["room", "start", "end"])]

    def __str__(self):
        if not (self.room_id and self.start and self.end):
            return f"Бронювання #{self.pk}"
        start = timezone.localtime(self.start)
        end = timezone.localtime(self.end)
        return f"#{self.pk} {self.room.name}: {start:%d.%m.%Y %H:%M} - {end:%d.%m.%Y %H:%M}"

    def get_absolute_url(self):
        return reverse("booking:booking_detail", args=[self.confirmation_token])

    @property
    def is_blocking(self):
        return self.status in self.BLOCKING_STATUSES

    def calculate_price(self):
        if not (self.room_id and self.start and self.end):
            return Decimal("0.00")
        hours = Decimal((self.end - self.start).total_seconds()) / Decimal(3600)
        return (hours * self.room.price_per_hour).quantize(Decimal("0.01"))

    def clean(self):
        errors = {}
        if self.start and self.end and self.end <= self.start:
            errors["end"] = "Дата завершення має бути пізніше за дату початку."
        if self.room_id:
            if not self.room.is_active and self.is_blocking:
                errors["room"] = "Ця кімната/місце зараз недоступна для бронювання."
            if self.guests and self.guests > self.room.capacity:
                errors["guests"] = f"Максимальна вмістимість: {self.room.capacity}."
            if (
                "end" not in errors
                and self.start
                and self.end
                and self.is_blocking
                and not self.room.is_available(self.start, self.end, exclude_booking_id=self.pk)
            ):
                errors["start"] = "Обраний період уже зайнятий."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.total_price = self.calculate_price()
        super().save(*args, **kwargs)
