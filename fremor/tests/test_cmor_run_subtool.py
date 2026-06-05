"""
tests for fremor.cmor_run_subtool
"""

from datetime import date
import json
from pathlib import Path
import subprocess
import shutil

import netCDF4
import numpy as np
import pytest

from fremor import cmor_run_subtool
from fremor.tests.conftest import _CMIP6_EXP_CONFIG_DATA


# where are we? we're running pytest from the base directory of this repo
ROOTDIR = 'fremor/tests/test_files'

# setup- cmip/cmor variable table(s)
CMIP6_TABLE_REPO_PATH = \
    f'{ROOTDIR}/cmip6-cmor-tables'
TABLE_CONFIG = \
    f'{CMIP6_TABLE_REPO_PATH}/Tables/CMIP6_Omon.json'

def test_setup_cmor_cmip_table_repo():
    """
    setup routine, make sure the recursively cloned tables exist
    """
    assert all( [ Path(CMIP6_TABLE_REPO_PATH).exists(),
                  Path(TABLE_CONFIG).exists()
                  ] )

# explicit inputs to tool
GRID = 'regridded to FOO grid from native' #placeholder value
GRID_LABEL = 'gr'
NOM_RES = '10000 km' #placeholder value

INDIR = f'{ROOTDIR}/ocean_sos_var_file'
VARLIST = f'{ROOTDIR}/varlist'
EXP_CONFIG = f'{ROOTDIR}/CMOR_input_example.json'
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
CMOR_CREATES_DIR = \
    f'CMIP6/CMIP6/ISMIP6/PCMDI/PCMDI-test-1-0/piControl-withism/r3i1p1f1/Omon/sos/{GRID_LABEL}'
FULL_OUTPUTDIR = \
   f'{OUTDIR}/{CMOR_CREATES_DIR}/v{YYYYMMDD}'
FULL_OUTPUTFILE = \
f'{FULL_OUTPUTDIR}/sos_Omon_PCMDI-test-1-0_piControl-withism_r3i1p1f1_{GRID_LABEL}_{DATETIMES_INPUTFILE}.nc'

# CMIP6-required global attributes that must be present in CMOR output
CMIP6_REQUIRED_GLOBAL_ATTRS = [
    'variable_id', 'mip_era', 'table_id',
    'experiment_id', 'institution_id', 'source_id'
]


def _assert_data_matches(ds_in, ds_out):
    """
    helper: assert that science variable data, coordinate data, and shapes
    are preserved between input and CMOR output datasets.
    """
    # the science variable data must be preserved exactly
    assert np.array_equal(ds_in.variables['sos'][:], ds_out.variables['sos'][:]), \
        'sos data values differ between input and CMOR output'

    # coordinate data must be preserved
    assert np.allclose(ds_in.variables['lat'][:], ds_out.variables['lat'][:]), \
        'latitude data differs between input and CMOR output'
    assert np.allclose(ds_in.variables['lon'][:], ds_out.variables['lon'][:]), \
        'longitude data differs between input and CMOR output'
    assert np.allclose(ds_in.variables['time'][:], ds_out.variables['time'][:]), \
        'time data differs between input and CMOR output'

    # variable shapes must be preserved
    assert ds_in.variables['sos'][:].shape == ds_out.variables['sos'][:].shape, \
        'sos data shape differs between input and CMOR output'


def _assert_metadata_matches(ds_in, ds_out):
    """
    helper: assert that CMIP6-required global attributes are present and that
    key variable-level metadata is preserved between input and CMOR output datasets.
    """
    # CMOR output must contain CMIP6-required global attributes
    for required_attr in CMIP6_REQUIRED_GLOBAL_ATTRS:
        assert required_attr in ds_out.ncattrs(), \
            f'CMOR output missing required global attribute {required_attr}'

    # science variable standard_name and long_name must be preserved
    assert ds_in.variables['sos'].standard_name == ds_out.variables['sos'].standard_name, \
        'sos standard_name differs between input and CMOR output'
    assert ds_in.variables['sos'].long_name == ds_out.variables['sos'].long_name, \
        'sos long_name differs between input and CMOR output'

    # _FillValue and missing_value must be preserved
    assert ds_in.variables['sos']._FillValue == ds_out.variables['sos']._FillValue, \
        'sos _FillValue differs between input and CMOR output' # pylint: disable=protected-access
    assert ds_in.variables['sos'].missing_value == ds_out.variables['sos'].missing_value, \
        'sos missing_value differs between input and CMOR output'


def _write_fake_table(tmp_path, filename, mip_era):
    """
    helper: create a minimal MIP table JSON with a mip_era header for mismatch tests
    """
    table_path = tmp_path / filename
    table_path.write_text(json.dumps({
        'Header': {'mip_era': mip_era},
        'variable_entry': {'tas': {'dimensions': ['time']}}
    }))
    return table_path


def test_cmip6_exp_with_cmip7_table_raises(tmp_path):
    """
    ValueError with clear message when CMIP6 experiment uses a CMIP7-format table.
    """
    table_path = _write_fake_table(tmp_path, 'CMIP7_fake.json', 'CMIP7')
    indir = tmp_path / 'indir'
    outdir = tmp_path / 'outdir'
    indir.mkdir()
    outdir.mkdir()

    with pytest.raises(ValueError, match='mip_era mismatch'):
        cmor_run_subtool(
            indir=str(indir),
            json_var_list=VARLIST,
            json_table_config=str(table_path),
            json_exp_config=EXP_CONFIG,
            outdir=str(outdir),
        )


def test_cmip7_exp_with_cmip6_table_raises(tmp_path):
    """
    ValueError with clear message when CMIP7 experiment uses a CMIP6-format table.
    """
    table_path = _write_fake_table(tmp_path, 'CMIP6_fake.json', 'CMIP6')
    indir = tmp_path / 'indir'
    outdir = tmp_path / 'outdir'
    indir.mkdir()
    outdir.mkdir()

    with pytest.raises(ValueError, match='mip_era mismatch'):
        cmor_run_subtool(
            indir=str(indir),
            json_var_list=VARLIST,
            json_table_config=str(table_path),
            json_exp_config=CMIP7_EXP_CONFIG,
            outdir=str(outdir),
        )


def test_setup_fre_cmor_run_subtool(capfd):
    """
    The routine generates a netCDF file from an ascii (cdl) file. It also checks for a ncgen
    output file from prev pytest runs, removes it if it's present, and ensures the new file is
    created without error.
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

    if Path(FULL_OUTPUTFILE).exists():
        Path(FULL_OUTPUTFILE).unlink()

    assert not Path(FULL_OUTPUTFILE).exists()
    _out, _err = capfd.readouterr()

def test_fre_cmor_run_subtool_case1(capfd):
    """
    fre cmor run, test-use case
    """

    #import sys
    #assert False, f'{sys.path}'

    #debug
    #print(
    #    f'cmor_run_subtool('
    #    f'\'{INDIR}\','
    #    f'\'{VARLIST}\','
    #    f'\'{TABLE_CONFIG}\','
    #    f'\'{EXP_CONFIG}\','
    #    f'\'{OUTDIR}\''
    #    ')'
    #)

    # test call, where meat of the workload gets done
    cmor_run_subtool(
        indir = INDIR,
        json_var_list = VARLIST,
        json_table_config = TABLE_CONFIG,
        json_exp_config = EXP_CONFIG,
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

def test_fre_cmor_run_subtool_case1_output_compare_data(capfd):
    """
    I/O data-only comparison of test case1
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

def test_fre_cmor_run_subtool_case1_output_compare_metadata(capfd):
    """
    I/O metadata-only comparison of test case1
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


# case 2: error path (sosV2 filename but sos inside → mismatch)
FILENAME_DIFF = \
    f'reduced_ocean_monthly_1x1deg.{DATETIMES_INPUTFILE}.sosV2.nc'
FULL_INPUTFILE_DIFF = \
    f'{INDIR}/{FILENAME_DIFF}'
VARLIST_DIFF = \
    f'{ROOTDIR}/varlist_local_target_vars_differ'
def test_setup_fre_cmor_run_subtool_case2(capfd):
    """
    make a copy of the input file to the slightly different name.
    checks for outputfile from prev pytest runs, removes it if it's present.
    this routine also checks to make sure the desired input file is present
    """
    if Path(FULL_OUTPUTFILE).exists():
        Path(FULL_OUTPUTFILE).unlink()
    assert not Path(FULL_OUTPUTFILE).exists()

    if Path(OUTDIR+'/CMIP6').exists():
        shutil.rmtree(OUTDIR+'/CMIP6')
    assert not Path(OUTDIR+'/CMIP6').exists()


    # VERY ANNOYING !!! FYI WARNING TODO
    if Path(TMPDIR).exists():
        try:
            shutil.rmtree(TMPDIR)
        except OSError as exc:
            print(f'WARNING: TMPDIR={TMPDIR} could not be removed.')
            print( '         this does not matter that much, but is unfortunate.')
            print( '         suspicion: something the cmor module is using is not being closed')
            print(f'         exc = {exc}')

    #assert not Path(TMPDIR).exists()    # VERY ANNOYING !!! FYI WARNING TODO

    # VERY ANNOYING !!! FYI WARNING TODO
    if Path(OUTDIR).exists():
        try:
            shutil.rmtree(OUTDIR)
        except OSError as exc:
            print(f'WARNING: OUTDIR={OUTDIR} could not be removed.')
            print( '         this does not matter that much, but is unfortunate.')
            print( '         suspicion: something the cmor module is using is not being closed')
            print(f'         exc = {exc}')

    #assert not Path(OUTDIR).exists()    # VERY ANNOYING !!! FYI WARNING TODO

    # make a copy of the usual test file.
    if not Path(FULL_INPUTFILE_DIFF).exists():
        shutil.copy(
            Path(FULL_INPUTFILE),
            Path(FULL_INPUTFILE_DIFF) )
    assert Path(FULL_INPUTFILE_DIFF).exists()
    _out, _err = capfd.readouterr()

def test_fre_cmor_run_subtool_case2(capfd):
    """
    fre cmor run, test-use case2: filename variable != file variable should error.
    The sosV2 file has variable "sos" inside, but the varlist expects "sosV2" as the
    modeler variable name (in both the filename and inside the file). This mismatch
    should cause cmor_run_subtool to return a non-zero status.
    """


    # test call, where meat of the workload gets done
    result = cmor_run_subtool(
        indir = INDIR,
        json_var_list = VARLIST_DIFF,
        json_table_config = TABLE_CONFIG,
        json_exp_config = EXP_CONFIG,
        outdir = OUTDIR,
        run_one_mode = True,
        grid_label = GRID_LABEL,
        grid = GRID,
        nom_res = NOM_RES,
        calendar_type = CALENDAR_TYPE
    )
    assert result != 0, f'expected non-zero return status for filename/variable mismatch, got {result}'
    _out, _err = capfd.readouterr()


# case 3: mapped variable (sea_sfc_salinity → sos)
VARLIST_MAPPED = f'{ROOTDIR}/varlist_mapped'
FILENAME_MAPPED = f'reduced_ocean_monthly_1x1deg.{DATETIMES_INPUTFILE}.sea_sfc_salinity'
FULL_INPUTFILE_MAPPED = f"{INDIR}/{FILENAME_MAPPED}.nc"
def test_setup_fre_cmor_run_subtool_case3(capfd):
    """
    Generate the sea_sfc_salinity NetCDF file from CDL and clean up previous output.
    """
    if Path(FULL_OUTPUTFILE).exists():
        Path(FULL_OUTPUTFILE).unlink()
    assert not Path(FULL_OUTPUTFILE).exists()

    if Path(OUTDIR+'/CMIP6').exists():
        shutil.rmtree(OUTDIR+'/CMIP6')
    assert not Path(OUTDIR+'/CMIP6').exists()

    if Path(TMPDIR).exists():
        try:
            shutil.rmtree(TMPDIR)
        except OSError as exc:
            print(f'WARNING: TMPDIR={TMPDIR} could not be removed. exc = {exc}')

    if Path(OUTDIR).exists():
        try:
            shutil.rmtree(OUTDIR)
        except OSError as exc:
            print(f'WARNING: OUTDIR={OUTDIR} could not be removed. exc = {exc}')

    ncgen_input = f"{ROOTDIR}/reduced_ascii_files/{FILENAME_MAPPED}.cdl"
    ncgen_output = FULL_INPUTFILE_MAPPED

    Path(ncgen_output).parent.mkdir(parents=True, exist_ok=True)
    if Path(ncgen_output).exists():
        Path(ncgen_output).unlink()
    assert Path(ncgen_input).exists()

    ex = [ 'ncgen3', '-k', 'netCDF-4', '-o', ncgen_output, ncgen_input ]
    sp = subprocess.run(ex, check = True)
    assert all( [ sp.returncode == 0, Path(ncgen_output).exists() ] )
    _out, _err = capfd.readouterr()

def test_fre_cmor_run_subtool_case3(capfd):
    """
    fre cmor run, test-use case3: mapped variable sea_sfc_salinity → sos
    """

    cmor_run_subtool(
        indir = INDIR,
        json_var_list = VARLIST_MAPPED,
        json_table_config = TABLE_CONFIG,
        json_exp_config = EXP_CONFIG,
        outdir = OUTDIR,
        run_one_mode = True,
        grid_label = GRID_LABEL,
        grid = GRID,
        nom_res = NOM_RES,
        calendar_type = CALENDAR_TYPE
    )

    assert all( [ Path(FULL_OUTPUTFILE).exists(),
                  Path(FULL_INPUTFILE_MAPPED).exists() ] )
    _out, _err = capfd.readouterr()


def _assert_mapped_data_matches(ds_in, ds_out):
    """
    helper: assert that science variable data, coordinate data, and shapes
    are preserved between input (sea_sfc_salinity) and CMOR output (sos) datasets.
    """
    assert np.array_equal(ds_in.variables['sea_sfc_salinity'][:], ds_out.variables['sos'][:]), \
        'sea_sfc_salinity data values differ from sos in CMOR output'

    assert np.allclose(ds_in.variables['lat'][:], ds_out.variables['lat'][:]), \
        'latitude data differs between input and CMOR output'
    assert np.allclose(ds_in.variables['lon'][:], ds_out.variables['lon'][:]), \
        'longitude data differs between input and CMOR output'
    assert np.allclose(ds_in.variables['time'][:], ds_out.variables['time'][:]), \
        'time data differs between input and CMOR output'

    assert ds_in.variables['sea_sfc_salinity'][:].shape == ds_out.variables['sos'][:].shape, \
        'sea_sfc_salinity data shape differs from sos in CMOR output'


def _assert_mapped_metadata_matches(ds_in, ds_out):
    """
    helper: assert that CMIP6-required global attributes are present and that
    key variable-level metadata is preserved between input (sea_sfc_salinity)
    and CMOR output (sos) datasets.
    """
    for required_attr in CMIP6_REQUIRED_GLOBAL_ATTRS:
        assert required_attr in ds_out.ncattrs(), \
            f'CMOR output missing required global attribute {required_attr}'

    assert ds_in.variables['sea_sfc_salinity'].standard_name == ds_out.variables['sos'].standard_name, \
        'standard_name differs between input sea_sfc_salinity and CMOR output sos'
    assert ds_in.variables['sea_sfc_salinity'].long_name == ds_out.variables['sos'].long_name, \
        'long_name differs between input sea_sfc_salinity and CMOR output sos'

    assert ds_in.variables['sea_sfc_salinity']._FillValue == ds_out.variables['sos']._FillValue, \
        '_FillValue differs between input sea_sfc_salinity and CMOR output sos'
    assert ds_in.variables['sea_sfc_salinity'].missing_value == ds_out.variables['sos'].missing_value, \
        'missing_value differs between input sea_sfc_salinity and CMOR output sos'


def test_fre_cmor_run_subtool_case3_output_compare_data(capfd):
    """
    I/O data-only comparison of test case3 (mapped variable)
    """
    print(f'FULL_OUTPUTFILE={FULL_OUTPUTFILE}')
    print(f'FULL_INPUTFILE_MAPPED={FULL_INPUTFILE_MAPPED}')

    with netCDF4.Dataset(FULL_INPUTFILE_MAPPED) as ds_in, \
         netCDF4.Dataset(FULL_OUTPUTFILE) as ds_out:
        assert ds_in.file_format != ds_out.file_format, \
            f'expected file formats to differ, got input={ds_in.file_format}, output={ds_out.file_format}'

        _assert_mapped_data_matches(ds_in, ds_out)
    _out, _err = capfd.readouterr()


def test_fre_cmor_run_subtool_case3_output_compare_metadata(capfd):
    """
    I/O metadata-only comparison of test case3 (mapped variable)
    """
    print(f'FULL_OUTPUTFILE={FULL_OUTPUTFILE}')
    print(f'FULL_INPUTFILE_MAPPED={FULL_INPUTFILE_MAPPED}')

    with netCDF4.Dataset(FULL_INPUTFILE_MAPPED) as ds_in, \
         netCDF4.Dataset(FULL_OUTPUTFILE) as ds_out:
        assert set(ds_in.ncattrs()) != set(ds_out.ncattrs()), \
            'expected global attributes to differ between input and CMOR output'

        _assert_mapped_metadata_matches(ds_in, ds_out)
    _out, _err = capfd.readouterr()

def test_exp_config_cleanup():
    """
    Restores the CMIP6 experiment config to its pristine state after tests
    that mutate it in-place (e.g. grid / calendar updates).

    The config is no longer tracked by git — it is materialized by a
    session-scoped conftest fixture — so we rewrite it from the canonical
    fixture data instead of running ``git restore``.
    """
    Path(EXP_CONFIG).write_text(
        json.dumps(_CMIP6_EXP_CONFIG_DATA, indent=4), encoding='utf-8'
    )

def test_cmor_run_subtool_raise_value_error():
    """
    test that ValueError raised when required args are absent
    """
    with pytest.raises(ValueError):
        cmor_run_subtool( indir = None,
                          json_var_list = None,
                          json_table_config = None,
                          json_exp_config = None,
                          outdir = None )

def test_fre_cmor_run_subtool_no_exp_config():
    """
    fre cmor run, exception, json_exp_config DNE
    """

    # test call, where meat of the workload gets done
    with pytest.raises(FileNotFoundError):
        cmor_run_subtool(
            indir = INDIR,
            json_var_list = VARLIST_DIFF,
            json_table_config = TABLE_CONFIG,
            json_exp_config = 'DOES NOT EXIST',
            outdir = OUTDIR
        )

VARLIST_EMPTY = \
    f'{ROOTDIR}/empty_varlist'
def test_fre_cmor_run_subtool_empty_varlist():
    """
    fre cmor run, exception, variable list is empty
    """

    # test call, where meat of the workload gets done
    with pytest.raises(ValueError):
        cmor_run_subtool(
            indir = INDIR,
            json_var_list = VARLIST_EMPTY,
            json_table_config = TABLE_CONFIG,
            json_exp_config = EXP_CONFIG,
            outdir = OUTDIR
        )


def test_fre_cmor_run_subtool_opt_var_name_not_in_table():
    """ fre cmor run, exception,  """

    # test call, where meat of the workload gets done
    with pytest.raises(ValueError):
        cmor_run_subtool(
            indir = INDIR,
            json_var_list = VARLIST,
            json_table_config = TABLE_CONFIG,
            json_exp_config = EXP_CONFIG,
            outdir = OUTDIR,
            opt_var_name='difmxybo'
        )


def test_fre_cmor_run_subtool_missing_mip_era(tmp_path):
    """
    KeyError when the exp config JSON has no mip_era entry.
    """
    # create a minimal exp config that is missing 'mip_era'
    bad_exp = tmp_path / 'no_mip_era.json'
    exp_data = {'institution_id': 'TEST', 'source_id': 'TEST-1-0'}
    bad_exp.write_text(json.dumps(exp_data))

    with pytest.raises(KeyError, match='noncompliant'):
        cmor_run_subtool(
            indir = INDIR,
            json_var_list = VARLIST,
            json_table_config = TABLE_CONFIG,
            json_exp_config = str(bad_exp),
            outdir = OUTDIR,
        )


def test_fre_cmor_run_subtool_unsupported_mip_era(tmp_path):
    """
    ValueError when mip_era is present but not CMIP6 or CMIP7.
    """
    # create an exp config with an unsupported mip_era value
    bad_exp = tmp_path / 'bad_mip_era.json'
    with open(EXP_CONFIG, 'r', encoding='utf-8') as f:
        exp_data = json.load(f)
    exp_data['mip_era'] = 'CMIP99'
    bad_exp.write_text(json.dumps(exp_data))

    with pytest.raises(ValueError, match='only supports CMIP6 and CMIP7'):
        cmor_run_subtool(
            indir = INDIR,
            json_var_list = VARLIST,
            json_table_config = TABLE_CONFIG,
            json_exp_config = str(bad_exp),
            outdir = OUTDIR,
        )
