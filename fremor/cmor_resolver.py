"""
``fremor resolve``: FRE-style YAML resolver
===========================================

This module resolves the small subset of FRE-flavored YAML needed for CMOR
debugging and iteration. It reads a model YAML, finds the referenced CMOR YAML
and optional grids YAML for a selected experiment, and returns the resolved
combined YAML mapping.
"""

from pathlib import Path
import json
import os
from typing import Optional

import yaml

from .cmor_helpers import check_path_existence


class FremorYamlLoader(yaml.SafeLoader):
    """Safe loader for FRE-flavored YAML, extended only with the ``!join`` string constructor."""


def _yaml_join(loader, node):
    """Support FRE's ``!join`` tag when resolving model/cmor YAML references."""
    return ''.join(
        '' if item is None else str(item)
        for item in loader.construct_sequence(node)
    )


FremorYamlLoader.add_constructor('!join', _yaml_join)


def _resolve_yaml_reference(base_yaml: Path, reference: str) -> Path:
    """Resolve a YAML reference relative to the file that declared it."""
    resolved = Path(os.path.expandvars(reference))
    if resolved.is_absolute():
        return resolved
    return (base_yaml.parent / resolved).resolve()


def _load_yaml_dict(yaml_path: Path) -> dict:
    """Load one YAML file with fremor's safe loader."""
    with open(yaml_path, encoding='utf-8') as handle:
        loaded = yaml.load(handle, Loader=FremorYamlLoader)  # nosec B506: SafeLoader subclass with !join only
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f'expected YAML mapping in {yaml_path}, got {type(loaded).__name__}')
    return loaded


def resolve_fremor_yaml(yamlfile: str,
                        experiment: str,
                        platform: Optional[str],
                        target: Optional[str],
                        output: Optional[str] = None) -> dict:
    """
    Resolve a FRE model YAML into the combined YAML mapping needed for debugging.

    :param yamlfile: Path to the model YAML file.
    :param experiment: Experiment name to resolve.
    :param platform: Platform name used by runtime anchors.
    :param target: Target name used by runtime anchors.
    :param output: Optional output path for the resolved YAML.
    :return: Resolved YAML dictionary.
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

    runtime_header = (
        'fremor_runtime:\n'
        f'  name: &name {json.dumps(experiment)}\n'
        f'  platform: &platform {json.dumps(platform)}\n'
        f'  target: &target {json.dumps(target)}\n'
    )

    combined_yaml_text = runtime_header
    for yaml_path in [model_yaml_path, *grid_yaml_paths, cmor_yaml_path]:
        combined_yaml_text += yaml_path.read_text(encoding='utf-8')
        combined_yaml_text += '\n'

    combined_yaml = yaml.load(combined_yaml_text, Loader=FremorYamlLoader)  # nosec B506: SafeLoader subclass with !join only
    if combined_yaml is None:
        combined_yaml = {}
    resolved_yaml = {
        key: combined_yaml[key]
        for key in ('fre_properties', 'grids', 'cmor')
        if key in combined_yaml
    }

    if output is not None:
        with open(output, 'w', encoding='utf-8') as handle:
            yaml.safe_dump(resolved_yaml, handle, sort_keys=False)

    return resolved_yaml
