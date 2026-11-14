from django.contrib import messages
from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from . import services
from .availability import build_month_calendar, parse_month, shift_month
from .forms import BookingForm, CalendarFilterForm, RegisterForm, RoomFilterForm
from .models import Booking, Room


def room_list(request):
    form = RoomFilterForm(request.GET or None)
    rooms = Room.objects.filter(is_active=True).select_related("room_type").prefetch_related("features")
    period = None
    if form.is_valid():
        room_type = form.cleaned_data.get("room_type")
        guests = form.cleaned_data.get("guests")
        start = form.cleaned_data.get("start")
        end = form.cleaned_data.get("end")
        if room_type:
            rooms = rooms.filter(room_type=room_type)
        if guests:
            rooms = rooms.filter(capacity__gte=guests)
        if start and end:
            busy = Booking.objects.active().filter(room=OuterRef("pk"), start__lt=end, end__gt=start)
            rooms = rooms.annotate(is_busy=Exists(busy)).filter(is_busy=False)
            period = (start, end)
    return render(request, "booking/room_list.html", {"form": form, "rooms": rooms, "period": period})


def room_detail(request, pk):
    room = get_object_or_404(
        Room.objects.select_related("room_type").prefetch_related("features"),
        pk=pk,
    )
    upcoming = Booking.objects.active().filter(room=room, end__gte=timezone.now()).order_by("start")
    return render(request, "booking/room_detail.html", {"room": room, "upcoming": upcoming})


def availability_calendar(request):
    form = CalendarFilterForm(request.GET or None)
    rooms = Room.objects.filter(is_active=True).select_related("room_type")
    month_value = None
    if form.is_valid():
        room_type = form.cleaned_data.get("room_type")
        if room_type:
            rooms = rooms.filter(room_type=room_type)
        month_value = form.cleaned_data.get("month")
    month_start = parse_month(month_value)
    data = build_month_calendar(rooms, month_start)
    query = request.GET.copy()
    query["month"] = shift_month(month_start, -1).strftime("%Y-%m")
    prev_query = query.urlencode()
    query["month"] = shift_month(month_start, 1).strftime("%Y-%m")
    next_query = query.urlencode()
    return render(
        request,
        "booking/calendar.html",
        {
            "form": form,
            "calendar": data,
            "month_start": month_start,
            "prev_query": prev_query,
            "next_query": next_query,
        },
    )


@login_required
def booking_create(request):
    initial = {
        "name": request.user.get_full_name() or request.user.username,
        "email": request.user.email,
    }
    room_id = request.GET.get("room")
    if room_id and room_id.isdigit():
        initial["room"] = room_id

    if request.method == "POST":
        form = BookingForm(request.POST)
        if form.is_valid():
            try:
                booking = services.create_booking(
                    room=form.cleaned_data["room"],
                    user=request.user,
                    name=form.cleaned_data["name"],
                    email=form.cleaned_data["email"],
                    start=form.cleaned_data["start"],
                    end=form.cleaned_data["end"],
                    guests=form.cleaned_data["guests"],
                    request=request,
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(
                    request,
                    "Бронювання створено. Ми надіслали лист для підтвердження на вашу пошту.",
                )
                return redirect("booking:booking_detail", token=booking.confirmation_token)
    else:
        form = BookingForm(initial=initial)
    return render(request, "booking/booking_form.html", {"form": form})


def _get_own_booking(request, token):
    booking = get_object_or_404(Booking.objects.select_related("room__room_type"), confirmation_token=token)
    if booking.user_id != request.user.id and not request.user.is_staff:
        raise Http404
    return booking


@login_required
def booking_detail(request, token):
    booking = _get_own_booking(request, token)
    can_pay = booking.user_id == request.user.id and booking.can_be_paid
    return render(request, "booking/booking_detail.html", {"booking": booking, "can_pay": can_pay})


def booking_confirm_email(request, token):
    booking = get_object_or_404(Booking, confirmation_token=token)
    if booking.status == Booking.STATUS_CANCELLED:
        messages.error(request, "Це бронювання скасовано, підтвердження неможливе.")
    elif booking.email_confirmed:
        messages.info(request, "Бронювання вже підтверджено через e-mail.")
    else:
        booking.email_confirmed = True
        booking.save(update_fields=["email_confirmed", "updated_at"])
        messages.success(request, "Дякуємо! Бронювання підтверджено через e-mail.")
    return redirect("booking:booking_detail", token=booking.confirmation_token)


@login_required
@require_POST
def booking_cancel(request, token):
    booking = _get_own_booking(request, token)
    if booking.status == Booking.STATUS_CANCELLED:
        messages.info(request, "Бронювання вже скасовано.")
    elif booking.end <= timezone.now():
        messages.error(request, "Не можна скасувати бронювання, яке вже завершилося.")
    else:
        services.change_status(booking, Booking.STATUS_CANCELLED, request=request)
        messages.success(request, "Бронювання скасовано.")
    return redirect("booking:booking_detail", token=booking.confirmation_token)


@login_required
@require_POST
def booking_pay(request, token):
    booking = _get_own_booking(request, token)
    if booking.user_id != request.user.id:
        raise Http404
    try:
        services.pay_booking(booking, request=request)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "Оплату прийнято. Бронювання з'явилося в активних.")
    return redirect("booking:booking_detail", token=booking.confirmation_token)


@login_required
def active_bookings(request):
    bookings = (
        Booking.objects.paid_active()
        .filter(user=request.user)
        .select_related("room__room_type")
        .order_by("start")
    )
    return render(request, "booking/active_bookings.html", {"bookings": bookings, "now": timezone.now()})


@login_required
def my_bookings(request):
    bookings = Booking.objects.filter(user=request.user).select_related("room__room_type")
    return render(request, "booking/my_bookings.html", {"bookings": bookings})


def _get_next_url(request):
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return ""


def register(request):
    next_url = _get_next_url(request)
    if request.user.is_authenticated:
        return redirect(next_url or settings.LOGIN_REDIRECT_URL)
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Реєстрація успішна.")
            return redirect(next_url or settings.LOGIN_REDIRECT_URL)
    else:
        form = RegisterForm()
    return render(request, "registration/register.html", {"form": form, "next": next_url})


def login_view(request):
    next_url = _get_next_url(request)
    if request.user.is_authenticated:
        return redirect(next_url or settings.LOGIN_REDIRECT_URL)
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Вітаємо, {user.get_full_name() or user.username}!")
            return redirect(next_url or settings.LOGIN_REDIRECT_URL)
    else:
        form = AuthenticationForm(request)
    return render(request, "registration/login.html", {"form": form, "next": next_url})


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        logout(request)
        messages.info(request, "Ви вийшли з акаунта.")
    return redirect(settings.LOGOUT_REDIRECT_URL)


def _parse_api_datetime(value):
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


@require_GET
def api_availability(request):
    room_id = request.GET.get("room")
    start = _parse_api_datetime(request.GET.get("start"))
    end = _parse_api_datetime(request.GET.get("end"))
    exclude = request.GET.get("exclude")

    if not room_id or not room_id.isdigit():
        return JsonResponse({"error": "Не вказано кімнату/місце."}, status=400)
    if start is None or end is None:
        return JsonResponse({"error": "Невірний формат дат."}, status=400)
    if end <= start:
        return JsonResponse({"error": "Дата завершення має бути пізніше за дату початку."}, status=400)

    room = get_object_or_404(Room, pk=int(room_id), is_active=True)
    exclude_id = int(exclude) if exclude and exclude.isdigit() else None
    result = services.check_availability(room, start, end, exclude_booking_id=exclude_id)
    result["room"] = room.pk
    result["capacity"] = room.capacity
    return JsonResponse(result)


@require_GET
def api_room_events(request, pk):
    room = get_object_or_404(Room, pk=pk)
    start = _parse_api_datetime(request.GET.get("start"))
    end = _parse_api_datetime(request.GET.get("end"))
    qs = Booking.objects.active().filter(room=room)
    if start:
        qs = qs.filter(end__gt=start)
    if end:
        qs = qs.filter(start__lt=end)
    events = [
        {
            "start": timezone.localtime(b.start).isoformat(),
            "end": timezone.localtime(b.end).isoformat(),
            "status": b.status,
        }
        for b in qs.order_by("start")
    ]
    return JsonResponse({"room": room.pk, "events": events})
