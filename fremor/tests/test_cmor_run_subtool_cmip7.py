"""
CMIP7-flavored tests for fremor.cmor_run_subtool

Each test mirrors a corresponding CMIP6 test in test_cmor_run_subtool.py but
targets the CMIP7 experiment-configuration JSON and CMIP7-format CMOR tables.
"""

from datetime import date, datetime
import json
from pathlib import Path
import subprocess
import shutil

import netCDF4
import numpy as np
import pytest

from fremor import cmor_mixer, cmor_run_subtool


# where are we? we're running pytest from the base directory of this repo
ROOTDIR = 'fremor/tests/test_files'

# setup- cmip/cmor variable table(s)
CMIP7_TABLE_REPO_PATH = \
    f'{ROOTDIR}/cmip7-cmor-tables'
TABLE_CONFIG = \
    f'{CMIP7_TABLE_REPO_PATH}/tables/CMIP7_ocean.json'

# explicit inputs to tool
GRID = 'regridded to FOO grid from native' #placeholder value
GRID_LABEL = 'g010'
NOM_RES = '100 km' #placeholder value

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
    f'CMIP/GFDL-ESM4p5/historical/r3i1p1f3/sos/tavg-u-hxy-sea/{GRID_LABEL}'
FULL_OUTPUTDIR = \
    f'{OUTDIR}/{CMOR_CREATES_DIR}'
FULL_OUTPUTFILE = \
    f'{FULL_OUTPUTDIR}/sos_tavg-u-hxy-sea_mon_glb_{GRID_LABEL}_GFDL-ESM4p5_historical_r3i1p1f3_{DATETIMES_INPUTFILE}.nc'

# CMIP7-required global attributes that must be present in CMOR output
# note: CMIP7 uses 'table_info' instead of 'table_id'
CMIP7_REQUIRED_GLOBAL_ATTRS = [
    'variable_id', 'mip_era', 'table_info',
    'experiment_id', 'institution_id', 'source_id'
]


def _assert_dtypes_match(ds_in, ds_out, in_var_name, out_var_name):
    """
    helper: assert that the science variable dtype is preserved between
    the input netCDF file and the CMORized output file.
    """
    in_dtype = ds_in.variables[in_var_name][:].dtype
    out_dtype = ds_out.variables[out_var_name][:].dtype
    assert in_dtype == out_dtype, (
        f'{in_var_name} input dtype {in_dtype} differs from '
        f'{out_var_name} CMOR output dtype {out_dtype}'
    )


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

    # dtype must be preserved through CMORization
    _assert_dtypes_match(ds_in, ds_out, in_var_name, 'sos')


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


def test_fre_cmor_run_subtool_cmip7_opt_var_name_selects_varlist_mapping(
        tmp_path, monkeypatch):
    """Selecting a local variable preserves its mapped CMIP7 target and excludes other entries."""
    varlist = tmp_path / 'varlist.json'
    varlist.write_text('{"LWP": "sos", "other": "sos"}', encoding='utf-8')
    captured = {}

    def capture_vars_to_run(vars_to_run, *_args, **_kwargs):
        captured['vars_to_run'] = vars_to_run
        return 0

    monkeypatch.setattr(cmor_mixer, 'cmorize_all_variables_in_dir', capture_vars_to_run)

    result = cmor_run_subtool(
        indir=INDIR,
        json_var_list=str(varlist),
        json_table_config=TABLE_CONFIG,
        json_exp_config=CMIP7_EXP_CONFIG,
        outdir=str(tmp_path / 'outdir'),
        opt_var_name='LWP',
    )

    assert result == 0
    assert captured['vars_to_run'] == {'LWP': 'sos'}


def test_fre_cmor_run_subtool_cmip7_scalar_wavelength_dimension(tmp_path):
    """A fixed wavelength in the input comment supplies the table's scalar lambda axis."""
    indir = tmp_path / 'indir'
    indir.mkdir()
    input_file = indir / 'aerosol.186901-186912.od550dust.nc'
    units = 'days since 1850-01-01 00:00:00'
    bounds = []
    midpoints = []
    for month in range(1, 13):
        start = datetime(1869, month, 1)
        stop = datetime(1870, 1, 1) if month == 12 else datetime(1869, month + 1, 1)
        bounds.append((start, stop))
        midpoints.append(start + (stop - start) / 2)

    with netCDF4.Dataset(input_file, 'w') as ds:
        ds.createDimension('time', 12)
        ds.createDimension('lat', 2)
        ds.createDimension('lon', 2)
        ds.createDimension('bnds', 2)

        lat = ds.createVariable('lat', 'f8', ('lat',))
        lat.axis = 'Y'
        lat.units = 'degrees_N'
        lat.bounds = 'lat_bnds'
        lat[:] = [-45.0, 45.0]
        lat_bnds = ds.createVariable('lat_bnds', 'f8', ('lat', 'bnds'))
        lat_bnds[:] = [[-90.0, 0.0], [0.0, 90.0]]

        lon = ds.createVariable('lon', 'f8', ('lon',))
        lon.axis = 'X'
        lon.units = 'degrees_E'
        lon.bounds = 'lon_bnds'
        lon[:] = [90.0, 270.0]
        lon_bnds = ds.createVariable('lon_bnds', 'f8', ('lon', 'bnds'))
        lon_bnds[:] = [[0.0, 180.0], [180.0, 360.0]]

        time = ds.createVariable('time', 'f8', ('time',))
        time.axis = 'T'
        time.units = units
        time.calendar = 'julian'
        time.bounds = 'time_bnds'
        time[:] = netCDF4.date2num(midpoints, units, calendar='julian')
        time_bnds = ds.createVariable('time_bnds', 'f8', ('time', 'bnds'))
        time_bnds[:] = netCDF4.date2num(bounds, units, calendar='julian')

        aerosol = ds.createVariable('od550dust', 'f4', ('time', 'lat', 'lon'),
                                    fill_value=1.0e20)
        aerosol.long_name = 'Dust aod at 550nm'
        aerosol.units = '1'
        aerosol.missing_value = np.float32(1.0e20)
        aerosol.comment = 'wavelength: 550 nm'
        aerosol.cell_methods = 'time: mean'
        aerosol.cell_measures = 'area: area'
        aerosol.standard_name = (
            'atmosphere_optical_thickness_due_to_dust_ambient_aerosol_particles'
        )
        aerosol[:] = 0.1
        ds.external_variables = 'area'

    varlist = tmp_path / 'varlist.json'
    varlist.write_text(json.dumps({'od550dust': 'od550dust'}), encoding='utf-8')
    outdir = tmp_path / 'outdir'

    result = cmor_run_subtool(
        indir=str(indir),
        json_var_list=str(varlist),
        json_table_config=f'{CMIP7_TABLE_REPO_PATH}/tables/CMIP7_aerosol.json',
        json_exp_config=CMIP7_EXP_CONFIG,
        outdir=str(outdir),
        run_one_mode=True,
        opt_var_name='od550dust',
        grid=GRID,
        grid_label=GRID_LABEL,
        nom_res=NOM_RES,
        start='1869',
        stop='1869',
        calendar_type=CALENDAR_TYPE,
    )

    assert result == 0
    outputs = [path for path in outdir.rglob('*.nc') if path.name.startswith('od550dust_')]
    assert len(outputs) == 1
    with netCDF4.Dataset(outputs[0]) as ds_out:
        assert 'wavelength' in ds_out.variables
        assert ds_out.variables['wavelength'].ndim == 0
        assert np.isclose(ds_out.variables['wavelength'].getValue(), 550.0)
        assert ds_out.variables['od550dust'].coordinates == 'wavelength'
