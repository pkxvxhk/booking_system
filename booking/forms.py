from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone

from .models import Booking, Room, RoomType

DATETIME_LOCAL_FORMAT = "%Y-%m-%dT%H:%M"


class DateTimeLocalInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format=DATETIME_LOCAL_FORMAT)


class BookingForm(forms.ModelForm):
    class Meta:
        model = Booking
        fields = ["name", "email", "room", "start", "end", "guests"]
        widgets = {
            "start": DateTimeLocalInput(),
            "end": DateTimeLocalInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["room"].queryset = Room.objects.filter(is_active=True).select_related("room_type")
        self.fields["start"].input_formats = [DATETIME_LOCAL_FORMAT, "%Y-%m-%d %H:%M"]
        self.fields["end"].input_formats = [DATETIME_LOCAL_FORMAT, "%Y-%m-%d %H:%M"]
        self.fields["guests"].min_value = 1
        self.fields["guests"].widget.attrs["min"] = 1

    def clean_start(self):
        start = self.cleaned_data["start"]
        if start < timezone.now():
            raise forms.ValidationError("Дата початку не може бути в минулому.")
        return start

    def clean_guests(self):
        guests = self.cleaned_data["guests"]
        if guests < 1:
            raise forms.ValidationError("Кількість гостей має бути не менше 1.")
        return guests


class RoomFilterForm(forms.Form):
    room_type = forms.ModelChoiceField(
        queryset=RoomType.objects.all(),
        required=False,
        empty_label="Усі типи",
        label="Тип",
    )
    guests = forms.IntegerField(required=False, min_value=1, label="Гостей не менше")
    start = forms.DateTimeField(
        required=False,
        label="Вільно з",
        widget=DateTimeLocalInput(),
        input_formats=[DATETIME_LOCAL_FORMAT],
    )
    end = forms.DateTimeField(
        required=False,
        label="Вільно до",
        widget=DateTimeLocalInput(),
        input_formats=[DATETIME_LOCAL_FORMAT],
    )

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start")
        end = cleaned.get("end")
        if bool(start) != bool(end):
            raise forms.ValidationError("Для перевірки доступності вкажіть обидві дати.")
        if start and end and end <= start:
            raise forms.ValidationError("Дата завершення має бути пізніше за дату початку.")
        return cleaned


class CalendarFilterForm(forms.Form):
    room_type = forms.ModelChoiceField(
        queryset=RoomType.objects.all(),
        required=False,
        empty_label="Усі типи",
        label="Тип",
    )
    month = forms.DateField(
        required=False,
        label="Місяць",
        input_formats=["%Y-%m"],
        widget=forms.DateInput(attrs={"type": "month"}, format="%Y-%m"),
    )


class RegisterForm(UserCreationForm):
    email = forms.EmailField(label="Електронна пошта", required=True)
    first_name = forms.CharField(label="Ім'я", max_length=150, required=False)

    class Meta:
        model = User
        fields = ["username", "first_name", "email"]

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data.get("first_name", "")
        if commit:
            user.save()
        return user
