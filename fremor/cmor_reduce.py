"""
Variable-list entries and input reductions
==========================================

A variable list maps each local (modeler) variable name, as found in pp filenames and files,
to a MIP table variable. The value is either the MIP variable name as a plain string::

    {"t_ref": "tas"}

or an object naming it together with a reduction applied to the input before CMORization::

    {"ta": {"name": "ta", "reduce": "zonal_mean"}}

e.g. to write a zonal-mean table such as ``AmonZ`` from the same lat-lon ``ta`` time series
used for ``Amon``. An empty string (or an object with an empty name) means unmapped.

Reductions
----------
- ``zonal_mean``: mean over longitude, weighted by the longitude cell widths (``lon_bnds``)
  when present, ignoring missing values. Needs a 1-D longitude axis (regular lat-lon or
  gaussian grids), so data on a native tripolar or cubed-sphere grid must be regridded first.
  The longitude coordinate and its bounds are dropped, leaving a latitude-only variable.

Functions
---------
- ``parse_varlist_value(value)``
- ``varlist_target(value)``
- ``apply_reduce(nc_path, var_name, reduce)``
"""

import logging
import os
from typing import Any, Optional, Tuple

import numpy as np
from netCDF4 import Dataset

fre_logger = logging.getLogger(__name__)

# reduce method -> number of input dimensions it removes
REDUCE_METHODS = {'zonal_mean': 1}
_VARLIST_OBJECT_KEYS = {'name', 'reduce'}


def parse_varlist_value(value: Any) -> Tuple[str, Optional[str]]:
    """
    Split a variable-list value into its MIP variable name and reduce method.

    :param value: A plain MIP variable name, or ``{'name': ..., 'reduce': ...}`` (``reduce``
        optional).
    :type value: str or dict
    :raises ValueError: If the value is neither, has unknown keys, or names an unknown reduce
        method.
    :return: ``(name, reduce)``; name is '' when unmapped, reduce None when not given.
    :rtype: tuple
    """
    if value is None:
        return '', None
    if isinstance(value, str):
        return value, None
    if not isinstance(value, dict):
        raise ValueError(f'variable list value must be a string or an object, got {value!r}')

    unknown = set(value) - _VARLIST_OBJECT_KEYS
    if unknown:
        raise ValueError(f'unknown key(s) {sorted(unknown)} in variable list value {value!r}, '
                         f'expected {sorted(_VARLIST_OBJECT_KEYS)}')
    name = value.get('name') or ''
    if not isinstance(name, str):
        raise ValueError(f'"name" must be a string in variable list value {value!r}')
    reduce = value.get('reduce') or None
    if reduce is not None and reduce not in REDUCE_METHODS:
        raise ValueError(f'unknown reduce method {reduce!r} in variable list value {value!r}, '
                         f'expected one of {sorted(REDUCE_METHODS)}')
    return name, reduce


def varlist_target(value: Any) -> str:
    """The MIP variable name of a variable-list value, '' if unmapped or malformed -- for
    callers that only need the mapping, and report malformed values elsewhere."""
    try:
        return parse_varlist_value(value)[0]
    except ValueError:
        return ''


def _longitude_dim(ds: Dataset, var_name: str) -> str:
    """The variable's longitude dimension, which must have a 1-D coordinate variable."""
    for dim in ds.variables[var_name].dimensions:
        coord = ds.variables.get(dim)
        if coord is None or coord.ndim != 1:
            continue
        if dim in ('lon', 'longitude') or getattr(coord, 'axis', '') == 'X' or \
                getattr(coord, 'standard_name', '') == 'longitude':
            return dim
    raise ValueError(f'zonal_mean needs a 1-D longitude axis, but {var_name} has dimensions '
                     f'{ds.variables[var_name].dimensions}; data on a native (e.g. tripolar) grid '
                     'must be regridded to lat-lon first')


def _longitude_weights(ds: Dataset, lon_dim: str) -> Optional[np.ndarray]:
    """Longitude cell widths from the coordinate's bounds, or None for equal weights."""
    bounds_name = getattr(ds.variables[lon_dim], 'bounds', None)
    if bounds_name not in ds.variables:
        return None
    bounds = np.asarray(ds.variables[bounds_name][:], dtype=float)
    widths = np.abs(bounds[:, 1] - bounds[:, 0]) if bounds.ndim == 2 else None
    return widths if widths is not None and np.all(widths > 0) else None


def _copy_variable(src: Dataset, dst: Dataset, name: str, dimensions: tuple, fill=None):
    """Create ``name`` in dst with src's attributes over ``dimensions``, and src's
    _FillValue unless ``fill`` is given."""
    var = src.variables[name]
    if fill is None and '_FillValue' in var.ncattrs():
        fill = var.getncattr('_FillValue')
    new = dst.createVariable(name, var.datatype, dimensions, fill_value=fill)
    new.setncatts({attr: var.getncattr(attr) for attr in var.ncattrs() if attr != '_FillValue'})
    return new


def _copy_all_but(src: Dataset, dst: Dataset, var_name: str, drop_dim: str) -> None:
    """Copy src's global attributes, dimensions and variables into dst as they are, except
    var_name, the dimension drop_dim, and every variable on drop_dim."""
    dst.setncatts({attr: src.getncattr(attr) for attr in src.ncattrs()})
    for name, dim in src.dimensions.items():
        if name != drop_dim:
            dst.createDimension(name, None if dim.isunlimited() else len(dim))

    for name, src_var in src.variables.items():
        if name == var_name or drop_dim in src_var.dimensions:
            continue
        new = _copy_variable(src, dst, name, src_var.dimensions)
        src_var.set_auto_maskandscale(False)
        new.set_auto_maskandscale(False)
        if src_var.ndim:
            new[:] = src_var[:]
        else:
            new.assignValue(src_var.getValue())


def _zonal_mean(nc_path: str, var_name: str) -> None:
    """Rewrite nc_path with var_name averaged over longitude and the longitude dimension
    (and every other variable on it, e.g. lon_bnds) removed."""
    tmp_path = f'{nc_path}.reduced'
    with Dataset(nc_path, 'r') as src, Dataset(tmp_path, 'w', format=src.data_model) as dst:
        lon_dim = _longitude_dim(src, var_name)
        weights = _longitude_weights(src, lon_dim)
        var = src.variables[var_name]
        lon_axis = var.dimensions.index(lon_dim)

        _copy_all_but(src, dst, var_name, lon_dim)

        out_dims = tuple(dim for dim in var.dimensions if dim != lon_dim)
        # longitude circles with no valid data at all come out masked, so they need a fill value
        fill = var.getncattr('_FillValue') if '_FillValue' in var.ncattrs() else \
            getattr(var, 'missing_value', 1.0e20)
        out = _copy_variable(src, dst, var_name, out_dims, fill=fill)
        cell_methods = getattr(var, 'cell_methods', '')
        out.cell_methods = f'{cell_methods} {lon_dim}: mean'.strip()

        # one step of the leading (usually time) dimension at a time, so a long daily or 3-D
        # series never has to fit in memory
        if lon_axis > 0:
            for step in range(var.shape[0]):
                out[step] = np.ma.average(np.ma.masked_invalid(var[step]), axis=lon_axis - 1,
                                          weights=weights)
        else:
            out[:] = np.ma.average(np.ma.masked_invalid(var[:]), axis=0, weights=weights)
    os.replace(tmp_path, nc_path)


def apply_reduce(nc_path: str, var_name: str, reduce: Optional[str]) -> None:
    """
    Apply a variable-list reduce method to ``var_name`` in ``nc_path``, rewriting the file in
    place. Meant for the working copy CMORization reads, never the pp file itself.

    :param nc_path: Path to the netCDF file to rewrite.
    :type nc_path: str
    :param var_name: The variable to reduce.
    :type var_name: str
    :param reduce: A REDUCE_METHODS key, or None to leave the file untouched.
    :type reduce: str or None
    :raises ValueError: If the method is unknown or the data cannot be reduced that way.
    """
    if reduce is None:
        return
    if reduce not in REDUCE_METHODS:
        raise ValueError(f'unknown reduce method {reduce!r}, expected one of {sorted(REDUCE_METHODS)}')
    fre_logger.info('applying reduce=%s to %s in %s', reduce, var_name, nc_path)
    _zonal_mean(nc_path, var_name)
