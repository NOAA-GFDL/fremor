"""
Tests for fremor.cmor_resolver.
"""

from pathlib import Path

import pytest
import yaml

import fremor
from fremor.cmor_resolver import (
    _load_yaml_dict,
    _resolve_yaml_reference,
    resolve_fremor_yaml,
)


ROOTDIR = Path(fremor.__file__).parent / 'tests' / 'test_files' / 'yaml_examples'
AM5_DIR = ROOTDIR / 'am5'
ESM4_DIR = ROOTDIR / 'esm4'


# ── resolve_fremor_yaml: happy-path ──────────────────────────────────────────

def test_resolve_fremor_yaml_am5_matches_expected():
    """AM5 fixture should resolve to the expected combined YAML mapping."""
    resolved = resolve_fremor_yaml(
        yamlfile=str(AM5_DIR / 'model.yaml'),
        experiment='c96L65_am5f7b12r1_amip',
        output=None,
    )

    with open(AM5_DIR / 'expected_resolved.yaml', encoding='utf-8') as handle:
        expected = yaml.safe_load(handle)

    assert resolved == expected


def test_resolve_fremor_yaml_writes_output(tmp_path):
    """Resolver should write the combined YAML when output is requested."""
    output_yaml = tmp_path / 'resolved.yaml'

    resolved = resolve_fremor_yaml(
        yamlfile=str(AM5_DIR / 'model.yaml'),
        experiment='c96L65_am5f7b12r1_amip',
        output=str(output_yaml),
    )

    assert output_yaml.exists()
    with open(output_yaml, encoding='utf-8') as handle:
        written = yaml.safe_load(handle)
    assert written == resolved


def test_resolve_fremor_yaml_esm4_matches_expected():
    """ESM4 fixture should resolve to the expected combined YAML mapping."""
    resolved = resolve_fremor_yaml(
        yamlfile=str(ESM4_DIR / 'model.yaml'),
        experiment='ESM4_historical_D1',
        output=None,
    )

    with open(ESM4_DIR / 'expected_resolved.yaml', encoding='utf-8') as handle:
        expected = yaml.safe_load(handle)

    assert resolved == expected


def test_resolve_fremor_yaml_esm4_grid_and_chunk():
    """ESM4 fixture: grid and chunk anchors from model/grids YAML resolve correctly."""
    resolved = resolve_fremor_yaml(
        yamlfile=str(ESM4_DIR / 'model.yaml'),
        experiment='ESM4_historical_D1',
        output=None,
    )

    cmor = resolved['cmor']
    assert cmor['directories']['pp_dir'].endswith('ESM4_historical_D1/pp')
    assert cmor['table_targets'][0]['gridding']['grid_label'] == 'gr1'
    assert cmor['table_targets'][0]['target_components'][0]['chunk'] == 'P5Y'


# ── resolve_fremor_yaml: error paths ─────────────────────────────────────────

def test_resolve_missing_experiment(tmp_path):
    """ValueError when the requested experiment is not in the model YAML."""
    model = tmp_path / 'model.yaml'
    model.write_text('experiments:\n  - name: "other"\n    cmor:\n      - "x.yaml"\n',
                     encoding='utf-8')
    with pytest.raises(ValueError, match='not found in model yaml'):
        resolve_fremor_yaml(yamlfile=str(model), experiment='missing')


def test_resolve_no_cmor_ref(tmp_path):
    """ValueError when the experiment has no cmor entry."""
    model = tmp_path / 'model.yaml'
    model.write_text('experiments:\n  - name: "exp"\n', encoding='utf-8')
    with pytest.raises(ValueError, match='no cmor yaml'):
        resolve_fremor_yaml(yamlfile=str(model), experiment='exp')


def test_resolve_multiple_cmor_refs(tmp_path):
    """ValueError when the experiment references more than one cmor YAML."""
    model = tmp_path / 'model.yaml'
    model.write_text(
        'experiments:\n  - name: "exp"\n    cmor:\n      - "a.yaml"\n      - "b.yaml"\n',
        encoding='utf-8',
    )
    with pytest.raises(ValueError, match='exactly one cmor yaml'):
        resolve_fremor_yaml(yamlfile=str(model), experiment='exp')


def test_resolve_cmor_ref_as_string(tmp_path):
    """A cmor reference given as a bare string (not a list) is accepted."""
    cmor = tmp_path / 'cmor.yaml'
    cmor.write_text('cmor:\n  mip_era: CMIP6\n', encoding='utf-8')
    model = tmp_path / 'model.yaml'
    model.write_text(
        f'experiments:\n  - name: "exp"\n    cmor: "{cmor.name}"\n',
        encoding='utf-8',
    )
    resolved = resolve_fremor_yaml(yamlfile=str(model), experiment='exp')
    assert resolved['cmor']['mip_era'] == 'CMIP6'


def test_resolve_grid_yaml_ref_as_string(tmp_path):
    """A grid_yaml reference given as a bare string (not a list) is accepted."""
    cmor = tmp_path / 'cmor.yaml'
    cmor.write_text('cmor:\n  mip_era: CMIP6\n', encoding='utf-8')
    grids = tmp_path / 'grids.yaml'
    grids.write_text('grids:\n  - gr: {grid_label: gr}\n', encoding='utf-8')
    model = tmp_path / 'model.yaml'
    model.write_text(
        f'experiments:\n  - name: "exp"\n'
        f'    grid_yaml: "{grids.name}"\n'
        f'    cmor:\n      - "{cmor.name}"\n',
        encoding='utf-8',
    )
    resolved = resolve_fremor_yaml(yamlfile=str(model), experiment='exp')
    assert resolved['grids'][0] == {'gr': {'grid_label': 'gr'}}


# ── _load_yaml_dict: edge cases ───────────────────────────────────────────────

def test_load_yaml_dict_empty_file(tmp_path):
    """An empty YAML file should return an empty dict."""
    f = tmp_path / 'empty.yaml'
    f.write_text('', encoding='utf-8')
    assert _load_yaml_dict(f) == {}


def test_load_yaml_dict_non_mapping(tmp_path):
    """A YAML file whose top-level value is not a mapping raises ValueError."""
    f = tmp_path / 'list.yaml'
    f.write_text('- item1\n- item2\n', encoding='utf-8')
    with pytest.raises(ValueError, match='expected YAML mapping'):
        _load_yaml_dict(f)


# ── _resolve_yaml_reference: path resolution ──────────────────────────────────

def test_resolve_yaml_reference_absolute(tmp_path):
    """An absolute reference is returned as-is."""
    base = tmp_path / 'base.yaml'
    result = _resolve_yaml_reference(base, '/absolute/path/grids.yaml')
    assert result == Path('/absolute/path/grids.yaml')


def test_resolve_yaml_reference_relative(tmp_path):
    """A relative reference is resolved relative to the declaring file."""
    base = tmp_path / 'subdir' / 'model.yaml'
    result = _resolve_yaml_reference(base, 'grids.yaml')
    assert result == (tmp_path / 'subdir' / 'grids.yaml').resolve()
