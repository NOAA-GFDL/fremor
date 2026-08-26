'''
tests for fremor.cmor_check.cmor_check_subtool
'''

import json
import tempfile
from pathlib import Path

import pytest

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


def test_cmor_check_subtool_novarlistdir_err(temp_dir): # pylint: disable=redefined-outer-name
    ''' varlist_dir arg does not exist '''
    varlist_dir_targ = Path(temp_dir) / 'varlists_dne'
    with pytest.raises(FileNotFoundError,
                       match=f'varlist_dir does not exist: {varlist_dir_targ}'):
        cmor_check_subtool(varlist_dir=str(varlist_dir_targ),
                           mip_tables_dir=temp_dir,
                           mip_era='cmip6')


def test_cmor_check_subtool_notabledir_err(temp_dir): # pylint: disable=redefined-outer-name
    ''' mip_tables_dir arg does not exist '''
    tables_dir_targ = Path(temp_dir) / 'tables_dne'
    with pytest.raises(FileNotFoundError,
                       match=f'mip_tables_dir does not exist: {tables_dir_targ}'):
        cmor_check_subtool(varlist_dir=temp_dir,
                           mip_tables_dir=str(tables_dir_targ),
                           mip_era='cmip6')


def test_cmor_check_subtool_notables_err(temp_dir): # pylint: disable=redefined-outer-name
    ''' no matching MIP tables found for the given era '''
    tables_dir = Path(temp_dir) / 'tables'
    tables_dir.mkdir()
    (tables_dir / 'CMIP7_ocean.json').write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError,
                       match=f'no MIP tables found in {tables_dir} for era cmip6 after filtering'):
        cmor_check_subtool(varlist_dir=temp_dir,
                           mip_tables_dir=str(tables_dir),
                           mip_era='cmip6')


def test_cmor_check_subtool_reports_unmapped_and_multiply_mapped(temp_dir): # pylint: disable=redefined-outer-name
    ''' full report: unmapped, multiply-mapped, and unknown-mapped variables '''
    tables_dir = Path(temp_dir) / 'tables'
    tables_dir.mkdir()
    _write_amon_table(tables_dir, ['tas', 'pr', 'ps'])

    varlist_dir = Path(temp_dir) / 'varlists'
    varlist_dir.mkdir()
    (varlist_dir / 'CMIP6_Amon_atmos.list').write_text(
        json.dumps({'t_ref': 'tas', 'precip': 'pr', 'sfc_pres': 'ps', 'weird': 'not_a_real_var'}),
        encoding='utf-8'
    )
    (varlist_dir / 'CMIP6_Amon_atmos_scalar.list').write_text(
        json.dumps({'sfc_pres_scalar': 'ps'}),
        encoding='utf-8'
    )

    report = cmor_check_subtool(varlist_dir=str(varlist_dir),
                                mip_tables_dir=str(tables_dir),
                                mip_era='cmip6')

    assert report['Amon']['reference_var_count'] == 3
    assert report['Amon']['unmapped'] == []
    assert set(report['Amon']['multiply_mapped']) == {'ps'}
    assert sorted(report['Amon']['multiply_mapped']['ps']) == [
        ('atmos', 'sfc_pres'), ('atmos_scalar', 'sfc_pres_scalar')
    ]
    assert report['Amon']['unknown_mapped'] == ['not_a_real_var']


def test_cmor_check_subtool_reports_fully_unmapped_table(temp_dir): # pylint: disable=redefined-outer-name
    ''' a table with no matching varlist files at all should report every variable unmapped '''
    tables_dir = Path(temp_dir) / 'tables'
    tables_dir.mkdir()
    _write_amon_table(tables_dir, ['tas', 'pr'])

    varlist_dir = Path(temp_dir) / 'varlists'
    varlist_dir.mkdir()

    report = cmor_check_subtool(varlist_dir=str(varlist_dir),
                                mip_tables_dir=str(tables_dir),
                                mip_era='cmip6')

    assert report['Amon']['unmapped'] == ['pr', 'tas']
    assert report['Amon']['multiply_mapped'] == {}
    assert report['Amon']['unknown_mapped'] == []


def test_cmor_check_subtool_show_mapped(temp_dir): # pylint: disable=redefined-outer-name
    ''' show_mapped=True reports variables mapped from exactly one component/diagnostic '''
    tables_dir = Path(temp_dir) / 'tables'
    tables_dir.mkdir()
    _write_amon_table(tables_dir, ['tas', 'pr', 'ps'])

    varlist_dir = Path(temp_dir) / 'varlists'
    varlist_dir.mkdir()
    (varlist_dir / 'CMIP6_Amon_atmos.list').write_text(
        json.dumps({'t_ref': 'tas', 'sfc_pres': 'ps'}),
        encoding='utf-8'
    )
    (varlist_dir / 'CMIP6_Amon_atmos_scalar.list').write_text(
        json.dumps({'sfc_pres_scalar': 'ps'}),
        encoding='utf-8'
    )

    report_default = cmor_check_subtool(varlist_dir=str(varlist_dir),
                                        mip_tables_dir=str(tables_dir),
                                        mip_era='cmip6')
    assert 'one_to_one_mapped' not in report_default['Amon']

    report = cmor_check_subtool(varlist_dir=str(varlist_dir),
                                mip_tables_dir=str(tables_dir),
                                mip_era='cmip6',
                                show_mapped=True)
    # 'ps' is multiply-mapped so it should not appear as one-to-one, only 'tas' should.
    assert report['Amon']['one_to_one_mapped'] == {'tas': ('atmos', 't_ref')}


def test_cmor_check_subtool_table_patterns_filters_tables(temp_dir): # pylint: disable=redefined-outer-name
    ''' positional table_patterns restrict which MIP tables are checked, wildcards included '''
    tables_dir = Path(temp_dir) / 'tables'
    tables_dir.mkdir()
    _write_table(tables_dir, 'Amon', ['tas'])
    _write_table(tables_dir, 'Lmon', ['mrso'])
    _write_table(tables_dir, 'AERmon', ['o3'])

    varlist_dir = Path(temp_dir) / 'varlists'
    varlist_dir.mkdir()

    report = cmor_check_subtool(varlist_dir=str(varlist_dir),
                                mip_tables_dir=str(tables_dir),
                                mip_era='cmip6',
                                table_patterns=['Lmon'])
    assert set(report) == {'Lmon'}

    report_wild = cmor_check_subtool(varlist_dir=str(varlist_dir),
                                     mip_tables_dir=str(tables_dir),
                                     mip_era='cmip6',
                                     table_patterns=['AER*'])
    assert set(report_wild) == {'AERmon'}

    report_all = cmor_check_subtool(varlist_dir=str(varlist_dir),
                                    mip_tables_dir=str(tables_dir),
                                    mip_era='cmip6')
    assert set(report_all) == {'Amon', 'Lmon', 'AERmon'}


def test_cmor_check_subtool_table_patterns_no_match_err(temp_dir): # pylint: disable=redefined-outer-name
    ''' table_patterns matching nothing raises ValueError '''
    tables_dir = Path(temp_dir) / 'tables'
    tables_dir.mkdir()
    _write_amon_table(tables_dir, ['tas'])

    varlist_dir = Path(temp_dir) / 'varlists'
    varlist_dir.mkdir()

    with pytest.raises(ValueError, match='no MIP tables .* matched table_patterns'):
        cmor_check_subtool(varlist_dir=str(varlist_dir),
                           mip_tables_dir=str(tables_dir),
                           mip_era='cmip6',
                           table_patterns=['Omon'])
