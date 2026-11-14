from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils import timezone

from . import services
from .models import Booking, Feature, Room, RoomType


@admin.register(RoomType)
class RoomTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "rooms_count"]
    search_fields = ["name"]

    @admin.display(description="Кількість кімнат/місць")
    def rooms_count(self, obj):
        return obj.rooms.count()


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]


class BookingInline(admin.TabularInline):
    model = Booking
    extra = 0
    fields = ["name", "email", "start", "end", "guests", "status", "email_confirmed", "total_price"]
    readonly_fields = ["total_price"]
    show_change_link = True


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ["name", "room_type", "capacity", "price_per_hour", "is_active"]
    list_filter = ["room_type", "is_active", "features"]
    list_editable = ["price_per_hour", "capacity", "is_active"]
    search_fields = ["name", "description"]
    filter_horizontal = ["features"]
    inlines = [BookingInline]


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "room",
        "name",
        "email",
        "start",
        "end",
        "guests",
        "status",
        "email_confirmed",
        "is_paid",
        "total_price",
        "created_at",
    ]
    list_filter = ["status", "email_confirmed", "is_paid", "room__room_type", "room"]
    search_fields = ["name", "email", "room__name"]
    date_hierarchy = "start"
    readonly_fields = ["confirmation_token", "total_price", "created_at", "updated_at"]
    list_select_related = ["room", "room__room_type"]
    actions = ["confirm_bookings", "cancel_bookings", "mark_paid"]
    fieldsets = [
        (None, {"fields": ["room", "user", "name", "email", "guests"]}),
        ("Період", {"fields": ["start", "end"]}),
        ("Статус", {"fields": ["status", "email_confirmed"]}),
        ("Оплата", {"fields": ["is_paid", "paid_at"]}),
        ("Службове", {"fields": ["total_price", "confirmation_token", "created_at", "updated_at"]}),
    ]

    def save_model(self, request, obj, form, change):
        status_changed = change and "status" in form.changed_data
        if obj.is_paid and obj.paid_at is None:
            obj.paid_at = timezone.now()
        elif not obj.is_paid:
            obj.paid_at = None
        super().save_model(request, obj, form, change)
        if status_changed:
            services.send_status_email(obj, request)

    def _apply_status(self, request, queryset, new_status, label):
        done = 0
        for booking in queryset.select_related("room"):
            if booking.status == new_status:
                continue
            try:
                services.change_status(booking, new_status, request=request)
                done += 1
            except ValidationError as exc:
                self.message_user(request, f"Бронювання #{booking.pk}: {' '.join(exc.messages)}", messages.ERROR)
        if done:
            self.message_user(request, f"{label}: {done}", messages.SUCCESS)

    @admin.action(description="Підтвердити обрані бронювання")
    def confirm_bookings(self, request, queryset):
        self._apply_status(request, queryset, Booking.STATUS_CONFIRMED, "Підтверджено")

    @admin.action(description="Скасувати обрані бронювання")
    def cancel_bookings(self, request, queryset):
        self._apply_status(request, queryset, Booking.STATUS_CANCELLED, "Скасовано")

    @admin.action(description="Позначити обрані як оплачені")
    def mark_paid(self, request, queryset):
        done = 0
        for booking in queryset.select_related("room"):
            if booking.is_paid:
                continue
            try:
                services.pay_booking(booking, request=request)
                done += 1
            except ValidationError as exc:
                self.message_user(request, f"Бронювання #{booking.pk}: {' '.join(exc.messages)}", messages.ERROR)
        if done:
            self.message_user(request, f"Оплачено: {done}", messages.SUCCESS)
