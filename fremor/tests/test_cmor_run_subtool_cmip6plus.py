"""
CMIP6Plus tests for fremor run — CMORizing ``tas`` with a scalar ``height`` coordinate.

This test exercises cmor_run_subtool against the ``tas`` variable whose input
file includes a scalar (0-dimensional) ``height`` coordinate variable, targeting
CMIP6Plus experiment configuration and a CMIP6-format CMOR table (CMIP6Plus is
currently treated as CMIP6 by fremor).

.. tip:: pytest temp directories
   By default pytest removes temp directories after the session. To keep
   them around for debugging, run::

       pytest --basetemp=/tmp/fremor-debug -k test_case_cmip6plus -x

   Output files will then persist under ``/tmp/fremor-debug``.
"""

from datetime import date
import glob
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from netCDF4 import Dataset

from fremor import cmor_run_subtool
from fremor.tests.conftest import _CMIP6_EXP_CONFIG_DATA


# ── path constants ──────────────────────────────────────────────────────────
ROOTDIR = 'fremor/tests/test_files'
VARLIST_TAS = f'{ROOTDIR}/varlist_tas'

# cmip6 table (CMIP6Plus uses CMIP6 tables)
CMIP6_TABLE_CONFIG = f'{ROOTDIR}/cmip6-cmor-tables/Tables/CMIP6_Amon.json'

# determined by cmor_run_subtool
YYYYMMDD = date.today().strftime('%Y%m%d')

# input data directory
INDIR = f'{ROOTDIR}/cmip6plus_tas_var_file'


# ── helper: convert CDL to NC ──────────────────────────────────────────────
def _ncgen_tas(testfile_dir, tmp_dir):
    """Convert the tas CDL file to NetCDF-4 inside *tmp_dir*."""
    cdl_files = glob.glob(f'{testfile_dir}/*.tas.cdl')
    assert len(cdl_files) >= 1, (
        f'no CDL file found for variable tas in {testfile_dir}'
    )
    cdl_file = cdl_files[0]
    nc_name = Path(cdl_file).name.replace('.cdl', '.nc')
    nc_file = str(tmp_dir / nc_name)
    subprocess.run(
        ['ncgen3', '-k', 'netCDF-4', '-o', nc_file, cdl_file],
        check=True,
    )
    assert Path(nc_file).exists(), f'ncgen3 failed to create {nc_file}'
    return nc_file


# ── CMIP6Plus tas test ─────────────────────────────────────────────────────
def test_case_cmip6plus_tas(tmp_path):
    """
    Run cmor_run_subtool for CMIP6Plus ``tas`` (with scalar ``height``)
    and assert output exists with correct dtype.

    CMIP6Plus is currently treated as CMIP6 by fremor, so this test uses a
    CMIP6 experiment config that mirrors the second metadata header (julian
    calendar, 1980-1984 date range) from the problem statement.
    """
    # write a CMIP6 exp config with julian calendar for this test
    exp_cfg_path = tmp_path / 'CMOR_cmip6plus_input.json'
    exp_cfg = dict(_CMIP6_EXP_CONFIG_DATA)
    exp_cfg['calendar'] = 'julian'
    exp_cfg_path.write_text(json.dumps(exp_cfg, indent=4))

    input_nc = _ncgen_tas(INDIR, tmp_path)
    outdir = str(tmp_path / 'outdir')

    # copy input NC to indir so cmor_run_subtool can find it
    indir = str(tmp_path / 'indir')
    Path(indir).mkdir()
    shutil.copy2(input_nc, indir)

    cmor_run_subtool(
        indir=indir,
        json_var_list=VARLIST_TAS,
        json_table_config=CMIP6_TABLE_CONFIG,
        json_exp_config=str(exp_cfg_path),
        outdir=outdir,
        run_one_mode=True,
        opt_var_name='tas',
        grid='FOO_PLACEHOLDER',
        grid_label='gr',
        nom_res='10000 km',
        start='1980',
        calendar_type='julian',
    )

    # find the CMOR output file
    cmor_output_glob = f'{outdir}/**/*tas*gr*.nc'
    cmor_output_files = glob.glob(cmor_output_glob, recursive=True)
    assert len(cmor_output_files) >= 1, (
        f'no CMOR output found matching {cmor_output_glob}'
    )
    assert Path(cmor_output_files[0]).exists()

    # dtype must be preserved between input and CMOR output
    with Dataset(input_nc) as ds_in, Dataset(cmor_output_files[0]) as ds_out:
        in_dtype = ds_in.variables['tas'][:].dtype
        out_dtype = ds_out.variables['tas'][:].dtype
        assert in_dtype == out_dtype, (
            f'tas input dtype {in_dtype} differs from CMOR output dtype {out_dtype}'
        )
