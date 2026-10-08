"""
Tests for the optional frequency check in ``fremor config``
============================================================

``fremor config --check_freq`` passes ``check_freq=True`` down to ``make_simple_varlist``,
which only maps a variable to a MIP table when the frequency read from its input file is
consistent with at least one of the table's entries for it.
"""

import json
import logging
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from netCDF4 import Dataset

from fremor.cli import fremor
from fremor.cmor_config import cmor_config_subtool
from fremor.cmor_finder import (detect_input_frequency, frequency_mismatch, make_simple_varlist,
                                mip_entry_frequency)


ROOTDIR = Path('fremor/tests/test_files')
CMIP6_TABLES = ROOTDIR / 'cmip6-cmor-tables' / 'Tables'
EXP_CONFIG = ROOTDIR / 'CMOR_input_example.json'


def _write_nc(path, var='tas', times=None, # pylint: disable=too-many-arguments, too-many-positional-arguments
              units='days since 1850-01-01', cell_methods='time: mean',
              climatology=False, bounds=None):
    ''' write a small file holding one variable; times=None makes it time-independent '''
    path.parent.mkdir(parents=True, exist_ok=True)
    with Dataset(path, 'w') as ds:
        ds.createDimension('lat', 2)
        dims = ('lat',)
        if times is not None:
            ds.createDimension('time', None)
            ds.createDimension('bnds', 2)
            time = ds.createVariable('time', 'f8', ('time',))
            time.units = units
            time.axis = 'T'
            time[:] = np.asarray(times, dtype=float)
            if bounds is not None:
                name = 'climatology_bnds' if climatology else 'time_bnds'
                ds.createVariable(name, 'f8', ('time', 'bnds'))[:] = np.asarray(bounds, dtype=float)
                if climatology:
                    time.climatology = name
                else:
                    time.bounds = name
            elif climatology:
                time.climatology = 'climatology_bnds'
            dims = ('time', 'lat')
        data = ds.createVariable(var, 'f4', dims)
        if cell_methods:
            data.cell_methods = cell_methods
    return str(path)


# ---------------------------------------------------------------------------
# input side
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('kwargs, expected', [
    ({'times': [15.5, 45.0, 74.5]}, ('mon', 'mean')),
    ({'times': [0.5, 1.5, 2.5], 'cell_methods': 'time: maximum'}, ('day', 'mean')),
    ({'times': [0, 3, 6, 9], 'units': 'hours since 1850-01-01', 'cell_methods': 'time: point'},
     ('3hr', 'point')),
    ({'times': [0, 3600, 7200], 'units': 'seconds since 1850-01-01'}, ('1hr', 'mean')),
    ({'times': [0, 1800, 3600], 'units': 'seconds since 1850-01-01', 'cell_methods': 'time: point'},
     ('subhr', 'point')),
    ({'times': [182.5, 547.5]}, ('yr', 'mean')),
    ({'times': [15.5, 45.0, 74.5], 'climatology': True}, ('mon', 'clim')),
    ({'times': [182.5], 'bounds': [[0, 365]]}, ('yr', 'mean')),
    ({'times': [182.5]}, (None, 'mean')),
    ({'times': [15.5, 45.0], 'cell_methods': ''}, ('mon', None)),
    ({'times': None}, ('fx', 'fixed')),
], ids=['mon', 'day-max', '3hr-point', '1hr-seconds', 'subhr-point', 'yr', 'mon-clim',
        'yr-single-step-bounds', 'single-step-no-bounds', 'no-cell-methods', 'fixed'])
def test_detect_input_frequency(tmp_path, kwargs, expected):
    ''' base frequency from the time spacing, sampling from climatology / cell_methods '''
    nc_file = _write_nc(tmp_path / 'atmos.18500101-18541231.tas.nc', **kwargs)
    detected = detect_input_frequency(nc_file, 'tas')
    assert (detected['base'], detected['sampling']) == expected


def test_detect_input_frequency_real_monthly_file(cli_sos_nc_file):
    ''' the sos test file is monthly means '''
    assert detect_input_frequency(cli_sos_nc_file, 'sos') == {'base': 'mon', 'sampling': 'mean'}


def test_detect_input_frequency_unreadable(tmp_path):
    ''' a file that cannot be read gives nothing to compare, rather than an error '''
    bad = tmp_path / 'atmos.185001-185412.tas.nc'
    bad.write_bytes(b'not netcdf')
    assert detect_input_frequency(str(bad), 'tas') == {'base': None, 'sampling': None}


# ---------------------------------------------------------------------------
# table side and comparison
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('entry, expected', [
    ({'frequency': 'mon', 'dimensions': 'longitude latitude time'}, ('mon', 'mean')),
    ({'frequency': '3hrPt', 'dimensions': 'longitude latitude time1'}, ('3hr', 'point')),
    ({'frequency': 'monC', 'dimensions': 'longitude latitude time2'}, ('mon', 'clim')),
    ({'frequency': '1hrCM', 'dimensions': 'longitude latitude time3'}, ('1hr', 'clim')),
    ({'frequency': 'subhrPt', 'dimensions': 'site time1'}, ('subhr', 'point')),
    ({'frequency': 'fx', 'dimensions': 'longitude latitude'}, ('fx', 'fixed')),
    ({'dimensions': ['longitude', 'latitude', 'time1', 'height2m']}, (None, 'point')),
    ({'dimensions': ['longitude', 'latitude', 'time4', 'height2m']}, (None, None)),
    ({'dimensions': ['longitude', 'latitude']}, ('fx', 'fixed')),
], ids=['cmip6-mon', 'cmip6-3hrPt', 'cmip6-monC', 'cmip6-1hrCM', 'cmip6-subhrPt', 'cmip6-fx',
        'cmip7-tpt', 'cmip7-time4', 'cmip7-ti'])
def test_mip_entry_frequency(entry, expected):
    ''' base frequency from the CMIP6 frequency field, sampling from the time dimension '''
    table_freq = mip_entry_frequency(entry)
    assert (table_freq['base'], table_freq['sampling']) == expected


def test_frequency_mismatch_only_compares_what_is_known():
    ''' unknown values on either side never count against a variable '''
    monthly_mean = {'base': 'mon', 'sampling': 'mean'}
    assert frequency_mismatch(monthly_mean, {'base': 'mon', 'sampling': 'mean'}) is None
    assert frequency_mismatch(monthly_mean, {'base': 'day', 'sampling': 'mean'}) == \
        'input base mon vs table day'
    assert frequency_mismatch(monthly_mean, {'base': 'mon', 'sampling': 'point'}) == \
        'input sampling mean vs table point'
    assert frequency_mismatch(monthly_mean, {'base': None, 'sampling': 'mean'}) is None
    assert frequency_mismatch({'base': None, 'sampling': None}, {'base': 'day', 'sampling': 'point'}) is None


# ---------------------------------------------------------------------------
# make_simple_varlist
# ---------------------------------------------------------------------------

@pytest.fixture(name='daily_tas_dir')
def fixture_daily_tas_dir(tmp_path):
    ''' a pp chunk dir holding daily-mean tas (two chunks) and a table dir '''
    ts_dir = tmp_path / 'atmos' / 'ts' / 'daily' / '5yr'
    _write_nc(ts_dir / 'atmos.18550101-18591231.tas.nc', times=[1826.5, 1827.5, 1828.5])
    _write_nc(ts_dir / 'atmos.18500101-18541231.tas.nc', times=[0.5, 1.5, 2.5])
    return ts_dir


def _table(tmp_path, name, entries):
    path = tmp_path / 'tables' / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({'variable_entry': entries}), encoding='utf-8')
    return str(path)


def test_make_simple_varlist_check_freq_cmip6(tmp_path, daily_tas_dir):
    ''' daily tas maps to a daily table, but not to a monthly one when check_freq is on '''
    amon = _table(tmp_path, 'CMIP6_Amon.json',
                  {'tas': {'frequency': 'mon', 'dimensions': 'longitude latitude time height2m'}})
    day = _table(tmp_path, 'CMIP6_day.json',
                 {'tas': {'frequency': 'day', 'dimensions': 'longitude latitude time height2m'}})

    assert make_simple_varlist(str(daily_tas_dir), None, json_mip_table=amon) == {'tas': 'tas'}
    assert make_simple_varlist(str(daily_tas_dir), None, json_mip_table=amon, check_freq=True) == {'tas': ''}
    assert make_simple_varlist(str(daily_tas_dir), None, json_mip_table=amon, check_freq=True,
                               return_none_if_no_mip_vars=True) is None
    assert make_simple_varlist(str(daily_tas_dir), None, json_mip_table=day, check_freq=True) == {'tas': 'tas'}


def test_make_simple_varlist_check_freq_cmip7_brands(tmp_path):
    ''' CMIP7 has no table frequency; a variable maps if any of its brands has matching sampling '''
    ts_dir = tmp_path / 'atmos' / 'ts' / '3hr' / '5yr'
    _write_nc(ts_dir / 'atmos.1850010100-1854123121.tas.nc', times=[0, 3, 6],
              units='hours since 1850-01-01', cell_methods='time: point')
    means_only = _table(tmp_path, 'CMIP7_atmos.json', {
        'tas_tavg-h2m-hxy-u': {'dimensions': ['longitude', 'latitude', 'time', 'height2m']},
        'tas_tmax-h2m-hxy-u': {'dimensions': ['longitude', 'latitude', 'time', 'height2m']}})
    with_points = _table(tmp_path, 'CMIP7_atmos2.json', {
        'tas_tavg-h2m-hxy-u': {'dimensions': ['longitude', 'latitude', 'time', 'height2m']},
        'tas_tpt-h2m-hxy-u': {'dimensions': ['longitude', 'latitude', 'time1', 'height2m']}})

    assert make_simple_varlist(str(ts_dir), None, json_mip_table=means_only, check_freq=True) == {'tas': ''}
    assert make_simple_varlist(str(ts_dir), None, json_mip_table=with_points, check_freq=True) == \
        {'tas': 'tas'}


# ---------------------------------------------------------------------------
# fremor config, with real CMIP6 tables
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('check_freq', [False, True])
def test_config_check_freq_real_tables(tmp_path, cli_sos_nc_file, check_freq):
    ''' monthly sos appears in Omon, Oday and Odec; with check_freq it only maps to Omon '''
    ts_dir = tmp_path / 'pp' / 'ocean_monthly' / 'ts' / 'monthly' / '5yr'
    ts_dir.mkdir(parents=True)
    (ts_dir / Path(cli_sos_nc_file).name).symlink_to(Path(cli_sos_nc_file).resolve())
    tables = tmp_path / 'tables'
    tables.mkdir()
    for name in ('Omon', 'Oday', 'Odec'):
        (tables / f'CMIP6_{name}.json').symlink_to((CMIP6_TABLES / f'CMIP6_{name}.json').resolve())
    varlists = tmp_path / 'varlists'

    args = ['config', '-p', str(tmp_path / 'pp'), '-t', str(tables), '-m', 'cmip6',
            '-e', str(EXP_CONFIG), '-o', str(tmp_path / 'cmor.yaml'), '-d', str(tmp_path / 'out'),
            '-l', str(varlists)]
    if check_freq:
        args.append('--check_freq')
    # the CLI sets the package logger's level, which later caplog-based tests depend on
    package_logger = logging.getLogger('fremor')
    level = package_logger.level
    try:
        result = CliRunner().invoke(fremor, args=args)
    finally:
        package_logger.setLevel(level)
    assert result.exit_code == 0, result.output

    mapped = {name: json.loads((varlists / f'CMIP6_{name}_ocean_monthly.list').read_text())['sos']
              for name in ('Omon', 'Oday', 'Odec')}
    if check_freq:
        assert mapped == {'Omon': 'sos', 'Oday': '', 'Odec': ''}
    else:
        assert mapped == {'Omon': 'sos', 'Oday': 'sos', 'Odec': 'sos'}


def test_config_subtool_passes_check_freq(tmp_path, daily_tas_dir):
    ''' cmor_config_subtool forwards check_freq to make_simple_varlist '''
    del daily_tas_dir
    _table(tmp_path, 'CMIP6_Amon.json',
           {'tas': {'frequency': 'mon', 'dimensions': 'longitude latitude time height2m'}})
    for check_freq, expected in ((False, 'tas'), (True, '')):
        cmor_config_subtool(pp_dir=str(tmp_path), mip_tables_dir=str(tmp_path / 'tables'),
                            mip_era='cmip6', exp_config=str(EXP_CONFIG),
                            output_yaml=str(tmp_path / 'cmor.yaml'), output_dir=str(tmp_path / 'out'),
                            varlist_dir=str(tmp_path / 'varlists'), pp_comp_glob='atmos',
                            freq='daily', overwrite=True, check_freq=check_freq)
        varlist = json.loads((tmp_path / 'varlists' / 'CMIP6_Amon_atmos.list').read_text())
        assert varlist == {'tas': expected}
