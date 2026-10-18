"""
tests for passing the table target's freq to CMOR as the CMIP7 dataset frequency. CMIP7 tables
carry no frequency, so without it CMOR cannot check the time axis.
"""

import json
from pathlib import Path
import subprocess

import netCDF4
import pytest

from fremor import cmor_run_subtool
from fremor.cmor_helpers import conv_bronx_to_cmip7_freq
from fremor.cmor_yamler import cmor_yaml_subtool

ROOTDIR = 'fremor/tests/test_files'
TABLE_CONFIG = f'{ROOTDIR}/cmip7-cmor-tables/tables/CMIP7_ocean.json'
CMIP7_EXP_CONFIG = f'{ROOTDIR}/CMOR_CMIP7_input_example.json'
FILENAME = 'reduced_ocean_monthly_1x1deg.199301-199302.sos'


@pytest.mark.parametrize('bronx_freq, cmip7_freq', [
    ('1hr', '1hr'), ('3hr', '3hr'), ('6hr', '6hr'), ('daily', 'day'),
    ('monthly', 'mon'), ('annual', 'yr'), ('static', 'fx'),
    ('mon', 'mon'), ('day', 'day'),
])
def test_conv_bronx_to_cmip7_freq(bronx_freq, cmip7_freq):
    ''' FRE-bronx frequencies map to CMIP7 ones, and CMIP7 ones pass through '''
    assert conv_bronx_to_cmip7_freq(bronx_freq) == cmip7_freq


@pytest.mark.parametrize('bad_freq', ['weekly', 'Monthly', 'monPt', '', None])
def test_conv_bronx_to_cmip7_freq_invalid(bad_freq):
    ''' a frequency with no CMIP7 equivalent raises '''
    with pytest.raises(ValueError, match='has no CMIP7 equivalent'):
        conv_bronx_to_cmip7_freq(bad_freq)


def test_yaml_passes_freq_to_run(tmp_path, monkeypatch):
    ''' fremor yaml hands the table target's freq to cmor_run_subtool '''
    pp_dir = tmp_path / 'pp'
    (pp_dir / 'ocean_monthly' / 'ts' / 'monthly' / '5yr').mkdir(parents=True)
    varlist = tmp_path / 'CMIP7_ocean_ocean_monthly.list'
    varlist.write_text(json.dumps({'sos': 'sos'}), encoding='utf-8')
    yamlfile = tmp_path / 'cmor.yaml'
    yamlfile.write_text(f'''
cmor:
  start: null
  stop: null
  calendar_type: 'noleap'
  mip_era: 'cmip7'
  exp_json: '{Path(CMIP7_EXP_CONFIG).resolve()}'
  directories:
    pp_dir: '{pp_dir}'
    table_dir: '{Path(TABLE_CONFIG).parent.resolve()}'
    outdir: '{tmp_path / 'out'}'
  table_targets:
    - table_name: 'ocean'
      freq: 'monthly'
      gridding:
        grid_label: 'g010'
        grid_desc: 'FOO'
        nom_res: '100 km'
      target_components:
        - component_name: 'ocean_monthly'
          variable_list: '{varlist}'
          data_series_type: 'ts'
          chunk: 'P5Y'
''', encoding='utf-8')
    calls = []
    monkeypatch.setattr('fremor.cmor_yamler.cmor_run_subtool', lambda **kwargs: calls.append(kwargs))
    cmor_yaml_subtool(yamlfile=str(yamlfile))
    assert len(calls) == 1
    assert calls[0]['freq'] == 'monthly'


@pytest.fixture(name='sos_indir')
def fixture_sos_indir(tmp_path):
    ''' a CMIP7 sos input file in its own directory '''
    indir = tmp_path / 'in'
    indir.mkdir()
    subprocess.run(['ncgen3', '-k', 'netCDF-4', '-o', str(indir / f'{FILENAME}.nc'),
                    f'{ROOTDIR}/reduced_ascii_files/{FILENAME}.cdl'], check=True)
    return indir


@pytest.mark.parametrize('exp_freq', [None, 'monthly'])
def test_run_sets_cmip7_frequency(tmp_path, sos_indir, exp_freq):
    '''
    with freq given, the CMIP7 frequency CMOR expects comes from it, whether the exp config
    has no frequency or one CMOR does not know
    '''
    exp_config = json.loads(Path(CMIP7_EXP_CONFIG).read_text(encoding='utf-8'))
    exp_config.pop('frequency', None)
    if exp_freq is not None:
        exp_config['frequency'] = exp_freq
    exp_json = tmp_path / 'exp_config.json'
    exp_json.write_text(json.dumps(exp_config), encoding='utf-8')
    varlist = tmp_path / 'varlist'
    varlist.write_text(json.dumps({'sos': 'sos'}), encoding='utf-8')
    outdir = tmp_path / 'out'

    cmor_run_subtool(
        indir = str(sos_indir),
        json_var_list = str(varlist),
        json_table_config = TABLE_CONFIG,
        json_exp_config = str(exp_json),
        outdir = str(outdir),
        run_one_mode = True,
        grid_label = 'g010',
        grid = 'regridded to FOO grid from native',
        nom_res = '100 km',
        calendar_type = 'julian',
        freq = 'monthly'
    )

    outputs = list((outdir / 'CMIP').rglob('sos_*.nc'))
    assert len(outputs) == 1
    assert '_mon_' in outputs[0].name
    with netCDF4.Dataset(outputs[0]) as ds_out:
        assert ds_out.getncattr('frequency') == 'mon'
