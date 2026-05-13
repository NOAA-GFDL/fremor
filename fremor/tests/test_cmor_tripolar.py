"""
tests for fremor.cmor_tripolar.load_tripolar_grid
"""

from pathlib import Path

import netCDF4
import numpy as np
import pytest

from fremor.cmor_tripolar import load_tripolar_grid


# ---------------------------------------------------------------------------
# Default grid sizes used across tests
# ---------------------------------------------------------------------------

YH_SIZE = 4
XH_SIZE = 5


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _bronx_paths(base: Path):
    """
    Return ``(data_nc, statics_nc)`` Path objects for a minimal FRE-bronx-style
    layout rooted at *base*.  The directory tree is created but the files are not.

    Layout::

        <base>/
        └── pp/
            └── ocean_monthly/
                ├── ocean_monthly.static.nc       <- statics_nc
                └── ts/monthly/5yr/
                    └── ocean_monthly.000101-000102.sos.nc   <- data_nc
    """
    pp_component = base / 'pp' / 'ocean_monthly'
    ts_dir = pp_component / 'ts' / 'monthly' / '5yr'
    ts_dir.mkdir(parents=True, exist_ok=True)
    data_nc = ts_dir / 'ocean_monthly.000101-000102.sos.nc'
    statics_nc = pp_component / 'ocean_monthly.static.nc'
    return data_nc, statics_nc


def _make_mock_statics_nc(path: Path,
                          yh_size: int = YH_SIZE,
                          xh_size: int = XH_SIZE) -> None:
    """
    Write a minimal ocean-statics-like NetCDF file at *path* that contains
    the variables load_tripolar_grid expects:
    geolat, geolon, geolat_c, geolon_c, yh, xh, yq, xq.
    """
    yq_size = yh_size + 1
    xq_size = xh_size + 1

    ds = netCDF4.Dataset(str(path), 'w')
    ds.createDimension('yh', yh_size)
    ds.createDimension('xh', xh_size)
    ds.createDimension('yq', yq_size)
    ds.createDimension('xq', xq_size)

    # 2-D center coordinates
    geolat = ds.createVariable('geolat', 'f4', ('yh', 'xh'))
    geolat[:] = np.linspace(-90, 90, yh_size * xh_size).reshape(yh_size, xh_size)
    geolon = ds.createVariable('geolon', 'f4', ('yh', 'xh'))
    geolon[:] = np.linspace(0, 60, yh_size * xh_size).reshape(yh_size, xh_size)

    # 2-D corner (q-point) coordinates -- shape (yq, xq)
    geolat_c = ds.createVariable('geolat_c', 'f4', ('yq', 'xq'))
    geolat_c[:] = np.linspace(-90, 90, yq_size * xq_size).reshape(yq_size, xq_size)
    geolon_c = ds.createVariable('geolon_c', 'f4', ('yq', 'xq'))
    geolon_c[:] = np.linspace(0, 60, yq_size * xq_size).reshape(yq_size, xq_size)

    # 1-D axis coordinates
    yh_var = ds.createVariable('yh', 'f4', ('yh',))
    yh_var[:] = np.linspace(-80, 80, yh_size)
    xh_var = ds.createVariable('xh', 'f4', ('xh',))
    xh_var[:] = np.linspace(0, 60, xh_size)

    # q-point 1-D coordinates (one element longer each axis)
    yq_var = ds.createVariable('yq', 'f4', ('yq',))
    yq_var[:] = np.linspace(-90, 90, yq_size)
    xq_var = ds.createVariable('xq', 'f4', ('xq',))
    xq_var[:] = np.linspace(-10, 70, xq_size)

    ds.close()


def _make_mock_data_nc(path: Path, yh_size: int = YH_SIZE, xh_size: int = XH_SIZE) -> None:
    """
    Write a minimal data NetCDF file that has yh/xh dimensions but
    no lat/lon yet (simulating a tripolar ocean file before statics injection).
    """
    ds = netCDF4.Dataset(str(path), 'w')
    ds.createDimension('yh', yh_size)
    ds.createDimension('xh', xh_size)
    ds.createDimension('nv', 2)
    # deliberately do NOT add lat/lon -- that's the job of load_tripolar_grid
    sos = ds.createVariable('sos', 'f4', ('yh', 'xh'))
    sos[:] = np.ones((yh_size, xh_size))
    yh_v = ds.createVariable('yh', 'f4', ('yh',))
    yh_v[:] = np.linspace(-80, 80, yh_size)
    xh_v = ds.createVariable('xh', 'f4', ('xh',))
    xh_v[:] = np.linspace(0, 60, xh_size)
    ds.close()


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

class TestLoadTripolarGrid:
    """Tests for load_tripolar_grid using mock statics and data files."""

    def test_return_keys(self, tmp_path, monkeypatch):
        """
        The returned dict must contain exactly the eight expected coordinate keys.
        """
        # determine file locations first, then create them
        data_nc, statics_nc = _bronx_paths(tmp_path)
        _make_mock_statics_nc(statics_nc)
        _make_mock_data_nc(data_nc)

        # prevent the gold-statics lookup from touching /net2
        monkeypatch.setattr('fremor.cmor_tripolar.find_gold_ocean_statics_file', lambda **kw: None)

        ds = netCDF4.Dataset(str(data_nc), 'r+')
        result = load_tripolar_grid(ds=ds, netcdf_file=str(data_nc), prev_path=str(data_nc))
        ds.close()

        expected_keys = {'lat', 'lon', 'lat_bnds', 'lon_bnds', 'yh', 'xh', 'yh_bnds', 'xh_bnds'}
        assert set(result.keys()) == expected_keys

    def test_coordinates_written_into_ds(self, tmp_path, monkeypatch):
        """
        After calling load_tripolar_grid, ds should contain lat/lon and their bounds.
        """
        # determine file locations first, then create them
        data_nc, statics_nc = _bronx_paths(tmp_path)
        _make_mock_statics_nc(statics_nc, yh_size=YH_SIZE, xh_size=XH_SIZE)
        _make_mock_data_nc(data_nc, yh_size=YH_SIZE, xh_size=XH_SIZE)

        # prevent the gold-statics lookup from touching /net2
        monkeypatch.setattr('fremor.cmor_tripolar.find_gold_ocean_statics_file', lambda **kw: None)

        ds = netCDF4.Dataset(str(data_nc), 'r+')
        load_tripolar_grid(ds=ds, netcdf_file=str(data_nc), prev_path=str(data_nc))

        assert 'lat' in ds.variables
        assert 'lon' in ds.variables
        assert 'lat_bnds' in ds.variables
        assert 'lon_bnds' in ds.variables
        assert 'vertex' in ds.dimensions
        assert ds.variables['lat'].shape == (YH_SIZE, XH_SIZE)
        assert ds.variables['lat_bnds'].shape == (YH_SIZE, XH_SIZE, 4)
        ds.close()

    def test_raises_file_not_found_when_no_statics(self, tmp_path, monkeypatch):
        """
        When neither the gold archive nor the FRE-bronx fallback can locate a
        statics file, load_tripolar_grid should raise FileNotFoundError.
        """
        # determine file locations first, then create only the data file (no statics)
        data_nc, _statics_nc = _bronx_paths(tmp_path)
        _make_mock_data_nc(data_nc)
        # statics_nc is intentionally NOT created

        # prevent the gold-statics lookup from touching /net2
        monkeypatch.setattr('fremor.cmor_tripolar.find_gold_ocean_statics_file', lambda **kw: None)

        ds = netCDF4.Dataset(str(data_nc), 'r+')
        with pytest.raises(FileNotFoundError, match='statics file not found'):
            load_tripolar_grid(ds=ds, netcdf_file=str(data_nc), prev_path=str(data_nc))
        ds.close()

    def test_raises_value_error_on_inconsistent_hq_dims(self, tmp_path, monkeypatch):
        """
        If the statics file's q-point dimensions are not exactly hpoint+1,
        load_tripolar_grid should raise ValueError.
        """
        # data has yh=4, xh=5; correct q-point sizes would be yq=5, xq=6
        # deliberately build statics with wrong q-point sizes yq=3 and xq=4
        data_nc, statics_nc = _bronx_paths(tmp_path)
        _make_mock_data_nc(data_nc, yh_size=YH_SIZE, xh_size=XH_SIZE)

        # statics with mismatched q-point sizes: yq=3 (should be yq=5), xq=4 (should be xq=6)
        bad_yq, bad_xq = 3, 4
        ds_statics = netCDF4.Dataset(str(statics_nc), 'w')
        ds_statics.createDimension('yh', YH_SIZE)
        ds_statics.createDimension('xh', XH_SIZE)
        ds_statics.createDimension('yq', bad_yq)
        ds_statics.createDimension('xq', bad_xq)
        for name, dim in [('geolat', ('yh', 'xh')), ('geolon', ('yh', 'xh')),
                          ('geolat_c', ('yq', 'xq')), ('geolon_c', ('yq', 'xq'))]:
            shape = tuple(ds_statics.dimensions[d].size for d in dim)
            v = ds_statics.createVariable(name, 'f4', dim)
            v[:] = np.ones(shape)
        for name, dim in [('yh', 'yh'), ('xh', 'xh'), ('yq', 'yq'), ('xq', 'xq')]:
            v = ds_statics.createVariable(name, 'f4', (dim,))
            v[:] = np.arange(ds_statics.dimensions[dim].size, dtype='f4')
        ds_statics.close()

        # prevent the gold-statics lookup from touching /net2
        monkeypatch.setattr('fremor.cmor_tripolar.find_gold_ocean_statics_file', lambda **kw: None)

        ds = netCDF4.Dataset(str(data_nc), 'r+')
        with pytest.raises(ValueError, match='hpoint_dim != qpoint_dim-1'):
            load_tripolar_grid(ds=ds, netcdf_file=str(data_nc), prev_path=str(data_nc))
        ds.close()
