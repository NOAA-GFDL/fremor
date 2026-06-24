"""
``fremor find`` and ``fremor varlist``
======================================

This module provides tools to find and print information about variables in CMIP6 JSON configuration files.
It is primarily used for inspecting variable entries and generating variable lists for use in FRE CMORization
workflows.

Functions
---------
- ``print_var_content(table_config_file, var_name)``
- ``cmor_find_subtool(json_var_list, json_table_config_dir, opt_var_name)``
- ``make_simple_varlist(dir_targ, output_variable_list, json_mip_table)``

Notes
-----
These utilities are intended to make it easier to inspect and extract variable information from CMIP6 JSON
tables, avoiding the need for manual shell scripting and ad-hoc file inspection.
"""

import glob
import json
import logging
import os
from pathlib import Path
from typing import Optional, Dict, IO

from .cmor_helpers import get_json_file_data
from .cmor_constants import DO_NOT_PRINT_LIST

fre_logger = logging.getLogger(__name__)

def print_var_content(table_config_file: IO[str],
                      var_name: str) -> None:
    """
    Print information about a specific variable from a given CMIP6 JSON configuration file.

    :param table_config_file: An open file object for a CMIP6 table JSON file. The file should be opened in text mode
    :type table_config_file: Input buffer/stream of text, usually output by the open() built-in. See python typing doc
    :param var_name: The name of the variable to look for in the configuration file.
    :type var_name: str
    :raises Exception: If there is an issue reading the JSON content from the file.
    :return: None
    :rtype: None

    .. note:: Outputs information to the logger at INFO level.
    .. note:: If the variable is not found, logs a debug message and returns.
    .. note:: Only prints selected fields, omitting any in DO_NOT_PRINT_LIST.
    """
    # this function can assume the existence of this was checked in the prev routine.
    proj_table_vars = json.load(table_config_file)
    if proj_table_vars is None or len(proj_table_vars) == 0:
        raise ValueError( 'proj_table_vars has nothing in it! contents are:'
                         f'{proj_table_vars}')

    table_name, table_file_name, mip_era = None, None, None
    try:
        table_mip_era = proj_table_vars['Header'].get('mip_era')
        mip_era = 'cmip7' if table_mip_era is None else 'cmip6'
        table_name_split = proj_table_vars['Header'].get('table_id').split(' ')
        table_name = table_name_split[0] if len(table_name_split) < 2 else table_name_split[1]
        table_file_name = Path(table_config_file.name).name # something not fun happening here...
    except KeyError:
        fre_logger.warning('couldn\'t get header and table_name field, possibly not a variable/mip table')

    if table_name is not None:
        fre_logger.debug('looking for %s data in table %s!', var_name, table_name)
    else:
        fre_logger.debug('looking for %s data in table %s, but could not find its table_name!',
                        var_name, table_config_file.name)

    var_content = None
    if mip_era != 'cmip7':
        var_content = proj_table_vars.get('variable_entry', {}).get(var_name)
    else:
        # branded variables
        fre_logger.debug('    cmip7 case detected, checking branded variable content')
        all_branded_vars = proj_table_vars.get('variable_entry', {}).keys()
        relevant_branded_vars = [ branded_var for branded_var in all_branded_vars if var_name in branded_var ]
        fre_logger.debug('found relevant_branded_vars = %s', relevant_branded_vars)

        var_content = []
        for relevant_var_name in relevant_branded_vars:
            var_content.append(
                { relevant_var_name : proj_table_vars.get('variable_entry', {}).get(relevant_var_name) }
            )

    if var_content in [None, []]:
        fre_logger.debug('variable %s not found in %s, moving on!', var_name, table_file_name)
        return

    if isinstance(var_content, list): # likely, cmip7 case, shouldn't occur unless brands
        fre_logger.info('amongst branded variables, looked for variable name: %s', var_name)
        for brand_var_content in var_content:
            branded_var=str(list(brand_var_content)[0])
            fre_logger.info('\n')

            fre_logger.info('in table %s / table_name %s, found %s', table_file_name, table_name, branded_var)
            fre_logger.debug(brand_var_content[branded_var])
            fre_logger.debug(type(brand_var_content[branded_var]))
            for thing in brand_var_content[branded_var]:
                if thing in DO_NOT_PRINT_LIST:
                    continue
                fre_logger.info('    %s: %s', thing, brand_var_content[branded_var][thing])
    else: # non cmip7 case
        fre_logger.info('    variable key: %s', var_name)
        for content in var_content:
            if content in DO_NOT_PRINT_LIST:
                continue
            fre_logger.info('    %s: %s', content, var_content[content])
    fre_logger.info('\n')

def print_var_content_in_dir_w_mip_tables(json_table_configs: list = None,
                                          var_name: str = None) -> None:
    """
    given a list of table configuration files and a variable name, find and print info
    on the variable name when found. CMIP6 and CMIP7 compatible.
    """
    if var_name in [None, '']:
        fre_logger.info('no varname, nothing to print, moving on')
        return
    if json_table_configs in [None, []] or len(json_table_configs)==0:
        fre_logger.warning('no mip table configurations to loop over, moving on')
        return
    for json_table_config in json_table_configs:
        fre_logger.debug('looking for %s content in %s', var_name, Path(json_table_config).name)
        with open(json_table_config, 'r', encoding='utf-8') as table_config_file:
            print_var_content(table_config_file, var_name)

def cmor_find_subtool( json_var_list: Optional[str] = None,
                       json_table_config_dir: Optional[str] = None,
                       opt_var_name: Optional[str] = None) -> None:
    """
    Find and print information about variables in CMIP6 JSON configuration files in a specified directory.

    :param json_var_list: path to JSON file containing variable names to look up in tables.
    :type json_var_list: str or None, optional
    :param json_table_config_dir: Directory containing CMIP6 table JSON files.
    :type json_table_config_dir: str
    :param opt_var_name: Name of a single variable to look up. If None, json_var_list must be provided.
    :type opt_var_name: str or None, optional
    :raises OSError: If the specified directory does not exist or contains no JSON files.
    :raises ValueError: If neither opt_var_name nor json_var_list is provided.
    :return: None
    :rtype: None

    .. note:: This function is intended as a helper tool for CLI users to quickly inspect variable definitions in
              CMIP6 tables. Information is printed via the logger.
    """
    if not Path(json_table_config_dir).exists():
        raise OSError(f'ERROR directory {json_table_config_dir} does not exist, exit.')

    fre_logger.debug('looking for files in dir: %s ', json_table_config_dir)
    json_table_configs = glob.glob(f'{json_table_config_dir}/*.json')
    if not json_table_configs:
        raise OSError(f'ERROR directory {json_table_config_dir} contains no JSON files, exit.')
    fre_logger.info('found JSON tables in json_table_config_dir')

    var_list = None
    if json_var_list is not None:
        with open(json_var_list, 'r', encoding='utf-8') as var_list_file:
            var_list = json.load(var_list_file)

    if opt_var_name is None and var_list is None:
        raise ValueError('ERROR: no opt_var_name given but also no content in variable list, exit')

    if opt_var_name is not None:
        fre_logger.info('looking for %s info', opt_var_name)
        print_var_content_in_dir_w_mip_tables(json_table_configs=json_table_configs,
                                              var_name=opt_var_name)

    elif var_list is not None:
        fre_logger.info('looking for %s variables worth of info', len(var_list))
        for var in var_list:
            print_var_content_in_dir_w_mip_tables(json_table_configs=json_table_configs,
                                                  var_name=var_list[var])

def make_simple_varlist( dir_targ: str,
                         output_variable_list: Optional[str],
                         return_none_if_no_mip_vars: Optional[bool] = False,
                         json_mip_table: Optional[str] = None) -> Optional[Dict[str, str]]:
    """
    Generate a JSON file containing a list of variable names from NetCDF files in a specified directory.
    This function searches for NetCDF files in the given directory, or a subdirectory, 'ts/monthly/5yr',
    if not already included. It then extracts variable names from the filenames, and writes these variable
    names to a JSON file.

    :param dir_targ: The target directory to search for NetCDF files.
    :type dir_targ: str
    :param output_variable_list: The path to the output JSON file where the variable list will be saved.
    :type output_variable_list: str
    :param return_none_if_no_mip_vars: return None if all values (mip vars) are empty for all keys in output varlist
    :type return_none_if_no_mip_vars: bool
    :param json_mip_table: target table for making the var list. found variables are included if they are in the table
    :type json_mip_table: str
    :raises OSError: if the outputfile cannot be written
    :return: Dictionary of variable names (keys == values), or None if no files are found or an error occurs
    :rtype: dict or None

    .. note:: Assumes NetCDF filenames are of the form: <something>.<datetime>.<variable>.nc
    .. note:: Variable name is assumed to be the second-to-last component when split by periods.
    .. note:: Logs a warning if only one file is found.

    .. warning:: Logs errors if no files are found in the directory or if no files match the expected pattern.

    """
    # if the variable is in the filename, it's likely delimited by another period.
    all_nc_files = glob.glob(os.path.join(dir_targ, '*.*.nc'))
    if not all_nc_files:
        fre_logger.error('No files found in the directory.')
        return None

    if len(all_nc_files) == 1:
        fre_logger.debug('Warning: Only one file found matching the pattern.')

    fre_logger.debug('Files found matching pattern. Number of files: %d', len(all_nc_files))

    mip_vars = None
    if json_mip_table is not None:
        try:
            # read in mip vars to check against later
            fre_logger.debug('attempting to read in variable entries in specified mip table')
            full_mip_vars_list=get_json_file_data(json_mip_table)['variable_entry'].keys()

        except Exception as exc:
            raise Exception( 'problem opening mip table and getting variable entry data.'
                            f'exc = {exc}') from exc

        fre_logger.debug('attempting to make mip variable list')
        mip_vars=[ key.split('_')[0] for key in full_mip_vars_list ]
        fre_logger.info('mip vars extracted for comparison when making var list: %s', mip_vars)

    # build deduplicated list of unique candidate variable names to push through comparison below
    candidate_var_list = []
    for targetfile in all_nc_files:
        var_name=os.path.basename(targetfile).split('.')[-2]
        if var_name not in candidate_var_list:
            candidate_var_list.append(var_name)
    fre_logger.info('candidate vars extracted for comparison when making var list: %s', candidate_var_list)

    # dict of variable names extracted from all filenames across all datetimes.
    # If a MIP table is provided, variables that match a MIP variable name get
    # self-mapped (key==value). Variables NOT in the MIP table get an empty string
    # as value, signaling they need manual mapping by the user.
    var_list: Dict[str, str] = {}
    for var_name in candidate_var_list:
        fre_logger.debug('candidate var_name = %s', var_name)

        if mip_vars is not None:
            is_mip_var = False
            for mip_var in mip_vars:
                if var_name.lower() != mip_var.lower():
                    continue
                var_list[var_name] = mip_var
                is_mip_var = True
                break
            if not is_mip_var:
                fre_logger.debug('%s is not a mip var name', var_name)
                if not return_none_if_no_mip_vars:
                    var_list[var_name] = ''
        else:
            fre_logger.warning('no mip variable list to compare to, setting found variable name value to key.')
            var_list[var_name] = var_name

    if return_none_if_no_mip_vars and len(var_list) == 0:
        fre_logger.warning('WARNING: all found variables have no known corresponding mip variable name.'
                           'returning None and not writing variable list!'
                           'return_none_if_no_mip_vars was True!')
        return None

    # Write the variable list to the output JSON file
    if output_variable_list is not None:
        try:
            fre_logger.debug('writing output variable list, %s', list(var_list.keys()))
            with open(output_variable_list, 'w', encoding='utf-8') as f:
                json.dump(var_list, f, indent=4)
        except Exception as exc:
            raise OSError('output variable list created but cannot be written') from exc
    return var_list
