"""Tests for fremor.cmor_resolver."""

from pathlib import Path

import yaml

import fremor
from fremor.cmor_resolver import resolve_fremor_yaml


ROOTDIR = Path(fremor.__file__).parent / 'tests' / 'test_files' / 'yaml_examples'
AM5_DIR = ROOTDIR / 'am5'
ESM4_DIR = ROOTDIR / 'esm4'


def test_resolve_fremor_yaml_am5_matches_expected():
    """AM5 fixture should resolve to the expected combined YAML mapping."""
    resolved = resolve_fremor_yaml(
        yamlfile=str(AM5_DIR / 'model.yaml'),
        experiment='c96L65_am5f7b12r1_amip',
        platform='ncrc5.intel',
        target='prod-openmp',
        output=None,
    )

    with open(AM5_DIR / 'expected_resolved.yaml', encoding='utf-8') as handle:
        expected = yaml.safe_load(handle)

    assert resolved == expected


def test_resolve_fremor_yaml_writes_output(tmp_path):
    """Resolver should still write the combined YAML when output is requested."""
    output_yaml = tmp_path / 'resolved.yaml'

    resolved = resolve_fremor_yaml(
        yamlfile=str(AM5_DIR / 'model.yaml'),
        experiment='c96L65_am5f7b12r1_amip',
        platform='ncrc5.intel',
        target='prod-openmp',
        output=str(output_yaml),
    )

    assert output_yaml.exists()
    with open(output_yaml, encoding='utf-8') as handle:
        written = yaml.safe_load(handle)
    assert written == resolved


def test_resolve_fremor_yaml_esm4_resolves_runtime_and_grid_data():
    """ESM4 fixture should resolve runtime joins and grid aliases from the model YAML."""
    resolved = resolve_fremor_yaml(
        yamlfile=str(ESM4_DIR / 'model.yaml'),
        experiment='ESM4_historical_D1',
        platform='gfdl.ncrc4-intel16',
        target='prod-openmp',
        output=None,
    )

    cmor = resolved['cmor']
    assert cmor['directories']['pp_dir'].endswith(
        'ascii_files/mock_archive/cm6/ESM4/DECK/ESM4_historical_D1/gfdl.ncrc4-intel16-prod-openmp/pp'
    )
    assert cmor['table_targets'][0]['gridding']['grid_label'] == 'gr1'
    assert cmor['table_targets'][0]['target_components'][0]['chunk'] == 'P5Y'
