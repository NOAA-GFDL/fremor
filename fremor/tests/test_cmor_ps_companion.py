"""
tests for how fremor finds the surface-pressure (ps) companion of hybrid-sigma variables:
the table's own mapped ps variable first, then the companion .ps.nc file next to the input.
"""

import json
from pathlib import Path

import pytest

from fremor import cmor_mixer, cmor_yamler
from fremor.cmor_helpers import find_ps_companion, resolve_named_ps_source, table_declares_ps

ROOTDIR = Path(__file__).parent / 'test_files'
CMIP6_TABLE_CONFIG = ROOTDIR / 'cmip6-cmor-tables' / 'Tables' / 'CMIP6_Amon.json'
CMIP6_EXP_CONFIG = ROOTDIR / 'CMOR_input_example.json'


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


# ---------------------------------------------------------------------------
# table_declares_ps
# ---------------------------------------------------------------------------
def test_table_declares_ps_cmip6():
    ''' a CMIP6-style bare ps entry is recognized '''
    assert table_declares_ps({'variable_entry': {'ps': {}, 'cl': {}}})


def test_table_declares_ps_cmip7_branded():
    ''' a CMIP7-style branded ps entry is recognized '''
    assert table_declares_ps({'variable_entry': {'ps_tavg-u-hxy-u': {}}})


def test_table_declares_ps_absent():
    ''' look-alike names are not mistaken for ps '''
    assert not table_declares_ps({'variable_entry': {'psl': {}, 'cl': {}}})
    assert not table_declares_ps({})


# ---------------------------------------------------------------------------
# find_ps_companion
# ---------------------------------------------------------------------------
def test_find_ps_companion_prefers_mapped_ps(tmp_path):
    ''' the table-mapped ps in another component wins over the adjacent .ps.nc file '''
    var_file = _touch(tmp_path / 'atmos_level' / 'atmos_level.197901-198312.cl.nc')
    _touch(tmp_path / 'atmos_level' / 'atmos_level.197901-198312.ps.nc')
    mapped = _touch(tmp_path / 'atmos' / 'atmos.197901-198312.pres.nc')

    ps_file, ps_var, searched = find_ps_companion(
        var_file, 'cl', {'indir': str(tmp_path / 'atmos'), 'local_var': 'pres'})

    assert ps_file == str(mapped)
    assert ps_var == 'pres'
    assert len(searched) == 1


def test_find_ps_companion_falls_back_to_adjacent(tmp_path):
    ''' with no same-date mapped ps file, the adjacent .ps.nc file is used '''
    var_file = _touch(tmp_path / 'atmos_level' / 'atmos_level.197901-198312.cl.nc')
    adjacent = _touch(tmp_path / 'atmos_level' / 'atmos_level.197901-198312.ps.nc')
    _touch(tmp_path / 'atmos' / 'atmos.198401-198812.pres.nc')  # different date range

    ps_file, ps_var, searched = find_ps_companion(
        var_file, 'cl', {'indir': str(tmp_path / 'atmos'), 'local_var': 'pres'})

    assert ps_file == str(adjacent)
    assert ps_var == 'ps'
    assert len(searched) == 2


def test_find_ps_companion_without_mapping(tmp_path):
    ''' without a mapped ps, only the adjacent .ps.nc file is searched '''
    var_file = _touch(tmp_path / 'atmos.197901-198312.cl.nc')
    adjacent = _touch(tmp_path / 'atmos.197901-198312.ps.nc')

    assert find_ps_companion(var_file, 'cl') == (str(adjacent), 'ps', [f'{adjacent} (companion .ps.nc file)'])


def test_find_ps_companion_not_found(tmp_path):
    ''' nothing found: None, with both searched places reported '''
    var_file = _touch(tmp_path / 'atmos_level' / 'atmos_level.197901-198312.cl.nc')

    ps_file, _ps_var, searched = find_ps_companion(
        var_file, 'cl', {'indir': str(tmp_path / 'atmos'), 'local_var': 'pres'})

    assert ps_file is None
    assert '*.197901-198312.pres.nc' in searched[0]
    assert 'atmos_level.197901-198312.ps.nc' in searched[1]


def test_find_ps_companion_ps_fallback_after_adjacent(tmp_path):
    ''' the ps_component fallback is used only when neither mapped nor adjacent ps exists '''
    var_file = _touch(tmp_path / 'atmos_level' / 'atmos_level.197901-198312.cl.nc')
    fallback_file = _touch(tmp_path / 'atmos' / 'atmos.197901-198312.ps.nc')
    fallback = {'indir': str(tmp_path / 'atmos'), 'local_var': 'ps'}

    ps_file, ps_var, searched = find_ps_companion(var_file, 'cl', ps_fallback=fallback)
    assert (ps_file, ps_var) == (str(fallback_file), 'ps')
    assert len(searched) == 2
    assert 'ps_component' in searched[1]

    adjacent = _touch(tmp_path / 'atmos_level' / 'atmos_level.197901-198312.ps.nc')
    assert find_ps_companion(var_file, 'cl', ps_fallback=fallback)[0] == str(adjacent)


def test_find_ps_companion_searches_all_three(tmp_path):
    ''' nothing found: all three places are reported, in search order '''
    var_file = _touch(tmp_path / 'atmos_level' / 'atmos_level.197901-198312.cl.nc')

    ps_file, _ps_var, searched = find_ps_companion(
        var_file, 'cl',
        ps_source={'indir': str(tmp_path / 'mapped'), 'local_var': 'pres'},
        ps_fallback={'indir': str(tmp_path / 'atmos'), 'local_var': 'ps'})

    assert ps_file is None
    assert [entry.split(' (')[1] for entry in searched] == [
        "table-mapped ps variable 'pres')", 'companion .ps.nc file)', "ps_component variable 'ps')"]


# ---------------------------------------------------------------------------
# resolve_named_ps_source
# ---------------------------------------------------------------------------
def _component(name, chunk='P5Y', data_series_type='ts'):
    return {'component_name': name, 'chunk': chunk, 'data_series_type': data_series_type,
            'variable_list': f'{name}.json'}


def test_resolve_named_ps_source_absent():
    ''' no ps_component key, no fallback '''
    assert resolve_named_ps_source({'target_components': [_component('atmos')]}, [], '/pp', 'monthly') is None


def test_resolve_named_ps_source_from_other_table_target():
    ''' chunk/data_series_type come from the component's entry in another table target '''
    table_target = {'table_name': 'APmonLev', 'ps_component': 'atmos', 'ps_local_name': 'pres',
                    'target_components': [_component('atmos_level', chunk='P5Y')]}
    other = {'table_name': 'APmon', 'target_components': [_component('atmos', chunk='P10Y', data_series_type='av')]}

    assert resolve_named_ps_source(table_target, [table_target, other], '/pp', 'monthly') == \
        {'indir': '/pp/atmos/av/monthly/10yr', 'local_var': 'pres'}


def test_resolve_named_ps_source_own_component_wins():
    ''' an entry in the table target itself is preferred, and ps_local_name defaults to ps '''
    table_target = {'ps_component': 'atmos',
                    'target_components': [_component('atmos_level'), _component('atmos', chunk='P1Y')]}
    other = {'target_components': [_component('atmos', chunk='P10Y')]}

    assert resolve_named_ps_source(table_target, [other, table_target], '/pp', 'monthly') == \
        {'indir': '/pp/atmos/ts/monthly/1yr', 'local_var': 'ps'}


def test_resolve_named_ps_source_unlisted_component():
    ''' a component listed nowhere borrows the table target's first component's chunk '''
    table_target = {'ps_component': 'atmos', 'target_components': [_component('atmos_level', chunk='P20Y')]}

    assert resolve_named_ps_source(table_target, [table_target], '/pp', 'monthly')['indir'] == \
        '/pp/atmos/ts/monthly/20yr'


def test_resolve_named_ps_source_no_components():
    ''' nothing to take a chunk from is an error '''
    with pytest.raises(ValueError, match='no target_components'):
        resolve_named_ps_source({'table_name': 'X', 'ps_component': 'atmos'}, [], '/pp', 'monthly')


# ---------------------------------------------------------------------------
# cmor_run_subtool: ps runs first and becomes the table's ps_source
# ---------------------------------------------------------------------------
def _capture_cmorize_all(monkeypatch) -> dict:
    captured = {}

    def fake_cmorize_all(vars_to_run, indir, *args, ps_source=None, **kwargs): # pylint: disable=unused-argument
        captured['vars_to_run'] = list(vars_to_run.items())
        captured['ps_source'] = ps_source
        return 0

    monkeypatch.setattr(cmor_mixer, 'cmorize_all_variables_in_dir', fake_cmorize_all)
    return captured


def test_cmor_run_subtool_runs_mapped_ps_first(monkeypatch, tmp_path):
    ''' a varlist mapping ps puts it first and makes it the ps_source '''
    captured = _capture_cmorize_all(monkeypatch)
    indir = tmp_path / 'indir'
    for local_var in ('cl', 'pres', 'tas'):
        _touch(indir / f'atmos.197901-198312.{local_var}.nc')
    varlist = tmp_path / 'varlist.json'
    varlist.write_text(json.dumps({'cl': 'cl', 'tas': 'tas', 'pres': 'ps'}), encoding='utf-8')

    cmor_mixer.cmor_run_subtool(indir=str(indir), json_var_list=str(varlist),
                                json_table_config=str(CMIP6_TABLE_CONFIG),
                                json_exp_config=str(CMIP6_EXP_CONFIG), outdir=str(tmp_path / 'out'))

    assert captured['vars_to_run'][0] == ('pres', 'ps')
    assert captured['ps_source'] == {'indir': str(indir), 'local_var': 'pres'}


def test_cmor_run_subtool_keeps_given_ps_source(monkeypatch, tmp_path):
    ''' an explicitly passed ps_source (e.g. from fremor yaml) is not overridden '''
    captured = _capture_cmorize_all(monkeypatch)
    indir = tmp_path / 'indir'
    _touch(indir / 'atmos_level.197901-198312.cl.nc')
    varlist = tmp_path / 'varlist.json'
    varlist.write_text(json.dumps({'cl': 'cl'}), encoding='utf-8')
    ps_source = {'indir': str(tmp_path / 'atmos'), 'local_var': 'pres'}

    cmor_mixer.cmor_run_subtool(indir=str(indir), json_var_list=str(varlist),
                                json_table_config=str(CMIP6_TABLE_CONFIG),
                                json_exp_config=str(CMIP6_EXP_CONFIG), outdir=str(tmp_path / 'out'),
                                ps_source=ps_source)

    assert captured['ps_source'] == ps_source


def test_cmor_run_subtool_no_ps_mapping(monkeypatch, tmp_path):
    ''' no ps mapping: no ps_source, so only the adjacent .ps.nc file will be searched '''
    captured = _capture_cmorize_all(monkeypatch)
    indir = tmp_path / 'indir'
    _touch(indir / 'atmos.197901-198312.cl.nc')
    varlist = tmp_path / 'varlist.json'
    varlist.write_text(json.dumps({'cl': 'cl'}), encoding='utf-8')

    cmor_mixer.cmor_run_subtool(indir=str(indir), json_var_list=str(varlist),
                                json_table_config=str(CMIP6_TABLE_CONFIG),
                                json_exp_config=str(CMIP6_EXP_CONFIG), outdir=str(tmp_path / 'out'))

    assert captured['ps_source'] is None


# ---------------------------------------------------------------------------
# cmor_yaml_subtool: the ps component runs first, and every component gets its ps_source
# ---------------------------------------------------------------------------
def test_cmor_yaml_subtool_uses_table_ps_across_components(monkeypatch, tmp_path):
    ''' ps mapped in a later component is run first and shared with the other components '''
    pp_dir, table_dir, outdir = tmp_path / 'pp', tmp_path / 'tables', tmp_path / 'out'
    for path in (pp_dir, table_dir, outdir):
        path.mkdir()
    exp_json = tmp_path / 'exp.json'
    exp_json.write_text('{}', encoding='utf-8')
    (table_dir / 'CMIP6_Amon.json').write_text(
        json.dumps({'variable_entry': {'ps': {}, 'cl': {}}}), encoding='utf-8')
    level_list = tmp_path / 'level.json'
    level_list.write_text(json.dumps({'cl': 'cl'}), encoding='utf-8')
    atmos_list = tmp_path / 'atmos.json'
    atmos_list.write_text(json.dumps({'pres': 'ps'}), encoding='utf-8')

    yamlfile = tmp_path / 'test.yaml'
    yamlfile.write_text(f"""
cmor:
  mip_era: CMIP6
  directories:
    pp_dir: {pp_dir}
    table_dir: {table_dir}
    outdir: {outdir}
  exp_json: {exp_json}
  table_targets:
    - table_name: Amon
      freq: monthly
      gridding: null
      target_components:
        - component_name: atmos_level
          chunk: "P5Y"
          data_series_type: ts
          variable_list: "{level_list}"
        - component_name: atmos
          chunk: "P5Y"
          data_series_type: ts
          variable_list: "{atmos_list}"
""", encoding='utf-8')

    calls = []
    monkeypatch.setattr(cmor_yamler, 'cmor_run_subtool',
                        lambda **kwargs: calls.append((kwargs['indir'], kwargs['ps_source'])))

    cmor_yamler.cmor_yaml_subtool(yamlfile=str(yamlfile), run_strict_mode=True)

    expected_ps_source = {'indir': f'{pp_dir}/atmos/ts/monthly/5yr', 'local_var': 'pres'}
    assert calls == [
        (f'{pp_dir}/atmos/ts/monthly/5yr', expected_ps_source),
        (f'{pp_dir}/atmos_level/ts/monthly/5yr', expected_ps_source),
    ]


def test_cmor_yaml_subtool_passes_ps_component_fallback(monkeypatch, tmp_path):
    ''' a table without ps (e.g. CMIP6Plus APmonLev) gets ps_component as its fallback '''
    pp_dir, table_dir, outdir = tmp_path / 'pp', tmp_path / 'tables', tmp_path / 'out'
    for path in (pp_dir, table_dir, outdir):
        path.mkdir()
    exp_json = tmp_path / 'exp.json'
    exp_json.write_text('{}', encoding='utf-8')
    for table_name, entries in (('APmonLev', {'cl': {}}), ('APmon', {'ps': {}, 'tas': {}})):
        (table_dir / f'MIP_{table_name}.json').write_text(
            json.dumps({'variable_entry': entries}), encoding='utf-8')
    level_list = tmp_path / 'level.json'
    level_list.write_text(json.dumps({'cl': 'cl'}), encoding='utf-8')
    atmos_list = tmp_path / 'atmos.json'
    atmos_list.write_text(json.dumps({'ps': 'ps', 'tas': 'tas'}), encoding='utf-8')

    yamlfile = tmp_path / 'test.yaml'
    yamlfile.write_text(f"""
cmor:
  mip_era: CMIP6Plus
  directories:
    pp_dir: {pp_dir}
    table_dir: {table_dir}
    outdir: {outdir}
  exp_json: {exp_json}
  table_targets:
    - table_name: APmonLev
      freq: monthly
      gridding: null
      ps_component: atmos
      target_components:
        - component_name: atmos_level
          chunk: "P5Y"
          data_series_type: ts
          variable_list: "{level_list}"
    - table_name: APmon
      freq: monthly
      gridding: null
      target_components:
        - component_name: atmos
          chunk: "P10Y"
          data_series_type: ts
          variable_list: "{atmos_list}"
""", encoding='utf-8')

    calls = []
    monkeypatch.setattr(cmor_yamler, 'cmor_run_subtool',
                        lambda **kwargs: calls.append((kwargs['indir'], kwargs['ps_source'],
                                                       kwargs['ps_fallback'])))

    cmor_yamler.cmor_yaml_subtool(yamlfile=str(yamlfile), run_strict_mode=True)

    assert calls == [
        (f'{pp_dir}/atmos_level/ts/monthly/5yr', None,
         {'indir': f'{pp_dir}/atmos/ts/monthly/10yr', 'local_var': 'ps'}),
        (f'{pp_dir}/atmos/ts/monthly/10yr', {'indir': f'{pp_dir}/atmos/ts/monthly/10yr', 'local_var': 'ps'},
         None),
    ]
