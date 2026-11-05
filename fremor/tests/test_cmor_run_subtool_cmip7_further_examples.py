"""
Expanded set of CMIP7 tests for fremor run — cases beyond test_cmor_run_subtool_cmip7.py.

These tests exercise cmor_run_subtool against a variety of variables, tables,
and grid labels drawn from a mock pp-archive, targeting CMIP7 experiment
configuration and CMIP7-format CMOR tables.

.. tip:: pytest temp directories
   By default pytest removes temp directories after the session. To keep
   them around for debugging, run::

       pytest --basetemp=/tmp/fremor-debug -k test_case_cmip7 -x

   Output files will then persist under ``/tmp/fremor-debug``.
"""

from datetime import date
import json

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

# cmip7 table repo
CMIP7_TABLE_REPO_PATH = f'{ROOTDIR}/cmip7-cmor-tables'

# experiment config (materialized by conftest._write_exp_configs)
EXP_CONFIG_CMIP7 = f'{ROOTDIR}/CMOR_CMIP7_input_example.json'

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

# CMIP7 output dir structure
# (activity_id/source_id/experiment_id/member_id/variable_id/branding_suffix/grid_label)
CMOR_CREATES_DIR_BASE_CMIP7 = (
    'CMIP/GFDL-ESM4p5/historical/r3i1p1f3'
)


# ── CMIP7 parametrized tests ──────────────────────────────────────────────
@pytest.mark.parametrize(
    'testfile_dir,table,opt_var_name,grid_label,start,calendar',
    [
        pytest.param(
            f'{MOCK_ARCHIVE_ROOT}/{ESM4_DECK_PP_DIR}'
            '/atmos_plev39_cmip/ts/monthly/5yr/zonavg/',
            'CMIP7_atmos', 'ta', 'g010', '1850', 'noleap',
            id='atmos_ta_g010',
        ),
        pytest.param(
            f'{MOCK_ARCHIVE_ROOT}/{ESM4_DECK_PP_DIR}'
            '/atmos_scalar/ts/monthly/5yr/',
            'CMIP7_atmosChem', 'ch4global', 'g010', '1850', 'noleap',
            id='atmosChem_ch4global_g010',
        ),
        pytest.param(
            f'{MOCK_ARCHIVE_ROOT}/{ESM4_DECK_PP_DIR}'
            '/LUmip_refined/ts/monthly/5yr/',
            'CMIP7_land', 'gppLut', 'g010', '1850', 'noleap',
            id='land_gppLut_g010',
        ),
        pytest.param(
            f'{MOCK_ARCHIVE_ROOT}/{ESM4_DECK_PP_DIR}'
            '/atmos_level_cmip/ts/monthly/5yr/',
            'CMIP7_atmos', 'cl', 'g010', '1850', 'noleap',
            id='atmos_cl_g010',
        ),
        pytest.param(
            f'{MOCK_ARCHIVE_ROOT}/{ESM4_DECK_PP_DIR}'
            '/atmos_level_cmip/ts/monthly/5yr/',
            'CMIP7_atmos', 'mc', 'g010', '1850', 'noleap',
            id='atmos_mc_g010',
        ),
        pytest.param(
            f'{MOCK_ARCHIVE_ROOT}/{ESM4_DEV_PP_DIR}'
            '/ocean_monthly_z_1x1deg/ts/monthly/5yr/',
            'CMIP7_ocean', 'so', 'g010', '0001', 'noleap',
            id='ocean_so_g010',
        ),
        pytest.param(
            f'{MOCK_ARCHIVE_ROOT}/{ESM4_DEV_PP_DIR}'
            '/ocean_monthly/ts/monthly/5yr/',
            'CMIP7_ocean', 'sos', 'g010', '0001', 'noleap',
            id='ocean_sos_g010',
        ),
        pytest.param(
            f'{MOCK_ARCHIVE_ROOT}/{ESM4_DEV_PP_DIR}'
            '/land/ts/monthly/5yr/',
            'CMIP7_land', 'lai', 'g010', '0001', 'noleap',
            id='land_lai_g010',
        ),
        pytest.param(
            f'{MOCK_ARCHIVE_ROOT}/{ESM4_DEV_PP_DIR}'
            '/atmos_cmip/ts/monthly/5yr/',
            'CMIP7_atmos', 'tas', 'g010', '0001', 'noleap',
            id='atmos_tas_g010',
        ),
    ],
)
def test_case_cmip7(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    testfile_dir, table, opt_var_name, grid_label, start, calendar,
    tmp_path,
):
    """
    Run cmor_run_subtool for a single CMIP7 variable and assert output exists.
    """
    target_var_name = opt_var_name
    varlist = CMORBITE_VARLIST
    if opt_var_name == 'ch4global':
        # CMIP7 names the global-mean methane target `ch4`; use the local
        # variable name as the varlist key and let the table select its brand.
        target_var_name = 'ch4'
        varlist = tmp_path / 'ch4global_varlist.json'
        varlist.write_text(
            json.dumps({opt_var_name: target_var_name}),
            encoding='utf-8',
        )

    input_nc = _ncgen_for_case(testfile_dir, opt_var_name, ncgen)

    table_file = f'{CMIP7_TABLE_REPO_PATH}/tables/{table}.json'
    outdir = str(tmp_path / 'outdir')

    cmor_run_subtool(
        indir=testfile_dir,
        json_var_list=str(varlist),
        json_table_config=table_file,
        json_exp_config=EXP_CONFIG_CMIP7,
        outdir=outdir,
        run_one_mode=True,
        opt_var_name=None if opt_var_name == 'ch4global' else opt_var_name,
        grid='FOO_PLACEHOLDER',
        grid_label=grid_label,
        nom_res='100 km',
        start=start,
        calendar_type=calendar,
    )

    # Use recursive glob to find output regardless of branding suffix via output_path_template
    cmor_output_glob = (
        f'{outdir}/{CMOR_CREATES_DIR_BASE_CMIP7}'
        f'/{target_var_name}/**/*{target_var_name}*{grid_label}*.nc'
    )
    cmor_output_file = find_cmor_output(cmor_output_glob)
    assert_cmor_output_matches_input(
        input_nc,
        cmor_output_file,
        opt_var_name,
        target_var_name,
        expected_standard_name=(
            'mole_fraction_of_methane_in_air'
            if opt_var_name == 'ch4global'
            else None
        ),
    )
