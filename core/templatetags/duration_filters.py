from django import template

register = template.Library()


@register.filter
def format_duration(seconds):
    """Convert seconds to readable duration (e.g., 3720 -> '1h 2m')."""
    if seconds is None:
        return ""

    try:
        total_seconds = int(seconds)
    except (ValueError, TypeError):
        return str(seconds)

    total_minutes = total_seconds // 60

    if total_minutes < 60:
        return f"{total_minutes}m"

    hours = total_minutes // 60
    mins = total_minutes % 60

    if mins == 0:
        return f"{hours}h"

    return f"{hours}h {mins}m"
