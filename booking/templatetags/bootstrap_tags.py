from django import forms
from django import template

register = template.Library()


@register.filter
def bs_widget(field):
    widget = field.field.widget
    if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect, forms.CheckboxSelectMultiple)):
        css_class = "form-check-input"
    elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
        css_class = "form-select"
    else:
        css_class = "form-control"
    classes = [widget.attrs.get("class", ""), css_class]
    if field.errors:
        classes.append("is-invalid")
    return field.as_widget(attrs={"class": " ".join(c for c in classes if c)})


@register.filter
def alert_class(message_tags):
    mapping = {
        "debug": "secondary",
        "info": "info",
        "success": "success",
        "warning": "warning",
        "error": "danger",
    }
    for tag in str(message_tags).split():
        if tag in mapping:
            return mapping[tag]
    return "info"


@register.filter
def status_color(status):
    return {
        "pending": "warning",
        "confirmed": "success",
        "cancelled": "secondary",
    }.get(status, "secondary")
