"""
unit tests for cmor_helpers.exp_config_overrides and cmor_helpers.warn_overridden_exp_config
"""

import logging

import pytest

from fremor.cmor_helpers import exp_config_overrides, warn_overridden_exp_config


def test_exp_config_overrides_none():
    ''' nothing given, nothing overridden '''
    assert not exp_config_overrides()


def test_exp_config_overrides_gridding():
    ''' grid_label, grid and nom_res override their exp config attributes together '''
    assert exp_config_overrides('gn', 'native grid', '100 km') == {
        'grid_label': 'gn', 'grid': 'native grid', 'nominal_resolution': '100 km'}


@pytest.mark.parametrize('grid_label, grid, nom_res', [
    (None, 'native grid', '100 km'),
    ('gn', None, '100 km'),
    ('gn', 'native grid', None),
])
def test_exp_config_overrides_partial_gridding_raises(grid_label, grid, nom_res):
    ''' grid_label, grid and nom_res must be given together '''
    with pytest.raises(ValueError, match='must be given together'):
        exp_config_overrides(grid_label, grid, nom_res)


def test_exp_config_overrides_calendar_normalized():
    ''' a CF calendar alias is normalized to its canonical name '''
    assert exp_config_overrides(calendar_type='noleap') == {'calendar': '365_day'}


def test_exp_config_overrides_all():
    ''' gridding and calendar together '''
    assert exp_config_overrides('gr1', 'regridded', '100 km', 'julian') == {
        'grid_label': 'gr1', 'grid': 'regridded', 'nominal_resolution': '100 km',
        'calendar': 'julian'}


EXP_CONFIG_DATA = {'grid_label': 'gn', 'grid': 'native', 'nominal_resolution': '250 km',
                   'calendar': 'noleap', 'frequency': 'monthly'}


def test_warn_overridden_exp_config_different_values(caplog):
    ''' each exp config attribute overridden with a different value is warned about '''
    overrides = {'grid_label': 'g010', 'grid': 'native', 'nominal_resolution': '100 km',
                 'frequency': 'mon'}
    with caplog.at_level(logging.WARNING):
        overridden = warn_overridden_exp_config(EXP_CONFIG_DATA, overrides, 'exp.json')
    assert overridden == ['grid_label', 'nominal_resolution', 'frequency']
    assert "grid_label = 'gn' in the exp config exp.json is overridden by 'g010' at runtime" in caplog.text
    assert 'grid =' not in caplog.text


def test_warn_overridden_exp_config_equivalent_calendar(caplog):
    ''' an equivalent calendar alias is not a different value '''
    with caplog.at_level(logging.WARNING):
        assert not warn_overridden_exp_config(EXP_CONFIG_DATA, {'calendar': '365_day'})
        assert warn_overridden_exp_config(EXP_CONFIG_DATA, {'calendar': '360_day'}) == ['calendar']
    assert caplog.text.count('overridden') == 1


def test_warn_overridden_exp_config_absent_attribute(caplog):
    ''' an attribute the exp config does not set is filled in, not overridden '''
    with caplog.at_level(logging.WARNING):
        assert not warn_overridden_exp_config({'grid_label': 'gn'}, {'frequency': 'mon'})
    assert not caplog.text
