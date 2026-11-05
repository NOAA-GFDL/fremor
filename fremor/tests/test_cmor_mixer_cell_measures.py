"""Tests for CMIP7 cell-measures lookup keys."""

from fremor.cmor_mixer import _cmip7_cell_measures_key


def test_cmip7_cell_measures_key_includes_table_variable_brand_frequency_and_region():
    ''' the lookup key matches the full CMIP7 cell-measures JSON key '''
    assert _cmip7_cell_measures_key(
        'aerosol', 'abs550aer', 'tavg-u-hxy-u', 'mon', 'glb'
    ) == 'aerosol.abs550aer.tavg-u-hxy-u.mon.glb'
