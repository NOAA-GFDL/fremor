"""
tests for fremor.cmor_helpers.update_calendar_type
"""
import json

import pytest

from fremor.cmor_helpers import (
    calendars_are_equivalent,
    get_time_calendar_value,
    normalize_calendar,
    update_calendar_type,
)

@pytest.fixture
def temp_json_file(tmp_path):
    """
    Fixture to create a temporary JSON file for testing.

    Args:
        tmp_path: pytest's fixture for temporary directories.

    Returns:
        Path to the temporary JSON file.
    """
    # Sample data for testing
    test_json_content = {
        'calendar': 'original_calendar_type',
        'other_field': 'some_value'
    }

    json_file = tmp_path / 'test_file.json'
    with open(json_file, 'w', encoding='utf-8') as file:
        json.dump(test_json_content, file, indent=4)
    return json_file

def test_update_calendar_type_success(temp_json_file): # pylint: disable=redefined-outer-name
    """
    Test successful update of 'grid_label' and 'grid' fields.
    """
    # Arrange
    new_calendar_type = '365_day'

    # Act
    update_calendar_type(temp_json_file, new_calendar_type)

    # Assert
    with open(temp_json_file, 'r', encoding='utf-8') as file:
        data = json.load(file)
        assert data['calendar'] == new_calendar_type
        assert data['other_field'] == 'some_value'

def test_update_calendar_type_alias_normalized(temp_json_file): # pylint: disable=redefined-outer-name
    """
    Calendar aliases should be normalized when updating the experiment config.
    """
    update_calendar_type(temp_json_file, 'noleap')

    with open(temp_json_file, 'r', encoding='utf-8') as file:
        data = json.load(file)
        assert data['calendar'] == '365_day'

def test_update_calendar_type_valerr_raise(temp_json_file): # pylint: disable=redefined-outer-name
    """
    Test error raising when the input calendar is None
    """
    with pytest.raises(ValueError):
        update_calendar_type(temp_json_file, None)

def test_update_calendar_type_unknown_err():
    """
    Test raising an exception not caught by the other ones
    """
    bad_path = 12345
    with pytest.raises(Exception):
        update_calendar_type( bad_path, '365_day')

@pytest.fixture
def temp_keyerr_json_file(tmp_path):
    """
    Fixture to create a temporary JSON file for testing.

    Args:
        tmp_path: pytest's fixture for temporary directories.

    Returns:
        Path to the temporary JSON file.
    """
    # Sample data for testing
    test_json_content = {
        'clendar': 'original_calendar_type', #oops spelling error  # cspell:disable-line
        'other_field': 'some_value'
    }

    json_file = tmp_path / 'test_file.json'
    with open(json_file, 'w', encoding='utf-8') as file:
        json.dump(test_json_content, file, indent=4)
    return json_file

def test_update_calendar_type_keyerror_raise(temp_keyerr_json_file): # pylint: disable=redefined-outer-name
    """
    Test error raising when the calendar key doesn't exist
    """
    with pytest.raises(KeyError):
        update_calendar_type(temp_keyerr_json_file,'365_day')

@pytest.fixture
def temp_jsondecodeerr_json_file(tmp_path):
    """
    Create a file with invalid JSON content
    """
    invalid_json_file = tmp_path / 'invalid.json'
    invalid_content = '{ "calendar": "original_calendar_type", "other_field": "some_value" '  # missing closing }
    with open(invalid_json_file, 'w', encoding='utf-8') as f:
        f.write(invalid_content)
    return invalid_json_file

def test_update_calendar_type_jsondecode_raise(temp_jsondecodeerr_json_file): # pylint: disable=redefined-outer-name
    """
    Test raising a JSONDecodeError
    """
    with pytest.raises(json.JSONDecodeError):
        update_calendar_type(temp_jsondecodeerr_json_file, '365_day')

def test_update_calendar_type_json_dne_raise():
    """
    Test error raising when the input experiment json doesn't exist
    """
    with pytest.raises(FileNotFoundError):
        update_calendar_type('DOES_NOT_EXIST.json','365_day')


def test_normalize_calendar_noleap():
    """ noleap is a CF alias for 365_day """
    assert normalize_calendar('noleap') == '365_day'

def test_normalize_calendar_365_day_passthrough():
    """ 365_day is already canonical """
    assert normalize_calendar('365_day') == '365_day'

def test_normalize_calendar_all_leap():
    """ all_leap is a CF alias for 366_day """
    assert normalize_calendar('all_leap') == '366_day'

def test_normalize_calendar_366_day_passthrough():
    """ 366_day is already canonical """
    assert normalize_calendar('366_day') == '366_day'

def test_normalize_calendar_standard():
    """ standard is a CF alias for gregorian """
    assert normalize_calendar('standard') == 'gregorian'

def test_normalize_calendar_gregorian_passthrough():
    """ gregorian is already canonical """
    assert normalize_calendar('gregorian') == 'gregorian'

def test_normalize_calendar_unknown_passthrough():
    """ unknown calendars are lowercased and passed through """
    assert normalize_calendar('proleptic_gregorian') == 'proleptic_gregorian'
    assert normalize_calendar('julian') == 'julian'
    assert normalize_calendar('CustomCalendar') == 'customcalendar'

def test_normalize_calendar_none():
    """ None input returns None """
    assert normalize_calendar(None) is None


# ---- calendars_are_equivalent tests ----

def test_calendars_are_equivalent_noleap_and_365_day():
    """ noleap and 365_day are CF aliases for the same calendar """
    assert calendars_are_equivalent('noleap', '365_day')

def test_calendars_are_equivalent_365_day_and_noleap():
    """ 365_day and noleap are CF aliases for the same calendar (reversed order) """
    assert calendars_are_equivalent('365_day', 'noleap')

def test_calendars_are_equivalent_all_leap_and_366_day():
    """ all_leap and 366_day are CF aliases for the same calendar """
    assert calendars_are_equivalent('all_leap', '366_day')

def test_calendars_are_equivalent_standard_and_gregorian():
    """ standard and gregorian are CF aliases for the same calendar """
    assert calendars_are_equivalent('standard', 'gregorian')

def test_calendars_are_equivalent_same_name():
    """ identical calendar names should be equivalent """
    assert calendars_are_equivalent('360_day', '360_day')
    assert calendars_are_equivalent('julian', 'julian')
    assert calendars_are_equivalent('proleptic_gregorian', 'proleptic_gregorian')

def test_calendars_are_equivalent_case_insensitive():
    """ comparison is case-insensitive """
    assert calendars_are_equivalent('NoLeap', '365_day')
    assert calendars_are_equivalent('STANDARD', 'gregorian')

def test_calendars_are_equivalent_different_calendars():
    """ distinct calendars should NOT be equivalent """
    assert not calendars_are_equivalent('noleap', '360_day')
    assert not calendars_are_equivalent('gregorian', '360_day')
    assert not calendars_are_equivalent('julian', 'noleap')


# ---- get_time_calendar_value tests ----

class _FakeTime:
    """Minimal stand-in for a netCDF time variable.

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
    """ calendar attribute takes priority over calendar_type """
    fake_time = _FakeTime(calendar='NoLeap', calendar_type='julian')
    assert get_time_calendar_value(fake_time) == '365_day'


def test_get_time_calendar_fallback_calendar_type():
    """ calendar_type is used when calendar attribute is absent """
    fake_time = _FakeTime(calendar_type='Standard')
    assert get_time_calendar_value(fake_time) == 'gregorian'


def test_get_time_calendar_missing_returns_none():
    """ None is returned when neither calendar attribute is present """
    fake_time = _FakeTime()
    assert get_time_calendar_value(fake_time) is None
