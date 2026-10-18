"""
unit tests for cmor_helpers.exp_config_overrides
"""

import pytest

from fremor.cmor_helpers import exp_config_overrides


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
