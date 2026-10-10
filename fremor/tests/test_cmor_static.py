'''
tests for mapping and CMORizing time-invariant (fx) variables from FRE static files,
``<pp_dir>/<component>/<component>.static.nc``: ``fremor config --freq static``, ``fremor map``,
``fremor check``, ``fremor stage``, ``fremor yaml`` and ``fremor run``.
'''

import glob
import json
from pathlib import Path

import pytest
import yaml
from netCDF4 import Dataset

from fremor import cmor_run_subtool
from fremor.cmor_check import cmor_check_subtool
from fremor.cmor_config import cmor_config_subtool
from fremor.cmor_finder import make_static_varlist
from fremor.cmor_helpers import ( component_input_path, conv_mip_to_bronx_freq, filter_brands,
                                  get_json_file_data, is_static_component, is_static_file,
                                  resolve_named_ps_source, static_file_path, static_file_variables )
from fremor.cmor_map import MapApp, MapSession
from fremor.cmor_mixer import STATIC_ISO_DATETIME, find_existing_output
from fremor.cmor_stage import collect_stage_files
from fremor.cmor_yamler import cmor_yaml_subtool
from fremor.tests.conftest import ncgen

ROOTDIR = Path('fremor/tests/test_files')
CMIP6_TABLES = ROOTDIR / 'cmip6-cmor-tables' / 'Tables'
CMIP7_TABLES = ROOTDIR / 'cmip7-cmor-tables' / 'tables'
MOCK_OCEAN_STATIC_CDL = ( ROOTDIR / 'ascii_files' / 'mock_archive' / 'USER' / 'CMIP7' / 'ESM4' / 'DEV' /
                          'ESM4.5v01_om5b04_piC' / 'gfdl.ncrc5-intel23-prod-openmp' / 'pp' /
                          'ocean_monthly' / 'ocean_monthly.static.cdl' )


# ── fixtures / helpers ─────────────────────────────────────────────────────────

def _write_static_nc(path, fields=('deptho', 'areacello', 'geolat')):
    ''' a small FRE-like static file: 2-D time-invariant fields on (yh, xh), plus the kinds of
    variables that are not mapping candidates -- coordinates, bounds, a time-varying field, a scalar '''
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Dataset(path, 'w') as ds:
        ds.createDimension('yh', 3)
        ds.createDimension('xh', 4)
        ds.createDimension('nv', 2)
        ds.createDimension('time', None)
        yh = ds.createVariable('yh', 'f8', ('yh',))
        yh.units = 'degrees_north'
        yh[:] = [-10., 0., 10.]
        xh = ds.createVariable('xh', 'f8', ('xh',))
        xh.units = 'degrees_east'
        xh.bounds = 'xh_bnds'
        xh[:] = [0., 90., 180., 270.]
        xh_bnds = ds.createVariable('xh_bnds', 'f8', ('xh', 'nv'))
        xh_bnds[:] = [[-45., 45.], [45., 135.], [135., 225.], [225., 315.]]
        time = ds.createVariable('time', 'f8', ('time',))
        time.units = 'days since 0001-01-01 00:00:00'
        time[:] = [15.]
        avg = ds.createVariable('tos', 'f4', ('time', 'yh', 'xh'))
        avg[:] = 1.
        ds.createVariable('scalar', 'f4', ())
        for field in fields:
            var = ds.createVariable(field, 'f4', ('yh', 'xh'))
            var.units = 'm'
            var.cell_methods = 'time: point'
            var[:] = 100.
    return str(path)


def _write_table(tables_dir, table_name, variable_entry, era='CMIP6'):
    path = Path(tables_dir) / f'{era}_{table_name}.json'
    path.write_text(json.dumps({'Header': {'table_id': f'Table {table_name}'},
                                'variable_entry': variable_entry}), encoding='utf-8')
    return str(path)


def _static_component(component_name, variable_list):
    return {'component_name': component_name, 'variable_list': str(variable_list),
            'data_series_type': 'static'}


def _static_table_target(table_name, components):
    return {'table_name': table_name, 'freq': 'static',
            'gridding': {'grid_label': 'gn', 'grid_desc': 'd', 'nom_res': '100 km'},
            'target_components': components}


def _write_yaml(root_dir, pp_dir, tables_dir, table_targets, mip_era='cmip6', exp_json=None):
    doc = {'cmor': {
        'start': None, 'stop': None, 'calendar_type': 'noleap', 'mip_era': mip_era,
        'exp_json': str(exp_json or Path(root_dir) / 'exp.json'),
        'directories': {'pp_dir': str(pp_dir), 'table_dir': str(tables_dir),
                        'outdir': str(Path(root_dir) / 'out')},
        'table_targets': table_targets,
    }}
    yamlfile = Path(root_dir) / 'cmor.yaml'
    yamlfile.write_text(yaml.safe_dump(doc), encoding='utf-8')
    return str(yamlfile)


@pytest.fixture
def static_tree(tmp_path):
    ''' pp_dir with ocean_monthly's static file (plus an unrelated ts dir), and a tables dir
    with the real CMIP6 Ofx and Omon tables '''
    pp_dir = tmp_path / 'pp'
    static_file = _write_static_nc(pp_dir / 'ocean_monthly' / 'ocean_monthly.static.nc')
    (pp_dir / 'ocean_monthly' / 'ts' / 'monthly' / '5yr').mkdir(parents=True)
    tables_dir = tmp_path / 'tables'
    tables_dir.mkdir()
    for name in ('Ofx', 'Omon'):
        (tables_dir / f'CMIP6_{name}.json').symlink_to((CMIP6_TABLES / f'CMIP6_{name}.json').resolve())
    return pp_dir, tables_dir, static_file


# ── helpers ─────────────────────────────────────────────────────────────────

def test_static_file_variables(tmp_path):
    ''' only time-invariant, non-coordinate, non-bounds, non-scalar data variables '''
    static_file = _write_static_nc(tmp_path / 'ocean.static.nc')
    assert static_file_variables(static_file) == ['deptho', 'areacello', 'geolat']


def test_component_input_path():
    ''' a static component reads its static file, a ts component its ts directory '''
    static = {'component_name': 'ocean_monthly', 'data_series_type': 'static'}
    ts = {'component_name': 'ocean_monthly', 'data_series_type': 'ts', 'chunk': 'P5Y'}
    assert is_static_component(static)
    assert not is_static_component(ts)
    assert component_input_path('/pp', None, static) == '/pp/ocean_monthly/ocean_monthly.static.nc'
    assert component_input_path('/pp', 'monthly', ts) == '/pp/ocean_monthly/ts/monthly/5yr'
    assert static_file_path('/pp', 'land') == '/pp/land/land.static.nc'
    assert is_static_file('/pp/land/land.static.nc')
    assert not is_static_file('/pp/land/ts/monthly/5yr/land.185001-185412.lai.nc')


def test_fx_table_freq_is_static():
    ''' the fx MIP frequency now has a FRE equivalent '''
    assert conv_mip_to_bronx_freq('fx') == 'static'


def test_named_ps_source_ignored_for_static():
    ''' static fields have no surface-pressure companion '''
    table_target = _static_table_target('Ofx', [_static_component('ocean', 'x.list')])
    table_target['ps_component'] = 'atmos'
    assert resolve_named_ps_source(table_target, [table_target], '/pp', 'static') is None


@pytest.mark.parametrize('cell_methods', [None, 'time: point'])
def test_filter_brands_time_invariant_picks_ti(cell_methods):
    ''' a field without a time dimension maps only to the time-invariant brand, even when it
    still carries a temporal cell_methods from the history file it came from '''
    mip_var_cfgs = get_json_file_data(str(CMIP7_TABLES / 'CMIP7_ocean.json'))
    brand = filter_brands(['tavg-ol-hxy-sea', 'ti-ol-hxy-sea'], 'thkcello', mip_var_cfgs,
                          has_time_bnds=False, input_vert_dim='z_l', cell_methods=cell_methods,
                          has_time_dim=False)
    assert brand == 'ti-ol-hxy-sea'


# ── varlist extraction ─────────────────────────────────────────────────────

def test_make_static_varlist_cmip6_ofx(tmp_path):
    ''' static variables self-map onto the fx table's entries, others get an empty value '''
    static_file = _write_static_nc(tmp_path / 'ocean.static.nc')
    out = tmp_path / 'out.list'
    var_list = make_static_varlist(static_file, str(out),
                                   json_mip_table=str(CMIP6_TABLES / 'CMIP6_Ofx.json'))
    assert var_list == {'deptho': 'deptho', 'areacello': 'areacello', 'geolat': ''}
    assert json.loads(out.read_text(encoding='utf-8')) == var_list


def test_make_static_varlist_strict(tmp_path):
    ''' strict mode leaves unmatched variables out '''
    static_file = _write_static_nc(tmp_path / 'ocean.static.nc')
    var_list = make_static_varlist(static_file, None, return_none_if_no_mip_vars=True,
                                   json_mip_table=str(CMIP6_TABLES / 'CMIP6_Ofx.json'))
    assert var_list == {'deptho': 'deptho', 'areacello': 'areacello'}


def test_make_static_varlist_table_without_fixed_entries(tmp_path):
    ''' a table with no fixed entries (e.g. Omon) yields no varlist at all '''
    static_file = _write_static_nc(tmp_path / 'ocean.static.nc')
    out = tmp_path / 'out.list'
    assert make_static_varlist(static_file, str(out),
                               json_mip_table=str(CMIP6_TABLES / 'CMIP6_Omon.json')) is None
    assert not out.exists()


def test_make_static_varlist_cmip7_matches_ti_entries_only(tmp_path):
    ''' in a CMIP7 realm table only the time-invariant brands are candidates '''
    tables_dir = tmp_path / 'tables'
    tables_dir.mkdir()
    table = _write_table(tables_dir, 'ocean', {
        'deptho_ti-u-hxy-sea': {'dimensions': ['longitude', 'latitude']},
        'tos_tavg-u-hxy-sea': {'dimensions': ['longitude', 'latitude', 'time']},
    }, era='CMIP7')
    static_file = _write_static_nc(tmp_path / 'ocean.static.nc', fields=('deptho', 'tos_static'))
    var_list = make_static_varlist(static_file, None, json_mip_table=table)
    assert var_list == {'deptho': 'deptho', 'tos_static': ''}


# ── fremor config --freq static ───────────────────────────────────────────────

def test_config_freq_static(tmp_path, static_tree, caplog): # pylint: disable=redefined-outer-name
    ''' --freq static scans static files, writes static components into fx tables only '''
    pp_dir, tables_dir, _ = static_tree
    # a component with only per-tile static files is not supported
    tile_dir = pp_dir / 'atmos'
    tile_dir.mkdir()
    _write_static_nc(tile_dir / 'atmos.static.tile1.nc')
    exp_config = tmp_path / 'exp.json'
    exp_config.write_text(json.dumps({'grid': 'g', 'nominal_resolution': '25 km'}), encoding='utf-8')
    varlist_dir = tmp_path / 'varlists'
    output_yaml = tmp_path / 'static.yaml'

    with caplog.at_level('WARNING'):
        cmor_config_subtool(pp_dir=str(pp_dir), mip_tables_dir=str(tables_dir), mip_era='cmip6',
                            exp_config=str(exp_config), output_yaml=str(output_yaml),
                            output_dir=str(tmp_path / 'out'), varlist_dir=str(varlist_dir),
                            freq='static')
    assert 'only per-tile static files' in caplog.text

    doc = yaml.safe_load(output_yaml.read_text(encoding='utf-8'))
    table_targets = doc['cmor']['table_targets']
    assert [target['table_name'] for target in table_targets] == ['Ofx']
    assert table_targets[0]['freq'] == 'static'
    varlist = str(varlist_dir / 'CMIP6_Ofx_ocean_monthly_static.list')
    assert table_targets[0]['target_components'] == [
        {'component_name': 'ocean_monthly', 'variable_list': varlist, 'data_series_type': 'static'}]
    assert json.loads(Path(varlist).read_text(encoding='utf-8'))['deptho'] == 'deptho'


# ── fremor yaml / stage ───────────────────────────────────────────────────────

def _ofx_yaml(tmp_path, pp_dir, tables_dir, exp_json=None, var_list=None):
    varlist = tmp_path / 'CMIP6_Ofx_ocean_monthly_static.list'
    varlist.write_text(json.dumps(var_list or {'deptho': 'deptho', 'geolat': ''}), encoding='utf-8')
    return _write_yaml(tmp_path, pp_dir, tables_dir,
                       [_static_table_target('Ofx', [_static_component('ocean_monthly', varlist)])],
                       exp_json=exp_json)


def test_yaml_passes_static_file_to_run(tmp_path, static_tree, cmip6_exp_config, monkeypatch): # pylint: disable=redefined-outer-name
    ''' fremor yaml hands the static file itself to cmor_run_subtool, with no ps companions '''
    pp_dir, tables_dir, static_file = static_tree
    yamlfile = _ofx_yaml(tmp_path, pp_dir, tables_dir, exp_json=cmip6_exp_config)
    calls = []
    monkeypatch.setattr('fremor.cmor_yamler.cmor_run_subtool', lambda **kwargs: calls.append(kwargs))
    cmor_yaml_subtool(yamlfile=yamlfile)
    assert len(calls) == 1
    assert calls[0]['indir'] == static_file
    assert calls[0]['ps_source'] is None and calls[0]['ps_fallback'] is None


def test_yaml_static_table_with_ts_component_raises(tmp_path, static_tree, cmip6_exp_config): # pylint: disable=redefined-outer-name
    ''' a static table target holds only static components '''
    pp_dir, tables_dir, _ = static_tree
    varlist = tmp_path / 'v.list'
    varlist.write_text('{}', encoding='utf-8')
    component = {'component_name': 'ocean_monthly', 'variable_list': str(varlist),
                 'data_series_type': 'ts', 'chunk': 'P5Y'}
    yamlfile = _write_yaml(tmp_path, pp_dir, tables_dir, [_static_table_target('Ofx', [component])],
                           exp_json=cmip6_exp_config)
    with pytest.raises(ValueError, match="are not data_series_type 'static'"):
        cmor_yaml_subtool(yamlfile=yamlfile, dry_run_mode=True)


def test_stage_collects_static_file(tmp_path, static_tree): # pylint: disable=redefined-outer-name
    ''' fremor stage selects the static file, regardless of the run's year bounds '''
    pp_dir, tables_dir, static_file = static_tree
    yamlfile = _ofx_yaml(tmp_path, pp_dir, tables_dir)
    assert collect_stage_files(yamlfile, start='1850', stop='1854') == [str(Path(static_file).resolve())]


def test_stage_missing_static_file_raises(tmp_path, static_tree): # pylint: disable=redefined-outer-name
    ''' a mapped static component without a static file is an error, like a missing ts dir '''
    pp_dir, tables_dir, static_file = static_tree
    Path(static_file).unlink()
    yamlfile = _ofx_yaml(tmp_path, pp_dir, tables_dir)
    with pytest.raises(FileNotFoundError, match='static file does not exist'):
        collect_stage_files(yamlfile)


# ── fremor check ────────────────────────────────────────────────────────────

def test_check_static_table(tmp_path, static_tree): # pylint: disable=redefined-outer-name
    ''' coverage against the fx table, and the input checks read the mapped variable out of
    the static file '''
    pp_dir, tables_dir, static_file = static_tree
    yamlfile = _ofx_yaml(tmp_path, pp_dir, tables_dir)
    report = cmor_check_subtool(yamlfile=yamlfile, show_mapped=True, check_staging=True,
                                check_dims=True, check_attrs=True)
    ofx = report['Ofx']
    assert 'deptho' in ofx['one_to_one_mapped']
    assert 'deptho' not in ofx['unmapped'] and 'areacello' in ofx['unmapped']
    deptho = ofx['files']['deptho']
    assert deptho['coverage']['status'] == 'static'
    assert deptho['dims']['file'] == static_file
    assert deptho['attrs']['file'] == static_file
    assert deptho['attrs']['units']['input'] == 'm'


def test_check_static_cmip7_counts_fixed_entries_only(tmp_path): # pylint: disable=redefined-outer-name
    ''' a static CMIP7 realm table target is only measured against its ti entries '''
    pp_dir = tmp_path / 'pp'
    _write_static_nc(pp_dir / 'ocean_monthly' / 'ocean_monthly.static.nc')
    tables_dir = tmp_path / 'tables'
    tables_dir.mkdir()
    _write_table(tables_dir, 'ocean', {
        'deptho_ti-u-hxy-sea': {'dimensions': ['longitude', 'latitude']},
        'areacello_ti-u-hxy-u': {'dimensions': ['longitude', 'latitude']},
        'tos_tavg-u-hxy-sea': {'dimensions': ['longitude', 'latitude', 'time']},
    }, era='CMIP7')
    varlist = tmp_path / 'CMIP7_ocean_ocean_monthly_static.list'
    varlist.write_text(json.dumps({'deptho': 'deptho'}), encoding='utf-8')
    yamlfile = _write_yaml(tmp_path, pp_dir, tables_dir,
                           [_static_table_target('ocean', [_static_component('ocean_monthly', varlist)])],
                           mip_era='cmip7')
    report = cmor_check_subtool(yamlfile=yamlfile)
    assert report['ocean']['reference_var_count'] == 2
    assert report['ocean']['unmapped'] == ['areacello']


# ── fremor map ────────────────────────────────────────────────────────────────

def test_mapsession_set_mapping_static_creates_component(tmp_path, static_tree): # pylint: disable=redefined-outer-name
    ''' mapping from a static file stages a static component: no chunk, a _static varlist '''
    pp_dir, tables_dir, _ = static_tree
    varlist_dir = tmp_path / 'varlists'
    varlist_dir.mkdir()
    other = varlist_dir / 'CMIP6_Ofx_land_static.list'
    other.write_text('{}', encoding='utf-8')
    yamlfile = _write_yaml(tmp_path, pp_dir, tables_dir,
                           [_static_table_target('Ofx', [_static_component('land', other)])])
    session = MapSession(yamlfile)
    session.set_mapping('Ofx', 'ocean_monthly', 'deptho', 'deptho', data_series_type='static')
    session.save_pending()

    doc = yaml.safe_load(Path(yamlfile).read_text(encoding='utf-8'))
    new_component = doc['cmor']['table_targets'][0]['target_components'][1]
    varlist = str(varlist_dir / 'CMIP6_Ofx_ocean_monthly_static.list')
    assert new_component == {'component_name': 'ocean_monthly', 'variable_list': varlist,
                             'data_series_type': 'static'}
    assert json.loads(Path(varlist).read_text(encoding='utf-8')) == {'deptho': 'deptho'}


class _FakeControl: # pylint: disable=too-few-public-methods
    def __init__(self, control_id):
        self.id = control_id


class _FakeTreeEvent: # pylint: disable=too-few-public-methods
    def __init__(self, node, control_id):
        self.node = node
        self.control = _FakeControl(control_id)


def _static_leaf(app, local_key):
    ''' expand the pp tree's ocean_monthly component and its static node, return local_key's leaf '''
    pp_tree = app.query_one('#pp_tree')
    component_node = next(n for n in pp_tree.root.children if n.data['component'] == 'ocean_monthly')
    app.on_tree_node_expanded(_FakeTreeEvent(component_node, 'pp_tree'))
    static_node = next(n for n in component_node.children if n.data['kind'] == 'static')
    app.on_tree_node_expanded(_FakeTreeEvent(static_node, 'pp_tree'))
    return next(n for n in static_node.children if n.data.get('local_key') == local_key)


def _select_unmapped(app, var):
    cmip_tree = app.query_one('#cmip_tree')
    unmapped_node = cmip_tree.root.children[0].children[0]
    node = next(n for n in unmapped_node.children if n.data['var'] == var)
    app.on_tree_node_selected(_FakeTreeEvent(node, 'cmip_tree'))


@pytest.mark.asyncio
async def test_map_app_maps_static_variable(tmp_path, static_tree): # pylint: disable=redefined-outer-name
    ''' the pp tree lists the static file's variables, which map into a static table '''
    pp_dir, tables_dir, _ = static_tree
    yamlfile = _ofx_yaml(tmp_path, pp_dir, tables_dir, var_list={'geolat': ''})
    session = MapSession(yamlfile)
    app = MapApp(session)
    async with app.run_test() as pilot:
        _select_unmapped(app, 'deptho')
        leaf = _static_leaf(app, 'deptho')
        assert leaf.data['freq'] == 'static'
        app.on_tree_node_selected(_FakeTreeEvent(leaf, 'pp_tree'))
        await pilot.pause()
        await pilot.press('m')
        await pilot.pause()
        await pilot.press('s')
        await pilot.pause()
    varlist = tmp_path / 'CMIP6_Ofx_ocean_monthly_static.list'
    assert json.loads(varlist.read_text(encoding='utf-8')) == {'geolat': '', 'deptho': 'deptho'}


@pytest.mark.asyncio
async def test_map_app_refuses_static_variable_in_ts_table(tmp_path, static_tree): # pylint: disable=redefined-outer-name
    ''' a static file's variable cannot be mapped into a time-series table target '''
    pp_dir, tables_dir, _ = static_tree
    varlist = tmp_path / 'CMIP6_Ofx_ocean_monthly.list'
    varlist.write_text('{}', encoding='utf-8')
    component = {'component_name': 'ocean_monthly', 'variable_list': str(varlist),
                 'data_series_type': 'ts', 'chunk': 'P5Y'}
    target = _static_table_target('Ofx', [component])
    target['freq'] = 'monthly'
    session = MapSession(_write_yaml(tmp_path, pp_dir, tables_dir, [target]))
    app = MapApp(session)
    async with app.run_test() as pilot:
        _select_unmapped(app, 'deptho')
        app.on_tree_node_selected(_FakeTreeEvent(_static_leaf(app, 'deptho'), 'pp_tree'))
        await pilot.pause()
        await pilot.press('m')
        await pilot.pause()
        assert not session.has_pending_changes


# ── fremor run ─────────────────────────────────────────────────────────────

def test_find_existing_output_static():
    ''' a static input matches an output without a date range, and only that '''
    fx_output = Path('/out/deptho_Ofx_src_exp_r1i1p1f1_gn.nc')
    dated_output = Path('/out/deptho_Ofx_src_exp_r1i1p1f1_gn_000101-000512.nc')
    assert find_existing_output('deptho_Ofx_', STATIC_ISO_DATETIME, [dated_output, fx_output]) == fx_output
    assert find_existing_output('deptho_Ofx_', STATIC_ISO_DATETIME, [dated_output]) is None
    # an input without a parseable date range never matches an fx output by accident
    assert find_existing_output('deptho_Ofx_', 'garbage', [fx_output]) is None


def test_run_rejects_non_static_file(tmp_path, cmip6_exp_config):
    ''' a file indir must be a FRE static file '''
    other = _write_static_nc(tmp_path / 'ocean.000101-000512.deptho.nc')
    varlist = tmp_path / 'v.list'
    varlist.write_text(json.dumps({'deptho': 'deptho'}), encoding='utf-8')
    with pytest.raises(ValueError, match='or a FRE static file'):
        cmor_run_subtool(indir=other, json_var_list=str(varlist),
                         json_table_config=str(CMIP6_TABLES / 'CMIP6_Ofx.json'),
                         json_exp_config=cmip6_exp_config, outdir=str(tmp_path / 'out'))


@pytest.fixture(scope='module')
def tripolar_static_file(tmp_path_factory):
    ''' the mock archive's native-grid MOM6 ocean static file, plus a deptho field '''
    pp_dir = tmp_path_factory.mktemp('static_run') / 'pp' / 'ocean_monthly'
    pp_dir.mkdir(parents=True)
    static_file = pp_dir / 'ocean_monthly.static.nc'
    ncgen(MOCK_OCEAN_STATIC_CDL, static_file)
    with Dataset(static_file, 'a') as ds:
        deptho = ds.createVariable('deptho', 'f4', ('yh', 'xh'), fill_value=1.e20)
        deptho.units = 'm'
        deptho.long_name = 'Sea Floor Depth Below Geoid'
        deptho.standard_name = 'sea_floor_depth_below_geoid'
        deptho.cell_methods = 'time: point'
        deptho[:] = 4000.
    return str(static_file)


@pytest.mark.parametrize('mip_era', ['cmip6', 'cmip7'])
def test_run_static_file_tripolar(tmp_path, tripolar_static_file, mip_era, monkeypatch, # pylint: disable=redefined-outer-name,too-many-arguments,too-many-positional-arguments
                                  request):
    ''' CMORize deptho straight from the static file: an fx output, without a time axis or a
    date range in its name -- and skipped when it already exists '''
    monkeypatch.setattr('fremor.cmor_tripolar.find_gold_ocean_statics_file', lambda **kw: None)
    exp_config = request.getfixturevalue(f'{mip_era}_exp_config')
    table = (str(CMIP6_TABLES / 'CMIP6_Ofx.json') if mip_era == 'cmip6'
             else str(CMIP7_TABLES / 'CMIP7_ocean.json'))
    varlist = tmp_path / 'v.list'
    varlist.write_text(json.dumps({'deptho': 'deptho', 'geolat': ''}), encoding='utf-8')
    outdir = tmp_path / 'out'

    def run():
        return cmor_run_subtool(indir=tripolar_static_file, json_var_list=str(varlist),
                                json_table_config=table, json_exp_config=exp_config,
                                outdir=str(outdir), grid='native tripolar',
                                grid_label='gn' if mip_era == 'cmip6' else 'g010',
                                nom_res='25 km', start='1850', calendar_type='noleap',
                                skip_existing=True)

    assert run() == 0
    outputs = [path for path in glob.glob(f'{outdir}/**/deptho_*.nc', recursive=True)
               if 'CMOR_tmp' not in path]
    assert len(outputs) == 1, outputs
    assert not Path(outputs[0]).name.split('_')[-1].startswith('0')  # no date range
    if mip_era == 'cmip7':
        assert '_fx_' in Path(outputs[0]).name
    with Dataset(outputs[0]) as ds:
        assert 'time' not in ds.dimensions
        assert ds.variables['deptho'].ndim == 2
        assert ds.getncattr('frequency') == 'fx'
    mtime = Path(outputs[0]).stat().st_mtime

    # --continue: the existing fx output is found, and not written again
    run()
    assert Path(outputs[0]).stat().st_mtime == mtime
