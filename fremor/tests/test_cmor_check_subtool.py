'''
tests for fremor.cmor_check.cmor_check_subtool
'''

import json
import tempfile
from pathlib import Path

import pytest
import yaml

from fremor.cmor_check import cmor_check_subtool


@pytest.fixture
def temp_dir():
    ''' fixture yielding a temporary directory '''
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def _write_table(tables_dir, table_name, var_names):
    variable_entry = {name: {'standard_name': name} for name in var_names}
    (Path(tables_dir) / f'CMIP6_{table_name}.json').write_text(
        json.dumps({'Header': {'table_id': f'Table {table_name}'}, 'variable_entry': variable_entry}),
        encoding='utf-8'
    )


def _write_amon_table(tables_dir, var_names):
    _write_table(tables_dir, 'Amon', var_names)


def _component_entry(component_name, variable_list_path, chunk='P5Y'):
    return {
        'component_name': component_name,
        'variable_list': str(variable_list_path),
        'data_series_type': 'ts',
        'chunk': chunk,
    }


def _table_target(table_name, components, freq='monthly'):
    return {
        'table_name': table_name,
        'freq': freq,
        'gridding': {'grid_label': 'gn', 'grid_desc': 'd', 'nom_res': '100 km'},
        'target_components': components,
    }


def _write_yaml(temp_dir, table_targets, mip_era='cmip6', pp_dir=None, table_dir=None): # pylint: disable=redefined-outer-name
    ''' write a minimal but structurally-real cmor yaml (as fremor config would produce) '''
    temp_root = Path(temp_dir)
    pp_dir = Path(pp_dir) if pp_dir else temp_root / 'pp'
    pp_dir.mkdir(parents=True, exist_ok=True)
    table_dir = Path(table_dir) if table_dir else temp_root / 'tables'
    table_dir.mkdir(parents=True, exist_ok=True)

    doc = {
        'cmor': {
            'start': None,
            'stop': None,
            'calendar_type': 'noleap',
            'mip_era': mip_era,
            'exp_json': str(temp_root / 'exp.json'),
            'directories': {
                'pp_dir': str(pp_dir),
                'table_dir': str(table_dir),
                'outdir': str(temp_root / 'out'),
            },
            'table_targets': table_targets,
        }
    }
    yamlfile = temp_root / 'cmor.yaml'
    yamlfile.write_text(yaml.safe_dump(doc), encoding='utf-8')
    return str(yamlfile)


def test_cmor_check_subtool_yamlfile_dne_err(temp_dir): # pylint: disable=redefined-outer-name
    ''' yamlfile arg does not exist '''
    yamlfile = str(Path(temp_dir) / 'cmor_dne.yaml')
    with pytest.raises(FileNotFoundError, match=f'yamlfile does not exist: {yamlfile}'):
        cmor_check_subtool(yamlfile=yamlfile)


def test_cmor_check_subtool_noppdir_err(temp_dir): # pylint: disable=redefined-outer-name
    ''' pp_dir referenced by the yaml does not exist '''
    temp_root = Path(temp_dir)
    pp_dir = temp_root / 'pp_dne'
    table_dir = temp_root / 'tables'
    table_dir.mkdir()
    yamlfile = _write_yaml(temp_dir, [], pp_dir=pp_dir, table_dir=table_dir)
    # _write_yaml eagerly creates pp_dir/table_dir; remove pp_dir to simulate a stale yaml
    pp_dir.rmdir()
    with pytest.raises(FileNotFoundError, match=f'pp_dir from yamlfile does not exist: {pp_dir}'):
        cmor_check_subtool(yamlfile=yamlfile)


def test_cmor_check_subtool_notabledir_err(temp_dir): # pylint: disable=redefined-outer-name
    ''' table_dir referenced by the yaml does not exist '''
    temp_root = Path(temp_dir)
    table_dir = temp_root / 'tables_dne'
    yamlfile = _write_yaml(temp_dir, [], table_dir=table_dir)
    table_dir.rmdir()
    with pytest.raises(FileNotFoundError,
                       match=f'mip_tables_dir from yamlfile does not exist: {table_dir}'):
        cmor_check_subtool(yamlfile=yamlfile)


def test_cmor_check_subtool_no_table_targets_err(temp_dir): # pylint: disable=redefined-outer-name
    ''' yaml has no table_targets at all '''
    yamlfile = _write_yaml(temp_dir, [])
    with pytest.raises(ValueError, match=f'no table_targets found in {yamlfile}'):
        cmor_check_subtool(yamlfile=yamlfile)


def test_cmor_check_subtool_missing_table_json_err(temp_dir): # pylint: disable=redefined-outer-name
    ''' a table_target references a table with no corresponding MIP table JSON file '''
    temp_root = Path(temp_dir)
    varlist_dir = temp_root / 'varlists'
    varlist_dir.mkdir()
    varlist_path = varlist_dir / 'CMIP6_Amon_atmos.list'
    varlist_path.write_text(json.dumps({'t_ref': 'tas'}), encoding='utf-8')

    yamlfile = _write_yaml(temp_dir, [
        _table_target('Amon', [_component_entry('atmos', varlist_path)])
    ])
    with pytest.raises(FileNotFoundError, match='MIP table for Amon not found'):
        cmor_check_subtool(yamlfile=yamlfile)


def test_cmor_check_subtool_reports_unmapped_and_multiply_mapped(temp_dir): # pylint: disable=redefined-outer-name
    ''' full report: unmapped, multiply-mapped, and unknown-mapped variables '''
    temp_root = Path(temp_dir)
    tables_dir = temp_root / 'tables'
    tables_dir.mkdir()
    _write_amon_table(tables_dir, ['tas', 'pr', 'ps'])

    varlist_dir = temp_root / 'varlists'
    varlist_dir.mkdir()
    atmos_list = varlist_dir / 'CMIP6_Amon_atmos.list'
    atmos_list.write_text(
        json.dumps({'t_ref': 'tas', 'precip': 'pr', 'sfc_pres': 'ps', 'weird': 'not_a_real_var'}),
        encoding='utf-8'
    )
    scalar_list = varlist_dir / 'CMIP6_Amon_atmos_scalar.list'
    scalar_list.write_text(
        json.dumps({'sfc_pres_scalar': 'ps'}),
        encoding='utf-8'
    )

    yamlfile = _write_yaml(temp_dir, [
        _table_target('Amon', [
            _component_entry('atmos', atmos_list),
            _component_entry('atmos_scalar', scalar_list),
        ])
    ], table_dir=tables_dir)

    report = cmor_check_subtool(yamlfile=yamlfile)

    assert report['Amon']['reference_var_count'] == 3
    assert report['Amon']['unmapped'] == []
    assert set(report['Amon']['multiply_mapped']) == {'ps'}
    assert sorted(report['Amon']['multiply_mapped']['ps']) == [
        ('atmos', 'sfc_pres'), ('atmos_scalar', 'sfc_pres_scalar')
    ]
    assert report['Amon']['unknown_mapped'] == ['not_a_real_var']


def test_cmor_check_subtool_reports_fully_unmapped_table(temp_dir): # pylint: disable=redefined-outer-name
    ''' a component whose varlist file is missing should report every variable unmapped '''
    temp_root = Path(temp_dir)
    tables_dir = temp_root / 'tables'
    tables_dir.mkdir()
    _write_amon_table(tables_dir, ['tas', 'pr'])

    varlist_dir = temp_root / 'varlists'
    varlist_dir.mkdir()
    missing_list = varlist_dir / 'CMIP6_Amon_atmos.list'  # never written

    yamlfile = _write_yaml(temp_dir, [
        _table_target('Amon', [_component_entry('atmos', missing_list)])
    ], table_dir=tables_dir)

    report = cmor_check_subtool(yamlfile=yamlfile)

    assert report['Amon']['unmapped'] == ['pr', 'tas']
    assert report['Amon']['multiply_mapped'] == {}
    assert report['Amon']['unknown_mapped'] == []


def test_cmor_check_subtool_show_mapped(temp_dir): # pylint: disable=redefined-outer-name
    ''' show_mapped=True reports variables mapped from exactly one component/diagnostic '''
    temp_root = Path(temp_dir)
    tables_dir = temp_root / 'tables'
    tables_dir.mkdir()
    _write_amon_table(tables_dir, ['tas', 'pr', 'ps'])

    varlist_dir = temp_root / 'varlists'
    varlist_dir.mkdir()
    atmos_list = varlist_dir / 'CMIP6_Amon_atmos.list'
    atmos_list.write_text(
        json.dumps({'t_ref': 'tas', 'sfc_pres': 'ps'}),
        encoding='utf-8'
    )
    scalar_list = varlist_dir / 'CMIP6_Amon_atmos_scalar.list'
    scalar_list.write_text(
        json.dumps({'sfc_pres_scalar': 'ps'}),
        encoding='utf-8'
    )

    yamlfile = _write_yaml(temp_dir, [
        _table_target('Amon', [
            _component_entry('atmos', atmos_list),
            _component_entry('atmos_scalar', scalar_list),
        ])
    ], table_dir=tables_dir)

    report_default = cmor_check_subtool(yamlfile=yamlfile)
    assert 'one_to_one_mapped' not in report_default['Amon']

    report = cmor_check_subtool(yamlfile=yamlfile, show_mapped=True)
    # 'ps' is multiply-mapped so it should not appear as one-to-one, only 'tas' should.
    assert report['Amon']['one_to_one_mapped'] == {'tas': ('atmos', 't_ref')}


def test_cmor_check_subtool_table_patterns_filters_tables(temp_dir): # pylint: disable=redefined-outer-name
    ''' positional table_patterns restrict which MIP tables are checked, wildcards included '''
    temp_root = Path(temp_dir)
    tables_dir = temp_root / 'tables'
    tables_dir.mkdir()
    _write_table(tables_dir, 'Amon', ['tas'])
    _write_table(tables_dir, 'Lmon', ['mrso'])
    _write_table(tables_dir, 'AERmon', ['o3'])

    varlist_dir = temp_root / 'varlists'
    varlist_dir.mkdir()
    amon_list = varlist_dir / 'CMIP6_Amon_atmos.list'
    amon_list.write_text('{}', encoding='utf-8')
    lmon_list = varlist_dir / 'CMIP6_Lmon_land.list'
    lmon_list.write_text('{}', encoding='utf-8')
    aermon_list = varlist_dir / 'CMIP6_AERmon_atmos.list'
    aermon_list.write_text('{}', encoding='utf-8')

    yamlfile = _write_yaml(temp_dir, [
        _table_target('Amon', [_component_entry('atmos', amon_list)]),
        _table_target('Lmon', [_component_entry('land', lmon_list)]),
        _table_target('AERmon', [_component_entry('atmos', aermon_list)]),
    ], table_dir=tables_dir)

    report = cmor_check_subtool(yamlfile=yamlfile, table_patterns=['Lmon'])
    assert set(report) == {'Lmon'}

    report_wild = cmor_check_subtool(yamlfile=yamlfile, table_patterns=['AER*'])
    assert set(report_wild) == {'AERmon'}

    report_all = cmor_check_subtool(yamlfile=yamlfile)
    assert set(report_all) == {'Amon', 'Lmon', 'AERmon'}


def test_cmor_check_subtool_table_patterns_no_match_err(temp_dir): # pylint: disable=redefined-outer-name
    ''' table_patterns matching nothing raises ValueError '''
    temp_root = Path(temp_dir)
    tables_dir = temp_root / 'tables'
    tables_dir.mkdir()
    _write_amon_table(tables_dir, ['tas'])

    varlist_dir = temp_root / 'varlists'
    varlist_dir.mkdir()
    amon_list = varlist_dir / 'CMIP6_Amon_atmos.list'
    amon_list.write_text('{}', encoding='utf-8')

    yamlfile = _write_yaml(temp_dir, [
        _table_target('Amon', [_component_entry('atmos', amon_list)])
    ], table_dir=tables_dir)

    with pytest.raises(ValueError, match='no table_targets .* matched table_patterns'):
        cmor_check_subtool(yamlfile=yamlfile, table_patterns=['Omon'])
