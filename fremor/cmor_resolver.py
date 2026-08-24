"""
``fremor resolve``: model-YAML resolver
=======================================

This module resolves the FRE-style model YAML workflow used in some test
fixtures and debugging sessions.

Here "resolve" means: locate the model YAML, identify which CMOR YAML and
optional grids YAML belong to the requested experiment, concatenate those
files into one YAML document so that anchors defined in the model or grids
files are visible when the CMOR section is parsed, and return the materialized
mapping with every anchor already expanded into plain Python values.
"""

from pathlib import Path
import os
from typing import Optional

import yaml

from .cmor_helpers import check_path_existence


def _resolve_yaml_reference(base_yaml: Path, reference: str) -> Path:
    """Resolve one referenced YAML path relative to the file that declared it."""
    resolved = Path(os.path.expandvars(reference))
    if resolved.is_absolute():
        return resolved
    return (base_yaml.parent / resolved).resolve()


def _load_yaml_dict(yaml_path: Path) -> dict:
    """Load one YAML file and require it to contain a mapping."""
    with open(yaml_path, encoding='utf-8') as handle:
        loaded = yaml.safe_load(handle)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f'expected YAML mapping in {yaml_path}, got {type(loaded).__name__}')
    return loaded


def resolve_fremor_yaml(yamlfile: str,
                        experiment: str,
                        output: Optional[str] = None) -> dict:
    """
    Resolve one model YAML experiment into the combined mapping used for inspection.

    "Resolve" here means: locate the model YAML, identify which CMOR YAML (and
    optional grids YAML) belong to the requested experiment, concatenate those
    files into one YAML document, and let the YAML parser expand all anchors and
    merge keys across the combined text.  The caller receives only the sections
    that are useful downstream — ``fre_properties``, ``grids``, and ``cmor`` —
    with every anchor already materialized into plain Python values.

    :param yamlfile: Path to the model YAML file.
    :param experiment: Experiment name to select from the model YAML.
    :param output: Optional path to write the resolved YAML.
    :return: Resolved YAML dictionary containing any present ``fre_properties``,
        ``grids``, and ``cmor`` sections.
    """
    model_yaml_path = Path(yamlfile).resolve()
    model_yaml = _load_yaml_dict(model_yaml_path)

    experiment_cfg = next(
        (entry for entry in model_yaml.get('experiments', []) if entry.get('name') == experiment),
        None,
    )
    if experiment_cfg is None:
        raise ValueError(f'experiment {experiment!r} not found in model yaml {model_yaml_path}')

    cmor_yaml_refs = experiment_cfg.get('cmor')
    if isinstance(cmor_yaml_refs, str):
        cmor_yaml_refs = [cmor_yaml_refs]
    if not cmor_yaml_refs:
        raise ValueError(f'no cmor yaml configured for experiment {experiment!r} in {model_yaml_path}')
    if len(cmor_yaml_refs) != 1:
        raise ValueError(
            f'experiment {experiment!r} in {model_yaml_path} must reference exactly one cmor yaml file, '
            f'found {len(cmor_yaml_refs)}'
        )

    grid_yaml_refs = experiment_cfg.get('grid_yaml', [])
    if isinstance(grid_yaml_refs, str):
        grid_yaml_refs = [grid_yaml_refs]

    cmor_yaml_path = _resolve_yaml_reference(model_yaml_path, cmor_yaml_refs[0])
    grid_yaml_paths = [
        _resolve_yaml_reference(model_yaml_path, grid_yaml_ref)
        for grid_yaml_ref in grid_yaml_refs
    ]

    check_path_existence(str(cmor_yaml_path))
    for grid_yaml_path in grid_yaml_paths:
        check_path_existence(str(grid_yaml_path))

    combined_yaml_text = ''
    for yaml_path in [model_yaml_path, *grid_yaml_paths, cmor_yaml_path]:
        combined_yaml_text += yaml_path.read_text(encoding='utf-8')
        combined_yaml_text += '\n'

    combined_yaml = yaml.safe_load(combined_yaml_text)

    resolved_yaml = {
        key: combined_yaml[key]
        for key in ('fre_properties', 'grids', 'cmor')
        if key in combined_yaml
    }

    if output is not None:
        with open(output, 'w', encoding='utf-8') as handle:
            yaml.safe_dump(resolved_yaml, handle, sort_keys=False)

    return resolved_yaml
