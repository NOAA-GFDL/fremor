'''Focused regressions for remaining CMOR mixer branches.'''

import json
import shutil
import subprocess
from pathlib import Path

import netCDF4
import pytest

from fremor import cmor_mixer
from fremor.tests.conftest import (
    CMIP6_TABLE_CONFIG,
    _CMIP6_EXP_CONFIG_DATA,
)


class _StopBeforeCmor(Exception):
    pass


class _StopAfterAxes(Exception):
    pass


def _write_experiment(path, calendar='julian'):
    exp_config = dict(_CMIP6_EXP_CONFIG_DATA)
    exp_config['calendar'] = calendar
    exp_config['outpath'] = str(path.parent / 'cmor_output')
    Path(exp_config['outpath']).mkdir()
    path.write_text(json.dumps(exp_config), encoding='utf-8')
    return str(path)


def _write_rewrite_input(path, local_var='tas', vertical_dim=None, vertical_dtype='f4',
                         time_length=2, calendar='julian', include_horizontal=False):
    with netCDF4.Dataset(path, 'w') as ds:
        ds.createDimension('time', time_length)
        time = ds.createVariable('time', 'f8', ('time',))
        time.units = 'days since 2000-01-01'
        if calendar is not None:
            time.calendar = calendar
        time[:] = range(time_length)

        if include_horizontal:
            ds.createDimension('lat', 2)
            ds.createDimension('lon', 2)
            latitude = ds.createVariable('lat', 'f4', ('lat',))
            latitude.axis = 'Y'
            latitude.units = 'degrees_north'
            latitude[:] = [-45.0, 45.0]
            longitude = ds.createVariable('lon', 'f4', ('lon',))
            longitude.axis = 'X'
            longitude.units = 'degrees_east'
            longitude[:] = [0.0, 180.0]

        dimensions = ['time']
        if vertical_dim is not None:
            ds.createDimension(vertical_dim, 2)
            level = ds.createVariable(vertical_dim, vertical_dtype, (vertical_dim,))
            level.axis = 'Z'
            level.units = 'm'
            if vertical_dtype == 'S1':
                level[:] = [b'a', b'b']
            else:
                level[:] = [10.0, 20.0]
            dimensions.append(vertical_dim)

        variable = ds.createVariable(local_var, 'f4', tuple(dimensions))
        variable.units = 'K'
        variable[:] = 1.0


def _rewrite_input(input_path, exp_config, local_var='tas', target_var='tas', dimensions=None):
    mip_var_cfgs = {
        'variable_entry': {
            target_var: {
                'dimensions': dimensions or ['time'],
                'standard_name': target_var,
                'units': 'K',
                'positive': 'up',
            }
        }
    }
    return cmor_mixer.rewrite_netcdf_file_var(
        mip_var_cfgs=mip_var_cfgs,
        local_var=local_var,
        netcdf_file=str(input_path),
        target_var=target_var,
        json_exp_config=exp_config,
        json_table_config=str(CMIP6_TABLE_CONFIG),
    )


def _replace_axes_with_ids(monkeypatch):
    calls = []

    def fake_axis(name, **kwargs):
        calls.append((name, kwargs))
        return len(calls)

    monkeypatch.setattr(cmor_mixer.cmor, 'axis', fake_axis)
    return calls


def test_rewrite_warns_when_time_calendar_is_missing(tmp_path, monkeypatch, caplog):
    ''' time without calendar metadata warns and proceeds to the normal CMOR setup boundary '''
    input_path = tmp_path / 'input.20000101.tas.nc'
    _write_rewrite_input(input_path, calendar=None)
    exp_config = _write_experiment(tmp_path / 'exp.json')

    def stop_setup(**_kwargs):
        raise _StopBeforeCmor

    monkeypatch.setattr(cmor_mixer.cmor, 'setup', stop_setup)
    with caplog.at_level('WARNING', logger='fremor.cmor_mixer'):
        with pytest.raises(_StopBeforeCmor):
            _rewrite_input(input_path, exp_config)

    assert 'time coordinates missing calendar' in caplog.text


def test_rewrite_rejects_calendar_mismatch_before_cmor_setup(tmp_path):
    ''' a real input time calendar that conflicts with the experiment config is rejected '''
    input_path = tmp_path / 'input.20000101.tas.nc'
    _write_rewrite_input(input_path, calendar='noleap')
    exp_config = _write_experiment(tmp_path / 'exp.json', calendar='julian')

    with pytest.raises(ValueError, match='does not match input config calendar type'):
        _rewrite_input(input_path, exp_config)


@pytest.mark.parametrize('vertical_dim', ['unknown_z'])
def test_rewrite_rejects_unsupported_vertical_dimension(tmp_path, vertical_dim):
    ''' a real coordinate marked axis=Z cannot bypass the accepted vertical-name set '''
    input_path = tmp_path / 'input.20000101.tas.nc'
    _write_rewrite_input(input_path, vertical_dim=vertical_dim)
    exp_config = _write_experiment(tmp_path / 'exp.json')

    with pytest.raises(ValueError, match='vert_dim = unknown_z is not supported'):
        _rewrite_input(input_path, exp_config, dimensions=['time', vertical_dim])


def test_rewrite_reports_unusable_depth_bounds(tmp_path, monkeypatch):
    ''' malformed non-numeric depth midpoints fail through the legacy bounds error path '''
    input_path = tmp_path / 'input.20000101.tas.nc'
    _write_rewrite_input(input_path, vertical_dim='z_l', vertical_dtype='S1')
    exp_config = _write_experiment(tmp_path / 'exp.json')
    _replace_axes_with_ids(monkeypatch)

    try:
        with pytest.raises(KeyError, match='input data have vertical level boundaries'):
            _rewrite_input(input_path, exp_config, dimensions=['time', 'z_l'])
    finally:
        cmor_mixer.cmor.close()


def test_rewrite_requires_hybrid_surface_pressure_file(tmp_path, monkeypatch):
    ''' a hybrid-sigma input without an adjacent pressure file reports the search context '''
    input_path = tmp_path / 'input.20000101.tas.nc'
    _write_rewrite_input(input_path, vertical_dim='lev')
    exp_config = _write_experiment(tmp_path / 'exp.json')
    _replace_axes_with_ids(monkeypatch)

    try:
        with pytest.raises(FileNotFoundError, match='no surface-pressure.*file found'):
            _rewrite_input(input_path, exp_config, dimensions=['time', 'lev'])
    finally:
        cmor_mixer.cmor.close()


def test_rewrite_rejects_pressure_file_without_requested_variable(tmp_path, monkeypatch):
    ''' an adjacent pressure companion lacking its ps variable is rejected explicitly '''
    input_path = tmp_path / 'input.20000101.tas.nc'
    _write_rewrite_input(input_path, vertical_dim='lev')
    exp_config = _write_experiment(tmp_path / 'exp.json')
    with netCDF4.Dataset(tmp_path / 'input.20000101.ps.nc', 'w') as ds:
        ds.createDimension('time', 2)
        ds.createVariable('other', 'f4', ('time',))[:] = 1.0
    _replace_axes_with_ids(monkeypatch)

    try:
        with pytest.raises(KeyError, match='surface-pressure variable ps not found'):
            _rewrite_input(input_path, exp_config, dimensions=['time', 'lev'])
    finally:
        cmor_mixer.cmor.close()


def test_rewrite_rejects_pressure_time_length_mismatch(tmp_path, monkeypatch):
    ''' an adjacent ps companion must cover the input variable's complete time axis '''
    input_path = tmp_path / 'input.20000101.tas.nc'
    _write_rewrite_input(input_path, vertical_dim='lev', time_length=2)
    exp_config = _write_experiment(tmp_path / 'exp.json')
    with netCDF4.Dataset(tmp_path / 'input.20000101.ps.nc', 'w') as ds:
        ds.createDimension('time', 1)
        ds.createVariable('ps', 'f4', ('time',))[:] = 1.0
    _replace_axes_with_ids(monkeypatch)

    try:
        with pytest.raises(ValueError, match='does not match'):
            _rewrite_input(input_path, exp_config, dimensions=['time', 'lev'])
    finally:
        cmor_mixer.cmor.close()


def test_cmorize_rejects_static_file_without_local_variable(tmp_path):
    ''' the static-file path validates the requested field before entering CMOR '''
    static_file = tmp_path / 'atmos.static.nc'
    with netCDF4.Dataset(static_file, 'w') as ds:
        ds.createDimension('lat', 2)
        ds.createVariable('another_variable', 'f4', ('lat',))[:] = 1.0
    exp_config = tmp_path / 'exp.json'
    exp_config.write_text('{}', encoding='utf-8')

    with pytest.raises(ValueError, match='missing_var not found in static file'):
        cmor_mixer.cmorize_target_var_files(
            indir=str(tmp_path),
            target_var='tas',
            local_var='missing_var',
            iso_datetime_range_arr=['static'],
            name_of_set='atmos',
            json_exp_config=str(exp_config),
            outdir=str(tmp_path / 'out'),
            mip_var_cfgs={},
            json_table_config='unused-table.json',
            static_file=str(static_file),
        )


def _run_with_fake_cmor_output(tmp_path, monkeypatch, output_path, create_log=False,
                              fail_log_move=False, caplog=None):
    indir = tmp_path / 'indir'
    indir.mkdir()
    (indir / 'set.20000101.tas.nc').write_bytes(b'input')
    outdir = tmp_path / 'out'
    exp_config = tmp_path / 'exp.json'
    exp_config.write_text(json.dumps({'outpath': 'CMIP6'}), encoding='utf-8')
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def fake_rewrite(*_args, **_kwargs):
        output_path.write_bytes(b'cmor output')
        if create_log:
            output_path.with_suffix('.log').write_text('cmor log', encoding='utf-8')
        return str(output_path)

    monkeypatch.setattr(cmor_mixer, 'rewrite_netcdf_file_var', fake_rewrite)
    if fail_log_move:
        run = subprocess.run

        def fail_sidecar_move(command, *args, **kwargs):
            if '.log' in command:
                raise OSError('test log relocation failure')
            return run(command, *args, **kwargs)

        monkeypatch.setattr(cmor_mixer.subprocess, 'run', fail_sidecar_move)

    with caplog.at_level('INFO', logger='fremor.cmor_mixer'):
        cmor_mixer.cmorize_target_var_files(
            indir=str(indir),
            target_var='tas',
            local_var='tas',
            iso_datetime_range_arr=['20000101'],
            name_of_set='set',
            json_exp_config=str(exp_config),
            outdir=str(outdir),
            mip_var_cfgs={'variable_entry': {}},
            json_table_config='unused-table.json',
            run_one_mode=True,
        )
    return outdir


def test_cmorize_does_not_move_file_already_at_final_path(tmp_path, monkeypatch, caplog):
    ''' CMOR's already-final output path is left in place instead of mv-ing onto itself '''
    output_path = tmp_path / 'final' / 'tas.nc'
    _run_with_fake_cmor_output(tmp_path, monkeypatch, output_path, caplog=caplog)

    assert output_path.read_bytes() == b'cmor output'
    assert 'already wrote the final output file directly' in caplog.text


def test_cmorize_continues_when_cmor_log_relocation_fails(tmp_path, monkeypatch, caplog):
    ''' a failed sidecar-log move warns but preserves the successfully moved NetCDF output '''
    output_path = tmp_path / 'out' / 'CMOR_tmp' / 'tas.nc'
    outdir = _run_with_fake_cmor_output(
        tmp_path, monkeypatch, output_path, create_log=True, fail_log_move=True, caplog=caplog)

    assert (outdir / 'tas.nc').read_bytes() == b'cmor output'
    assert output_path.with_suffix('.log').read_text(encoding='utf-8') == 'cmor log'
    assert 'could not move cmor_logfile next to cmorized file' in caplog.text


def _write_sos_config(tmp_path, input_path, outdir):
    indir = tmp_path / 'indir'
    indir.mkdir()
    shutil.copy(input_path, indir / Path(input_path).name)
    varlist = tmp_path / 'varlist.json'
    varlist.write_text(json.dumps({'sos': 'sos'}), encoding='utf-8')
    exp_config = tmp_path / 'exp.json'
    exp_data = dict(_CMIP6_EXP_CONFIG_DATA)
    exp_data['outpath'] = str(outdir)
    exp_config.write_text(json.dumps(exp_data), encoding='utf-8')
    return indir, varlist, exp_config


def _run_sos_cmorization(tmp_path, input_path, outdir, expected_result=0, **kwargs):
    indir, varlist, exp_config = _write_sos_config(tmp_path, input_path, outdir)
    result = cmor_mixer.cmor_run_subtool(
        indir=str(indir),
        json_var_list=str(varlist),
        json_table_config=str(CMIP6_TABLE_CONFIG),
        json_exp_config=str(exp_config),
        outdir=str(outdir),
        run_one_mode=True,
        grid_label='gr',
        grid='coverage test grid',
        nom_res='10000 km',
        calendar_type=None,
        **kwargs,
    )
    assert result == expected_result
    if expected_result == 0:
        assert list(outdir.rglob('sos_*.nc'))
    return result


def test_rewrite_uses_no_bounds_axes_and_warns_for_missing_calendar(
        tmp_path, monkeypatch, caplog):
    ''' a time coordinate without calendar and horizontal bounds reaches the no-bounds axes '''
    input_path = tmp_path / 'input.20000101.tas.nc'
    _write_rewrite_input(input_path, calendar=None, include_horizontal=True)
    exp_config = _write_experiment(tmp_path / 'exp.json')
    axes = _replace_axes_with_ids(monkeypatch)

    def stop_after_axes(*_args, **_kwargs):
        raise _StopAfterAxes

    monkeypatch.setattr(cmor_mixer.cmor, 'variable', stop_after_axes)
    try:
        with caplog.at_level('WARNING', logger='fremor.cmor_mixer'):
            with pytest.raises(_StopAfterAxes):
                _rewrite_input(
                    input_path, exp_config, dimensions=['longitude', 'latitude', 'time'])
    finally:
        cmor_mixer.cmor.close()

    axis_calls = {name: kwargs for name, kwargs in axes}
    assert {'latitude', 'longitude', 'time'} <= set(axis_calls)
    assert 'cell_bounds' not in axis_calls['latitude']
    assert 'cell_bounds' not in axis_calls['longitude']
    assert 'time coordinates missing calendar' in caplog.text


def test_real_cmorization_retries_time_axis_without_bounds(
        cli_sos_nc_file, tmp_path, monkeypatch, caplog):
    ''' if CMOR rejects time bounds, retry the same real axis with no bounds '''
    real_axis = cmor_mixer.cmor.axis
    rejected_once = False

    def reject_first_bounded_time_axis(name, **kwargs):
        nonlocal rejected_once
        if name == 'time' and kwargs.get('cell_bounds') is not None and not rejected_once:
            rejected_once = True
            raise ValueError('test rejects the first bounded time axis')
        return real_axis(name, **kwargs)

    monkeypatch.setattr(cmor_mixer.cmor, 'axis', reject_first_bounded_time_axis)
    outdir = tmp_path / 'out'

    try:
        with caplog.at_level('INFO', logger='fremor.cmor_mixer'):
            result = _run_sos_cmorization(
                tmp_path, cli_sos_nc_file, outdir, expected_result=1)
    finally:
        cmor_mixer.cmor.close()

    assert result == 1
    assert rejected_once
    assert 'assigning cmor_time WITHOUT time_bnds' in caplog.text
