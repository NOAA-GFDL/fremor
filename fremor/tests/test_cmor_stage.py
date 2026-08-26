"""Tests for archive input discovery and batched dmget staging."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from fremor.cmor_stage import collect_stage_files, cmor_stage_subtool


def _stage_case(tmp_path: Path, *, mip_era: str = 'CMIP6') -> tuple[Path, Path]:
    """Create a small self-contained YAML staging case."""
    pp_dir = tmp_path / 'pp'
    input_dir = pp_dir / 'atmos' / 'ts' / 'monthly' / '5yr'
    input_dir.mkdir(parents=True)
    table_dir = tmp_path / 'tables'
    table_dir.mkdir()
    varlist = tmp_path / 'varlist.json'

    table_variables = {'tas': {}}
    if mip_era == 'CMIP7':
        table_variables = {'tas_tavg-u-hxy-u': {}}
    (table_dir / f'{mip_era}_Amon.json').write_text(
        json.dumps({'variable_entry': table_variables}), encoding='utf-8'
    )
    varlist.write_text(json.dumps({'temp': 'tas', 'unused': 'not_in_table'}), encoding='utf-8')

    for name in (
        'atmos.199001-199412.temp.nc',
        'atmos.199501-199912.temp.nc',
        'atmos.199501-199912.ps.nc',
        'atmos.199501-199912.unused.nc',
        'atmos.200001-200412.temp.nc',
    ):
        (input_dir / name).touch()

    config = {
        'cmor': {
            'mip_era': mip_era,
            'start': '1995',
            'stop': '1999',
            'directories': {
                'pp_dir': str(pp_dir),
                'table_dir': str(table_dir),
                'outdir': str(tmp_path / 'output'),
            },
            'table_targets': [{
                'table_name': 'Amon',
                'freq': 'monthly',
                'target_components': [{
                    'component_name': 'atmos',
                    'data_series_type': 'ts',
                    'chunk': 'P5Y',
                    'variable_list': str(varlist),
                }],
            }],
        },
    }
    yamlfile = tmp_path / 'cmor.yaml'
    yamlfile.write_text(yaml.safe_dump(config, sort_keys=False), encoding='utf-8')
    return yamlfile, input_dir


@pytest.mark.parametrize('mip_era', ['CMIP6', 'CMIP7'])
def test_collect_stage_files_uses_mappings_bounds_and_ps(tmp_path, mip_era):
    """Only runnable mapped files and their same-date ps auxiliary are selected."""
    yamlfile, input_dir = _stage_case(tmp_path, mip_era=mip_era)

    result = collect_stage_files(str(yamlfile))

    assert result == sorted([
        str((input_dir / 'atmos.199501-199912.ps.nc').resolve()),
        str((input_dir / 'atmos.199501-199912.temp.nc').resolve()),
    ])


def test_collect_stage_files_cli_bounds_override_yaml(tmp_path):
    """Explicit bounds take precedence over bounds stored in YAML."""
    yamlfile, input_dir = _stage_case(tmp_path)

    result = collect_stage_files(str(yamlfile), start='2000', stop='2004')

    assert result == [str((input_dir / 'atmos.200001-200412.temp.nc').resolve())]


def test_stage_invokes_dmget_once_with_deduplicated_files(tmp_path):
    """Every selected path is passed to one subprocess invocation."""
    yamlfile, _ = _stage_case(tmp_path)

    with patch('fremor.cmor_stage.subprocess.run') as run_mock:
        result = cmor_stage_subtool(str(yamlfile), dmget_bin='/opt/bin/dmget')

    run_mock.assert_called_once_with(['/opt/bin/dmget', *result], check=True)


def test_stage_dry_run_does_not_invoke_dmget(tmp_path):
    """Dry-run discovery is side-effect free."""
    yamlfile, _ = _stage_case(tmp_path)

    with patch('fremor.cmor_stage.subprocess.run') as run_mock:
        result = cmor_stage_subtool(str(yamlfile), dry_run=True)

    assert len(result) == 2
    run_mock.assert_not_called()


def test_collect_stage_files_rejects_invalid_year(tmp_path):
    """Invalid year bounds fail before invoking dmget."""
    yamlfile, _ = _stage_case(tmp_path)

    with pytest.raises(ValueError, match='four-digit year'):
        collect_stage_files(str(yamlfile), start='95')


def test_stage_rejects_empty_selection(tmp_path):
    """An empty batch is reported rather than invoking dmget with no paths."""
    yamlfile, _ = _stage_case(tmp_path)

    with pytest.raises(ValueError, match='no mapped input files'):
        cmor_stage_subtool(str(yamlfile), start='2010', stop='2014', dry_run=True)
