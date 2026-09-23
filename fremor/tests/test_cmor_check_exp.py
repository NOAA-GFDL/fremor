"""
tests for fremor check's experiment-config checks (--check-exp-config) and the CMIP7
grid-label check run alongside --check-dims
"""

import json
import re
import shutil
from pathlib import Path

import numpy as np
import pytest
import yaml
from netCDF4 import Dataset

from fremor import cmor_check_exp
from fremor.cmor_check import cmor_check_subtool
from fremor.cmor_check_exp import ( _posix_bre_to_python, check_exp_config, find_emd_grid_cells_dir,
                                    grid_finding, grid_label_spec, load_cv, load_emd_grid_cell )

ROOTDIR = Path(__file__).parent / 'test_files'
CMIP6_TABLES = ROOTDIR / 'cmip6-cmor-tables' / 'Tables'
CMIP6_EXP_CONFIG = ROOTDIR / 'CMOR_input_example.json'
CMIP7_TABLES = ROOTDIR / 'cmip7-cmor-tables' / 'tables'
CMIP7_CV = ROOTDIR / 'cmip7-cmor-tables' / 'tables-cvs' / 'cmor-cvs.json'
CMIP7_EXP_CONFIG = ROOTDIR / 'CMOR_CMIP7_input_example.json'
EMD_GRID_CELLS = ROOTDIR / 'emd_horizontal_grid_cell'
CMIP6PLUS_OLD_CV = (ROOTDIR / 'mip-cmor-tables' / 'src' / 'exploration' / 'old' / 'mip_cmor_tables' /
                    'out' / 'CMIP6Plus_CV.json')


def _exp_config(tmp_path: Path, base: Path, **changes) -> str:
    ''' a copy of an example experiment config with some keys changed (None removes a key) '''
    data = json.loads(base.read_text(encoding='utf-8'))
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    path = tmp_path / 'exp.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    return str(path)


def _messages(report: dict, attribute: str) -> list:
    return [(f['level'], f['message']) for f in report['findings'] if f['attribute'] == attribute]


# ---------------------------------------------------------------------------
# POSIX BRE -> python regex
# ---------------------------------------------------------------------------
def test_posix_bre_to_python():
    ''' literal parens, escaped groups/intervals, and [[:digit:]] all translate '''
    assert _posix_bre_to_python(r'a (b)\. *c') == r'a \(b\)\. *c'
    assert re.fullmatch(_posix_bre_to_python(r'^r[[:digit:]]\{1,\}$'), 'r12')
    assert re.fullmatch(_posix_bre_to_python(r'^CF-1.7\( UGRID-1.0\)\{0,\}$'), 'CF-1.7 UGRID-1.0')


# ---------------------------------------------------------------------------
# check_exp_config: CMIP6
# ---------------------------------------------------------------------------
def test_check_exp_config_further_info_url(tmp_path):
    ''' without _further_info_url_tmpl CMOR cannot write the CV-required further_info_url '''
    report = check_exp_config(_exp_config(tmp_path, CMIP6_EXP_CONFIG), str(CMIP6_TABLES), 'CMIP6')
    assert report['status'] == 'error'
    assert _messages(report, 'further_info_url')[0][0] == 'error'

    fixed = _exp_config(tmp_path, CMIP6_EXP_CONFIG, _further_info_url_tmpl=(
        'https://furtherinfo.es-doc.org/<mip_era><institution_id><source_id><experiment_id>'
        '<sub_experiment_id><variant_label>'))
    assert not _messages(check_exp_config(fixed, str(CMIP6_TABLES), 'CMIP6'), 'further_info_url')


def test_check_exp_config_required_attributes(tmp_path):
    ''' absent and blank CV-required attributes are errors '''
    path = _exp_config(tmp_path, CMIP6_EXP_CONFIG, source_type=None, grid='')
    report = check_exp_config(path, str(CMIP6_TABLES), 'CMIP6')
    assert _messages(report, 'source_type') == [('error', 'required by the CV, but absent')]
    assert 'blank' in _messages(report, 'grid')[0][1]


def test_check_exp_config_cv_membership(tmp_path):
    ''' values outside their CV collection are errors, multi-term attributes checked per term '''
    path = _exp_config(tmp_path, CMIP6_EXP_CONFIG, experiment_id='not-an-experiment',
                       source_type='AOGCM NOTATYPE', grid_label='gX')
    report = check_exp_config(path, str(CMIP6_TABLES), 'CMIP6')
    assert "'not-an-experiment' not in" in _messages(report, 'experiment_id')[0][1]
    assert "'NOTATYPE'" in _messages(report, 'source_type')[0][1]
    assert "'AOGCM'" not in _messages(report, 'source_type')[0][1]
    assert _messages(report, 'grid_label')


def test_check_exp_config_experiment_consistency(tmp_path):
    ''' activity and parent must agree with the CV's entry for the experiment '''
    path = _exp_config(tmp_path, CMIP6_EXP_CONFIG, experiment_id='amip', activity_id='CMIP',
                       parent_experiment_id='piControl', sub_experiment_id='none')
    report = check_exp_config(path, str(CMIP6_TABLES), 'CMIP6')
    assert "'piControl' is not a parent of experiment amip" in _messages(report, 'parent_experiment_id')[0][1]

    path = _exp_config(tmp_path, CMIP6_EXP_CONFIG, experiment_id='amip', activity_id='ScenarioMIP')
    report = check_exp_config(path, str(CMIP6_TABLES), 'CMIP6')
    assert any('is not an activity of experiment amip' in msg for _lvl, msg in _messages(report, 'activity_id'))


def test_check_exp_config_source_institution(tmp_path):
    ''' institution_id must be one of the source's institutions '''
    path = _exp_config(tmp_path, CMIP6_EXP_CONFIG, source_id='GFDL-CM4', institution_id='NCAR')
    report = check_exp_config(path, str(CMIP6_TABLES), 'CMIP6')
    assert "'NCAR' is not an institution of source GFDL-CM4" in _messages(report, 'institution_id')[0][1]


def test_check_exp_config_calendar(tmp_path):
    ''' a non-CF calendar is an error; julian is only flagged for CMIP6Plus/CMIP7 '''
    report = check_exp_config(_exp_config(tmp_path, CMIP6_EXP_CONFIG, calendar='lunar'),
                              str(CMIP6_TABLES), 'CMIP6')
    assert _messages(report, 'calendar')[0][0] == 'error'

    report = check_exp_config(_exp_config(tmp_path, CMIP6_EXP_CONFIG, calendar='julian'),
                              str(CMIP6_TABLES), 'CMIP6')
    assert not _messages(report, 'calendar')


def test_check_exp_config_file_problems(tmp_path):
    ''' missing file, invalid JSON, mip_era mismatch, and a missing auxiliary table '''
    assert check_exp_config(None, str(CMIP6_TABLES), 'CMIP6')['status'] == 'error'
    assert 'does not exist' in check_exp_config(str(tmp_path / 'nope.json'), str(CMIP6_TABLES),
                                                'CMIP6')['findings'][0]['message']

    bad_json = tmp_path / 'bad.json'
    bad_json.write_text('{not json', encoding='utf-8')
    assert 'not valid JSON' in check_exp_config(str(bad_json), str(CMIP6_TABLES), 'CMIP6')['findings'][0]['message']

    report = check_exp_config(_exp_config(tmp_path, CMIP6_EXP_CONFIG, _AXIS_ENTRY_FILE='missing.json'),
                              str(CMIP6_TABLES), 'CMIP7')
    assert _messages(report, 'mip_era')
    assert 'missing.json not found' in _messages(report, '_AXIS_ENTRY_FILE')[0][1]


# ---------------------------------------------------------------------------
# check_exp_config: CMIP6Plus license (the esgf-qa finding) and CMIP7
# ---------------------------------------------------------------------------
def test_check_exp_config_cmip6plus_license(tmp_path):
    ''' the CMIP6Plus license must include the further_info_url sentence the CV pattern requires '''
    tables = tmp_path / 'tables'
    tables.mkdir()
    shutil.copy(CMIP6PLUS_OLD_CV, tables / 'CMIP6Plus_CV.json')
    base = ROOTDIR / 'CMOR_CMIP6PLUS_input_example.json'
    no_aux = {'_AXIS_ENTRY_FILE': None, '_FORMULA_VAR_FILE': None}

    report = check_exp_config(_exp_config(tmp_path, base, **no_aux), str(tables), 'CMIP6Plus')
    assert _messages(report, 'license')[0][0] == 'error'

    license_text = json.loads(base.read_text(encoding='utf-8'))['license'].replace(
        'proper acknowledgment. ',
        'proper acknowledgment. Further information about this data, including some limitations, '
        'can be found via the further_info_url (recorded as a global attribute in this file). ')
    report = check_exp_config(_exp_config(tmp_path, base, license=license_text, **no_aux),
                              str(tables), 'CMIP6Plus')
    assert not _messages(report, 'license')


def test_check_exp_config_cmip7(tmp_path):
    ''' the CMIP7 example config passes but for julian; license text and license_id checked '''
    report = check_exp_config(str(CMIP7_EXP_CONFIG), str(CMIP7_TABLES), 'CMIP7')
    assert report['status'] == 'warning'
    assert [f['attribute'] for f in report['findings']] == ['calendar']

    report = check_exp_config(_exp_config(tmp_path, CMIP7_EXP_CONFIG, license='CC-BY-4.0; something else',
                                          _controlled_vocabulary_file=str(CMIP7_CV)),
                              str(CMIP7_TABLES), 'CMIP7')
    assert _messages(report, 'license')[0][0] == 'warning'

    report = check_exp_config(_exp_config(tmp_path, CMIP7_EXP_CONFIG, license_id='MIT',
                                          _controlled_vocabulary_file=str(CMIP7_CV)),
                              str(CMIP7_TABLES), 'CMIP7')
    assert _messages(report, 'license_id')[0][0] == 'error'


# ---------------------------------------------------------------------------
# grid_label_spec / grid_finding
# ---------------------------------------------------------------------------
def _cmip7_cv() -> dict:
    return json.loads(CMIP7_CV.read_text(encoding='utf-8'))['CV']


@pytest.fixture(autouse=True)
def no_emd_download(monkeypatch):
    ''' no test may reach the network for an EMD grid definition '''
    def _offline(*args, **kwargs):
        raise OSError('network disabled in tests')
    monkeypatch.setattr(cmor_check_exp.urllib.request, 'urlopen', _offline)
    monkeypatch.setattr(cmor_check_exp, '_EMD_CACHE', {})


def _g225_spec():
    return grid_label_spec('g225', _cmip7_cv(), EMD_GRID_CELLS)


def test_grid_label_spec_from_emd():
    ''' EMD gives g225's spacing, first cell centres and cell count; g224 differs only in origin '''
    cv = _cmip7_cv()
    assert _g225_spec() == {
        'grid_type': 'regular-latitude-longitude', 'source': 'emd', 'checkable': True,
        'description': ('Horizontal grid cell with a regular latitude longitude grid type and '
                        '1.25 x 1.0 degree resolution.'),
        'dlon': 1.25, 'dlat': 1.0, 'first_lon': 0.625, 'first_lat': -89.5, 'n_cells': 51840,
        'region': ['global']}
    g224 = grid_label_spec('g224', cv, EMD_GRID_CELLS)
    assert (g224['first_lon'], g224['first_lat']) == (0.0, -90.0)

    gaussian = grid_label_spec('g208', cv, EMD_GRID_CELLS)
    assert gaussian['checkable'] and 'dlat' not in gaussian  # gaussian latitudes are uneven
    assert not grid_label_spec('g102', cv, EMD_GRID_CELLS)['checkable']  # tripolar


def test_grid_label_spec_cv_fallback():
    ''' without the EMD entry, only the spacing from the CV description is known '''
    cv = _cmip7_cv()
    assert grid_label_spec('g225', cv) == {
        'grid_type': 'regular-latitude-longitude', 'checkable': True, 'source': 'cv',
        'description': cv['grid_label']['g225'], 'dlon': 1.25, 'dlat': 1.0}
    assert not grid_label_spec('g102', cv)['checkable']
    assert grid_label_spec('g-nope', cv) is None
    assert grid_label_spec(None, cv) is None


def test_load_emd_grid_cell_download(monkeypatch):
    ''' with no local copy the EMD entry is downloaded, once per label '''
    calls = []

    class _Response:
        ''' stands in for the urlopen response '''
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):  # pylint: disable=missing-function-docstring
            return (EMD_GRID_CELLS / 'g225.json').read_bytes()

    def _urlopen(url, timeout):  # pylint: disable=unused-argument
        calls.append(url)
        return _Response()

    monkeypatch.setattr(cmor_check_exp.urllib.request, 'urlopen', _urlopen)
    assert load_emd_grid_cell('g225')['westernmost_longitude'] == 0.625
    assert load_emd_grid_cell('g225')['southernmost_latitude'] == -89.5
    assert calls == ['https://raw.githubusercontent.com/WCRP-CMIP/Essential-Model-Documentation/'
                     'src-data/horizontal_grid_cell/g225.json']
    assert load_emd_grid_cell('g225', download=False) is None


def test_find_emd_grid_cells_dir(tmp_path):
    ''' found in the tables directory or up to two levels above it '''
    tables = tmp_path / 'init' / 'repo' / 'tables'
    tables.mkdir(parents=True)
    assert find_emd_grid_cells_dir(str(tables)) is None
    (tmp_path / 'init' / 'emd_horizontal_grid_cell').mkdir()
    assert find_emd_grid_cells_dir(str(tables)) == (tmp_path / 'init' / 'emd_horizontal_grid_cell').resolve()


def _write_lat_lon_nc(nc_path, lon, lat, local_var='tas', lon_units='degrees_east', lat_units='degrees_north'):
    with Dataset(str(nc_path), 'w') as ds:
        ds.createDimension('time', 1)
        ds.createDimension('lat', len(lat))
        ds.createDimension('lon', len(lon))
        ds.createVariable('time', 'f8', ('time',))
        lat_var = ds.createVariable('lat', 'f8', ('lat',))
        lat_var.units = lat_units
        lat_var[:] = lat
        lon_var = ds.createVariable('lon', 'f8', ('lon',))
        lon_var.units = lon_units
        lon_var[:] = lon
        ds.createVariable(local_var, 'f4', ('time', 'lat', 'lon'))


G225_LON = np.arange(288) * 1.25 + 0.625
G225_LAT = np.arange(180) * 1.0 - 89.5


@pytest.mark.parametrize('lat', [G225_LAT, G225_LAT[::-1]], ids=['south-to-north', 'north-to-south'])
def test_grid_finding_g225_ok(tmp_path, lat):
    ''' a true g225 grid passes, whichever way latitude runs '''
    nc_path = tmp_path / 'atmos.197901-198312.tas.nc'
    _write_lat_lon_nc(nc_path, G225_LON, lat)
    finding = grid_finding(str(nc_path), 'tas', 'g225', _g225_spec())
    assert finding['status'] == 'ok', finding.get('problems')


@pytest.mark.parametrize('lon, lat, expected_problem', [
    (np.arange(288) * 1.25, G225_LAT, 'first longitude 0, expected 0.625'),
    (np.arange(288) * 1.25 - 179.375, G225_LAT, 'first longitude 180.625, expected 0.625'),
    (G225_LON, np.arange(181) * 1.0 - 90.0, 'southernmost latitude -90, expected -89.5'),
    (np.arange(360) * 1.0 + 0.5, G225_LAT, 'longitude spacing 1, expected 1.25'),
    (G225_LON[:144], G225_LAT, '144 x 180 = 25920 cells, expected 51840'),
], ids=['lon-edge-origin', 'lon-minus-180', 'lat-edge-origin', 'wrong-resolution', 'not-global'])
def test_grid_finding_g225_mismatch(tmp_path, lon, lat, expected_problem):
    ''' spacing, origin, and global extent are each checked '''
    nc_path = tmp_path / 'atmos.197901-198312.tas.nc'
    _write_lat_lon_nc(nc_path, lon, lat)
    finding = grid_finding(str(nc_path), 'tas', 'g225', _g225_spec())
    assert finding['status'] == 'mismatch'
    assert any(expected_problem in problem for problem in finding['problems']), finding['problems']


def test_grid_finding_not_checkable(tmp_path):
    ''' native grids without 1-D lat/lon, non-lat-lon labels, and unknown labels '''
    nc_path = tmp_path / 'ocean.197901-198312.tos.nc'
    _write_lat_lon_nc(nc_path, np.arange(10.0), np.arange(10.0), local_var='tos', lon_units='1', lat_units='1')
    cv = _cmip7_cv()
    assert grid_finding(str(nc_path), 'tos', 'g225', _g225_spec())['status'] == 'unknown'
    assert grid_finding(str(nc_path), 'tos', 'g102',
                        grid_label_spec('g102', cv, EMD_GRID_CELLS))['status'] == 'not_checked'
    assert grid_finding(str(nc_path), 'tos', 'g-nope', None)['status'] == 'unknown'


def test_grid_finding_cv_fallback_checks_spacing_only(tmp_path):
    ''' with only the CV's description, a wrong origin passes but a wrong spacing does not '''
    nc_path = tmp_path / 'atmos.197901-198312.tas.nc'
    _write_lat_lon_nc(nc_path, np.arange(288) * 1.25, G225_LAT)
    spec = grid_label_spec('g225', _cmip7_cv())
    assert grid_finding(str(nc_path), 'tas', 'g225', spec)['status'] == 'ok'

    _write_lat_lon_nc(nc_path, np.arange(360) * 1.0 + 0.5, G225_LAT)
    assert grid_finding(str(nc_path), 'tas', 'g225', spec)['status'] == 'mismatch'


def test_grid_finding_gaussian(tmp_path):
    ''' a regular gaussian grid is checked on longitude spacing, origin and cell count '''
    nc_path = tmp_path / 'atmos.197901-198312.tas.nc'
    lat = np.linspace(-89.14152, 89.14152, 160)  # spacing unchecked; starts at the EMD's southernmost latitude
    _write_lat_lon_nc(nc_path, np.arange(320) * 1.125, lat)
    spec = grid_label_spec('g208', _cmip7_cv(), EMD_GRID_CELLS)
    assert grid_finding(str(nc_path), 'tas', 'g208', spec)['status'] == 'ok'


# ---------------------------------------------------------------------------
# through fremor check
# ---------------------------------------------------------------------------
def _write_cmip7_case(tmp_path: Path, grid_label: str, lon, lat) -> str:
    tables = tmp_path / 'tables'
    tables.mkdir()
    shutil.copytree(EMD_GRID_CELLS, tmp_path / 'emd_horizontal_grid_cell')  # as fremor init saves it
    (tables / 'CMIP7_atmos.json').write_text(json.dumps({
        'Header': {'table_id': 'Table atmos'},
        'variable_entry': {'tas_tavg-h2m-hxy-u': {'dimensions': ['longitude', 'latitude', 'time', 'height2m']},
                           'co2mass_tavg-u-hm-u': {'dimensions': ['time']}},
    }), encoding='utf-8')
    varlist = tmp_path / 'varlist.json'
    varlist.write_text(json.dumps({'tas': 'tas', 'co2mass': 'co2mass'}), encoding='utf-8')
    exp_json = _exp_config(tmp_path, CMIP7_EXP_CONFIG, grid_label=grid_label,
                           _controlled_vocabulary_file=str(CMIP7_CV))

    input_dir = tmp_path / 'pp' / 'atmos' / 'ts' / 'monthly' / '5yr'
    input_dir.mkdir(parents=True)
    _write_lat_lon_nc(input_dir / 'atmos.197901-198312.tas.nc', lon, lat)
    with Dataset(str(input_dir / 'atmos.197901-198312.co2mass.nc'), 'w') as ds:
        ds.createDimension('time', 1)
        ds.createVariable('co2mass', 'f4', ('time',))

    yamlfile = tmp_path / 'cmor.yaml'
    yamlfile.write_text(yaml.safe_dump({'cmor': {
        'mip_era': 'CMIP7', 'exp_json': exp_json, 'start': None, 'stop': None,
        'directories': {'pp_dir': str(tmp_path / 'pp'), 'table_dir': str(tables), 'outdir': str(tmp_path / 'out')},
        'table_targets': [{'table_name': 'atmos', 'freq': 'monthly', 'gridding': None,
                           'target_components': [{'component_name': 'atmos', 'variable_list': str(varlist),
                                                  'data_series_type': 'ts', 'chunk': 'P5Y'}]}],
    }}), encoding='utf-8')
    return str(yamlfile)


def test_cmor_check_subtool_cmip7_grid_label(tmp_path, capsys):
    ''' --check-dims flags a g225 label on a grid starting at 0E; non-lat-lon variables are skipped '''
    yamlfile = _write_cmip7_case(tmp_path, 'g225', np.arange(288) * 1.25, G225_LAT)

    report = cmor_check_subtool(yamlfile=yamlfile, check_dims=True)
    files = report['atmos']['files']
    assert files['tas']['grid']['status'] == 'mismatch'
    assert 'grid' not in files['co2mass']
    assert 'grid=g225 mismatch: first longitude 0, expected 0.625' in capsys.readouterr().out


def test_cmor_check_subtool_cmip7_grid_label_ok(tmp_path):
    ''' a true g225 grid passes, and without --check-dims no grid check runs '''
    yamlfile = _write_cmip7_case(tmp_path, 'g225', G225_LON, G225_LAT)
    assert cmor_check_subtool(yamlfile=yamlfile, check_dims=True)['atmos']['files']['tas']['grid']['status'] == 'ok'
    assert 'files' not in cmor_check_subtool(yamlfile=yamlfile)['atmos']


def test_cmor_check_subtool_check_exp_config(tmp_path, capsys):
    ''' --check-exp-config reports under _exp_config and prints its own section '''
    yamlfile = _write_cmip7_case(tmp_path, 'g-nope', G225_LON, G225_LAT)

    report = cmor_check_subtool(yamlfile=yamlfile, check_exp_config=True)
    exp_report = report['_exp_config']
    assert exp_report['status'] == 'error'
    assert any(f['attribute'] == 'grid_label' for f in exp_report['findings'])
    output = capsys.readouterr().out
    assert '[EXPERIMENT CONFIG]' in output
    assert "ERROR grid_label: 'g-nope' not in the CV's grid_label collection" in output
    assert '_exp_config' not in cmor_check_subtool(yamlfile=yamlfile)


def test_load_cv_default_name(tmp_path):
    ''' without _controlled_vocabulary_file the era's default CV name is used '''
    cv, cv_path = load_cv(str(CMIP6_TABLES), {}, 'CMIP6')
    assert cv_path.name == 'CMIP6_CV.json' and 'experiment_id' in cv
    assert load_cv(str(tmp_path), {}, 'CMIP6')[0] is None
