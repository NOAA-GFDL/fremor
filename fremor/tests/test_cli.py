"""
CLI Tests for fremor subcommands

Tests the command-line-interface calls for the fremor CLI (fremor package).
Each tool generally gets 3 tests:

- fremor $tool, checking for exit code 0 or 2 (fails if cli isn't configured right)
- fremor $tool --help, checking for exit code 0 (fails if the code doesn't run)
- fremor $tool --optionDNE, checking for exit code 2 (fails if cli isn't configured
  right and thinks the tool has a --optionDNE option)

We also have a set of more complicated tests for testing the full set of
command-line args for fremor yaml and fremor run.

Migrated from NOAA-GFDL/fre-cli fre/tests/test_fre_cmor_cli.py.
"""

import json
import os
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch

from click.testing import CliRunner
import yaml

from fremor.cli import fremor

from .conftest import (
    ROOTDIR, INDIR, VARLIST, VARLIST_DIFF, VARLIST_MAPPED,
    EXP_CONFIG, EXP_CONFIG_CMIP7,
    CMIP6_TABLE_CONFIG, CMIP7_TABLE_CONFIG,
)

runner = CliRunner()
AM5_YAML_EX_DIR = ROOTDIR / 'yaml_examples' / 'am5'

# log format strings produced by the fremor group callback (cli.py / fremor)
LOG_INFO_LINE = '[ INFO:                  cli.py:                  fremor] ' + \
                'fre_file_handler added to base_fre_logger\n'
LOG_DEBUG_LINE = '[DEBUG:                  cli.py:                  fremor] ' + \
                 'click entry-point function call done.\n'


# ── setup ──────────────────────────────────────────────────────────────────

def test_setup_test_files(cli_sos_nc_file, cli_sosv2_nc_file, cli_mapped_nc_file):
    """
    Verify all required NetCDF test files exist via session-scoped fixtures.
    """
    assert Path(cli_sos_nc_file).exists()
    assert Path(cli_sosv2_nc_file).exists()
    assert Path(cli_mapped_nc_file).exists()


# ── fremor (top-level group) ──────────────────────────────────────────────

def test_cli_fremor():
    """
    fremor
    """
    result = runner.invoke(fremor, args=[])
    assert result.exit_code == 2

def test_cli_fremor_help():
    """
    fremor --help
    """
    result = runner.invoke(fremor, args=['--help'])
    assert result.exit_code == 0

def test_cli_fremor_help_and_debuglog(tmp_path):
    """
    fremor -vv -l LOG yaml --help (logs created by group callback)
    """
    log_file = tmp_path / 'TEST_FOO_LOG.log'

    result = runner.invoke(fremor, args=['-vv', '-l', str(log_file), 'yaml', '--help'])
    assert result.exit_code == 0
    assert log_file.exists()

    line_list = log_file.read_text(encoding='utf-8').splitlines(keepends=True)
    assert LOG_INFO_LINE in line_list[0]
    assert LOG_DEBUG_LINE in line_list[1]

def test_cli_fremor_help_and_infolog(tmp_path):
    """
    fremor -v -l LOG yaml --help
    """
    log_file = tmp_path / 'TEST_FOO_LOG.log'

    result = runner.invoke(fremor, args=['-v', '-l', str(log_file), 'yaml', '--help'])
    assert result.exit_code == 0
    assert log_file.exists()

    line_list = log_file.read_text(encoding='utf-8').splitlines(keepends=True)
    assert LOG_INFO_LINE in line_list[0]

def test_cli_fremor_help_and_quietlog(tmp_path):
    """
    fremor -q -l LOG yaml --help
    """
    log_file = tmp_path / 'TEST_FOO_LOG.log'

    result = runner.invoke(fremor, args=['-q', '-l', str(log_file), 'yaml', '--help'])
    assert result.exit_code == 0
    assert log_file.exists()

    line_list = log_file.read_text(encoding='utf-8').splitlines(keepends=True)
    assert line_list == []

def test_cli_fremor_opt_dne():
    """
    fremor optionDNE
    """
    result = runner.invoke(fremor, args=['optionDNE'])
    assert result.exit_code == 2


# ── fremor yaml ───────────────────────────────────────────────────────────

def test_cli_fremor_yaml():
    """
    fremor yaml
    """
    result = runner.invoke(fremor, args=['yaml'])
    assert result.exit_code == 2

def test_cli_fremor_yaml_help():
    """ fremor yaml --help """
    result = runner.invoke(fremor, args=['yaml', '--help'])
    assert result.exit_code == 0

def test_cli_fremor_yaml_opt_dne():
    """ fremor yaml optionDNE """
    result = runner.invoke(fremor, args=['yaml', 'optionDNE'])
    assert result.exit_code == 2

@patch('fremor.cli.cmor_yaml_subtool')
def test_cli_fremor_yaml_case1(mock_subtool, tmp_path):
    """ fremor yaml --dry_run -y YAMLFILE """
    dummy_yaml = tmp_path / 'cmor.yaml'
    dummy_yaml.write_text('placeholder', encoding='utf-8')

    mock_subtool.return_value = None

    result = runner.invoke(fremor, args=['-v', '-v', 'yaml', '--dry_run',
                                         '-y', str(dummy_yaml)])

    assert result.exit_code == 0
    mock_subtool.assert_called_once_with(
        yamlfile=str(dummy_yaml),
        run_strict_mode=False,
        run_one_mode=False,
        dry_run_mode=True,
        start=None,
        stop=None,
        print_cli_call=True,
    )


# ── fremor stage ───────────────────────────────────────────────────

def test_cli_fremor_stage_help():
    """fremor stage --help."""
    result = runner.invoke(fremor, args=['stage', '--help'])
    assert result.exit_code == 0


@patch('fremor.cli.cmor_stage_subtool')
def test_cli_fremor_stage_dry_run(mock_subtool, tmp_path):
    """The stage CLI prints dry-run paths and forwards its options."""
    yamlfile = tmp_path / 'cmor.yaml'
    yamlfile.touch()
    mock_subtool.return_value = ['/archive/case/a.nc', '/archive/case/b.nc']

    result = runner.invoke(fremor, args=[
        'stage', '-y', str(yamlfile), '--start', '2000', '--stop', '2004',
        '--dmget_bin', '/usr/local/bin/dmget', '--dry_run',
    ])

    assert result.exit_code == 0
    assert '/archive/case/a.nc' in result.output
    assert 'Would stage 2 files in one dmget batch.' in result.output
    mock_subtool.assert_called_once_with(
        yamlfile=str(yamlfile),
        start='2000',
        stop='2004',
        dmget_bin='/usr/local/bin/dmget',
        dry_run=True,
    )


# ── fremor resolve ───────────────────────────────────────────────────────────

def test_cli_fremor_resolve():
    """ fremor resolve """
    result = runner.invoke(fremor, args=['resolve'])
    assert result.exit_code == 2


def test_cli_fremor_resolve_help():
    """ fremor resolve --help """
    result = runner.invoke(fremor, args=['resolve', '--help'])
    assert result.exit_code == 0


def test_cli_fremor_resolve_opt_dne():
    """ fremor resolve optionDNE """
    result = runner.invoke(fremor, args=['resolve', 'optionDNE'])
    assert result.exit_code == 2


def test_cli_fremor_resolve_case1(tmp_path):
    """ fremor resolve --output should write the resolved AM5 YAML """
    output_yaml = tmp_path / 'resolved_am5.yaml'
    expected_yaml = AM5_YAML_EX_DIR / 'expected_resolved.yaml'

    result = runner.invoke(fremor, args=[
        'resolve',
        '-y', str(AM5_YAML_EX_DIR / 'model.yaml'),
        '-e', 'c96L65_am5f7b12r1_amip',
        '--output', str(output_yaml),
    ])

    assert result.exit_code == 0, result.output
    with open(output_yaml, encoding='utf-8') as handle:
        resolved = yaml.safe_load(handle)
    with open(expected_yaml, encoding='utf-8') as handle:
        expected = yaml.safe_load(handle)
    assert resolved == expected


def test_cli_fremor_resolve_case2_stdout():
    """ fremor resolve without --output should print resolved YAML to stdout """
    result = runner.invoke(fremor, args=[
        'resolve',
        '-y', str(AM5_YAML_EX_DIR / 'model.yaml'),
        '-e', 'c96L65_am5f7b12r1_amip',
    ])

    assert result.exit_code == 0, result.output
    resolved = yaml.safe_load(result.output)
    assert resolved['cmor']['directories']['pp_dir'].endswith(
        'c96L65_am5f7b12r1_amip/pp'
    )


# ── fremor run ────────────────────────────────────────────────────────────

def test_cli_fremor_run():
    """ fremor run (no args) """
    result = runner.invoke(fremor, args=['run'])
    assert result.exit_code == 2

def test_cli_fremor_run_help():
    """ fremor run --help """
    result = runner.invoke(fremor, args=['run', '--help'])
    assert result.exit_code == 0

def test_cli_fremor_run_opt_dne():
    """ fremor run optionDNE """
    result = runner.invoke(fremor, args=['run', 'optionDNE'])
    assert result.exit_code == 2


def test_cli_fremor_run_case1(cli_sos_nc_file, tmp_path):
    """fremor run, test-use case: sos → sos (CMIP6)"""
    outdir = str(tmp_path / 'outdir')

    result = runner.invoke(fremor, args = [ '-v', '-v',
                                            'run', '--run_one',
                                            '--indir', str(INDIR),
                                            '--varlist', str(VARLIST),
                                            '--table_config', str(CMIP6_TABLE_CONFIG),
                                            '--exp_config', str(EXP_CONFIG),
                                            '--outdir', outdir,
                                            '--calendar', 'julian',
                                            '--grid_label', 'gr',
                                            '--grid_desc', 'FOO_BAR_PLACEHOLD',
                                            '--nom_res', '10000 km' ] )
    assert result.exit_code == 0, f'case1 failed: {result.output}'

    output_ncs = list(Path(outdir).rglob('sos_Omon_*.nc'))
    assert len(output_ncs) > 0, 'no output sos file found'
    assert Path(cli_sos_nc_file).exists(), 'input file should still exist'


def test_cli_fremor_run_case2(cli_sosv2_nc_file, tmp_path):
    """
    fremor run, test error case: filename variable != file variable (CMIP6).
    The sosV2 file has variable 'sos' inside, but the varlist expects 'sosV2' as the
    modeler variable name. This mismatch should cause a non-zero exit code.
    """
    outdir = str(tmp_path / 'outdir')

    result = runner.invoke(fremor, args = ['-v', '-v',
                                           'run', '--run_one',
                                           '--indir', str(INDIR),
                                           '--varlist', str(VARLIST_DIFF),
                                           '--table_config', str(CMIP6_TABLE_CONFIG),
                                           '--exp_config', str(EXP_CONFIG),
                                           '--outdir', outdir,
                                           '--calendar', 'julian',
                                           '--grid_label', 'gr',
                                           '--grid_desc', 'FOO_BAR_PLACEHOLD',
                                           '--nom_res', '10000 km' ] )
    assert result.exit_code == 0


def test_cli_fremor_run_cmip7_case1(cli_sos_nc_file, tmp_path): # pylint: disable=redefined-outer-name
    """fremor run, test-use case for cmip7: sos → sos"""
    outdir = str(tmp_path / 'outdir')

    result = runner.invoke(fremor, args = [ '-v', '-v',
                                            'run', '--run_one',
                                            '--indir', str(INDIR),
                                            '--varlist', str(VARLIST),
                                            '--table_config', str(CMIP7_TABLE_CONFIG),
                                            '--exp_config', str(EXP_CONFIG_CMIP7),
                                            '--outdir', outdir,
                                            '--calendar', 'julian',
                                            '--grid_label', 'g999',
                                            '--grid_desc', 'FOO_BAR_PLACEHOLD',
                                            '--nom_res', '10000 km' ] )
    assert result.exit_code == 0, f'cmip7 case1 failed: {result.output}'

    output_ncs = list(Path(outdir).rglob('sos_*.nc'))
    assert len(output_ncs) > 0, 'no output sos file found'
    assert Path(cli_sos_nc_file).exists(), 'input file should still exist'


def test_cli_fremor_run_cmip7_case2(cli_sosv2_nc_file, tmp_path):
    """
    fremor run, test error case for cmip7: filename variable != file variable.
    The sosV2 file has variable 'sos' inside, but the varlist expects 'sosV2' as the
    modeler variable name. This mismatch should cause a non-zero exit code.
    """
    outdir = str(tmp_path / 'outdir')

    result = runner.invoke(fremor, args = [ '-v', '-v',
                                            'run', '--run_one',
                                            '--indir', str(Path(cli_sosv2_nc_file).parent),
                                            '--varlist', str(VARLIST_DIFF),
                                            '--table_config', str(CMIP7_TABLE_CONFIG),
                                            '--exp_config', str(EXP_CONFIG_CMIP7),
                                            '--outdir', outdir,
                                            '--calendar', 'julian',
                                            '--grid_label', 'g99',
                                            '--grid_desc', 'FOO_BAR_PLACEHOLD',
                                            '--nom_res', '10000 km' ] )
    assert result.exit_code == 0


def test_cli_fremor_run_case3(cli_mapped_nc_file, tmp_path):
    """fremor run, test-use case 3: sea_sfc_salinity → sos mapped variable (CMIP6)"""
    outdir = str(tmp_path / 'outdir')

    result = runner.invoke(fremor, args = [ '-v', '-v',
                                            'run', '--run_one',
                                            '--indir', str(INDIR),
                                            '--varlist', str(VARLIST_MAPPED),
                                            '--table_config', str(CMIP6_TABLE_CONFIG),
                                            '--exp_config', str(EXP_CONFIG),
                                            '--outdir', outdir,
                                            '--calendar', 'julian',
                                            '--grid_label', 'gr',
                                            '--grid_desc', 'FOO_BAR_PLACEHOLD',
                                            '--nom_res', '10000 km' ] )
    assert result.exit_code == 0, f'case3 failed: {result.output}'

    output_ncs = list(Path(outdir).rglob('sos_Omon_*.nc'))
    assert len(output_ncs) > 0, 'no output sos file found'
    assert Path(cli_mapped_nc_file).exists(), 'input file should still exist'


def test_cli_fremor_run_cmip7_case3(cli_mapped_nc_file, tmp_path):
    """fremor run, test-use case 3 for cmip7: sea_sfc_salinity → sos mapped variable"""
    outdir = str(tmp_path / 'outdir')

    result = runner.invoke(fremor, args = [ '-v', '-v',
                                            'run', '--run_one',
                                            '--indir', str(INDIR),
                                            '--varlist', str(VARLIST_MAPPED),
                                            '--table_config', str(CMIP7_TABLE_CONFIG),
                                            '--exp_config', str(EXP_CONFIG_CMIP7),
                                            '--outdir', outdir,
                                            '--calendar', 'julian',
                                            '--grid_label', 'g999',
                                            '--grid_desc', 'FOO_BAR_PLACEHOLD',
                                            '--nom_res', '10000 km' ] )
    assert result.exit_code == 0, f'cmip7 case3 failed: {result.output}'

    output_ncs = list(Path(outdir).rglob('sos_*.nc'))
    assert len(output_ncs) > 0, 'no output sos file found'
    assert Path(cli_mapped_nc_file).exists(), 'input file should still exist'


# ── fremor find ───────────────────────────────────────────────────────────

def test_cli_fremor_find():
    """ fremor find (no args) """
    result = runner.invoke(fremor, args=['find'])
    assert result.exit_code == 2

def test_cli_fremor_find_help():
    """ fremor find --help """
    result = runner.invoke(fremor, args=['find', '--help'])
    assert result.exit_code == 0

def test_cli_fremor_find_opt_dne():
    """ fremor find optionDNE """
    result = runner.invoke(fremor, args=['find', 'optionDNE'])
    assert result.exit_code == 2


def test_cli_fremor_find_cmip6_case1():
    """ fremor find, test-use case searching for variables in cmip6 tables """
    result = runner.invoke(fremor, args=['-v', 'find',
                                         '--varlist', str(VARLIST),
                                         '--table_config_dir', str(CMIP6_TABLE_CONFIG.parent)] )
    assert result.exit_code == 0

def test_cli_fremor_find_cmip6_case2():
    """ fremor find, test-use case searching for variables in cmip6 tables """
    result = runner.invoke(fremor, args=['-v', 'find',
                                         '--opt_var_name', 'sos',
                                         '--table_config_dir', str(CMIP6_TABLE_CONFIG.parent)] )
    assert result.exit_code == 0


# ── fremor config ─────────────────────────────────────────────────────────

def test_cli_fremor_config():
    """ fremor config (no args) """
    result = runner.invoke(fremor, args=['config'])
    assert result.exit_code == 2

def test_cli_fremor_config_help():
    """ fremor config --help """
    result = runner.invoke(fremor, args=['config', '--help'])
    assert result.exit_code == 0

def test_cli_fremor_config_opt_dne():
    """ fremor config optionDNE """
    result = runner.invoke(fremor, args=['config', 'optionDNE'])
    assert result.exit_code == 2


def test_cli_fremor_config_case1(cli_sos_nc_file): # pylint: disable=redefined-outer-name
    """
    fremor config -- generate a CMOR YAML config from a mock pp directory tree.
    Uses the ocean_sos_var_file test data with a mock pp layout.
    """
    # set up a mock pp directory tree that the writer can scan
    mock_pp_dir = ROOTDIR / 'mock_pp_writer'
    comp_ts_dir = mock_pp_dir / 'ocean' / 'ts' / 'monthly' / '5yr'
    comp_ts_dir.mkdir(parents=True, exist_ok=True)

    # make an ice component dir with no chunk-dir to skip accordingly
    (mock_pp_dir / 'ice' / 'ts' / 'monthly' ).mkdir(parents=True, exist_ok=True)

    # make a land component dir with no ts dir to skip accordingly
    (mock_pp_dir / 'land' / 'av').mkdir(parents=True, exist_ok=True)

    # make an empty atmos component dir with no netcdf files to make sure we skip a dir with no nc files
    (mock_pp_dir / 'atmos' / 'ts' / 'monthly' / '5yr').mkdir(parents=True, exist_ok=True)

    # create random file that's not a directory in the pp_dir that we should skip over gracefully
    (mock_pp_dir / 'foo.json').touch()

    # put an av directory in to make sure we're not targeting that at the moment
    (mock_pp_dir / 'ocean' / 'av').mkdir(parents=True, exist_ok=True)

    # put an annual directory in to make sure we're not targeting that at the moment
    (mock_pp_dir / 'ocean' / 'ts' / 'annual').mkdir(parents=True, exist_ok=True)

    # symlink the test nc file into the mock tree
    src_nc = Path(cli_sos_nc_file)
    dst_nc = comp_ts_dir / src_nc.name
    if dst_nc.exists() or dst_nc.is_symlink():
        dst_nc.unlink()
    dst_nc.symlink_to(src_nc.resolve())

    varlist_out_dir = ROOTDIR / 'mock_writer_varlists'
    varlist_out_dir.mkdir(exist_ok=True)

    # create an empty variable list of one we want to create. it should be remade.
    (varlist_out_dir / 'CMIP6_CMIP6_Omon_ocean.list').touch()
    assert (varlist_out_dir / 'CMIP6_CMIP6_Omon_ocean.list').exists(), \
        'pre-existing variable list failed to be created for tests'

    output_yaml = ROOTDIR / 'mock_writer_output.yaml'
    output_data_dir = ROOTDIR / 'mock_writer_outdir'

    # clean up previous runs
    for p in [output_yaml]:
        if p.exists():
            p.unlink()

    # recreate the yaml to make sure it's recreated
    output_yaml.touch()

    result = runner.invoke(fremor, args=[
        '-v', '-v',
        'config',
        '--pp_dir', str(mock_pp_dir),
        '--mip_tables_dir', str(CMIP6_TABLE_CONFIG.parent),
        '--mip_era', 'cmip6',
        '--exp_config', str(EXP_CONFIG),
        '--output_yaml', str(output_yaml),
        '--output_dir', str(output_data_dir),
        '--varlist_dir', str(varlist_out_dir),
        '--freq', 'monthly',
        '--chunk', '5yr',
        '--grid', 'gn',
        '--overwrite'
    ])
    assert result.exit_code == 0, f'config failed: {result.output}'
    assert output_yaml.exists(), 'output YAML was not created'
    assert (varlist_out_dir / 'CMIP6_CMIP6_Omon_ocean.list').exists(), \
        'CMIP6_CMIP6_Omon_ocean.list was not created for some reason'

    # basic sanity: the written file should contain 'cmor:' and 'table_targets:'
    yaml_text = output_yaml.read_text(encoding='utf-8')
    assert 'cmor:' in yaml_text
    assert 'table_targets:' in yaml_text
    loaded_yaml = yaml.safe_load(yaml_text)
    assert loaded_yaml['cmor']['start'] is None
    assert loaded_yaml['cmor']['stop'] is None
    assert loaded_yaml['cmor']['table_targets'][0]['gridding']['grid_label'] == 'gn'
    assert loaded_yaml['cmor']['table_targets'][0]['target_components'][0]['chunk'] == 'P5Y'

    # clean up
    if dst_nc.is_symlink():
        dst_nc.unlink()
    shutil.rmtree(mock_pp_dir, ignore_errors=True)
    shutil.rmtree(varlist_out_dir, ignore_errors=True)
    if output_yaml.exists():
        output_yaml.unlink()


# ── fremor varlist ────────────────────────────────────────────────────────

def test_cli_fremor_varlist():
    """ fremor varlist (no args) """
    result = runner.invoke(fremor, args=['varlist'])
    assert result.exit_code == 2

def test_cli_fremor_varlist_help():
    """ fremor varlist --help """
    result = runner.invoke(fremor, args=['varlist', '--help'])
    assert result.exit_code == 0

def test_cli_fremor_varlist_opt_dne():
    """ fremor varlist optionDNE """
    result = runner.invoke(fremor, args=['varlist', 'optionDNE'])
    assert result.exit_code == 2


def test_cli_fremor_varlist_no_table_filter(cli_sos_nc_file, cli_sosv2_nc_file, cli_mapped_nc_file, tmp_path):
    """
    fremor varlist — no MIP table filter.
    Creates a variable list from the ocean_sos_var_file test data without a MIP table,
    so sos, sosV2, and sea_sfc_salinity should all appear.
    """
    output_varlist = tmp_path / 'test_varlist_no_filter.json'
    assert Path(cli_sos_nc_file).parent == Path(cli_sosv2_nc_file).parent, 'something wrong with input nc files'

    result = runner.invoke(fremor, args=[
        '-v', '-v',
        'varlist',
        '--dir_targ', str(Path(cli_sos_nc_file).parent),
        '--output_variable_list', str(output_varlist)
    ])
    assert result.exit_code == 0, f'varlist failed: {result.output}'
    assert output_varlist.exists(), 'output variable list was not created'

    with open(output_varlist, 'r', encoding='utf-8') as f:
        var_list = json.load(f)

    assert 'sos' in var_list
    assert 'sosV2' in var_list
    assert 'sea_sfc_salinity' in var_list
    assert len(var_list) == 3


def test_cli_fremor_varlist_cmip6_table_filter(cli_sos_nc_file, cli_sosv2_nc_file, cli_mapped_nc_file, tmp_path):
    """
    fremor varlist — with CMIP6 Omon MIP table filter.
    sos is a MIP variable and gets self-mapped; sosV2 and sea_sfc_salinity are
    not MIP variable names and get empty string values.
    """
    output_varlist = tmp_path / 'test_varlist_cmip6_filter.json'
    assert Path(cli_sos_nc_file).parent == Path(cli_sosv2_nc_file).parent, 'something wrong with input nc files'

    result = runner.invoke(fremor, args=[
        '-v', '-v',
        'varlist',
        '--dir_targ', str(Path(cli_sos_nc_file).parent),
        '--output_variable_list', str(output_varlist),
        '--mip_table', str(CMIP6_TABLE_CONFIG)
    ])
    assert result.exit_code == 0, f'varlist failed: {result.output}'
    assert output_varlist.exists(), 'output variable list was not created'

    with open(output_varlist, 'r', encoding='utf-8') as f:
        var_list = json.load(f)

    assert var_list.get('sos') == 'sos', 'sos should be self-mapped as a MIP variable'
    assert 'sosV2' in var_list, 'sosV2 should be included'
    assert var_list['sosV2'] == '', 'sosV2 should have empty string value (not a MIP variable name)'
    assert 'sea_sfc_salinity' in var_list, 'sea_sfc_salinity should be included'
    assert var_list['sea_sfc_salinity'] == '', 'sea_sfc_salinity should have empty string value'


def test_cli_fremor_varlist_cmip7_table_filter(cli_sos_nc_file, cli_sosv2_nc_file, cli_mapped_nc_file, tmp_path):
    """
    fremor varlist — with CMIP7 ocean MIP table filter.
    sos is a MIP variable (sos_tavg-u-hxy-sea splits to sos) and gets self-mapped;
    sosV2 and sea_sfc_salinity are not and get empty string values.
    """

    output_varlist = tmp_path / 'test_varlist_cmip7_filter.json'
    assert Path(cli_sos_nc_file).parent == Path(cli_sosv2_nc_file).parent, 'something wrong with input nc files'

    result = runner.invoke(fremor, args=[
        '-v', '-v',
        'varlist',
        '--dir_targ', str(Path(cli_sos_nc_file).parent),
        '--output_variable_list', str(output_varlist),
        '--mip_table', str(CMIP7_TABLE_CONFIG)
    ])
    assert result.exit_code == 0, f'varlist failed: {result.output}'
    assert output_varlist.exists(), 'output variable list was not created'

    with open(output_varlist, 'r', encoding='utf-8') as f:
        var_list = json.load(f)

    assert var_list.get('sos') == 'sos', 'sos should be self-mapped as a MIP variable'
    assert 'sosV2' in var_list, 'sosV2 should be included'
    assert var_list['sosV2'] == '', 'sosV2 should have empty string value (not a MIP variable name)'
    assert 'sea_sfc_salinity' in var_list, 'sea_sfc_salinity should be included'
    assert var_list['sea_sfc_salinity'] == '', 'sea_sfc_salinity should have empty string value'


# ── fremor init ───────────────────────────────────────────────────────────

def test_cli_fremor_init():
    """ fremor init (no args) """
    result = runner.invoke(fremor, args=['init'])
    assert result.exit_code == 2

def test_cli_fremor_init_help():
    """ fremor init --help """
    result = runner.invoke(fremor, args=['init', '--help'])
    assert result.exit_code == 0

def test_cli_fremor_init_opt_dne():
    """ fremor init optionDNE """
    result = runner.invoke(fremor, args=['init', 'optionDNE'])
    assert result.exit_code == 2


def test_cli_fremor_init_cmip6_exp_config(tmp_path):
    """
    fremor init -- generate a CMIP6 experiment config template.
    """
    output_path = tmp_path / 'test_cmip6_init_template.json'

    result = runner.invoke(fremor, args=[
        'init',
        '--mip_era', 'cmip6',
        '--exp_config', str(output_path)
    ])
    assert result.exit_code == 0, f'init failed: {result.output}'
    assert output_path.exists(), 'output config was not created'

    with open(output_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    assert config['mip_era'] == 'CMIP6'
    assert config['_cmip6_option'] == 'CMIP6'
    assert 'experiment_id' in config
    assert 'output_path_template' in config


def test_cli_fremor_init_cmip7_exp_config(tmp_path):
    """
    fremor init -- generate a CMIP7 experiment config template.
    """
    output_path = tmp_path / 'test_cmip7_init_template.json'

    result = runner.invoke(fremor, args=[
        'init',
        '--mip_era', 'cmip7',
        '--exp_config', str(output_path)
    ])
    assert result.exit_code == 0, f'init failed: {result.output}'
    assert output_path.exists(), 'output config was not created'

    with open(output_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    assert config['mip_era'] == 'CMIP7'
    assert config['_cmip7_option'] == 1
    assert 'experiment_id' in config
    assert 'output_path_template' in config


def test_cli_fremor_init_default_name(tmp_path):
    """
    fremor init -- when no --exp_config is given and no --tables_dir,
    a default-named file should be created in the current directory.
    """
    # Use CliRunner's isolated_filesystem to avoid polluting the actual working directory
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(fremor, args=[
            'init',
            '--mip_era', 'cmip6'
        ])
        assert result.exit_code == 0, f'init failed: {result.output}'

        default_path = Path('CMOR_cmip6_template.json')
        assert default_path.exists(), 'default output config was not created'

        with open(default_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        assert config['mip_era'] == 'CMIP6'


# ── fremor run: logfile + omission tracking ───────────────────────────────

def test_cli_fremor_run_with_logfile(cli_sos_nc_file, tmp_path): # pylint: disable=redefined-outer-name
    """
    fremor -vv -l LOGFILE run ...

    Runs a real CMOR workflow with the -l flag and verifies that the resulting
    log file contains log lines from both cli.py (the CLI entry point) and
    cmor_mixer (the CMOR processing module).
    """
    log_path = tmp_path / 'TEST_CMOR_RUN.log'
    outdir = str(tmp_path / 'outdir')

    result = runner.invoke(fremor, args=[
        '-vv', '-l', str(log_path),
        'run', '--run_one',
        '--indir', str(Path(cli_sos_nc_file).parent),
        '--varlist', str(VARLIST),
        '--table_config', str(CMIP6_TABLE_CONFIG),
        '--exp_config', str(EXP_CONFIG),
        '--outdir', outdir,
        '--calendar', 'julian',
        '--grid_label', 'gr',
        '--grid_desc', 'FOO_BAR_PLACEHOLD',
        '--nom_res', '10000 km',
    ])

    assert result.exit_code == 0, f'run failed: {result.output}'
    assert log_path.exists(), 'log file was not created'

    log_text = log_path.read_text(encoding='utf-8')

    # cli.py entry-point must have written this line when setting up the file handler
    assert 'fre_file_handler added to base_fre_logger' in log_text, \
        'expected cli.py log line not found in log file'

    # cmor_mixer must have emitted at least one line carrying its module filename
    assert 'cmor_mixer.py' in log_text, \
        'expected cmor_mixer.py log line not found in log file'


def test_cli_fremor_run_with_logfile_omission_case(cli_sos_nc_file, cli_sosv2_nc_file, tmp_path): # pylint: disable=redefined-outer-name
    """
    fremor -vv -l LOGFILE run ...

    Uses a varlist where sos->sos succeeds and sosV2->tob fails (tob is a valid
    CMIP6_Omon variable but the sosV2 file contains sos data, not tob).
    Verifies the OMISSION LOG appears in the log file with the failed variable info.
    """
    log_path = tmp_path / 'TEST_CMOR_RUN_OMISSION.log'
    outdir = str(tmp_path / 'outdir')

    # create a temporary varlist: sos->sos will succeed, sosV2->tob will fail
    varlist_data = {'sos': 'sos', 'sosV2': 'tob'}
    varlist_fd, varlist_path = tempfile.mkstemp(suffix='.json')
    with os.fdopen(varlist_fd, 'w') as f:
        json.dump(varlist_data, f)
    assert Path(cli_sos_nc_file).parent == Path(cli_sosv2_nc_file).parent, 'something wrong with input nc files'

    result = runner.invoke(fremor, args=[
        '-vv', '-l', str(log_path),
        'run',
        '--indir', str(Path(cli_sos_nc_file).parent),
        '--varlist', varlist_path,
        '--table_config', str(CMIP6_TABLE_CONFIG),
        '--exp_config', str(EXP_CONFIG),
        '--outdir', outdir,
        '--calendar', 'julian',
        '--grid_label', 'gr',
        '--grid_desc', 'FOO_BAR_PLACEHOLD',
        '--nom_res', '10000 km',
    ])

    assert result.exit_code == 0, f'run failed: {result.output}'
    assert log_path.exists(), 'log file was not created'

    log_text = log_path.read_text(encoding='utf-8')

    # the omission log summary must appear
    assert 'OMISSION LOG' in log_text, \
        'expected OMISSION LOG not found in log file'

    # the failed variable (sosV2/tob) must be mentioned in the omission
    assert 'OMITTED local_var=sosV2 / target_var=tob' in log_text, \
        'expected omission entry for sosV2/tob not found in log file'

    # the expected file path for the omitted variable must appear
    assert '.sosV2.nc' in log_text, \
        'expected file path for omitted variable not found in log file'

    # the CMOR module must have emitted log lines
    assert 'cmor_mixer.py' in log_text, \
        'expected cmor_mixer.py log line not found in log file'

    Path(varlist_path).unlink(missing_ok=True)
