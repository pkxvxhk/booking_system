from django.urls import path

from . import views

app_name = "booking"

urlpatterns = [
    path("", views.room_list, name="room_list"),
    path("rooms/<int:pk>/", views.room_detail, name="room_detail"),
    path("calendar/", views.availability_calendar, name="calendar"),
    path("book/", views.booking_create, name="booking_create"),
    path("booking/<uuid:token>/", views.booking_detail, name="booking_detail"),
    path("booking/<uuid:token>/confirm/", views.booking_confirm_email, name="booking_confirm_email"),
    path("booking/<uuid:token>/cancel/", views.booking_cancel, name="booking_cancel"),
    path("booking/<uuid:token>/pay/", views.booking_pay, name="booking_pay"),
    path("my/", views.my_bookings, name="my_bookings"),
    path("my/active/", views.active_bookings, name="active_bookings"),
    path("register/", views.register, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("api/availability/", views.api_availability, name="api_availability"),
    path("api/rooms/<int:pk>/events/", views.api_room_events, name="api_room_events"),
]
