"""Tests for CMIP7 sea-ice long-name overrides."""

import json

from fremor import cmor_mixer


def test_cmip7_seaice_long_name_override_uses_table_variable_brand_frequency_and_region(
        tmp_path, monkeypatch):
    """Apply the configured override for the matching table, variable, brand, and region."""
    overrides_path = tmp_path / 'CMIP7_long_name_overrides.json'
    overrides_path.write_text(json.dumps({
        'long_name_overrides': {
            'seaIce.siarea.tavg-u-hm-u.mon.nh': 'Sea-Ice Area North',
        },
    }), encoding='utf-8')
    calls = []
    monkeypatch.setattr(
        cmor_mixer.cmor,
        'set_variable_attribute',
        lambda *args: calls.append(args),
    )

    cmor_mixer._set_cmip7_seaice_long_name_override(
        1, 'seaIce', 'siarea', 'tavg-u-hm-u', 'mon', 'nh', str(tmp_path / 'CMIP7_seaIce.json')
    )

    assert calls == [(1, 'long_name', 'c', 'Sea-Ice Area North')]


def test_cmip7_seaice_long_name_override_skips_other_tables(tmp_path, monkeypatch):
    """Do not apply a sea-ice override while processing another table."""
    calls = []
    monkeypatch.setattr(
        cmor_mixer.cmor,
        'set_variable_attribute',
        lambda *args: calls.append(args),
    )

    cmor_mixer._set_cmip7_seaice_long_name_override(
        1, 'ocean', 'siarea', 'tavg-u-hm-u', 'mon', 'nh', str(tmp_path / 'CMIP7_ocean.json')
    )

    assert not calls


def test_cmip7_seaice_long_name_override_skips_empty_values(tmp_path, monkeypatch):
    """Ignore an override whose configured long-name value is empty."""
    overrides_path = tmp_path / 'CMIP7_long_name_overrides.json'
    overrides_path.write_text(json.dumps({
        'long_name_overrides': {
            'seaIce.siarea.tavg-u-hm-u.mon.nh': '',
        },
    }), encoding='utf-8')
    calls = []
    monkeypatch.setattr(
        cmor_mixer.cmor,
        'set_variable_attribute',
        lambda *args: calls.append(args),
    )

    cmor_mixer._set_cmip7_seaice_long_name_override(
        1, 'seaIce', 'siarea', 'tavg-u-hm-u', 'mon', 'nh', str(tmp_path / 'CMIP7_seaIce.json')
    )

    assert not calls
