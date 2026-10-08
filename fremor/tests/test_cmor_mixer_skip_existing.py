"""
Tests for skipping input files whose CMOR output already exists
================================================================

``fremor yaml --continue`` passes ``skip_existing=True`` down to ``cmor_run_subtool``, which
indexes the output directory once and skips each input file whose output (same variable,
table or CMIP7 brand, and year range) is already there.
"""

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from fremor import cmor_mixer
from fremor.cmor_mixer import (cmor_run_subtool, expected_output_prefix, find_existing_output,
                               index_existing_outputs)


ROOTDIR = 'fremor/tests/test_files'
CMIP6_TABLE_CONFIG = f'{ROOTDIR}/cmip6-cmor-tables/Tables/CMIP6_Omon.json'
CMIP7_TABLE_CONFIG = f'{ROOTDIR}/cmip7-cmor-tables/tables/CMIP7_ocean.json'
EXP_CONFIG = f'{ROOTDIR}/CMOR_input_example.json'
CMIP7_EXP_CONFIG = f'{ROOTDIR}/CMOR_CMIP7_input_example.json'


def _touch(path, content=b'x'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


# ---------------------------------------------------------------------------
# filename matching
# ---------------------------------------------------------------------------

def test_index_existing_outputs_skips_tmp_and_empty(tmp_path):
    ''' outputs still in CMOR_tmp, or empty, do not count as existing '''
    good = _touch(tmp_path / 'CMIP6/x/tas_Amon_M_exp_r1_gn_185001-185412.nc')
    _touch(tmp_path / 'CMOR_tmp/tas_Amon_M_exp_r1_gn_185501-185912.nc')
    _touch(tmp_path / 'CMIP6/x/tas_Amon_M_exp_r1_gn_186001-186412.nc', b'')
    assert index_existing_outputs(str(tmp_path)) == [good]
    assert index_existing_outputs(str(tmp_path / 'dne')) == []


def test_find_existing_output_matches_variable_and_years(tmp_path):
    ''' a match needs the same prefix and the same year range; date precision may differ '''
    outputs = [_touch(tmp_path / 'tas_Amon_M_exp_r1_gn_185001-185412.nc'),
               _touch(tmp_path / 'tasmax_Amon_M_exp_r1_gn_185501-185912.nc')]
    assert find_existing_output('tas_Amon_', '185001-185412', outputs) == outputs[0]
    assert find_existing_output('tas_Amon_', '18500101-18541231', outputs) == outputs[0]
    assert find_existing_output('tas_Amon_', '185501-185912', outputs) is None
    assert find_existing_output('tas_Omon_', '185001-185412', outputs) is None
    assert find_existing_output(None, '185001-185412', outputs) is None


def test_expected_output_prefix_cmip6_table_id_or_filename():
    ''' CMIP6 prefix uses the Header table_id, else the table filename '''
    with_header = {'Header': {'table_id': 'Table Amon'}, 'variable_entry': {}}
    assert expected_output_prefix('in.nc', 'tas', 'tas', with_header,
                                  '/t/CMIP6_Amon.json', 'CMIP6') == 'tas_Amon_'
    assert expected_output_prefix('in.nc', 'sos', 'sos', {'variable_entry': {}},
                                  '/t/CMIP6_Omon.json', 'CMIP6') == 'sos_Omon_'
    assert expected_output_prefix('in.nc', 'sos', 'sos', {'variable_entry': {}},
                                  '/t/MIP_Omon.json', 'CMIP6PLUS') == 'sos_Omon_'


def test_expected_output_prefix_cmip7_single_brand_needs_no_file():
    ''' a CMIP7 variable with one brand in the table never opens the input file '''
    cfgs = {'variable_entry': {'sos_tavg-u-hxy-sea': {}, 'tos_tavg-u-hxy-sea': {}}}
    assert expected_output_prefix('/does/not/exist.nc', 'sos', 'sos', cfgs,
                                  'CMIP7_ocean.json', 'CMIP7') == 'sos_tavg-u-hxy-sea_'


def test_expected_output_prefix_cmip7_multi_brand_unresolvable():
    ''' a CMIP7 variable with several brands whose input cannot be read gives no prefix, so
    that input file is processed rather than wrongly skipped '''
    cfgs = {'variable_entry': {'tas_tavg-h2m-hxy-u': {}, 'tas_tmax-h2m-hxy-u': {}}}
    assert expected_output_prefix('/does/not/exist.nc', 'tasmax', 'tas', cfgs,
                                  'CMIP7_atmos.json', 'CMIP7') is None


def test_expected_output_prefix_cmip7_multi_brand_resolved_from_input():
    ''' with several brands, the brand is resolved from the input file's header '''
    cfgs = {'variable_entry': {'tas_tavg-h2m-hxy-u': {}, 'tas_tmax-h2m-hxy-u': {}}}
    with patch('fremor.cmor_mixer.nc.Dataset') as mock_ds, \
         patch('fremor.cmor_mixer.resolve_cmip7_brand', return_value='tmax-h2m-hxy-u') as mock_brand:
        mock_ds.return_value.__enter__.return_value.variables = {'tasmax': type('V', (), {'ndim': 3})()}
        prefix = expected_output_prefix('in.nc', 'tasmax', 'tas', cfgs, 'CMIP7_atmos.json', 'CMIP7')
    assert prefix == 'tas_tmax-h2m-hxy-u_'
    assert mock_brand.call_args.args[4] == 3


# ---------------------------------------------------------------------------
# real CMORization, run twice
# ---------------------------------------------------------------------------

@pytest.fixture
def sos_run(cli_sos_nc_file, tmp_path):
    ''' an indir holding only the sos input file, a sos varlist, and an empty outdir '''
    indir = tmp_path / 'indir'
    indir.mkdir()
    shutil.copy(cli_sos_nc_file, indir)
    varlist = tmp_path / 'varlist.json'
    varlist.write_text(json.dumps({'sos': 'sos'}), encoding='utf-8')
    return {'indir': str(indir), 'varlist': str(varlist), 'outdir': str(tmp_path / 'outdir')}


@pytest.mark.parametrize('table_config, exp_config, grid_label, nom_res', [
    (CMIP6_TABLE_CONFIG, EXP_CONFIG, 'gr', '10000 km'),
    (CMIP7_TABLE_CONFIG, CMIP7_EXP_CONFIG, 'g010', '100 km'),
], ids=['cmip6', 'cmip7'])
def test_skip_existing_rerun_skips_done_files(sos_run, tmp_path, table_config, exp_config, # pylint: disable=redefined-outer-name, too-many-arguments, too-many-positional-arguments
                                              grid_label, nom_res):
    ''' after a real run, a skip_existing rerun does not CMORize the file again, while a
    plain rerun still does '''
    local_exp = tmp_path / 'exp.json'
    shutil.copy(exp_config, local_exp)
    run_kwargs = {'indir': sos_run['indir'], 'json_var_list': sos_run['varlist'],
                  'json_table_config': table_config, 'json_exp_config': str(local_exp),
                  'outdir': sos_run['outdir'], 'grid': 'FOO_BAR_PLACEHOLD',
                  'grid_label': grid_label, 'nom_res': nom_res, 'calendar_type': 'julian'}

    assert cmor_run_subtool(**run_kwargs) == 0
    outputs = index_existing_outputs(sos_run['outdir'])
    assert len(outputs) == 1 and outputs[0].name.startswith('sos_')
    first_mtime = outputs[0].stat().st_mtime_ns

    with patch('fremor.cmor_mixer.rewrite_netcdf_file_var',
               wraps=cmor_mixer.rewrite_netcdf_file_var) as mock_rewrite:
        assert cmor_run_subtool(**run_kwargs, skip_existing=True) == 0
    mock_rewrite.assert_not_called()
    assert outputs[0].stat().st_mtime_ns == first_mtime

    outputs[0].unlink()
    with patch('fremor.cmor_mixer.rewrite_netcdf_file_var',
               wraps=cmor_mixer.rewrite_netcdf_file_var) as mock_rewrite:
        assert cmor_run_subtool(**run_kwargs, skip_existing=True) == 0
    mock_rewrite.assert_called_once()
    assert len(index_existing_outputs(sos_run['outdir'])) == 1


# ---------------------------------------------------------------------------
# plumbing from fremor yaml
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('skip_existing', [True, False])
def test_yaml_subtool_passes_skip_existing(tmp_path, skip_existing):
    ''' cmor_yaml_subtool hands skip_existing through to every cmor_run_subtool call '''
    from fremor.cmor_yamler import cmor_yaml_subtool  # pylint: disable=import-outside-toplevel
    pp_dir = tmp_path / 'pp'
    (pp_dir / 'ocean' / 'ts' / 'monthly' / '5yr').mkdir(parents=True)
    table_dir = tmp_path / 'tables'
    table_dir.mkdir()
    (table_dir / 'CMIP6_Omon.json').write_text(json.dumps({'variable_entry': {}}), encoding='utf-8')
    yamlfile = tmp_path / 'cmor.yaml'
    yamlfile.write_text(json.dumps({'cmor': {
        'mip_era': 'CMIP6', 'exp_json': str(Path(EXP_CONFIG).resolve()),
        'directories': {'pp_dir': str(pp_dir), 'table_dir': str(table_dir),
                        'outdir': str(tmp_path / 'out')},
        'table_targets': [{'table_name': 'Omon', 'freq': 'monthly', 'gridding': None,
                           'target_components': [{'component_name': 'ocean', 'chunk': 'P5Y',
                                                  'data_series_type': 'ts',
                                                  'variable_list': str(tmp_path / 'v.json')}]}],
    }}), encoding='utf-8')

    with patch('fremor.cmor_yamler.cmor_run_subtool') as mock_run:
        cmor_yaml_subtool(yamlfile=str(yamlfile), skip_existing=skip_existing)
    assert mock_run.call_args.kwargs['skip_existing'] is skip_existing
