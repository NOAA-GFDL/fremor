'''
Expanded set of tests for fremor run — cases beyond test_cmor_run_subtool.py.

These tests exercise cmor_run_subtool against a variety of variables, tables,
and grid labels drawn from a mock pp-archive.

.. tip:: pytest temp directories
   By default pytest removes temp directories after the session. To keep
   them around for debugging, run::

       pytest --basetemp=/tmp/fremor-debug -k test_case_cmip6 -x

   Output files will then persist under ``/tmp/fremor-debug``.
'''

from datetime import date

import pytest

from fremor import cmor_run_subtool
from fremor.tests._cmor_test_helpers import (
    assert_cmor_output_matches_input,
    find_cmor_output,
    ncgen_for_case as _ncgen_for_case,
)
from fremor.tests.conftest import ncgen


# ── path constants ──────────────────────────────────────────────────────────
ROOTDIR = 'fremor/tests/test_files'
CMORBITE_VARLIST = f'{ROOTDIR}/CMORbite_var_list.json'

# cmip6 table repo
CMIP6_TABLE_REPO_PATH = f'{ROOTDIR}/cmip6-cmor-tables'

# experiment config (materialized by conftest._write_exp_configs)
EXP_CONFIG_CMIP6 = f'{ROOTDIR}/CMOR_input_example.json'

# determined by cmor_run_subtool
YYYYMMDD = date.today().strftime('%Y%m%d')

# mock-archive base paths
MOCK_ARCHIVE_ROOT = f'{ROOTDIR}/ascii_files/mock_archive'
ESM4_DECK_PP_DIR = (
    'cm6/ESM4/DECK/ESM4_historical_D1/gfdl.ncrc4-intel16-prod-openmp/pp'
)
ESM4_DEV_PP_DIR = (
    'USER/CMIP7/ESM4/DEV/ESM4.5v01_om5b04_piC'
    '/gfdl.ncrc5-intel23-prod-openmp/pp'
)

# CMIP6 output dir structure
CMOR_CREATES_DIR_BASE_CMIP6 = (
    'CMIP6/CMIP6/ISMIP6/PCMDI/PCMDI-test-1-0/piControl-withism/r3i1p1f1'
)


# ── CMIP6 parametrized tests ───────────────────────────────────────────────
# zonal/global means are written under the label the CV reserves for them, not the table's
# (see cmor_helpers.variable_grid_label)
OUTPUT_GRID_LABELS = {('AERmonZ', 'ta'): 'gr1z', ('Amon', 'ch4global'): 'gm'}

@pytest.mark.parametrize(
    'testfile_dir,table,opt_var_name,grid_label,start,calendar',
    [
        pytest.param(
            f'{MOCK_ARCHIVE_ROOT}/{ESM4_DECK_PP_DIR}'
            '/atmos_plev39_cmip/ts/monthly/5yr/zonavg/',
            'AERmonZ', 'ta', 'gr1', '1850', 'noleap',
            id='AERmonZ_ta_gr1',
        ),
        pytest.param(
            f'{MOCK_ARCHIVE_ROOT}/{ESM4_DECK_PP_DIR}'
            '/atmos_scalar/ts/monthly/5yr/',
            'Amon', 'ch4global', 'gr', '1850', 'noleap',
            id='Amon_ch4global_gr',
        ),
        pytest.param(
            f'{MOCK_ARCHIVE_ROOT}/{ESM4_DECK_PP_DIR}'
            '/LUmip_refined/ts/monthly/5yr/',
            'Emon', 'gppLut', 'gr1', '1850', 'noleap',
            id='Emon_gppLut_gr1',
        ),
        pytest.param(
            f'{MOCK_ARCHIVE_ROOT}/{ESM4_DECK_PP_DIR}'
            '/atmos_level_cmip/ts/monthly/5yr/',
            'Amon', 'cl', 'gr1', '1850', 'noleap',
            id='Amon_cl_gr1',
        ),
        pytest.param(
            f'{MOCK_ARCHIVE_ROOT}/{ESM4_DECK_PP_DIR}'
            '/atmos_level_cmip/ts/monthly/5yr/',
            'Amon', 'mc', 'gr1', '1850', 'noleap',
            id='Amon_mc_gr1',
        ),
        pytest.param(
            f'{MOCK_ARCHIVE_ROOT}/{ESM4_DEV_PP_DIR}'
            '/ocean_monthly_z_1x1deg/ts/monthly/5yr/',
            'Omon', 'so', 'gr', '0001', 'noleap',
            id='Omon_so_gr',
        ),
        pytest.param(
            f'{MOCK_ARCHIVE_ROOT}/{ESM4_DEV_PP_DIR}'
            '/ocean_monthly/ts/monthly/5yr/',
            'Omon', 'sos', 'gn', '0001', 'noleap',
            id='Omon_sos_gn',
        ),
        pytest.param(
            f'{MOCK_ARCHIVE_ROOT}/{ESM4_DEV_PP_DIR}'
            '/land/ts/monthly/5yr/',
            'Lmon', 'lai', 'gr1', '0001', 'noleap',
            id='Lmon_lai_gr1',
        ),
    ],
)
def test_case_cmip6(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    testfile_dir, table, opt_var_name, grid_label, start, calendar,
    tmp_path, monkeypatch,
):
    '''Run cmor_run_subtool for a single CMIP6 variable and assert output exists.'''
    # native-grid ocean tests: prevent gold statics lookup from finding /archive files
    if grid_label == 'gn':
        monkeypatch.setattr(
            'fremor.cmor_helpers.find_gold_ocean_statics_file',
            lambda **kw: None,
        )

    input_nc = _ncgen_for_case(testfile_dir, opt_var_name, ncgen)

    table_file = f'{CMIP6_TABLE_REPO_PATH}/Tables/CMIP6_{table}.json'
    outdir = str(tmp_path / 'outdir')

    cmor_run_subtool(
        indir=testfile_dir,
        json_var_list=CMORBITE_VARLIST,
        json_table_config=table_file,
        json_exp_config=EXP_CONFIG_CMIP6,
        outdir=outdir,
        run_one_mode=True,
        opt_var_name=opt_var_name,
        grid='FOO_PLACEHOLDER',
        grid_label=grid_label,
        nom_res='10000 km',
        start=start,
        calendar_type=calendar,
    )

    output_grid_label = OUTPUT_GRID_LABELS.get((table, opt_var_name), grid_label)
    cmor_output_dir = (
        f'{outdir}/{CMOR_CREATES_DIR_BASE_CMIP6}'
        f'/{table}/{opt_var_name}/{output_grid_label}/v{YYYYMMDD}'
    )
    cmor_output_glob = (
        f'{cmor_output_dir}/{opt_var_name}_{table}_PCMDI-test-1-0'
        f'_piControl-withism_r3i1p1f1_{output_grid_label}_??????-??????.nc'
    )
    cmor_output_file = find_cmor_output(cmor_output_glob)
    assert_cmor_output_matches_input(
        input_nc, cmor_output_file, opt_var_name, opt_var_name
    )
