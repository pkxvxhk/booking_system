from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import services
from .availability import DAY_BUSY, DAY_FREE, DAY_PARTIAL, build_month_calendar
from .models import Booking, Room, RoomType


class BaseBookingTestCase(TestCase):
    def setUp(self):
        self.room_type = RoomType.objects.create(name="Переговорна")
        self.other_type = RoomType.objects.create(name="Зал")
        self.room = Room.objects.create(
            name="A", room_type=self.room_type, capacity=4, price_per_hour=Decimal("100.00")
        )
        self.hall = Room.objects.create(
            name="Hall", room_type=self.other_type, capacity=50, price_per_hour=Decimal("500.00")
        )
        base = timezone.localtime() + timedelta(days=2)
        self.start = base.replace(hour=10, minute=0, second=0, microsecond=0)
        self.end = self.start + timedelta(hours=2)

    def make_booking(self, **kwargs):
        data = {
            "room": self.room,
            "name": "Ivan",
            "email": "ivan@example.com",
            "start": self.start,
            "end": self.end,
            "guests": 2,
        }
        data.update(kwargs)
        booking = Booking(**data)
        booking.full_clean()
        booking.save()
        return booking


class BookingModelTests(BaseBookingTestCase):
    def test_price_is_calculated(self):
        booking = self.make_booking()
        self.assertEqual(booking.total_price, Decimal("200.00"))

    def test_end_before_start_rejected(self):
        with self.assertRaises(ValidationError):
            self.make_booking(end=self.start - timedelta(hours=1))

    def test_overlap_rejected(self):
        self.make_booking()
        with self.assertRaises(ValidationError):
            self.make_booking(start=self.start + timedelta(hours=1), end=self.end + timedelta(hours=1))

    def test_adjacent_allowed(self):
        self.make_booking()
        self.make_booking(start=self.end, end=self.end + timedelta(hours=1))
        self.assertEqual(Booking.objects.count(), 2)

    def test_cancelled_does_not_block(self):
        booking = self.make_booking()
        booking.status = Booking.STATUS_CANCELLED
        booking.save()
        self.make_booking()
        self.assertEqual(Booking.objects.active().count(), 1)

    def test_capacity_limit(self):
        with self.assertRaises(ValidationError):
            self.make_booking(guests=10)

    def test_inactive_room_rejected(self):
        self.room.is_active = False
        self.room.save()
        with self.assertRaises(ValidationError):
            self.make_booking()


class BookingFlowTests(BaseBookingTestCase):
    def post_data(self, **kwargs):
        data = {
            "name": "Ivan",
            "email": "ivan@example.com",
            "room": self.room.pk,
            "start": timezone.localtime(self.start).strftime("%Y-%m-%dT%H:%M"),
            "end": timezone.localtime(self.end).strftime("%Y-%m-%dT%H:%M"),
            "guests": 2,
        }
        data.update(kwargs)
        return data

    def test_create_sends_email_and_confirm(self):
        response = self.client.post(reverse("booking:booking_create"), self.post_data())
        booking = Booking.objects.get()
        self.assertRedirects(response, booking.get_absolute_url())
        self.assertEqual(len(mail.outbox), 1)
        confirm_url = reverse("booking:booking_confirm_email", args=[booking.confirmation_token])
        self.assertIn(confirm_url, mail.outbox[0].body)
        self.client.get(confirm_url)
        booking.refresh_from_db()
        self.assertTrue(booking.email_confirmed)

    def test_create_conflict_shows_error(self):
        self.make_booking()
        response = self.client.post(reverse("booking:booking_create"), self.post_data())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Booking.objects.count(), 1)

    def test_past_start_rejected(self):
        past = timezone.localtime() - timedelta(days=1)
        response = self.client.post(
            reverse("booking:booking_create"),
            self.post_data(
                start=past.strftime("%Y-%m-%dT%H:%M"),
                end=(past + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Booking.objects.exists())

    def test_logged_user_attached(self):
        user = User.objects.create_user("u", "u@example.com", "pass12345!")
        self.client.force_login(user)
        self.client.post(reverse("booking:booking_create"), self.post_data())
        self.assertEqual(Booking.objects.get().user, user)
        response = self.client.get(reverse("booking:my_bookings"))
        self.assertContains(response, self.room.name)

    def test_cancel(self):
        booking = self.make_booking()
        self.client.post(reverse("booking:booking_cancel", args=[booking.confirmation_token]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.STATUS_CANCELLED)
        self.assertEqual(len(mail.outbox), 1)


class ServiceTests(BaseBookingTestCase):
    def test_reconfirm_cancelled_conflict(self):
        first = self.make_booking()
        services.change_status(first, Booking.STATUS_CANCELLED, notify=False)
        self.make_booking()
        with self.assertRaises(ValidationError):
            services.change_status(first, Booking.STATUS_CONFIRMED, notify=False)
        first.refresh_from_db()
        self.assertEqual(first.status, Booking.STATUS_CANCELLED)


class ApiTests(BaseBookingTestCase):
    def test_availability(self):
        url = reverse("booking:api_availability")
        params = {
            "room": self.room.pk,
            "start": timezone.localtime(self.start).strftime("%Y-%m-%dT%H:%M"),
            "end": timezone.localtime(self.end).strftime("%Y-%m-%dT%H:%M"),
        }
        data = self.client.get(url, params).json()
        self.assertTrue(data["available"])
        self.assertEqual(data["price"], "200.00")
        self.make_booking()
        data = self.client.get(url, params).json()
        self.assertFalse(data["available"])
        self.assertEqual(len(data["conflicts"]), 1)

    def test_availability_bad_params(self):
        response = self.client.get(reverse("booking:api_availability"), {"room": self.room.pk})
        self.assertEqual(response.status_code, 400)

    def test_room_events(self):
        self.make_booking()
        data = self.client.get(reverse("booking:api_room_events", args=[self.room.pk])).json()
        self.assertEqual(len(data["events"]), 1)
        self.assertNotIn("email", data["events"][0])


class FilterAndCalendarTests(BaseBookingTestCase):
    def test_filter_by_type(self):
        response = self.client.get(reverse("booking:room_list"), {"room_type": self.other_type.pk})
        self.assertContains(response, "Hall")
        self.assertNotContains(response, ">A<")

    def test_filter_by_free_period(self):
        self.make_booking()
        response = self.client.get(
            reverse("booking:room_list"),
            {
                "start": timezone.localtime(self.start).strftime("%Y-%m-%dT%H:%M"),
                "end": timezone.localtime(self.end).strftime("%Y-%m-%dT%H:%M"),
            },
        )
        self.assertNotIn(self.room, list(response.context["rooms"]))
        self.assertIn(self.hall, list(response.context["rooms"]))

    def test_month_calendar_statuses(self):
        self.make_booking()
        day_start = timezone.localtime(self.start).replace(hour=0)
        self.make_booking(
            start=day_start + timedelta(days=1),
            end=day_start + timedelta(days=2),
            guests=1,
        )
        data = build_month_calendar(Room.objects.filter(pk=self.room.pk), self.start.date())
        cells = {c["date"]: c["status"] for c in data["rows"][0]["cells"] if c["date"].month == self.start.month}
        self.assertEqual(cells[self.start.date()], DAY_PARTIAL)
        next_day = self.start.date() + timedelta(days=1)
        if next_day in cells:
            self.assertEqual(cells[next_day], DAY_BUSY)
        free_days = [s for s in cells.values() if s == DAY_FREE]
        self.assertTrue(free_days)

    def test_calendar_page(self):
        response = self.client.get(reverse("booking:calendar"), {"room_type": self.room_type.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A")


class AdminTests(BaseBookingTestCase):
    def test_admin_confirm_action(self):
        admin = User.objects.create_superuser("admin", "a@example.com", "pass12345!")
        self.client.force_login(admin)
        booking = self.make_booking()
        self.client.post(
            reverse("admin:booking_booking_changelist"),
            {"action": "confirm_bookings", "_selected_action": [booking.pk]},
        )
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.STATUS_CONFIRMED)
        self.assertEqual(len(mail.outbox), 1)
