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
- ``make_simple_varlist(dir_targ, output_variable_list, json_mip_table, check_freq)``
- ``detect_input_frequency(nc_file, var_name)``
- ``mip_entry_frequency(var_entry)``
- ``frequency_mismatch(input_freq, table_freq)``

Notes
-----
These utilities are intended to make it easier to inspect and extract variable information from CMIP6 JSON
tables, avoiding the need for manual shell scripting and ad-hoc file inspection.
"""

from functools import lru_cache
import glob
import json
import logging
import os
from pathlib import Path
import re
from typing import Optional, Dict, IO

import numpy as np
from netCDF4 import Dataset, Variable

from .cmor_helpers import get_json_file_data
from .cmor_reduce import varlist_target
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
        mip_era = table_mip_era.lower() if table_mip_era is not None else None
        if mip_era is None:
            mip_era = 'cmip6plus' if 'CMIP-6.5' in str(proj_table_vars['Header'].get('Conventions')) else 'cmip7'
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
        fre_logger.ddebug('found relevant_branded_vars = %s', relevant_branded_vars)

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
            fre_logger.ddebug(brand_var_content[branded_var])
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
                                                  var_name=varlist_target(var_list[var]))

# base frequencies recognized from an input file's time spacing, as (name, low, high) in days
_SPACING_TO_BASE_FREQ = (
    ('subhr', 0.0, 0.99 / 24),
    ('1hr', 0.99 / 24, 1.01 / 24),
    ('3hr', 2.97 / 24, 3.03 / 24),
    ('6hr', 5.94 / 24, 6.06 / 24),
    ('day', 0.99, 1.01),
    ('mon', 27.5, 31.5),
    ('yr', 359.0, 367.0),
    ('dec', 3590.0, 3670.0),
)
_TIME_UNIT_IN_DAYS = {'d': 1.0, 'h': 1.0 / 24, 'm': 1.0 / 1440, 's': 1.0 / 86400}


def _base_freq_from_spacing(spacing_days: float) -> Optional[str]:
    """Classify a time step (in days) as a MIP base frequency, e.g. 29.5 -> 'mon'."""
    for name, low, high in _SPACING_TO_BASE_FREQ:
        if low <= spacing_days < high:
            return name
    return None


def _time_unit_in_days(units: str) -> Optional[float]:
    """Length of one unit of a CF time units string in days, e.g. 'hours since ...' -> 1/24."""
    match = re.match(r'\s*(day|hour|hr|minute|min|second|sec|s\b|d\b|h\b)', units or '', re.IGNORECASE)
    if match is None:
        return None
    return _TIME_UNIT_IN_DAYS[match.group(1)[0].lower()]


def _input_sampling(var: Variable, time_var: Optional[Variable]) -> Optional[str]:
    """How an input variable samples time: 'clim' (climatological time axis), 'point'
    (``time: point``), 'mean' (any other ``time:`` cell method, e.g. mean/maximum/sum), or
    None if the file does not say."""
    if time_var is not None and getattr(time_var, 'climatology', None) is not None:
        return 'clim'
    match = re.search(r'time\s*:\s*(\w+)', getattr(var, 'cell_methods', '') or '')
    if match is None:
        return None
    return 'point' if match.group(1) == 'point' else 'mean'


def _time_spacing_days(ds: Dataset, time_var: Variable) -> Optional[float]:
    """Median time step of a time axis in days, or for a single time step the width of its
    bounds; None if neither is available or the units are not understood."""
    unit_days = _time_unit_in_days(getattr(time_var, 'units', ''))
    if unit_days is None:
        return None
    values = np.asarray(time_var[:], dtype=float)
    if values.size > 1:
        return float(np.median(np.diff(values))) * unit_days
    bounds_name = getattr(time_var, 'climatology', None) or getattr(time_var, 'bounds', None)
    if values.size == 1 and bounds_name in ds.variables:
        bounds = np.asarray(ds.variables[bounds_name][:], dtype=float).ravel()
        return float(bounds[-1] - bounds[0]) * unit_days
    return None


@lru_cache(maxsize=None)
def detect_input_frequency(nc_file: str, var_name: str) -> Dict[str, Optional[str]]:
    """
    Work out the actual frequency of a variable in a pp file from the file itself, rather than
    from the directory it sits in.

    The base frequency comes from the median spacing of the time axis (or, for a file holding a
    single time step, the width of its time bounds). The sampling comes from the time axis'
    ``climatology`` attribute and the variable's ``cell_methods``.

    :param nc_file: Path to a netCDF file holding ``var_name``.
    :type nc_file: str
    :param var_name: Name of the variable in the file.
    :type var_name: str
    :return: dict with ``base`` ('fx', 'subhr', '1hr', '3hr', '6hr', 'day', 'mon', 'yr',
        'dec', or None if unknown) and ``sampling`` ('fixed', 'clim', 'point', 'mean', or None
        if unknown). Both are None if the file cannot be read.
    :rtype: dict

    .. note:: Results are cached per (file, variable), since ``fremor config`` checks the same
        files against every MIP table. Reading a file that is offline on tape recalls it.
    """
    unknown = {'base': None, 'sampling': None}
    try:
        with Dataset(nc_file, 'r') as ds:
            var = ds.variables[var_name]
            time_dims = [dim for dim in var.dimensions
                         if dim == 'time' or ds.dimensions[dim].isunlimited()
                         or getattr(ds.variables.get(dim), 'axis', '') == 'T']
            if not time_dims:
                return {'base': 'fx', 'sampling': 'fixed'}
            time_var = ds.variables.get(time_dims[0])
            sampling = _input_sampling(var, time_var)
            if time_var is None:
                return {'base': None, 'sampling': sampling}

            spacing = _time_spacing_days(ds, time_var)
            base = _base_freq_from_spacing(spacing) if spacing is not None else None
            return {'base': base, 'sampling': sampling}
    except Exception as exc: # pylint: disable=broad-exception-caught
        fre_logger.warning('could not read the time axis of %s in %s, not checking its frequency: %s',
                           var_name, nc_file, exc)
        return unknown


def mip_entry_frequency(var_entry: dict) -> Dict[str, Optional[str]]:
    """
    The frequency a MIP table variable entry asks for, in the same terms as
    ``detect_input_frequency``.

    The sampling comes from the entry's time dimension (``time`` -> 'mean', ``time1`` -> 'point',
    ``time2``/``time3`` -> 'clim', none -> 'fixed'), which both CMIP6 and CMIP7 tables carry.
    The base frequency comes from the entry's ``frequency`` field, e.g. 'monPt' -> 'mon'. CMIP7
    tables have no ``frequency`` field, so for CMIP7 only the sampling is known.

    :param var_entry: One ``variable_entry`` value from a MIP table.
    :type var_entry: dict
    :return: dict with ``base`` and ``sampling``, either of which may be None if not known.
    :rtype: dict
    """
    dims = var_entry.get('dimensions') or []
    if isinstance(dims, str):
        dims = dims.split()
    time_dims = [dim for dim in dims if dim.startswith('time')]
    if not time_dims:
        sampling = 'fixed'
    else:
        sampling = {'time': 'mean', 'time1': 'point', 'time2': 'clim', 'time3': 'clim'}.get(time_dims[0])

    freq = var_entry.get('frequency')
    base = None
    if freq == 'fx' or sampling == 'fixed':
        base = 'fx'
    elif freq:
        base = re.sub(r'(Pt|CM|C)$', '', freq)
    return {'base': base, 'sampling': sampling}


def frequency_mismatch(input_freq: Dict[str, Optional[str]],
                       table_freq: Dict[str, Optional[str]]) -> Optional[str]:
    """
    Compare an input file's frequency with a MIP table entry's. Only what is known on both
    sides is compared, so an unreadable file or a CMIP7 entry's missing base frequency never
    counts as a mismatch.

    :return: A short reason if they are inconsistent, e.g. 'input mon vs table day', else None.
    :rtype: str or None
    """
    for key in ('base', 'sampling'):
        have, want = input_freq.get(key), table_freq.get(key)
        if have is not None and want is not None and have != want:
            return f'input {key} {have} vs table {want}'
    return None


def _input_freq_matches_table(nc_files: list, var_name: str, mip_var: str,
                              variable_entries: dict, json_mip_table: str) -> bool:
    """Whether the frequency of ``var_name``'s first input file is consistent with at least
    one of the table's entries for ``mip_var`` (a CMIP7 table may hold several brands)."""
    var_files = sorted(f for f in nc_files if os.path.basename(f).split('.')[-2] == var_name)
    input_freq = detect_input_frequency(var_files[0], var_name)
    entries = [entry for key, entry in variable_entries.items() if key.split('_')[0] == mip_var]
    reasons = [frequency_mismatch(input_freq, mip_entry_frequency(entry)) for entry in entries]
    if None in reasons:
        return True
    fre_logger.info('%s not mapped to %s in %s, its frequency does not match the table (%s)',
                    var_name, mip_var, Path(json_mip_table).name, '; '.join(sorted(set(reasons))))
    return False


def make_simple_varlist( dir_targ: str,
                         output_variable_list: Optional[str],
                         return_none_if_no_mip_vars: Optional[bool] = False,
                         json_mip_table: Optional[str] = None,
                         check_freq: bool = False) -> Optional[Dict[str, str]]:
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
    :param check_freq: also require the frequency of the variable's input files (read from the first file's
        time axis and cell_methods, see ``detect_input_frequency``) to be consistent with at least one of the
        table's entries for that variable. A variable failing this is treated like one not in the table.
    :type check_freq: bool
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
            full_mip_vars_list=get_json_file_data(json_mip_table)['variable_entry']

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
            for mip_var in mip_vars:
                if var_name.lower() != mip_var.lower():
                    continue
                if check_freq and not _input_freq_matches_table(
                        all_nc_files, var_name, mip_var, full_mip_vars_list, json_mip_table):
                    break
                var_list[var_name] = mip_var
                break
            if var_name not in var_list:
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
