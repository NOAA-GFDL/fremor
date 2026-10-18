"""
tests for the calendar helpers in fremor.cmor_helpers
"""

import json

import pytest

from fremor.cmor_helpers import (
    calendars_are_equivalent,
    get_time_calendar_ds,
    get_time_calendar_value,
    normalize_calendar,
)

def test_normalize_calendar_noleap():
    """
    noleap is a CF alias for 365_day
    """
    assert normalize_calendar('noleap') == '365_day'

def test_normalize_calendar_365_day_passthrough():
    """
    365_day is already canonical
    """
    assert normalize_calendar('365_day') == '365_day'

def test_normalize_calendar_all_leap():
    """
    all_leap is a CF alias for 366_day
    """
    assert normalize_calendar('all_leap') == '366_day'

def test_normalize_calendar_366_day_passthrough():
    """
    366_day is already canonical
    """
    assert normalize_calendar('366_day') == '366_day'

def test_normalize_calendar_standard():
    """
    standard is a CF alias for gregorian
    """
    assert normalize_calendar('standard') == 'gregorian'

def test_normalize_calendar_gregorian_passthrough():
    """
    gregorian is already canonical
    """
    assert normalize_calendar('gregorian') == 'gregorian'

def test_normalize_calendar_unknown_passthrough():
    """
    unknown calendars are lowercased and passed through
    """
    assert normalize_calendar('proleptic_gregorian') == 'proleptic_gregorian'
    assert normalize_calendar('julian') == 'julian'
    assert normalize_calendar('CustomCalendar') == 'customcalendar'

def test_normalize_calendar_none():
    """
    None input returns None
    """
    assert normalize_calendar(None) is None


# ---- calendars_are_equivalent tests ----

def test_calendars_are_equivalent_noleap_and_365_day():
    """
    noleap and 365_day are CF aliases for the same calendar
    """
    assert calendars_are_equivalent('noleap', '365_day')

def test_calendars_are_equivalent_365_day_and_noleap():
    """
    365_day and noleap are CF aliases for the same calendar (reversed order)
    """
    assert calendars_are_equivalent('365_day', 'noleap')

def test_calendars_are_equivalent_all_leap_and_366_day():
    """
    all_leap and 366_day are CF aliases for the same calendar
    """
    assert calendars_are_equivalent('all_leap', '366_day')

def test_calendars_are_equivalent_standard_and_gregorian():
    """
    standard and gregorian are CF aliases for the same calendar
    """
    assert calendars_are_equivalent('standard', 'gregorian')

def test_calendars_are_equivalent_same_name():
    """
    identical calendar names should be equivalent
    """
    assert calendars_are_equivalent('360_day', '360_day')
    assert calendars_are_equivalent('julian', 'julian')
    assert calendars_are_equivalent('proleptic_gregorian', 'proleptic_gregorian')

def test_calendars_are_equivalent_case_insensitive():
    """
    comparison is case-insensitive
    """
    assert calendars_are_equivalent('NoLeap', '365_day')
    assert calendars_are_equivalent('STANDARD', 'gregorian')

def test_calendars_are_equivalent_different_calendars():
    """
    distinct calendars should NOT be equivalent
    """
    assert not calendars_are_equivalent('noleap', '360_day')
    assert not calendars_are_equivalent('gregorian', '360_day')
    assert not calendars_are_equivalent('julian', 'noleap')


class _FakeTime: # pylint: disable=too-few-public-methods
    """
    Minimal stand-in for a netCDF time variable.

    Only sets an attribute when a non-None value is supplied, so that
    accessing an absent attribute raises AttributeError — matching the
    behavior of a real netCDF4.Variable object.   
    """
    def __init__(self, calendar=None, calendar_type=None):
        if calendar is not None:
            self.calendar = calendar
        if calendar_type is not None:
            self.calendar_type = calendar_type
        self.units = 'days since 0001-01-01'


def test_get_time_calendar_prefers_calendar_attr():
    """
    calendar attribute takes priority over calendar_type
    """
    fake_time = _FakeTime(calendar='NoLeap', calendar_type='julian')
    assert get_time_calendar_value(fake_time) == '365_day'


def test_get_time_calendar_fallback_calendar_type():
    """
    calendar_type is used when calendar attribute is absent
    """
    fake_time = _FakeTime(calendar_type='Standard')
    assert get_time_calendar_value(fake_time) == 'gregorian'


def test_get_time_calendar_missing_returns_none():
    """
    None is returned when neither calendar attribute is present
    """
    fake_time = _FakeTime()
    assert get_time_calendar_value(fake_time) is None

def test_get_time_calendar_ds_success():
    """ get_time_calendar_ds returns the normalized calendar when a 'time' variable is present """
    fake_time = _FakeTime(calendar='NoLeap')
    mock_ds = {'time': fake_time}
    assert get_time_calendar_ds(mock_ds) == '365_day'

def test_get_time_calendar_ds_missing_time():
    """ get_time_calendar_ds raises a KeyError when the 'time' variable is missing from the dataset """
    mock_ds = {'lat': [0, 1, 2]} # Missing 'time' key
    with pytest.raises(KeyError):
        get_time_calendar_ds(mock_ds)
