"""
``fremor``: tripolar ocean grid helpers
=========================================

This module provides functions for setting up and processing tripolar ocean grids
in the CMORization workflow. It is used by ``cmor_mixer`` when ocean data is being
processed on a native MOM6 tripolar grid.

Functions
---------
- ``load_tripolar_grid(ds, netcdf_file, prev_path)``

Notes
-----
Processing tripolar data requires an ocean statics file that contains the geographic
lat/lon coordinates and their cell corner (vertex) equivalents. The function here
handles locating that statics file, reading its coordinates, and writing the necessary
grid coordinate variables into the working NetCDF dataset.
"""

import getpass
import logging
from pathlib import Path
import shutil
from typing import Optional

import netCDF4 as nc

from .cmor_helpers import ( print_data_minmax, from_dis_gimme_dis,
                            find_statics_file, find_gold_ocean_statics_file )

fre_logger = logging.getLogger(__name__)


def load_tripolar_grid( ds: nc.Dataset,
                        netcdf_file: str,
                        prev_path: Optional[str] = None ) -> dict:
    """
    Load tripolar ocean grid coordinates from an ocean statics file into the working dataset.

    This function locates the appropriate ocean statics file (first attempting the gold-standard
    archived file, then falling back to the FRE-bronx directory convention), reads geographic
    lat/lon coordinates for cell centers and corners, and writes ``lat``, ``lon``, ``lat_bnds``,
    ``lon_bnds``, ``yh_bnds``, and ``xh_bnds`` variables into ``ds`` in-place.

    :param ds: Open (writable) NetCDF4 dataset for the variable being CMORized. This dataset is
        modified in-place to add the tripolar grid coordinate variables.
    :type ds: netCDF4.Dataset
    :param netcdf_file: Path to the input NetCDF file being processed. Used to determine where to
        stage a local copy of the statics file.
    :type netcdf_file: str
    :param prev_path: Path to the previous file (used as a hint for locating the statics file
        under the legacy FRE-bronx directory convention).
    :type prev_path: str, optional
    :raises FileNotFoundError: If the ocean statics file cannot be found through any fallback.
    :raises ValueError: If the number of h-point coordinates is inconsistent with the number of
        q-point coordinates (i.e. ``hpoint_dim != qpoint_dim - 1``).
    :return: Dictionary containing the grid coordinate arrays written into ``ds``:

        - ``lat``: 2-D cell-center latitude variable (``netCDF4.Variable``).
        - ``lon``: 2-D cell-center longitude variable (``netCDF4.Variable``).
        - ``lat_bnds``: 2-D cell-corner latitude bounds variable (``netCDF4.Variable``).
        - ``lon_bnds``: 2-D cell-corner longitude bounds variable (``netCDF4.Variable``).
        - ``yh``: 1-D projected y-axis coordinate array (``numpy.ndarray``).
        - ``xh``: 1-D projected x-axis coordinate array (``numpy.ndarray``, offset by +300).
        - ``yh_bnds``: 1-D y-axis bounds variable (``netCDF4.Variable``).
        - ``xh_bnds``: 1-D x-axis bounds variable (``netCDF4.Variable``).
    :rtype: dict
    """
    fre_logger.info('netcdf_file is %s', netcdf_file)

    # first, try the gold-standard archived ocean statics file
    statics_file_path = None
    try:
        statics_file_path = find_gold_ocean_statics_file(
            put_copy_here=f'/net2/{getpass.getuser()}')
    except (OSError, FileNotFoundError) as exc:
        fre_logger.warning('gold statics lookup raised %s, trying FRE-bronx fallback', exc)

    # fall back to the legacy FRE-bronx directory convention if gold statics was unavailable
    if statics_file_path is None and prev_path is not None:
        fre_logger.info('gold statics not available, falling back to find_statics_file')
        statics_file_path = find_statics_file(prev_path)

    fre_logger.info('statics_file_path is %s', statics_file_path)

    if statics_file_path is None:
        raise FileNotFoundError('statics file not found.')

    fre_logger.info('statics file found.')

    statics_file_name = Path(statics_file_path).name
    put_statics_file_here = str(Path(netcdf_file).parent)
    shutil.copy(statics_file_path, put_statics_file_here)
    del statics_file_path

    statics_file_path = put_statics_file_here + '/' + statics_file_name
    fre_logger.info('statics file path is now: %s', statics_file_path)

    # statics file read
    statics_ds = nc.Dataset(statics_file_path, 'r')

    # grab the h-point lat and lon
    fre_logger.info('reading yh, xh')
    yh = from_dis_gimme_dis(ds, 'yh')
    xh = from_dis_gimme_dis(ds, 'xh') + 300.

    fre_logger.info('')
    print_data_minmax(yh[:], 'yh')
    print_data_minmax(xh[:], 'xh')
    fre_logger.info('')

    yh_dim = len(yh)
    xh_dim = len(xh)

    # read the q-point native-grid lat lon points
    fre_logger.info('reading yq, xq from statics file')
    yq = from_dis_gimme_dis(statics_ds, 'yq')
    xq = from_dis_gimme_dis(statics_ds, 'xq') + 300.

    fre_logger.info('')
    print_data_minmax(yq, 'yq')
    print_data_minmax(xq, 'xq')
    fre_logger.info('')

    xq_dim = len(xq)
    yq_dim = len(yq)

    if any( [yh_dim != (yq_dim - 1),
             xh_dim != (xq_dim - 1)]):
        raise ValueError(
            'the number of h-point lat/lon coordinates is inconsistent with the number of\n'
            'q-point lat/lon coordinates! i.e. ( hpoint_dim != qpoint_dim-1 )\n'
            f'yh_dim = {yh_dim}\n'
            f'xh_dim = {xh_dim}\n'
            f'yq_dim = {yq_dim}\n'
            f'xq_dim = {xq_dim}'
        )


    # grab the lat/lon points, have shape (yh, xh)
    fre_logger.info('reading geolat and geolon coordinates of cell centers from statics file')
    statics_lat = from_dis_gimme_dis(statics_ds, 'geolat')
    statics_lon = from_dis_gimme_dis(statics_ds, 'geolon') + 300.

    fre_logger.info('')
    print_data_minmax(statics_lat, 'statics_lat')
    print_data_minmax(statics_lon, 'statics_lon')
    fre_logger.info('')

    # spherical lat and lon coords
    fre_logger.info('creating lat and lon variables in temp file')
    lat = ds.createVariable('lat', statics_lat.dtype, ('yh', 'xh'))
    lon = ds.createVariable('lon', statics_lon.dtype, ('yh', 'xh'))
    lat[:] = statics_lat[:]
    lon[:] = statics_lon[:]

    fre_logger.info('')
    print_data_minmax(lat[:], 'lat')
    print_data_minmax(lon[:], 'lon')
    fre_logger.info('')

    # grab the corners of the cells, should have shape (yh+1, xh+1)
    fre_logger.info('reading geolat and geolon coordinates of cell corners from statics file')
    lat_c = from_dis_gimme_dis(statics_ds, 'geolat_c')
    lon_c = from_dis_gimme_dis(statics_ds, 'geolon_c') + 300.

    fre_logger.info('')
    print_data_minmax(lat_c, 'lat_c')
    print_data_minmax(lon_c, 'lon_c')
    fre_logger.info('')

    # vertex
    fre_logger.info('creating vertex dimension')
    vertex = 4
    ds.createDimension('vertex', vertex)

    # lat and lon bnds
    fre_logger.info('creating lat and lon bnds from geolat and geolon of corners')
    lat_bnds = ds.createVariable('lat_bnds', lat_c.dtype, ('yh', 'xh', 'vertex'))
    lat_bnds[:, :, 0] = lat_c[1:, 1:]  # NE corner
    lat_bnds[:, :, 1] = lat_c[1:, :-1]  # NW corner
    lat_bnds[:, :, 2] = lat_c[:-1, :-1]  # SW corner
    lat_bnds[:, :, 3] = lat_c[:-1, 1:]  # SE corner

    lon_bnds = ds.createVariable('lon_bnds', lon_c.dtype, ('yh', 'xh', 'vertex'))
    lon_bnds[:, :, 0] = lon_c[1:, 1:]  # NE corner
    lon_bnds[:, :, 1] = lon_c[1:, :-1]  # NW corner
    lon_bnds[:, :, 2] = lon_c[:-1, :-1]  # SW corner
    lon_bnds[:, :, 3] = lon_c[:-1, 1:]  # SE corner

    fre_logger.info('')
    print_data_minmax(lat_bnds[:], 'lat_bnds')
    print_data_minmax(lon_bnds[:], 'lon_bnds')
    fre_logger.info('')

    # create h-point bounds from the q-point lat lons
    fre_logger.info('creating yh_bnds, xh_bnds from yq, xq')

    yh_bnds = ds.createVariable('yh_bnds', yq.dtype, ('yh', 'nv'))
    for i in range(0, yh_dim):
        yh_bnds[i, 0] = yq[i]
        yh_bnds[i, 1] = yq[i + 1]

    xh_bnds = ds.createVariable('xh_bnds', xq.dtype, ('xh', 'nv'))
    for i in range(0, xh_dim):
        xh_bnds[i, 0] = xq[i]
        xh_bnds[i, 1] = xq[i + 1]
        if i % 200 == 0:
            fre_logger.info('AFTER assignment: xh_bnds[%d][0] = %s', i, xh_bnds[i][0])
            fre_logger.info('AFTER assignment: xh_bnds[%d][1] = %s', i, xh_bnds[i][1])
            fre_logger.info('type(xh_bnds[%d][1]) = %s', i, type(xh_bnds[i][1]))

    fre_logger.info('')
    print_data_minmax(yh_bnds[:], 'yh_bnds')
    print_data_minmax(xh_bnds[:], 'xh_bnds')
    fre_logger.info('')

    return {
        'lat':     lat,
        'lon':     lon,
        'lat_bnds': lat_bnds,
        'lon_bnds': lon_bnds,
        'yh':      yh,
        'xh':      xh,
        'yh_bnds': yh_bnds,
        'xh_bnds': xh_bnds,
    }
