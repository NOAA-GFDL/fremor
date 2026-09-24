"""
``fremor run``
==============

This submodule currently follows a composite pattern, analogous to nested/russian doll, where a large piece contains a
smaller piece which contains another. ``fremor run`` leads directly to ``cmor_run_subtool``, which calls
``cmorize_all_variables_in_dir`` once, which calls ``cmorize_all_variables_in_dir`` once, which calls
``cmorize_target_var_files`` once per variable in a variable list, and calls ``rewrite_netcdf_file_var`` once per found
datetime for a given variable. Functions within ``cmor_helpers`` assist with the CMORization process.

Functions
---------
- ``resolve_cmip7_brand(...)``
- ``index_existing_outputs(...)``
- ``expected_output_prefix(...)``
- ``find_existing_output(...)``
- ``rewrite_netcdf_file_var(...)``
- ``cmorize_target_var_files(...)``
- ``cmorize_all_variables_in_dir(...)``
- ``cmor_run_subtool(...)``

.. note:: The name "mixer" comes from a conversation between Chris Blanton, the original code author (Sergey Nikonov),
          and the next author/maintainer, Ian Laflotte, in 2022. Chris wanted to change the name, and Sergey kind of
          enjoyed the original CMORCommander.py, and so did not have any suggestions. Ian, whom was very new and knew
          nothing, suggested "cmor mixer", not truly understanding why. Chris and Sergey decided to go with it.
"""


import glob
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Optional, List, Dict, Any

import cmor
import numpy as np
import netCDF4 as nc

from .cmor_helpers import ( from_ds_get_this, create_lev_bnds,
                            get_iso_datetime_ranges, check_dataset_for_ocean_grid, get_vertical_dimension,
                            create_tmp_dir, get_json_file_data, update_grid_and_label,
                            update_calendar_type, filter_brands,
                            normalize_calendar, get_time_calendar_value, calendars_are_equivalent,
                            resolve_mip_era_table_resource, find_ps_companion, table_declares_ps )
from .cmor_tripolar import load_tripolar_grid
from .cmor_validate import check_exp_config_required_attributes
from .cmor_constants import ( ACCEPTED_VERT_DIMS, NON_HYBRID_SIGMA_COORDS, ALT_HYBRID_SIGMA_COORDS,
                              DEPTH_COORDS, CMOR_NC_FILE_ACTION, CMOR_VERBOSITY,
                              CMOR_EXIT_CTL, CMOR_EXIT_CTL_BY_ERA, CMOR_MK_SUBDIRS, CMOR_LOG,
                              CMOR_LAT_AXIS_NAME, CMOR_LON_AXIS_NAME )

fre_logger = logging.getLogger(__name__)

def _scalar_z_coords(ds: nc.Dataset, local_var: str) -> dict:
    """
    Scalar (0-dimensional) coordinate variables with ``axis='Z'`` referenced by ``local_var``'s
    ``coordinates`` attribute, e.g. ``height``. MIP tables count these as dimensions, so they
    must be accounted for before CMIP7 brand matching.

    :return: ``{coord_name: netCDF4 variable}``
    :rtype: dict
    """
    scalar_z_coords = {}
    try:
        coord_attr = ds.variables[local_var].coordinates
        for coord_name in coord_attr.split():
            if coord_name in ds.variables:
                coord_var = ds.variables[coord_name]
                if len(coord_var.dimensions) == 0:  # scalar (0-dim)
                    if hasattr(coord_var, 'axis') and coord_var.axis == 'Z':
                        scalar_z_coords[coord_name] = coord_var
                        fre_logger.info('detected scalar Z-coordinate: %s', coord_name)
    except AttributeError:
        pass
    return scalar_z_coords


def resolve_cmip7_brand(ds: nc.Dataset, local_var: str, target_var: str,
                        mip_var_cfgs: dict, var_dim_with_scalars: int) -> str:
    """
    Pick the CMIP7 brand of ``target_var`` that the input data matches: candidates are the
    table's ``<target_var>_<brand>`` entries with as many dimensions as the input (scalar Z
    coordinates included), disambiguated by ``filter_brands`` when more than one remains.

    :raises ValueError: If no brand's dimensions match the input data.
    :return: The brand, e.g. ``'tavg-h2m-hxy-u'``.
    :rtype: str
    """
    brands = []
    for mip_var in mip_var_cfgs['variable_entry'].keys():
        if all([ target_var == mip_var.split('_')[0],
                 var_dim_with_scalars == len(mip_var_cfgs['variable_entry'][mip_var]['dimensions']) ]):
            brands.append(mip_var.split('_')[1])

    if len(brands) == 0:
        fre_logger.error('cmip7 case detected, but dimensions of input data do not match '
                         'any of those found for the associated brands.')
        raise ValueError('no variable brand was able to be identified for this CMIP7 case')
    if len(brands) == 1:
        var_brand = brands[0]
        fre_logger.debug('cmip7 case, extracted brand %s', var_brand)
    else:
        fre_logger.warning('cmip7 case, extracted multiple brands %s, attempting disambiguation',
                           brands)
        var_brand = filter_brands(
            brands, target_var, mip_var_cfgs,
            has_time_bnds = 'time_bnds' in ds.variables,
            input_vert_dim = get_vertical_dimension(ds, local_var),
            cell_methods = getattr(ds.variables[local_var], 'cell_methods', None)
        )
    fre_logger.debug('cmip7 case, filtered possible brands to %s', var_brand)
    return var_brand


def index_existing_outputs(outdir: str) -> List[Path]:
    """
    Every non-empty ``.nc`` file already under ``outdir``, outside CMOR's ``CMOR_tmp`` work
    area, listed once so each input file can be checked against it cheaply. Used by
    ``fremor yaml --continue`` to skip input files whose output already exists.

    :param outdir: Output directory root for CMORized files.
    :type outdir: str
    :return: Paths of the existing output files.
    :rtype: list of Path
    """
    if not Path(outdir).is_dir():
        return []
    return [path for path in Path(outdir).rglob('*.nc')
            if 'CMOR_tmp' not in path.parts and path.stat().st_size > 0]


def _iso_daterange_years(iso_daterange: str) -> Optional[tuple]:
    """``(first_year, last_year)`` of a ``'YYYY[MM[DD..]]-YYYY[MM[DD..]]'`` range, else None."""
    match = re.fullmatch(r'(\d{4,})-(\d{4,})', iso_daterange)
    if match is None:
        return None
    return int(match.group(1)[:4]), int(match.group(2)[:4])


def expected_output_prefix(input_file: str, local_var: str, target_var: str,
                           mip_var_cfgs: dict, json_table_config: str,
                           mip_era: str) -> Optional[str]:
    """
    The filename prefix CMOR gives ``target_var``'s output: ``<variable_id>_<table>_``
    (CMIP6/CMIP6Plus, e.g. ``tas_Amon_``) or ``<variable_id>_<brand>_`` (CMIP7, e.g.
    ``tas_tavg-h2m-hxy-u_``). A CMIP7 variable with several brands in the table (e.g. tas's
    time-mean, max and min) needs the brand the input data would get, so only then is the
    input file's header opened, to pick it the same way the CMORization does.

    :return: The prefix, or None if it cannot be determined.
    :rtype: str or None
    """
    if mip_era != 'CMIP7':
        table_id = mip_var_cfgs.get('Header', {}).get('table_id') or \
            Path(json_table_config).stem.split('_', maxsplit=1)[-1]
        return f'{target_var}_{table_id.split()[-1]}_'

    brands = [key.split('_', 1)[1] for key in mip_var_cfgs['variable_entry']
              if key.split('_')[0] == target_var and '_' in key]
    if len(brands) == 1:
        return f'{target_var}_{brands[0]}_'
    try:
        with nc.Dataset(input_file, 'r') as ds:
            var_dim = ds.variables[local_var].ndim + len(_scalar_z_coords(ds, local_var))
            var_brand = resolve_cmip7_brand(ds, local_var, target_var, mip_var_cfgs, var_dim)
    except Exception as exc:  # pylint: disable=broad-except
        fre_logger.warning('could not resolve the CMIP7 brand of %s in %s to look for '
                           'existing output: %s', local_var, input_file, exc)
        return None
    return f'{target_var}_{var_brand}_'


def find_existing_output(prefix: Optional[str], iso_datetime: str,
                         existing_outputs: List[Path]) -> Optional[Path]:
    """
    Find an already-written output file for one input file, purely by filename: one named
    ``<prefix>..._<start>-<stop>.nc`` whose date range covers the same years as the input
    file's ``iso_datetime`` (each input chunk yields one output chunk).

    :param prefix: Output filename prefix, see ``expected_output_prefix``. None never matches.
    :type prefix: str or None
    :param iso_datetime: The input file's date range, e.g. ``'185001-185412'``.
    :type iso_datetime: str
    :param existing_outputs: Output files to search, see ``index_existing_outputs``.
    :type existing_outputs: list of Path
    :return: The matching output file, or None.
    :rtype: Path or None
    """
    if prefix is None:
        return None
    input_years = _iso_daterange_years(iso_datetime)
    for path in existing_outputs:
        if not path.name.startswith(prefix):
            continue
        match = re.search(r'_(\d{4,}-\d{4,})\.nc$', path.name)
        output_years = None if match is None else _iso_daterange_years(match.group(1))
        if output_years == input_years:
            return path
    return None


def rewrite_netcdf_file_var( mip_var_cfgs: dict = None,
                             local_var: str = None,
                             netcdf_file: str = None,
                             target_var: str = None,
                             json_exp_config: str = None,
                             json_table_config: str = None,
                             prev_path: Optional[str] = None,
                             ps_file: Optional[str] = None,
                             ps_var: str = 'ps',
                             ps_searched: Optional[List[str]] = None ) -> str:
    """
    Rewrite the input NetCDF file for a target variable in a CMIP-compliant manner and write output using CMOR.

    :param mip_var_cfgs: Variable table, as loaded from the MIP table JSON config.
    :type mip_var_cfgs: dict
    :param local_var: Modeler's variable name, used for finding files and reading data from them.
    :type local_var: str
    :param netcdf_file: Path to the input NetCDF file to be CMORized.
    :type netcdf_file: str
    :param target_var: MIP table variable name for metadata lookups.
    :type target_var: str
    :param json_exp_config: Path to experiment configuration JSON file (for dataset metadata).
    :type json_exp_config: str
    :param json_table_config: Path to MIP table JSON file.
    :type json_table_config: str
    :param prev_path: Path to previous file (used for finding statics file for tripolar grids).
    :type prev_path: str, optional
    :param ps_file: Path to the surface-pressure file for hybrid-sigma data, see ``find_ps_companion``.
                    If None, the ``.ps.nc`` file next to ``netcdf_file`` is used when present.
    :type ps_file: str, optional
    :param ps_var: Name of the surface-pressure variable inside ``ps_file``.
    :type ps_var: str
    :param ps_searched: Places already searched for ``ps_file``, reported if it is required but missing.
    :type ps_searched: list of str, optional
    :raises ValueError: If unsupported vertical dimensions or inconsistent grid dimensions are found.
    :raises FileNotFoundError: If required statics file for tripolar ocean grid is missing, or if
                               hybrid-sigma data has no surface-pressure file.
    :raises Exception: For other errors in the metadata, file IO, or CMOR calls.
    :return: Absolute path to the output file written by cmor.close.
    :rtype: str

    .. note:: This function performs extensive setup of axes and metadata, and conditionally handles tripolar
              ocean grids.
    """
    fre_logger.info('input data:')
    fre_logger.info('     local_var = %s (modeler variable name, in filename and file)', local_var)
    fre_logger.info('    target_var = %s (MIP table variable name)', target_var)

    # open the input file
    fre_logger.info('opening %s', netcdf_file)
    ds = nc.Dataset(netcdf_file, 'r+')

    # read the input variable data using the modeler's variable name (local_var)
    fre_logger.info('attempting to read variable data, %s', local_var)
    var = from_ds_get_this(from_ds=ds, var_name=local_var)

    ## var type
    #var_dtype = var.dtype

    # var missing_value, in numpy masked_array land, called the fill_value
    var_missing_val = var.fill_value

    # grab var_dim
    var_dim = len(var.shape)
    fre_logger.info('var_dim = %d, local_var = %s', var_dim, local_var)

    # detect scalar coordinate variables (0-dimensional) with axis='Z'
    # these are auxiliary coordinates like "height" referenced via the coordinates attribute
    # and must be accounted for before brand matching, as MIP tables count them as dimensions
    scalar_z_coords = _scalar_z_coords(ds, local_var)
    var_dim_with_scalars = var_dim + len(scalar_z_coords)

    # CMORizing ocean grids are implemented only for scalar quantities valued at the central T/h-point of the grid cell.
    # https://en.wikipedia.org/wiki/Arakawa_grids heavily consulted for this work.
    # we also need to do:
    # - ice tripolar cases
    # - vector cases (quantities valued on edges in B/C/D for ocean and ice)
    # - probably others that i cannot currently fathom but will bump into.
    fre_logger.info('checking input netcdf file for oceangrid condition')
    uses_ocean_grid = check_dataset_for_ocean_grid(ds)
    if uses_ocean_grid:
        fre_logger.warning(
            'cmor_mixer suspects this is ocean data, being reported on \n'
            ' native tripolar grid. i may treat this differently than other files!'
        )

    # check for cmip7 case and extract possible brands here
    var_brand = None
    exp_cfg_mip_era = get_json_file_data(json_exp_config)['mip_era'].upper()
    if exp_cfg_mip_era == 'CMIP7':
        var_brand = resolve_cmip7_brand(ds, local_var, target_var, mip_var_cfgs, var_dim_with_scalars)
    else:
        fre_logger.debug('non-cmip7 case detected, skipping variable brands')

    # try to read what coordinate(s) we're going to be expecting for the variable according to the mip table and compare
    expected_mip_coord_dims = None
    try:
        if exp_cfg_mip_era == 'CMIP7':
            expected_mip_coord_dims = mip_var_cfgs['variable_entry'][f'{target_var}_{var_brand}']['dimensions']
        else:
            expected_mip_coord_dims = mip_var_cfgs['variable_entry'][target_var]['dimensions']

        fre_logger.info(
            'I am hoping to find data for the following coordinate dimensions:\n'
            '    expected_mip_coord_dims = %s\n',
            expected_mip_coord_dims
        )
    except Exception as exc:
        fre_logger.warning(
            'could not get expected coordinate dimensions for %s. '
            '   in mip_var_cfgs file %s. \n exc = %s',
            target_var, json_table_config, exc
        )

    # Attempt to read lat/lon coordinates and bnds. will check for none later
    fre_logger.info('attempting to read coordinate, lat')
    lat = from_ds_get_this(from_ds=ds, var_name='lat')
    fre_logger.info('attempting to read coordinate BNDS, lat_bnds')
    lat_bnds = from_ds_get_this(from_ds=ds, var_name='lat_bnds')
    fre_logger.info('attempting to read coordinate, lon')
    lon = from_ds_get_this(from_ds=ds, var_name='lon')
    fre_logger.info('attempting to read coordinate BNDS, lon_bnds')
    lon_bnds = from_ds_get_this(from_ds=ds, var_name='lon_bnds')

    # read in time_coords + units
    fre_logger.info('attempting to read coordinate time, and units...')
    time_coords = from_ds_get_this(from_ds=ds, var_name='time')
    time_coord_units = ds['time'].units
    fre_logger.info('    time_coord_units = %s', time_coord_units)

    # check the calendar of the input netcdf file time coordinate, if present
    time_coords_calendar = None
    try:
        time_coords_calendar = get_time_calendar_value(ds['time'])
    except Exception:
        fre_logger.debug('could not read time variable for calendar detection.')

    # if it's still None, give a warning and move on.
    if time_coords_calendar is None:
        fre_logger.warning('WARNING input file\'s time coordinates missing calendar and/or calendar_type field'
                           'this output could have the wrong calendar!')
    else:
        with open(json_exp_config, 'r', encoding='utf-8') as file:
            exp_cfg_calendar = json.load(file)['calendar']
            if not calendars_are_equivalent(time_coords_calendar, exp_cfg_calendar):
                norm_time = normalize_calendar(time_coords_calendar)
                norm_cfg = normalize_calendar(exp_cfg_calendar)
                raise ValueError(f'data calendar type {norm_time} '
                                 f'does not match input config calendar type: {norm_cfg}')

    # read in time_bnds, if present
    fre_logger.info('attempting to read coordinate BNDS, time_bnds')
    time_bnds = from_ds_get_this(from_ds=ds, var_name='time_bnds')

    # determine the vertical dimension by looping over netcdf variables
    vert_dim = get_vertical_dimension(ds, local_var)  # returns int(0) if not present
    fre_logger.info('Vertical dimension of %s: %s', local_var, vert_dim)

    # Check var_dim and vert_dim and assign lev if relevant.
    lev, lev_units = None, '1'
    lev_bnds = None
    if vert_dim != 0:
        if vert_dim.lower() not in ACCEPTED_VERT_DIMS:
            raise ValueError(f'var_dim={var_dim}, vert_dim = {vert_dim} is not supported') #uncovered
        lev = ds[vert_dim]
        if vert_dim.lower() != 'landuse':
            lev_units = ds[vert_dim].units

    # if no vertical dimension found in data but scalar Z-coordinates exist,
    # identify the corresponding MIP axis name from expected dimensions
    if vert_dim == 0 and scalar_z_coords and expected_mip_coord_dims is not None:
        dims_to_check = (expected_mip_coord_dims.split()
                         if isinstance(expected_mip_coord_dims, str)
                         else expected_mip_coord_dims)
        for dim_name in dims_to_check:
            if dim_name.lower() in [d.lower() for d in ACCEPTED_VERT_DIMS]:
                scalar_coord_name = list(scalar_z_coords.keys())[0]
                vert_dim = dim_name
                lev = ds.variables[scalar_coord_name]
                lev_units = ds.variables[scalar_coord_name].units
                fre_logger.info('scalar Z-coordinate %s mapped to MIP axis %s',
                                scalar_coord_name, dim_name)
                break

    process_tripolar_data = all([uses_ocean_grid, lat is None, lon is None])
    xh, yh = None, None
    xh_bnds, yh_bnds = None, None
    if process_tripolar_data:
        tripolar_grid = load_tripolar_grid(ds=ds, netcdf_file=netcdf_file, prev_path=prev_path)
        lat      = tripolar_grid['lat']
        lon      = tripolar_grid['lon']
        lat_bnds = tripolar_grid['lat_bnds']
        lon_bnds = tripolar_grid['lon_bnds']
        yh       = tripolar_grid['yh']
        xh       = tripolar_grid['xh']
        yh_bnds  = tripolar_grid['yh_bnds']
        xh_bnds  = tripolar_grid['xh_bnds']

    # now we set up the cmor module object
    # initialize CMOR
    # CMOR's own error messages (e.g. "Problem with 'cmor.variable'.") are content-free unless
    # a logfile is configured; without one, the real reason for a CMORError is discarded.
    cmor_logfile = CMOR_LOG if CMOR_LOG is not None else f'cmor_{target_var}.log'
    # exit control is per-era: CMIP6Plus tables always warn (see CMOR_EXIT_CTL_BY_ERA)
    cmor_exit_ctl = CMOR_EXIT_CTL_BY_ERA.get(exp_cfg_mip_era, CMOR_EXIT_CTL)
    fre_logger.debug('cmor exit_control for %s = %s', exp_cfg_mip_era, cmor_exit_ctl)
    cmor.setup(
        # CMOR falls back to inpath when a table's neighbours are not where it first looks.
        # The CMIP6Plus auxiliary tables sit in Auxillary_files/, so loading one from there
        # would otherwise leave CMOR hunting for the CV in the wrong directory.
        inpath=str(Path(json_table_config).parent),
        netcdf_file_action=CMOR_NC_FILE_ACTION,
        set_verbosity=CMOR_VERBOSITY,
        exit_control=cmor_exit_ctl,
        create_subdirectories=CMOR_MK_SUBDIRS,
        logfile=cmor_logfile
    )

    # read experiment configuration file
    fre_logger.info('cmor is opening: json_exp_config = %s', json_exp_config)
    cmor.dataset_json(json_exp_config)

    # load CMOR table
    fre_logger.info('cmor is loading+setting json_table_config = %s', json_table_config)
    loaded_cmor_table_cfg = cmor.load_table(json_table_config)
    cmor.set_table(loaded_cmor_table_cfg)

    # if ocean tripolar grid, we need the CMIP grids configuration file. load it but don't set the table yet.
    json_grids_config, loaded_cmor_grids_cfg = None, None
    if process_tripolar_data:
        json_grids_config = resolve_mip_era_table_resource(json_table_config, exp_cfg_mip_era, 'grids')
        fre_logger.info('cmor is loading/opening %s', json_grids_config)
        loaded_cmor_grids_cfg = cmor.load_table(json_grids_config)
        cmor.set_table(loaded_cmor_grids_cfg)

    # setup cmor latitude axis if relevant
    cmor_y = None
    if process_tripolar_data:
        fre_logger.warning('calling cmor.axis for a projected y coordinate!!')
        cmor_y = cmor.axis('y_deg', coord_vals=yh[:], cell_bounds=yh_bnds[:], units='degrees')
    elif lat is None:
        fre_logger.warning('lat or lat_bnds is None, skipping assigning cmor_y')
    else:
        fre_logger.info('assigning cmor_y')
        if lat_bnds is None:
            cmor_y = cmor.axis(CMOR_LAT_AXIS_NAME, coord_vals=lat[:], units='degrees_N') #uncovered
        else:
            cmor_y = cmor.axis(CMOR_LAT_AXIS_NAME, coord_vals=lat[:], cell_bounds=lat_bnds, units='degrees_N')
        fre_logger.info('DONE assigning cmor_y')

    # setup cmor longitude axis if relevant
    cmor_x = None
    if process_tripolar_data:
        fre_logger.warning('calling cmor.axis for a projected x coordinate!!')
        cmor_x = cmor.axis('x_deg', coord_vals=xh[:], cell_bounds=xh_bnds[:], units='degrees')
    elif lon is None:
        fre_logger.warning('lon or lon_bnds is None, skipping assigning cmor_x')
    else:
        fre_logger.info('assigning cmor_x')
        if lon_bnds is None:
            cmor_x = cmor.axis(CMOR_LON_AXIS_NAME, coord_vals=lon[:], units='degrees_E') #uncovered
        else:
            cmor_x = cmor.axis(CMOR_LON_AXIS_NAME, coord_vals=lon[:], cell_bounds=lon_bnds, units='degrees_E')
        fre_logger.info('DONE assigning cmor_x')

    cmor_grid = None
    if process_tripolar_data:
        fre_logger.warning('setting cmor.grid, process_tripolar_data = %s', process_tripolar_data)
        cmor_grid = cmor.grid(axis_ids=[cmor_y, cmor_x],
                              latitude=lat[:], longitude=lon[:],
                              latitude_vertices=lat_bnds[:],
                              longitude_vertices=lon_bnds[:])

        # now that we are done with setting the grid, we can go back to the usual approach
        cmor.set_table(loaded_cmor_table_cfg)

    # setup cmor time axis if relevant
    cmor_time = None
    ntimes_passed = None
    fre_logger.info('assigning cmor_time')
    try:
        fre_logger.info('assigning cmor_time using time_bnds...')
        ntimes_passed=len(time_coords)
        fre_logger.debug('Executing: \n'
            'cmor.axis(\'time\', \n'
            '    coord_vals = %s, \n'
            '    length = %s, \n'
            '    cell_bounds = %s, units = %s)',
            time_coords, ntimes_passed, time_bnds, time_coord_units
        )
        cmor_time = cmor.axis('time',
                              units=time_coord_units,
                              length=ntimes_passed,
                              coord_vals=time_coords,
                              cell_bounds=time_bnds,
                              interval=None)#interval='mon')#
    except Exception as exc: #ValueError as exc: #uncovered
        fre_logger.error('exc is %s', str(exc))
        fre_logger.info('assigning cmor_time WITHOUT time_bnds...')
        ntimes_passed=len(time_coords)
        fre_logger.debug('Executing: \n'
            'cmor_time = cmor.axis(\'time\', \n'
            '    coord_vals = %s, \n'
            '    length = %s, \n'
            '    cell_bounds = None, units = %s)',
            time_coords, ntimes_passed, time_coord_units
        )
        cmor_time = cmor.axis('time',
                              units=time_coord_units,
                              length=ntimes_passed,
                              coord_vals=time_coords,
                              cell_bounds=None,
                              interval=None)#interval='mon')

    fre_logger.info('DONE assigning cmor_time')

    # other vertical-axis-relevant initializations
    save_ps, ps, ips = False, None, None
    ierr_ap, ierr_b = None, None

    # set cmor vertical axis if relevant
    cmor_z = None
    if lev is not None:
        fre_logger.info('assigning cmor_z')

        if vert_dim.lower() in NON_HYBRID_SIGMA_COORDS:
            fre_logger.info('vert_dim is NON_HYBRID_SIGMA_COORDS')
            if vert_dim.lower() != 'landuse':
                cmor_vert_dim_name = vert_dim
                lev_vals = np.atleast_1d(np.array(lev[:]))
                cmor_z = cmor.axis(cmor_vert_dim_name,
                                   coord_vals=lev_vals, units=lev_units)
            else:
                landuse_str_list = ['primary_and_secondary_land', 'pastures', 'crops', 'urban']
                cmor_vert_dim_name = 'landUse' if exp_cfg_mip_era in ['CMIP6', 'CMIP6PLUS'] else 'landuse'
                cmor_z = cmor.axis(cmor_vert_dim_name,
                                   coord_vals=np.array(
                                       landuse_str_list,
                                       dtype=f'S{len(landuse_str_list[0])}'
                                   ),
                                   units=lev_units)

        elif vert_dim.lower() in DEPTH_COORDS:
            fre_logger.info('vert_dim is DEPTH_COORDS')
            try:
                lev_bnds = create_lev_bnds(bound_these=lev, with_these=ds['z_i'])
                fre_logger.info('created lev_bnds...')
            except Exception as exc:
                fre_logger.error('the cmor module always requires vertical levels to have bounds.')
                raise KeyError('CMOR requires the input data have vertical level boundaries (bnds)') from exc

            fre_logger.info('lev_bnds = \n%s', lev_bnds)
            cmor_z = cmor.axis('depth_coord',
                               coord_vals=lev[:],
                               units=lev_units,
                               cell_bounds=lev_bnds)

        elif vert_dim in ALT_HYBRID_SIGMA_COORDS:
            fre_logger.info('vert_dim is ALT_HYBRID_SIGMA_COORDS')
            # find the surface-pressure file, see find_ps_companion for where it may come from
            if ps_file is None and ps_searched is None:
                ps_file, ps_var, ps_searched = find_ps_companion(netcdf_file, local_var)
            if ps_file is None:
                raise FileNotFoundError(
                    f'no surface-pressure (ps) file found for hybrid-sigma variable {local_var} '
                    f'in {netcdf_file}.\n'
                    '  searched:\n    ' + '\n    '.join(ps_searched or []) + '\n'
                    '  map a ps variable in this MIP table\'s variable list, provide the companion '
                    '.ps.nc file alongside the input, or set ps_component for the table in the cmor yaml.')
            fre_logger.info('reading surface pressure %s from %s', ps_var, ps_file)
            with nc.Dataset(ps_file) as ds_ps:
                ps = from_ds_get_this(ds_ps, ps_var)
            if ps is None:
                raise KeyError(f'surface-pressure variable {ps_var} not found in {ps_file}')
            if ps.shape[0] != var.shape[0]:
                raise ValueError(
                    f'surface-pressure time length {ps.shape[0]} in {ps_file} does not match '
                    f'{local_var} time length {var.shape[0]} in {netcdf_file}')

            # assign lev_half specifics
            if vert_dim == 'levhalf':
                cmor_z = cmor.axis('alternate_hybrid_sigma_half',
                                   coord_vals=lev[:],
                                   units=lev_units)
                ierr_ap = cmor.zfactor(zaxis_id=cmor_z,
                                       zfactor_name='ap_half',
                                       axis_ids=[cmor_z, ],
                                       zfactor_values=ds['ap_bnds'][:],
                                       units=ds['ap_bnds'].units)
                ierr_b = cmor.zfactor(zaxis_id=cmor_z,
                                      zfactor_name='b_half',
                                      axis_ids=[cmor_z, ],
                                      zfactor_values=ds['b_bnds'][:],
                                      units=ds['b_bnds'].units)
            else:
                cmor_z = cmor.axis('alternate_hybrid_sigma',
                                   coord_vals=lev[:],
                                   units=lev_units,
                                   cell_bounds=ds[vert_dim + '_bnds'])
                ierr_ap = cmor.zfactor(zaxis_id=cmor_z,
                                       zfactor_name='ap',
                                       axis_ids=[cmor_z, ],
                                       zfactor_values=ds['ap'][:],
                                       zfactor_bounds=ds['ap_bnds'][:],
                                       units=ds['ap'].units)
                ierr_b = cmor.zfactor(zaxis_id=cmor_z,
                                      zfactor_name='b',
                                      axis_ids=[cmor_z, ],
                                      zfactor_values=ds['b'][:],
                                      zfactor_bounds=ds['b_bnds'][:],
                                      units=ds['b'].units)

            fre_logger.info('ierr_ap after calling cmor_zfactor: %s\n', ierr_ap)
            fre_logger.info('ierr_b after calling cmor_zfactor: %s', ierr_b)

            axis_ids = []
            if cmor_time is not None:
                fre_logger.info('appending cmor_time to axis_ids list...')
                axis_ids.append(cmor_time)
                fre_logger.info('axis_ids now = %s', axis_ids)
                # might there need to be a conditional check for tripolar ocean data here as well? TODO
            if cmor_y is not None:
                fre_logger.info('appending cmor_y to axis_ids list...')
                axis_ids.append(cmor_y)
                fre_logger.info('axis_ids now = %s', axis_ids)
            if cmor_x is not None:
                fre_logger.info('appending cmor_x to axis_ids list...')
                axis_ids.append(cmor_x)
                fre_logger.info('axis_ids now = %s', axis_ids)

            ips = cmor.zfactor(zaxis_id=cmor_z,
                               zfactor_name='ps',
                               axis_ids=axis_ids,
                               units='Pa')
            save_ps = True


        fre_logger.info('DONE assigning cmor_z')

    axes = []
    if cmor_time is not None:
        fre_logger.info('appending cmor_time to axes list...')
        axes.append(cmor_time)
        fre_logger.info('axes now = %s', axes)

    if cmor_z is not None:
        fre_logger.info('appending cmor_z to axes list...')
        axes.append(cmor_z)
        fre_logger.info('axes now = %s', axes)

    if process_tripolar_data:
        axes.append(cmor_grid)
    else:
        if cmor_y is not None:
            fre_logger.info('appending cmor_y to axes list...')
            axes.append(cmor_y)
            fre_logger.info('axes now = %s', axes)
        if cmor_x is not None:
            fre_logger.info('appending cmor_x to axes list...')
            axes.append(cmor_x)
            fre_logger.info('axes now = %s', axes)

    # read positive/units attribute and create cmor_var
    #units = mip_var_cfgs['variable_entry'][target_var]['units']
    if exp_cfg_mip_era == 'CMIP7':
        units = mip_var_cfgs['variable_entry'][f'{target_var}_{var_brand}']['units']
    else:
        units = mip_var_cfgs['variable_entry'][target_var]['units']
    fre_logger.info('units = %s', units)

    #positive = mip_var_cfgs['variable_entry'][target_var]['positive']
    if exp_cfg_mip_era == 'CMIP7':
        positive = mip_var_cfgs['variable_entry'][f'{target_var}_{var_brand}']['positive']
    else:
        positive = mip_var_cfgs['variable_entry'][target_var]['positive']
    fre_logger.info('positive = %s', positive)

    if exp_cfg_mip_era == 'CMIP7':
        fre_logger.info('cmor.variable call: for cmip7_target_var = %s ', f'{target_var}_{var_brand}')

        cmor_var = cmor.variable(f'{target_var}_{var_brand}', units, axes,
                                 missing_value = var_missing_val,
                                 positive = positive)
        fre_logger.info('DONE cmor.variable call: for cmip7_target_var = %s ',f'{target_var}_{var_brand}')

        # need to add this kind of file opening
        fre_logger.info('NOW trying to add the cell_measures field from CMIP7_cell_measures.json')
        with open(f'{Path(json_table_config).parent}/CMIP7_cell_measures.json', 'r', encoding='utf-8') as handle:
            cell_measures = json.load(handle)['cell_measures']

            # need to add this kind of line
            fre_logger.debug('setting cell_measures attribute for cmor variable: %s', cmor_var)
            cmor.set_variable_attribute(
                cmor_var,
                'cell_measures',
                'c',
                cell_measures.get(f'{target_var}_{var_brand}', ''),
            )


    else:
        fre_logger.info('cmor.variable call: for target_var = %s ',target_var)
        cmor_var = cmor.variable(target_var, units, axes,
                                 missing_value = var_missing_val,
                                 positive = positive)
        fre_logger.info('DONE cmor.variable call: for target_var = %s ',target_var)

    # Write the output to disk
    #fre_logger.debug('var is: %s', var)
    fre_logger.info('cmor.write call: for var data into cmor_var')
    cmor.write(cmor_var, var)
    fre_logger.info('DONE cmor.write call: for var data into cmor_var')
    if save_ps:
        if any([ips is None, ps is None]):
            fre_logger.warning('ps or ips is None!, but save_ps is True!\n' #uncovered
                               'ps = %s, ips = %s\n'
                               'skipping ps writing!', ps, ips)
        else:
            fre_logger.info('cmor.write call: for interp-pressure data (ips)')
            cmor.write(ips, ps, store_with=cmor_var, ntimes_passed=ntimes_passed)
            fre_logger.info('DONE cmor.write call: for interp-pressure data (ips)')

    fre_logger.info('cmor.close call: for cmor_var')
    filename = cmor.close(cmor_var, file_name=True, preserve=False)
    fre_logger.info('DONE cmor.close call: for cmor_var')
    filename = str( Path(filename).resolve() )
    fre_logger.info('returned by cmor.close: filename = %s', filename)
    fre_logger.info('closing netcdf4 dataset... ds')
    ds.close()
    fre_logger.info('tearing-down the cmor module instance')
    cmor.close()

    fre_logger.info('-------------------------- END rewrite_netcdf_file_var call -----\n\n')
    return filename


def cmorize_target_var_files(indir: str = None,
                             target_var: str = None,
                             local_var: str = None,
                             iso_datetime_range_arr: List[str] = None,
                             name_of_set: str = None,
                             json_exp_config: str = None,
                             outdir: str = None,
                             mip_var_cfgs: Dict[str, Any] = None,
                             json_table_config: str = None,
                             run_one_mode: bool = False,
                             ps_source: Optional[Dict[str, str]] = None,
                             ps_fallback: Optional[Dict[str, str]] = None,
                             existing_outputs: Optional[List[Path]] = None):
    """
    CMORize a target variable across all NetCDF files in a directory.

    :param indir: Path to the directory containing NetCDF files to process.
    :type indir: str
    :param target_var: MIP table variable name for metadata lookups.
    :type target_var: str
    :param local_var: Modeler's variable name, used for file-targeting and reading data from files.
    :type local_var: str
    :param iso_datetime_range_arr: List of ISO datetime strings, each identifying a specific file.
    :type iso_datetime_range_arr: list of str
    :param name_of_set: Post-processing component or label for the targeted files.
    :type name_of_set: str
    :param json_exp_config: Path to experiment configuration JSON file.
    :type json_exp_config: str
    :param outdir: Output directory root for CMORized files.
    :type outdir: str
    :param mip_var_cfgs: Variable table from the MIP table JSON config.
    :type mip_var_cfgs: dict
    :param json_table_config: Path to MIP table JSON file.
    :type json_table_config: str
    :param run_one_mode: If True, processes only one file and exits.
    :type run_one_mode: bool, optional
    :param ps_source: Optional ``{'indir': ..., 'local_var': ...}`` locating the table's mapped ps variable,
                      searched before the companion ``.ps.nc`` file. See ``find_ps_companion``.
    :type ps_source: dict, optional
    :param ps_fallback: Optional ``{'indir': ..., 'local_var': ...}`` locating the cmor yaml's ``ps_component``,
                        searched after the companion ``.ps.nc`` file.
    :type ps_fallback: dict, optional
    :param existing_outputs: If given (see ``index_existing_outputs``), input files whose output
                             is already among these are skipped rather than CMORized again.
    :type existing_outputs: list of Path, optional
    :raises ValueError: See function body for details.
    :raises OSError: See function body for details.
    :raises Exception: See function body for details.
    :return: None
    :rtype: None

    .. note:: Copies files to a temporary directory, runs CMORization, moves results to output, cleans up temp files.
    """

    fre_logger.info('local_var = %s to be used for file-targeting and reading data.\n'
                    'target_var = %s to be used for MIP table lookups.\n'
                    'outdir = %s', local_var, target_var, outdir)

    # determine a tmp dir for working on files.
    tmp_dir = create_tmp_dir(outdir, json_exp_config) + '/'
    fre_logger.info('will use tmp_dir=%s', tmp_dir)

    mip_era = get_json_file_data(json_exp_config)['mip_era'].upper() if existing_outputs is not None else None
    skipped_files = []

    # loop over sets of dates, each one pointing to a file
    nc_fls = {}
    for i, iso_datetime in enumerate(iso_datetime_range_arr):
        # why is nc_fls a filled list/array/object thingy here? see above line
        nc_fls[i] = f'{indir}/{name_of_set}.{iso_datetime}.{local_var}.nc'

        fre_logger.info('input file = %s', nc_fls[i])
        if not Path(nc_fls[i]).exists():
            fre_logger.warning('input file not found, omitting: %s', nc_fls[i])
            continue

        if not Path(nc_fls[i]).is_absolute():
            nc_fls[i]=str(Path(nc_fls[i]).resolve())

        if existing_outputs is not None:
            prefix = expected_output_prefix(nc_fls[i], local_var, target_var,
                                            mip_var_cfgs, json_table_config, mip_era)
            existing_output = find_existing_output(prefix, iso_datetime, existing_outputs)
            if existing_output is not None:
                fre_logger.info('output already exists, skipping input file %s: %s',
                                nc_fls[i], existing_output)
                skipped_files.append(nc_fls[i])
                continue

        # create a copy of the input file with local var name into the work directory
        nc_file_work = f'{tmp_dir}{name_of_set}.{iso_datetime}.{local_var}.nc'

        fre_logger.info('nc_file_work = %s', nc_file_work)
        shutil.copy(nc_fls[i], nc_file_work)

        # if a ps file is found, we'll copy it to the work directory too
        nc_ps_file, ps_var, ps_searched = find_ps_companion(nc_fls[i], local_var,
                                                                ps_source, ps_fallback)
        nc_ps_file_work = None
        if nc_ps_file is not None and Path(nc_ps_file).resolve() != Path(nc_fls[i]).resolve():
            nc_ps_file_work = f'{tmp_dir}{Path(nc_ps_file).name}'
            fre_logger.info('nc_ps_file_work = %s', nc_ps_file_work)
            shutil.copy(nc_ps_file, nc_ps_file_work)

        # TODO think of better way to write this kind of conditional data movement...
        # now we have a file in our targets, point CMOR to the configs and the input file(s)
        make_cmor_write_here = tmp_dir
        # make sure we know where we are writing, or else!
        if not Path(make_cmor_write_here).exists():
            raise ValueError(f'\ntmp_dir = \n{tmp_dir}\ncannot be found/created/resolved!') #uncovered

        gotta_go_back_here = os.getcwd()
        try:
            fre_logger.warning('changing directory to: \n%s', make_cmor_write_here)
            os.chdir(make_cmor_write_here)
        except Exception as exc: #uncovered
            raise OSError(f'(cmorize_target_var_files) could not chdir to {make_cmor_write_here}') from exc

        fre_logger.info('calling rewrite_netcdf_file_var')
        try:
            local_file_name = rewrite_netcdf_file_var(mip_var_cfgs,
                                                      local_var,
                                                      nc_file_work,
                                                      target_var,
                                                      json_exp_config,
                                                      json_table_config,
                                                      prev_path=nc_fls[i],
                                                      ps_file=nc_ps_file_work,
                                                      ps_var=ps_var,
                                                      ps_searched=ps_searched )
        except Exception as exc:
            raise Exception(
                'problem with rewrite_netcdf_file_var. '
                f'exc={exc}\n'
                'exiting and executing finally block.') from exc
        finally:  # should always execute, errors or not!
            fre_logger.warning('finally, changing directory to: \n%s', gotta_go_back_here)
            os.chdir(gotta_go_back_here)

#        assert False, 'made it to break-point for current work, good job'

        # now that CMOR has rewritten things... we can take our post-rewriting actions
        # first, remove /CMOR_tmp/ from the output path.
        if not Path(local_file_name).is_absolute():
            raise ValueError(f'local_file_name should be an absolute path, not a relative one. \n '
                             f'local_file_name = {local_file_name}')

        fre_logger.info('local_file_name = %s', local_file_name)
        filename = local_file_name.replace('/CMOR_tmp/','/')
        fre_logger.info('filename = %s', filename)

        # the final output file directory will be...
        filedir = Path(filename).parent
        fre_logger.info('FINAL OUTPUT FILE DIR WILL BE filedir = %s', filedir)
        try:
            fre_logger.info('ATTEMPTING TO CREATE filedir=%s', filedir)
            os.makedirs(filedir)
        except FileExistsError:
            fre_logger.warning('directory %s already exists!', filedir)

        if Path(local_file_name).resolve() == Path(filename).resolve():
            # cmor.close(), with create_subdirectories enabled, sometimes writes the output file
            # directly to its final DRS location (no /CMOR_tmp/ in the returned path) rather than
            # into the tmp_dir this function expects to relocate from. When that happens the file
            # is already where it needs to be, and 'mv'-ing it onto itself would just fail.
            fre_logger.info('cmor already wrote the final output file directly to %s; nothing to move',
                            filename)
        else:
            mv_cmd = f'mv {local_file_name} {filedir}'
            fre_logger.info('moving files...\n%s', mv_cmd)
            subprocess.run(mv_cmd, shell=True, check=True)

        # ------ refactor this into function? #TODO
        # ------ what is the use case for this logic really??
        filename_no_nc = filename[:filename.rfind('.nc')]
        chunk_str = filename_no_nc[-6:]
        if not chunk_str.isdigit():
            fre_logger.warning('chunk_str is not a digit: chunk_str = %s', chunk_str)
            filename_corr = f'{filename[:filename.rfind(".nc")]}_{iso_datetime}.nc'
            mv_cmd = f'mv {filename} {filename_corr}'
            fre_logger.warning('moving files, strange chunkstr logic...\n%s', mv_cmd)
            subprocess.run(mv_cmd, shell=True, check=True)
        # ------ end refactor this into function?

        # delete files in work dirs
        if Path(nc_file_work).exists():
            Path(nc_file_work).unlink()

        if nc_ps_file_work is not None and Path(nc_ps_file_work).exists():
            Path(nc_ps_file_work).unlink()

        if run_one_mode:
            fre_logger.warning('run_one_mode is True!!!!')
            fre_logger.warning('done processing one file!!!')
            break

    if skipped_files:
        fre_logger.warning('%s: skipped %d of %d input file(s) whose output already exists',
                           local_var, len(skipped_files), len(iso_datetime_range_arr))


def cmorize_all_variables_in_dir(vars_to_run: Dict[str, Any],
                                 indir: str,
                                 iso_datetime_range_arr: List[str],
                                 name_of_set: str,
                                 json_exp_config: str,
                                 outdir: str,
                                 mip_var_cfgs: Dict[str, Any],
                                 json_table_config: str,
                                 run_one_mode: bool,
                                 ps_source: Optional[Dict[str, str]] = None,
                                 ps_fallback: Optional[Dict[str, str]] = None,
                                 existing_outputs: Optional[List[Path]] = None) -> int:
    """
    CMORize all variables in a directory according to a variable mapping.

    :param vars_to_run: Mapping of modeler variable names to MIP table variable names.
    :type vars_to_run: dict
    :param indir: Directory containing NetCDF files to process.
    :type indir: str
    :param iso_datetime_range_arr: List of ISO datetime strings to identify files.
    :type iso_datetime_range_arr: list of str
    :param name_of_set: Post-processing component or set label.
    :type name_of_set: str
    :param json_exp_config: Path to experiment configuration JSON file.
    :type json_exp_config: str
    :param outdir: Output directory root for CMORized files.
    :type outdir: str
    :param mip_var_cfgs: Variable table from the MIP table JSON config.
    :type mip_var_cfgs: dict
    :param json_table_config: Path to MIP table JSON file.
    :type json_table_config: str
    :param run_one_mode: If True, process only one file per variable.
    :type run_one_mode: bool
    :param ps_source: Optional ``{'indir': ..., 'local_var': ...}`` locating the table's mapped ps variable.
    :type ps_source: dict, optional
    :param ps_fallback: Optional ``{'indir': ..., 'local_var': ...}`` locating the cmor yaml's ``ps_component``.
    :type ps_fallback: dict, optional
    :param existing_outputs: Existing output files to skip inputs for, see ``cmorize_target_var_files``.
    :type existing_outputs: list of Path, optional
    :return: 0 if last file processed was successful, 1 if last file processed failed, -1 if no files were processed.
    :rtype: int

    .. note:: Errors for individual variables are logged and processing continues (except for run_one_mode).
    """

    # loop over modeler-variable:mip-variable pairs in vars_to_run
    return_status = -1
    omissions = []
    for local_var in vars_to_run:
        # if the target-variable is 'good', get the name of the data inside the netcdf file.
        target_var = vars_to_run[local_var]  # often equiv to local_var but not necessarily.
        if local_var != target_var:
            fre_logger.info('local_var == %s != %s == target_var\n'
                            'modeler variable name differs from MIP table variable name.\n'
                            'i am expecting %s in both the filename and the file, and will map it\n'
                            'to MIP table variable %s', local_var, target_var, local_var, target_var)

        fre_logger.info('........beginning CMORization for %s/%s..........', local_var, target_var)
        try:
            cmorize_target_var_files(indir, target_var, local_var, iso_datetime_range_arr,
                                     name_of_set, json_exp_config, outdir,
                                     mip_var_cfgs, json_table_config, run_one_mode,
                                     ps_source=ps_source, ps_fallback=ps_fallback,
                                     existing_outputs=existing_outputs)
            return_status = 0
        except Exception as exc:
            return_status = 1
            fre_logger.exception('!!!EXCEPTION CAUGHT!!!')
            fre_logger.warning('this message came from within cmorize_target_var_files')
            fre_logger.warning('COULD NOT PROCESS: %s/%s...moving on', local_var, target_var)
            expected_files = [
                f'{indir}/{name_of_set}.{dt}.{local_var}.nc'
                for dt in iso_datetime_range_arr
            ]
            omissions.append(
                {'local_var': local_var, 'target_var': target_var,
                 'exception': str(exc), 'files': expected_files}
            )

        if run_one_mode:
            fre_logger.warning('run_one_mode is True. breaking vars_to_run loop')
            break

    if len(omissions) > 0:
        fre_logger.warning('--- OMISSION LOG: %s %s could not be processed ---',
                         len(omissions), 'variable' if len(omissions) == 1 else 'variables')
        for entry in omissions:
            fre_logger.warning('  OMITTED local_var=%s / target_var=%s, reason: %s',
                               entry['local_var'], entry['target_var'], entry['exception'])
            for fpath in entry['files']:
                fre_logger.warning('    file: %s', fpath)
        fre_logger.warning('--- END OMISSION LOG ---')

    return return_status


def cmor_run_subtool(indir: str = None,
                     json_var_list: str = None,
                     json_table_config: str = None,
                     json_exp_config: str = None,
                     outdir: str = None,
                     run_one_mode: Optional[bool] = False,
                     opt_var_name: Optional[str] = None,
                     grid: Optional[str] = None,
                     grid_label: Optional[str] = None,
                     nom_res: Optional[str] = None,
                     start: Optional[str] = None,
                     stop: Optional[str] = None,
                     calendar_type: Optional[str] = None,
                     ps_source: Optional[Dict[str, str]] = None,
                     ps_fallback: Optional[Dict[str, str]] = None,
                     skip_existing: bool = False) -> int:
    """
    Main entry point for CMORization workflow, steering all routines in this file.

    :param indir: Directory containing NetCDF files to process.
    :type indir: str
    :param json_var_list: Path to JSON file with variable mapping (modeler names to MIP table names).
    :type json_var_list: str
    :param json_table_config: Path to MIP table JSON file (per-variable metadata).
    :type json_table_config: str
    :param json_exp_config: Path to experiment configuration JSON file (for header metadata).
    :type json_exp_config: str
    :param outdir: Output directory root for CMORized files.
    :type outdir: str
    :param run_one_mode: If True, process only one file per variable.
    :type run_one_mode: bool, optional
    :param opt_var_name: If provided, only process this variable.
    :type opt_var_name: str, optional
    :param grid: Grid description (if gridding is specified).
    :type grid: str, optional
    :param grid_label: Grid label (must match controlled vocabulary if provided).
    :type grid_label: str, optional
    :param nom_res: Nominal resolution for grid (must match controlled vocabulary if provided).
    :type nom_res: str, optional
    :param start: Start year (YYYY) for files to process.
    :type start: str, optional
    :param stop: Stop year (YYYY) for files to process.
    :type stop: str, optional
    :param calendar_type: CF-compliant calendar type.
    :type calendar_type: str, optional
    :param ps_source: Optional ``{'indir': ..., 'local_var': ...}`` locating the table's mapped ps variable,
                      used as the surface-pressure companion for hybrid-sigma variables. If None and
                      ``json_var_list`` maps a local variable to the table's ps, that one is used.
    :type ps_source: dict, optional
    :param ps_fallback: Optional ``{'indir': ..., 'local_var': ...}`` locating the cmor yaml's ``ps_component``,
                        searched after the companion ``.ps.nc`` file.
    :type ps_fallback: dict, optional
    :param skip_existing: If True, skip input files whose CMOR output already exists under ``outdir``,
                          and only CMORize the missing ones.
    :type skip_existing: bool
    :raises ValueError: If required parameters are missing or inconsistent.
    :raises FileNotFoundError: If required files do not exist.
    :return: 0 if successful.
    :rtype: int

    .. note:: Updates grid, label, and calendar fields in experiment config if needed.
    .. note:: Loads variable mapping and MIP table, filters variables, and orchestrates file processing.
    """
    # CHECK req'd inputs
    if None in [indir, json_var_list, json_table_config, json_exp_config, outdir]:
        raise ValueError('the following input arguments are required:\n'
                         '[indir, json_var_list, json_table_config, json_exp_config, outdir] = \n'
                        f'[{indir}, {json_var_list}, {json_table_config}, {json_exp_config}, {outdir}]')

    # CHECK existence of the exp-specific metadata file
    if Path(json_exp_config).exists():
        json_exp_config = str(Path(json_exp_config).resolve())
    else:
        raise FileNotFoundError('ERROR: json_exp_config file cannot be opened.\n'
                               f'json_exp_config = {json_exp_config}')

    # CHECK mip_era entry of exp config exists, needed ?
    try:
        exp_cfg_mip_era = get_json_file_data(json_exp_config)['mip_era'].upper()
    except KeyError as exc:
        raise KeyError('no mip_era entry in experimental metadata configuration, the file is noncompliant!') from exc

    fre_logger.debug('exp_cfg_mip_era = %s', exp_cfg_mip_era)
    if exp_cfg_mip_era not in ['CMIP6', 'CMIP6PLUS', 'CMIP7']:
        raise ValueError('cmor_mixer only supports CMIP6, CMIP6 Plus, and CMIP7 cases')

    if exp_cfg_mip_era == 'CMIP7':
        fre_logger.warning('CMIP7 config detected, will be expecting and enforcing variable brands.')

    if exp_cfg_mip_era == 'CMIP6PLUS':
        fre_logger.warning('CMIP6Plus config detected, capability under development, treating as a CMIP6 case for now')

    # CHECK optional grid/grid_label/nom_res inputs from exp config, the function raises the potential error conditions
    if any( [ grid_label is not None,
              grid is not None,
              nom_res is not None ] ):
        update_grid_and_label(json_exp_config,
                              grid_label, grid, nom_res,
                              output_file_path = None)

    # CHECK optional grid/grid_label inputs, the function checks the potential error conditions RE CF compliance.
    if calendar_type is not None:
        update_calendar_type(json_exp_config, calendar_type, output_file_path = None)


    # open CMOR table config file - need it here for checking the TABLE's variable list
    json_table_config = str(Path(json_table_config).resolve())
    fre_logger.info('loading json_table_config = \n%s', json_table_config)

    mip_var_cfgs = get_json_file_data(json_table_config)
    table_mip_era = mip_var_cfgs.get('Header', {}).get('mip_era')
    table_name_prefix = Path(json_table_config).stem.split('_', maxsplit=1)[0].upper()
    if isinstance(table_mip_era, str):
        table_mip_era = table_mip_era.upper()
    elif table_name_prefix in ['CMIP6', 'CMIP6PLUS', 'CMIP7', 'MIP']:
        # CMIP6Plus tables (PCMDI/mip-cmor-tables) are named MIP_<table>.json, so the bare
        # 'MIP' prefix identifies a CMIP6Plus table set.
        table_mip_era = 'CMIP6PLUS' if table_name_prefix == 'MIP' else table_name_prefix

    if table_mip_era is not None and table_mip_era != exp_cfg_mip_era:
        raise ValueError(
            'mip_era mismatch between experiment config and MIP table.\n'
            f'  experiment mip_era: {exp_cfg_mip_era}\n'
            f'  table format detected in {json_table_config}: {table_mip_era}\n'
            '  supply a MIP table that matches the experiment mip_era.')

    # CHECK the exp config against the CV before any CMORization work happens. this runs after the
    # grid/calendar updates above so it sees what CMOR will actually see -- the cmor yaml's gridding
    # block is written into the exp config there, and can blank out fields the user filled in.
    check_exp_config_required_attributes(json_exp_config, json_table_config)
    mip_fullvar_list = mip_var_cfgs['variable_entry'].keys()
    fre_logger.debug('the following variables were read from the table: %s', mip_fullvar_list)

    # make the TABLE's variable list, and brand list (if CMIP7)
    mip_var_list, mip_var_brand_list = None, None
    if exp_cfg_mip_era == 'CMIP7':
        fre_logger.warning('cmip7 capabilities in-development now. extracting brands from variables '
                           'within MIP cmor table configs')
        mip_var_list = [ var.split('_')[0] for var in mip_fullvar_list ]
        mip_var_brand_list = [ var.split('_')[1] for var in mip_fullvar_list ]
        if len(mip_var_list) != len(mip_var_brand_list):
            raise ValueError('the number of brands is not one-to-one with the number of variables. check config.')
    elif exp_cfg_mip_era in ['CMIP6', 'CMIP6PLUS']:
        mip_var_list = mip_fullvar_list

    fre_logger.debug('list of table variables we will process = \n %s', mip_var_list)
    if mip_var_brand_list is not None:
        fre_logger.debug('the following brands were extracted from the variables: %s', mip_var_brand_list)

    # open USER input variable list, no brands required regardless of CMIP6/7
    # these are largely for targeting GFDL's input files and reading them
    json_var_list = str(Path(json_var_list).resolve())
    fre_logger.debug('loading json_var_list = \n%s', json_var_list)

    var_list = get_json_file_data(json_var_list)
    fre_logger.debug('var_list is = \n %s', var_list)

    # CHECK that the user's input variables make sense against those in the targeted table
    # if the check(s) pass, the final list of variables to run is stored in vars_to_run
    # if opt_var_name is specified, the routine is short-circuited to care only about opt_var_name
    vars_to_run = {}
    for local_var in var_list:
        if all( [ opt_var_name is not None, opt_var_name != '', opt_var_name in mip_var_list ] ):
            vars_to_run[opt_var_name] = opt_var_name
            break
        if var_list[local_var] not in mip_var_list: #mip_var_cfgs['variable_entry']:
            fre_logger.warning('skipping local_var = %s /\n'
                               'target_var = %s\n'
                               'target_var not found in CMOR variable group', local_var, var_list[local_var])
            continue

        fre_logger.info('%s found in %s', var_list[local_var], Path(json_table_config).name)
        vars_to_run[local_var] = var_list[local_var]
    fre_logger.info('vars_to_run = %s', vars_to_run)

    # CHECK that there's at least one variable to run after comparing use inputs vars to MIP config input vars
    if len(vars_to_run) < 1:
        raise ValueError('runnable variable list is of length 0 '
                         'this means no variables in input variable list are in '
                         'the mip table configuration, so there\'s nothing to process!')
    if all([opt_var_name is not None, opt_var_name != '', opt_var_name not in list(vars_to_run)]):
        raise ValueError(f'opt_var_name is not None! (== {opt_var_name})'
                          '... but the variable is not contained in the target mip table'
                          '... there\'s nothing to process, exit')

    # if the table maps a ps variable, CMORize it first and use it as the surface-pressure
    # companion for the table's hybrid-sigma variables. the user is responsible for the mapping.
    if table_declares_ps(mip_var_cfgs):
        ps_local_vars = [local_var for local_var, target in var_list.items() if target == 'ps']
        if ps_source is None and ps_local_vars:
            if len(ps_local_vars) > 1:
                fre_logger.warning('multiple local variables map to ps: %s, using %s',
                                   ps_local_vars, ps_local_vars[0])
            ps_source = {'indir': str(indir), 'local_var': ps_local_vars[0]}
        vars_to_run = dict(sorted(vars_to_run.items(), key=lambda item: item[1] != 'ps'))
    if ps_source is not None:
        fre_logger.info('using table-mapped ps variable %s in %s as the surface-pressure companion',
                        ps_source['local_var'], ps_source['indir'])

    fre_logger.info('runnable variable list formed, it is vars_to_run=\n%s', vars_to_run)

    # make list of target files within targeted indir here
    # examine input directory to obtain a list of input file targets
    fre_logger.info('indir = %s', indir)
    indir_filenames = glob.glob(f'{indir}/*.nc')
    indir_filenames.sort()
    if len(indir_filenames) == 0:
        raise ValueError(f'no files in input target directory = indir = \n{indir}')
    fre_logger.debug('found %s filenames', len(indir_filenames))

    # name_of_set == component label
    name_of_set = Path(indir_filenames[0]).name.split('.')[0]
    fre_logger.info('setting name_of_set = %s', name_of_set)

    # make list of iso-datetimes here
    iso_datetime_range_arr = []
    get_iso_datetime_ranges(indir_filenames, iso_datetime_range_arr, start, stop)
    fre_logger.info('\nfound iso datetimes = %s', iso_datetime_range_arr)

    # no longer needed.
    del indir_filenames

    existing_outputs = None
    if skip_existing:
        existing_outputs = index_existing_outputs(outdir)
        fre_logger.info('skip_existing: found %d existing output file(s) under %s',
                        len(existing_outputs), outdir)

    # now we descend into more CPU-heavy work here
    return cmorize_all_variables_in_dir( vars_to_run,
                                         indir, iso_datetime_range_arr, name_of_set, json_exp_config,
                                         outdir, mip_var_cfgs, json_table_config, run_one_mode,
                                         ps_source=ps_source, ps_fallback=ps_fallback,
                                         existing_outputs=existing_outputs )
