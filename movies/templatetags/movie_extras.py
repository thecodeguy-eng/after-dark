from django import template

register = template.Library()

@register.filter
def calc_rating(view_count):
    """
    Converts view_count into a rating out of 5 with one decimal place.
    Example:
    - 0 views = 0
    - 1000 views = 5.0
    """
    try:
        rating = (view_count / 1000) * 5
        return round(rating, 1)
    except (TypeError, ZeroDivisionError):
        return 0
