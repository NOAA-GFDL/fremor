"""
CMIP7-flavored tests for fremor.cmor_run_subtool

Each test mirrors a corresponding CMIP6 test in test_cmor_run_subtool.py but
targets the CMIP7 experiment-configuration JSON and CMIP7-format CMOR tables.
"""

from datetime import date
from pathlib import Path
import subprocess
import shutil

import netCDF4
import numpy as np
import pytest

from fremor import cmor_run_subtool


# where are we? we're running pytest from the base directory of this repo
ROOTDIR = 'fremor/tests/test_files'

# setup- cmip/cmor variable table(s)
CMIP7_TABLE_REPO_PATH = \
    f'{ROOTDIR}/cmip7-cmor-tables'
TABLE_CONFIG = \
    f'{CMIP7_TABLE_REPO_PATH}/tables/CMIP7_ocean.json'

# explicit inputs to tool
GRID = 'regridded to FOO grid from native' #placeholder value
GRID_LABEL = 'g999'
NOM_RES = '10000 km' #placeholder value

INDIR = f'{ROOTDIR}/ocean_sos_var_file'
VARLIST = f'{ROOTDIR}/varlist'
CMIP7_EXP_CONFIG = f'{ROOTDIR}/CMOR_CMIP7_input_example.json'
OUTDIR = f'{ROOTDIR}/outdir'
TMPDIR = f'{OUTDIR}/tmp'

# input file details. if calendar matches data, the dates should be preserved or equiv.
DATETIMES_INPUTFILE='199301-199302'
FILENAME = f'reduced_ocean_monthly_1x1deg.{DATETIMES_INPUTFILE}.sos'
FULL_INPUTFILE=f'{INDIR}/{FILENAME}.nc'
CALENDAR_TYPE = 'julian'

# determined by cmor_run_subtool
YYYYMMDD = date.today().strftime('%Y%m%d')

# CMIP7 output path follows output_path_template:
# <activity_id><source_id><experiment_id><member_id><variable_id><branding_suffix><grid_label>
CMOR_CREATES_DIR = \
    f'CMIP/DUMMY-MODEL/historical/r3i1p1f3/sos/tavg-u-hxy-sea/{GRID_LABEL}'
FULL_OUTPUTDIR = \
    f'{OUTDIR}/{CMOR_CREATES_DIR}'
FULL_OUTPUTFILE = \
    f'{FULL_OUTPUTDIR}/sos_tavg-u-hxy-sea_mon_glb_{GRID_LABEL}_DUMMY-MODEL_historical_r3i1p1f3_{DATETIMES_INPUTFILE}.nc'

# CMIP7-required global attributes that must be present in CMOR output
# note: CMIP7 uses 'table_info' instead of 'table_id'
CMIP7_REQUIRED_GLOBAL_ATTRS = [
    'variable_id', 'mip_era', 'table_info',
    'experiment_id', 'institution_id', 'source_id'
]


def _assert_data_matches(ds_in, ds_out, in_var_name='sos'):
    """
    helper: assert that science variable data, coordinate data, and shapes
    are preserved between input and CMOR output datasets.
    """
    # the science variable data must be preserved exactly
    assert np.array_equal(ds_in.variables[in_var_name][:], ds_out.variables['sos'][:]), \
        'sos data values differ between input and CMOR output'

    # coordinate data must be preserved
    assert np.allclose(ds_in.variables['lat'][:], ds_out.variables['lat'][:]), \
        'latitude data differs between input and CMOR output'
    assert np.allclose(ds_in.variables['lon'][:], ds_out.variables['lon'][:]), \
        'longitude data differs between input and CMOR output'
    assert np.allclose(ds_in.variables['time'][:], ds_out.variables['time'][:]), \
        'time data differs between input and CMOR output'

    # variable shapes must be preserved
    assert ds_in.variables[in_var_name][:].shape == ds_out.variables['sos'][:].shape, \
        'sos data shape differs between input and CMOR output'


def _assert_metadata_matches(ds_in, ds_out, in_var_name='sos'):
    """
    helper: assert that CMIP7-required global attributes are present and that
    key variable-level metadata is preserved between input and CMOR output datasets.
    """
    # CMOR output must contain CMIP7-required global attributes
    for required_attr in CMIP7_REQUIRED_GLOBAL_ATTRS:
        assert required_attr in ds_out.ncattrs(), \
            f'CMOR output missing required global attribute {required_attr}'

    # CMIP7 uses 'table_info' instead of 'table_id'
    assert 'table_info' in ds_out.ncattrs(), \
        'CMOR output missing table_info attribute (CMIP7-specific)'
    assert 'table_id' not in ds_out.ncattrs(), \
        'CMOR output should not have table_id for CMIP7 (uses table_info instead)'

    # science variable standard_name and long_name must be preserved
    assert ds_in.variables[in_var_name].standard_name == ds_out.variables['sos'].standard_name, \
        'sos standard_name differs between input and CMOR output'
    assert ds_in.variables[in_var_name].long_name == ds_out.variables['sos'].long_name, \
        'sos long_name differs between input and CMOR output'

    # _FillValue and missing_value must be preserved
    assert ds_in.variables[in_var_name]._FillValue == ds_out.variables['sos']._FillValue, \
        'sos _FillValue differs between input and CMOR output' # pylint: disable=protected-access
    assert ds_in.variables[in_var_name].missing_value == ds_out.variables['sos'].missing_value, \
        'sos missing_value differs between input and CMOR output'


# ---------------------------------------------------------------------------
# CMIP7 table repo setup
# ---------------------------------------------------------------------------
def test_setup_cmip7_cmor_table_repo():
    """
    setup routine, make sure the recursively cloned CMIP7 tables exist
    """
    assert all( [ Path(CMIP7_TABLE_REPO_PATH).exists(),
                  Path(TABLE_CONFIG).exists()
                  ] )


# ---------------------------------------------------------------------------
# CMIP7 case 1: basic CMORization run
# ---------------------------------------------------------------------------
def test_setup_fre_cmor_run_subtool_cmip7(capfd):
    """
    The routine generates a netCDF file from an ascii (cdl) file. It also checks for a ncgen
    output file from prev pytest runs, removes it if it's present, and ensures the new file is
    created without error. (CMIP7 version)
    """
    ncgen_input = f'{ROOTDIR}/reduced_ascii_files/{FILENAME}.cdl'
    ncgen_output = f'{ROOTDIR}/ocean_sos_var_file/{FILENAME}.nc'

    Path(ncgen_output).parent.mkdir(parents=True, exist_ok=True)
    if Path(ncgen_output).exists():
        Path(ncgen_output).unlink()
    assert Path(ncgen_input).exists()

    ex = [ 'ncgen3', '-k', 'netCDF-4', '-o', ncgen_output, ncgen_input ]

    sp = subprocess.run(ex, check = True)

    assert all( [ sp.returncode == 0, Path(ncgen_output).exists() ] )
    _out, _err = capfd.readouterr()

def test_fre_cmor_run_subtool_cmip7_case1(capfd):
    """
    fre cmor run, CMIP7 test-use case
    """

    cmor_run_subtool(
        indir = INDIR,
        json_var_list = VARLIST,
        json_table_config = TABLE_CONFIG,
        json_exp_config = CMIP7_EXP_CONFIG,
        outdir = OUTDIR,
        run_one_mode = True,
        grid_label = GRID_LABEL,
        grid = GRID,
        nom_res = NOM_RES,
        calendar_type = CALENDAR_TYPE
    )

    assert all( [ Path(FULL_OUTPUTFILE).exists(),
                  Path(FULL_INPUTFILE).exists() ] )
    _out, _err = capfd.readouterr()

def test_fre_cmor_run_subtool_cmip7_case1_output_compare_data(capfd):
    """
    I/O data-only comparison of CMIP7 test case1
    """
    print(f'FULL_OUTPUTFILE={FULL_OUTPUTFILE}')
    print(f'FULL_INPUTFILE={FULL_INPUTFILE}')

    with netCDF4.Dataset(FULL_INPUTFILE) as ds_in, \
         netCDF4.Dataset(FULL_OUTPUTFILE) as ds_out:
        # file formats should differ: CMOR converts input to NETCDF4_CLASSIC
        assert ds_in.file_format != ds_out.file_format, \
            f'expected file formats to differ, got input={ds_in.file_format}, output={ds_out.file_format}'

        _assert_data_matches(ds_in, ds_out)
    _out, _err = capfd.readouterr()

def test_fre_cmor_run_subtool_cmip7_case1_output_compare_metadata(capfd):
    """
    I/O metadata-only comparison of CMIP7 test case1
    """
    print(f'FULL_OUTPUTFILE={FULL_OUTPUTFILE}')
    print(f'FULL_INPUTFILE={FULL_INPUTFILE}')

    with netCDF4.Dataset(FULL_INPUTFILE) as ds_in, \
         netCDF4.Dataset(FULL_OUTPUTFILE) as ds_out:
        # CMOR processing should add/change global attributes
        assert set(ds_in.ncattrs()) != set(ds_out.ncattrs()), \
            'expected global attributes to differ between input and CMOR output'

        _assert_metadata_matches(ds_in, ds_out)
    _out, _err = capfd.readouterr()


# ---------------------------------------------------------------------------
# CMIP7 case 2: differing local vs target variable names
# ---------------------------------------------------------------------------
FILENAME_DIFF = \
    f'reduced_ocean_monthly_1x1deg.{DATETIMES_INPUTFILE}.sosV2.nc'
FULL_INPUTFILE_DIFF = \
    f'{INDIR}/{FILENAME_DIFF}'
VARLIST_DIFF = \
    f'{ROOTDIR}/varlist_local_target_vars_differ'

def test_setup_fre_cmor_run_subtool_cmip7_case2(capfd):
    """
    make a copy of the input file to the slightly different name.
    checks for outputfile from prev pytest runs, removes it if it's present.
    this routine also checks to make sure the desired input file is present (CMIP7 version)
    """

    if Path(OUTDIR).exists():
        try:
            shutil.rmtree(OUTDIR)
        except OSError as exc:
            print(f'WARNING: OUTDIR={OUTDIR} could not be removed: {exc}')

    # make a copy of the usual test file, always recreating so the variable rename is fresh.
    if Path(FULL_INPUTFILE_DIFF).exists():
        Path(FULL_INPUTFILE_DIFF).unlink()
    # copy and rename the variable inside from 'sos' to 'sosV2' using netCDF4,
    # so that local_var='sosV2' matches the variable name in the file per new semantics.
    with netCDF4.Dataset(str(FULL_INPUTFILE), 'r') as src, \
         netCDF4.Dataset(str(FULL_INPUTFILE_DIFF), 'w') as dst:
        for name, dim in src.dimensions.items():
            dst.createDimension(name, None if dim.isunlimited() else len(dim))
        for name, var in src.variables.items():
            out_name = 'sosV2' if name == 'sos' else name
            out_var = dst.createVariable(out_name, var.datatype, var.dimensions)
            out_var.setncatts({k: var.getncattr(k) for k in var.ncattrs()})
            out_var[:] = var[:]
        dst.setncatts({k: src.getncattr(k) for k in src.ncattrs()})
    assert Path(FULL_INPUTFILE_DIFF).exists()
    _out, _err = capfd.readouterr()

def test_fre_cmor_run_subtool_cmip7_case2(capfd):
    """
    fre cmor run, CMIP7 test-use case2
    """

    cmor_run_subtool(
        indir = INDIR,
        json_var_list = VARLIST_DIFF,
        json_table_config = TABLE_CONFIG,
        json_exp_config = CMIP7_EXP_CONFIG,
        outdir = OUTDIR,
        run_one_mode = True,
        grid_label = GRID_LABEL,
        grid = GRID,
        nom_res = NOM_RES,
        calendar_type = CALENDAR_TYPE
    )

    # check we ran on the right input file and output was created.
    assert all( [ Path(FULL_OUTPUTFILE).exists(),
                  Path(FULL_INPUTFILE_DIFF).exists() ] )
    _out, _err = capfd.readouterr()

def test_fre_cmor_run_subtool_cmip7_case2_output_compare_data(capfd):
    """
    I/O data-only comparison of CMIP7 test case2
    """
    print(f'FULL_OUTPUTFILE={FULL_OUTPUTFILE}')
    print(f'FULL_INPUTFILE_DIFF={FULL_INPUTFILE_DIFF}')

    with netCDF4.Dataset(FULL_INPUTFILE_DIFF) as ds_in, \
         netCDF4.Dataset(FULL_OUTPUTFILE) as ds_out:
        # file formats should differ: CMOR converts input to NETCDF4_CLASSIC
        assert ds_in.file_format != ds_out.file_format, \
            f'expected file formats to differ, got input={ds_in.file_format}, output={ds_out.file_format}'

        _assert_data_matches(ds_in, ds_out, in_var_name='sosV2')
    _out, _err = capfd.readouterr()

def test_fre_cmor_run_subtool_cmip7_case2_output_compare_metadata(capfd):
    """
    I/O metadata-only comparison of CMIP7 test case2
    """
    print(f'FULL_OUTPUTFILE={FULL_OUTPUTFILE}')
    print(f'FULL_INPUTFILE_DIFF={FULL_INPUTFILE_DIFF}')

    with netCDF4.Dataset(FULL_INPUTFILE_DIFF) as ds_in, \
         netCDF4.Dataset(FULL_OUTPUTFILE) as ds_out:
        # CMOR processing should add/change global attributes
        assert set(ds_in.ncattrs()) != set(ds_out.ncattrs()), \
            'expected global attributes to differ between input and CMOR output'

        _assert_metadata_matches(ds_in, ds_out, in_var_name='sosV2')
    _out, _err = capfd.readouterr()


# ---------------------------------------------------------------------------
# CMIP7 error handling tests
# ---------------------------------------------------------------------------
def test_cmor_run_subtool_cmip7_raise_value_error():
    """
    test that ValueError raised when required args are absent (CMIP7 version)
    """
    with pytest.raises(ValueError):
        cmor_run_subtool( indir = None,
                          json_var_list = None,
                          json_table_config = None,
                          json_exp_config = None,
                          outdir = None )

def test_fre_cmor_run_subtool_cmip7_no_exp_config():
    """
    fre cmor run, exception, json_exp_config DNE (CMIP7 version)
    """

    with pytest.raises(FileNotFoundError):
        cmor_run_subtool(
            indir = INDIR,
            json_var_list = VARLIST_DIFF,
            json_table_config = TABLE_CONFIG,
            json_exp_config = 'DOES NOT EXIST',
            outdir = OUTDIR
        )

def test_fre_cmor_run_subtool_cmip7_empty_varlist():
    """
    fre cmor run, exception, variable list is empty (CMIP7 version)
    """
    varlist_empty = f'{ROOTDIR}/empty_varlist'

    with pytest.raises(ValueError):
        cmor_run_subtool(
            indir = INDIR,
            json_var_list = varlist_empty,
            json_table_config = TABLE_CONFIG,
            json_exp_config = CMIP7_EXP_CONFIG,
            outdir = OUTDIR
        )

def test_fre_cmor_run_subtool_cmip7_opt_var_name_not_in_table():
    """
    fre cmor run, exception, opt_var_name not in CMIP7 table
    """

    with pytest.raises(ValueError):
        cmor_run_subtool(
            indir = INDIR,
            json_var_list = VARLIST,
            json_table_config = TABLE_CONFIG,
            json_exp_config = CMIP7_EXP_CONFIG,
            outdir = OUTDIR,
            opt_var_name='zzzz_nonexistent_var'
        )
