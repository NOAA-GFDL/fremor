"""
tests for fremor.cmor_finder.cmor_find_subtool, mostly
"""

import json
import logging
from pathlib import Path

import pytest
from netCDF4 import Dataset

from fremor.cmor_finder import ( cmor_find_subtool, detect_input_frequency, make_simple_varlist,
                                 make_static_varlist, print_var_content,
                                 print_var_content_in_dir_w_mip_tables )


def _write_frequency_input(path, *, units='days since 2000-01-01', values=(0.0, 1.0),
                           time_variable=True):
    """Create a minimal time-dependent NetCDF variable for frequency detection."""
    with Dataset(path, 'w') as ds:
        ds.createDimension('time', len(values))
        if time_variable:
            time = ds.createVariable('time', 'f8', ('time',))
            time.units = units
            time[:] = values
        variable = ds.createVariable('tas', 'f4', ('time',))
        variable.cell_methods = 'time: mean'
        variable[:] = range(len(values))
    return str(path)

def test_make_simple_varlist(tmp_path):
    """
    quick tests of make_simple_varlist
    """
    # Create some dummy netCDF files
    nc_files = ['test.20230101.var1.nc', 'test.20230101.var2.nc', 'test.20230101.var3.nc']
    assert Path(tmp_path).exists()
    for nc_file in nc_files:
        Path(tmp_path, nc_file).touch()

    output_file = Path(tmp_path, 'varlist.json')
    make_simple_varlist(tmp_path, output_file)

    # Check if the output file is created
    assert output_file.exists()

    # Check the contents of the output file
    with open(output_file, 'r', encoding='utf-8') as f:
        var_list = json.load(f)

    expected_var_list = {
        'var1': 'var1',
        'var2': 'var2',
        'var3': 'var3'
    }
    assert var_list == expected_var_list


def test_detect_input_frequency_unknown_time_units(tmp_path):
    """Unrecognized CF time units leave both the input base frequency and spacing unknown."""
    nc_file = _write_frequency_input(tmp_path / 'unknown_units.nc',
                                    units='fortnights since 2000-01-01')

    assert detect_input_frequency(nc_file, 'tas') == {'base': None, 'sampling': 'mean'}


def test_detect_input_frequency_unrecognized_spacing(tmp_path):
    """A valid time axis with an unrecognized spacing has no base frequency."""
    nc_file = _write_frequency_input(tmp_path / 'unknown_spacing.nc', values=(0.0, 2.0))

    assert detect_input_frequency(nc_file, 'tas') == {'base': None, 'sampling': 'mean'}


def test_detect_input_frequency_without_time_coordinate_variable(tmp_path):
    """A time dimension without a time coordinate variable leaves frequency unknown."""
    nc_file = _write_frequency_input(tmp_path / 'missing_time_variable.nc', time_variable=False)

    assert detect_input_frequency(nc_file, 'tas') == {'base': None, 'sampling': 'mean'}


def test_make_static_varlist_missing_file_returns_none(tmp_path, caplog):
    """A nonexistent static input is reported and does not create a variable list."""
    static_file = tmp_path / 'missing.static.nc'
    output_list = tmp_path / 'varlist.json'

    with caplog.at_level(logging.ERROR):
        result = make_static_varlist(str(static_file), str(output_list))

    assert result is None
    assert f'static file not found: {static_file}' in caplog.text
    assert not output_list.exists()


def test_make_static_varlist_without_candidate_variables_returns_none(tmp_path, caplog):
    """A static file containing only a coordinate has no variable-list candidates."""
    static_file = tmp_path / 'coordinates_only.static.nc'
    with Dataset(static_file, 'w') as ds:
        ds.createDimension('x', 2)
        coordinate = ds.createVariable('x', 'f4', ('x',))
        coordinate[:] = [0.0, 1.0]
    output_list = tmp_path / 'varlist.json'

    with caplog.at_level(logging.WARNING):
        result = make_static_varlist(str(static_file), str(output_list))

    assert result is None
    assert f'no time-invariant data variables found in {static_file}' in caplog.text
    assert not output_list.exists()


def test_find_subtool_no_json_dir_err(tmp_path):
    """
    test json_table_config_dir does not exist error
    """
    target_dir_dne = Path(tmp_path) / 'foo'
    assert not target_dir_dne.exists(), 'target dir should not exist for this test'
    with pytest.raises(OSError, match=f'ERROR directory {target_dir_dne} does not exist, exit.'):
        cmor_find_subtool(json_var_list=None,
                          json_table_config_dir=str(target_dir_dne),
                          opt_var_name=None)


def test_find_subtool_no_json_files_in_dir_err(tmp_path):
    """
    test json_table_config_dir has no files in it error
    """
    target_dir = Path(tmp_path) / 'foo'
    target_dir.mkdir(exist_ok=False)
    assert target_dir.is_dir() and target_dir.exists(), 'temp dir directory creation failed, inspect code'
    with pytest.raises(OSError, match=f'ERROR directory {target_dir} contains no JSON files, exit.'):
        cmor_find_subtool(json_var_list=None,
                          json_table_config_dir=str(target_dir),
                          opt_var_name=None)


def test_find_subtool_no_varlist_no_optvarname_err():
    """
    test no opt_var_name AND no varlist error
    """
    with pytest.raises(ValueError, match='ERROR: no opt_var_name given but also no content in variable list, exit'):
        cmor_find_subtool(json_var_list=None,
                          json_table_config_dir='fremor/tests/test_files/cmip6-cmor-tables/Tables',
                          opt_var_name=None)

def test_print_var_content_cmip7_branded_vars(tmp_path, caplog):
    """
    Test print_var_content for the CMIP7 branch to cover branded variables.
    Omitting 'mip_era' from the Header triggers the cmip7 logic.
    """
    mock_table_path = Path(tmp_path) / 'CMIP7_Amon.json'

    # Create mock JSON data lacking a mip_era to trigger cmip7 logic
    mock_data = {
        'Header': {
            'table_id': 'Table Amon'
            # 'mip_era' explicitly omitted to test the cmip7 fallback
        },
        'variable_entry': {
            'tas_brandA': {
                'standard_name': 'air_temperature',
                'units': 'K',
                'valid_min': 0 # for DO_NOT_PRINT_LIST control path coverage
            },
            'tas_brandB': {
                'standard_name': 'air_temperature_2',
                'units': 'C'
            },
            'pr_brandC': {
                'standard_name': 'precipitation_flux',
                'units': 'kg m-2 s-1'
            }
        }
    }

    # Write the dummy table to the temporary path
    with open(mock_table_path, 'w', encoding='utf-8') as f:
        json.dump(mock_data, f)

    # Open the file and run the function, capturing INFO logs
    with open(mock_table_path, 'r', encoding='utf-8') as table_file:
        with caplog.at_level(logging.INFO):
            print_var_content(table_file, var_name='tas')

    # Assertions to verify the CMIP7 branches were covered correctly
    log_output = caplog.text

    # Verify the branded variables loop was executed
    assert 'amongst branded variables, looked for variable name: tas' in log_output

    # Verify the specific branded variables matching 'tas' were found and printed
    assert 'found tas_brandA' in log_output
    assert 'found tas_brandB' in log_output
    assert 'air_temperature' in log_output

    # Verify that non-matching variables ('pr_brandC') were ignored
    assert 'pr_brandC' not in log_output
    assert 'precipitation_flux' not in log_output

def test_print_var_content_cmip7_branded_vars_no_content(tmp_path):
    """
    Test print_var_content for the CMIP7 branch to cover branded variables.
    Omitting 'mip_era' from the Header triggers the cmip7 logic.
    """
    mock_table_path = Path(tmp_path) / 'CMIP7_Amon.json'

    # Create mock JSON data lacking a mip_era to trigger cmip7 logic
    mock_data = {
    }

    # Write the dummy table to the temporary path
    with open(mock_table_path, 'w', encoding='utf-8') as f:
        json.dump(mock_data, f)

    # Open the file and run the function, capturing INFO logs
    with open(mock_table_path, 'r', encoding='utf-8') as table_file:
        with pytest.raises(ValueError):
            print_var_content(table_file, var_name='tas')


def test_print_var_content_in_dir_w_mip_tables_err_1(caplog):
    """
    test first simple return-none condition in print_var_content_in_dir_w_mip_tables
    """
    with caplog.at_level(logging.INFO):
        print_var_content_in_dir_w_mip_tables(json_table_configs = None, var_name = None)
    assert 'no varname, nothing to print, moving on' in caplog.text

def test_print_var_content_in_dir_w_mip_tables_err_2(caplog):
    """
    test second simple return-none condition in print_var_content_in_dir_w_mip_tables
    """
    with caplog.at_level(logging.WARNING):
        print_var_content_in_dir_w_mip_tables(json_table_configs = None, var_name = 'foo')
    assert 'no mip table configurations to loop over, moving on' in caplog.text
