"""Date helpers."""

from datetime import date


def age_in_years(born: date, today: date) -> int:
    """Whole years between a birth date and today (a 29 February birthday counts from 1 March)."""
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
