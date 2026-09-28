"""
Tests for variable-list object values and input reductions
===========================================================

A varlist value may be ``{"name": <MIP variable>, "reduce": <method>}`` instead of a plain
name; ``reduce: zonal_mean`` averages the input over longitude before CMORization, e.g. to
write a zonal-mean table from the same lat-lon time series used for a lat-lon table.
"""

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from netCDF4 import Dataset

from fremor import cmor_mixer
from fremor.cmor_check import _build_table_report
from fremor.cmor_map import _remapped_value
from fremor.cmor_mixer import cmor_run_subtool, index_existing_outputs
from fremor.cmor_reduce import apply_reduce, parse_varlist_value, varlist_target
from fremor.cmor_stage import _table_local_variables


ROOTDIR = Path('fremor/tests/test_files')
CMIP6_AERMONZ = ROOTDIR / 'cmip6-cmor-tables' / 'Tables' / 'CMIP6_AERmonZ.json'
CMIP7_ATMOS = ROOTDIR / 'cmip7-cmor-tables' / 'tables' / 'CMIP7_atmos.json'
EXP_CONFIG = ROOTDIR / 'CMOR_input_example.json'
CMIP7_EXP_CONFIG = ROOTDIR / 'CMOR_CMIP7_input_example.json'
PLEV39 = [100000., 92500., 85000., 70000., 60000., 50000., 40000., 30000., 25000., 20000.,
          17000., 15000., 13000., 11500., 10000., 9000., 8000., 7000., 5000., 3000., 2000.,
          1500., 1000., 700., 500., 300., 200., 150., 100., 70., 50., 40., 30., 20., 15., 10.,
          7., 5., 3.]
ZONAL_TA = {'name': 'ta', 'reduce': 'zonal_mean'}


# ---------------------------------------------------------------------------
# varlist values
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('value, expected', [
    ('tas', ('tas', None)),
    ('', ('', None)),
    (None, ('', None)),
    ({'name': 'ta'}, ('ta', None)),
    (ZONAL_TA, ('ta', 'zonal_mean')),
    ({'name': '', 'reduce': 'zonal_mean'}, ('', 'zonal_mean')),
])
def test_parse_varlist_value(value, expected):
    ''' a plain name, or an object with a name and optional reduce method '''
    assert parse_varlist_value(value) == expected


@pytest.mark.parametrize('value, match', [
    ({'name': 'ta', 'reduce': 'meridional_mean'}, 'unknown reduce method'),
    ({'name': 'ta', 'method': 'zonal_mean'}, 'unknown key'),
    ({'name': 3}, '"name" must be a string'),
    (['ta'], 'must be a string or an object'),
])
def test_parse_varlist_value_invalid(value, match):
    ''' malformed values are refused with the reason; varlist_target treats them as unmapped '''
    with pytest.raises(ValueError, match=match):
        parse_varlist_value(value)
    assert varlist_target(value) == ''


def test_remapped_value_keeps_reduce():
    ''' fremor map re-pointing an object value keeps its reduce; clearing leaves '' '''
    assert _remapped_value(ZONAL_TA, 'ua') == {'name': 'ua', 'reduce': 'zonal_mean'}
    assert _remapped_value(ZONAL_TA, '') == ''
    assert _remapped_value('ta', 'ua') == 'ua'


# ---------------------------------------------------------------------------
# zonal_mean
# ---------------------------------------------------------------------------

def _write_ta(path, lon_bnds=((0, 90), (90, 180), (180, 270), (270, 360)), mask_point=True):
    ''' ta(time, plev39, lat, lon) whose value at each point is its longitude index, plus
    an all-missing latitude circle at the first level and time '''
    lon_bnds = np.asarray(lon_bnds, dtype=float)
    with Dataset(path, 'w') as ds:
        for name, size in (('time', None), ('plev39', 39), ('lat', 3), ('lon', len(lon_bnds)),
                           ('bnds', 2)):
            ds.createDimension(name, size)
        time = ds.createVariable('time', 'f8', ('time',))
        time.setncatts({'units': 'days since 1850-01-01', 'calendar': 'julian', 'axis': 'T',
                        'bounds': 'time_bnds'})
        time[:] = [15.5, 45.0]
        ds.createVariable('time_bnds', 'f8', ('time', 'bnds'))[:] = [[0, 31], [31, 59]]
        plev = ds.createVariable('plev39', 'f8', ('plev39',))
        plev.setncatts({'units': 'Pa', 'axis': 'Z', 'positive': 'down'})
        plev[:] = PLEV39
        lat = ds.createVariable('lat', 'f8', ('lat',))
        lat.setncatts({'units': 'degrees_north', 'axis': 'Y', 'bounds': 'lat_bnds'})
        lat[:] = [-60., 0., 60.]
        ds.createVariable('lat_bnds', 'f8', ('lat', 'bnds'))[:] = [[-90, -30], [-30, 30], [30, 90]]
        lon = ds.createVariable('lon', 'f8', ('lon',))
        lon.setncatts({'units': 'degrees_east', 'axis': 'X', 'bounds': 'lon_bnds'})
        lon[:] = lon_bnds.mean(axis=1)
        ds.createVariable('lon_bnds', 'f8', ('lon', 'bnds'))[:] = lon_bnds
        ta = ds.createVariable('ta', 'f4', ('time', 'plev39', 'lat', 'lon'), fill_value=1.0e20)
        ta.setncatts({'units': 'K', 'cell_methods': 'time: mean'})
        data = np.ma.masked_array(
            np.broadcast_to(200. + np.arange(len(lon_bnds)), (2, 39, 3, len(lon_bnds))).copy())
        if mask_point:
            data[0, 0, 0, :] = np.ma.masked      # a whole circle missing
            data[0, 0, 1, 0] = np.ma.masked      # one point missing
        ta[:] = data
    return str(path)


def test_zonal_mean_values_and_structure(tmp_path):
    ''' weighted by lon_bnds widths, missing points ignored, all-missing circles stay missing;
    lon and lon_bnds are dropped while everything else is kept '''
    nc_path = _write_ta(tmp_path / 'atmos.185001-185002.ta.nc',
                        lon_bnds=((0, 180), (180, 240), (240, 300), (300, 360)))
    apply_reduce(nc_path, 'ta', 'zonal_mean')

    with Dataset(nc_path) as ds:
        assert 'lon' not in ds.dimensions and 'lon' not in ds.variables
        assert 'lon_bnds' not in ds.variables
        assert {'time', 'time_bnds', 'plev39', 'lat', 'lat_bnds'} <= set(ds.variables)
        ta = ds.variables['ta']
        assert ta.dimensions == ('time', 'plev39', 'lat')
        assert ta.cell_methods == 'time: mean lon: mean'
        weighted = np.average(200. + np.arange(4), weights=[180, 60, 60, 60])
        assert ta[1, 5, 2] == pytest.approx(weighted)
        assert ta[0, 0, 1] == pytest.approx(np.average(201. + np.arange(3), weights=[60, 60, 60]))
        assert np.ma.is_masked(ta[0, 0, 0])
        assert ds.variables['plev39'][:].tolist() == PLEV39


def test_zonal_mean_equal_weights_without_bounds(tmp_path):
    ''' without lon bounds every longitude counts the same '''
    nc_path = _write_ta(tmp_path / 'in.nc', mask_point=False)
    with Dataset(nc_path, 'a') as ds:
        ds.variables['lon'].delncattr('bounds')
    apply_reduce(nc_path, 'ta', 'zonal_mean')
    with Dataset(nc_path) as ds:
        assert ds.variables['ta'][0, 0, 0] == pytest.approx(201.5)


def test_apply_reduce_none_unknown_and_no_longitude(tmp_path):
    ''' no method leaves the file alone; an unknown method or a missing 1-D longitude axis is
    an error '''
    nc_path = _write_ta(tmp_path / 'in.nc')
    before = Path(nc_path).read_bytes()
    apply_reduce(nc_path, 'ta', None)
    assert Path(nc_path).read_bytes() == before
    with pytest.raises(ValueError, match='unknown reduce method'):
        apply_reduce(nc_path, 'ta', 'global_mean')
    with pytest.raises(ValueError, match='needs a 1-D longitude axis'):
        apply_reduce(nc_path, 'time_bnds', 'zonal_mean')


# ---------------------------------------------------------------------------
# real CMORization
# ---------------------------------------------------------------------------

@pytest.fixture(name='zonal_run')
def fixture_zonal_run(tmp_path):
    ''' an indir with a lat-lon ta file and a varlist asking for its zonal mean '''
    indir = tmp_path / 'indir'
    indir.mkdir()
    input_file = _write_ta(indir / 'atmos.185001-185002.ta.nc')
    varlist = tmp_path / 'varlist.json'
    varlist.write_text(json.dumps({'ta': ZONAL_TA}), encoding='utf-8')
    return {'indir': str(indir), 'input_file': input_file, 'varlist': str(varlist),
            'outdir': str(tmp_path / 'outdir')}


@pytest.mark.parametrize('table_config, exp_config, grid_label, nom_res, prefix', [
    (CMIP6_AERMONZ, EXP_CONFIG, 'gr', '10000 km', 'ta_AERmonZ_'),
    (CMIP7_ATMOS, CMIP7_EXP_CONFIG, 'g010', '100 km', 'ta_tavg-p39-hy-air_'),
], ids=['cmip6', 'cmip7'])
def test_cmor_run_zonal_mean(zonal_run, tmp_path, table_config, exp_config, grid_label, nom_res, # pylint: disable=too-many-arguments, too-many-positional-arguments
                             prefix):
    ''' the lat-lon input is CMORized into a latitude-plev39 zonal-mean table variable; the pp
    input itself is left untouched; a skip_existing rerun finds the CMIP7 output under the
    zonal-mean brand '''
    local_exp = tmp_path / 'exp.json'
    shutil.copy(exp_config, local_exp)
    before = Path(zonal_run['input_file']).read_bytes()
    run_kwargs = {'indir': zonal_run['indir'], 'json_var_list': zonal_run['varlist'],
                  'json_table_config': str(table_config), 'json_exp_config': str(local_exp),
                  'outdir': zonal_run['outdir'], 'grid': 'FOO_BAR_PLACEHOLD',
                  'grid_label': grid_label, 'nom_res': nom_res, 'calendar_type': 'julian'}

    assert cmor_run_subtool(**run_kwargs) == 0
    outputs = index_existing_outputs(zonal_run['outdir'])
    assert len(outputs) == 1 and outputs[0].name.startswith(prefix)
    with Dataset(outputs[0]) as ds:
        assert ds.variables['ta'].dimensions == ('time', 'plev', 'lat')
        assert 'lon' not in ds.dimensions
        assert ds.variables['ta'][1, 5, 2] == pytest.approx(201.5)
    assert Path(zonal_run['input_file']).read_bytes() == before

    with patch('fremor.cmor_mixer.rewrite_netcdf_file_var',
               wraps=cmor_mixer.rewrite_netcdf_file_var) as mock_rewrite:
        assert cmor_run_subtool(**run_kwargs, skip_existing=True) == 0
    mock_rewrite.assert_not_called()


def test_cmor_run_invalid_varlist_value(zonal_run, tmp_path):
    ''' a malformed object value stops the run up front, naming the entry '''
    Path(zonal_run['varlist']).write_text(
        json.dumps({'ta': {'name': 'ta', 'reduce': 'zonal_max'}}), encoding='utf-8')
    local_exp = tmp_path / 'exp.json'
    shutil.copy(EXP_CONFIG, local_exp)
    with pytest.raises(ValueError, match='invalid entry for ta'):
        cmor_run_subtool(indir=zonal_run['indir'], json_var_list=zonal_run['varlist'],
                         json_table_config=str(CMIP6_AERMONZ), json_exp_config=str(local_exp),
                         outdir=zonal_run['outdir'])


# ---------------------------------------------------------------------------
# other varlist readers
# ---------------------------------------------------------------------------

def test_stage_reads_object_values(tmp_path):
    ''' fremor stage selects inputs for object-valued mappings too '''
    varlist = tmp_path / 'varlist.json'
    varlist.write_text(json.dumps({'ta': ZONAL_TA, 'ua': 'ua', 'foo': {'name': 'nope'}}),
                       encoding='utf-8')
    assert _table_local_variables(CMIP6_AERMONZ, varlist, 'CMIP6') == {'ta', 'ua'}


def test_check_report_reduce_and_invalid_entries():
    ''' fremor check counts object values as mappings, lists their reduce method, and reports
    malformed values instead of silently ignoring them '''
    varlists = {'AERmonZ': [('atmos', 'v.json', {
        'ta': ZONAL_TA, 'ua': 'ua', 'va': {'name': 'va', 'reduce': 'bogus'}})]}
    report = _build_table_report(str(CMIP6_AERMONZ), 'CMIP6', varlists, show_mapped=True)
    assert report['one_to_one_mapped']['ta'] == ('atmos', 'ta')
    assert report['reduce'] == {'ta': 'zonal_mean'}
    assert 'va' in report['unmapped']
    assert report['invalid_entries'][0]['local_key'] == 'va'
    assert 'unknown reduce method' in report['invalid_entries'][0]['error']

    plain = _build_table_report(str(CMIP6_AERMONZ), 'CMIP6',
                                {'AERmonZ': [('atmos', 'v.json', {'ta': 'ta'})]})
    assert 'reduce' not in plain and 'invalid_entries' not in plain
