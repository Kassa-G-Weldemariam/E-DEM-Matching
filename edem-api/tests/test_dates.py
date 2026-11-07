from datetime import date

from app.core.dates import age_in_years


def test_birthday_today_counts_as_the_new_age():
    assert age_in_years(date(2000, 5, 10), date(2020, 5, 10)) == 20


def test_the_day_before_the_birthday_is_still_the_old_age():
    assert age_in_years(date(2000, 5, 10), date(2020, 5, 9)) == 19


def test_the_day_after_the_birthday_is_the_new_age():
    assert age_in_years(date(2000, 5, 10), date(2020, 5, 11)) == 20


def test_a_leap_day_birth_is_not_a_year_older_on_28_february():
    assert age_in_years(date(2000, 2, 29), date(2021, 2, 28)) == 20


def test_a_leap_day_birth_is_a_year_older_on_1_march():
    assert age_in_years(date(2000, 2, 29), date(2021, 3, 1)) == 21
