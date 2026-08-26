"""
``fremor check``: Variable Mapping Coverage Check
==================================================

This module powers the ``fremor check`` command. It reads a self-contained CMOR YAML file
(as written by ``fremor config``) to derive pp_dir, the MIP tables directory, the MIP era,
and each component's variable list path, cross-references the per-component variable lists
against the authoritative MIP table JSON files fetched by ``fremor init`` (e.g. the
``cmip6-cmor-tables`` / ``cmip7-cmor-tables`` repos), and reports, per MIP table:

- variables the MIP table actually requires (its ``variable_entry`` keys)
  that are not mapped from any GFDL post-processing component, and
- variables mapped from more than one ``(component, GFDL diagnostic key)``
  pair, and
- values written into a varlist that don't correspond to any variable
  actually defined in that MIP table (typos / stale mappings).

The reference set of variables per table comes straight from the downloaded
MIP table JSON, not from whatever happens to already be mapped somewhere in
the varlist directory -- so this also catches variables GFDL has never
mapped at all.

By default every MIP table found in mip_tables_dir is checked; pass one or
more glob-style table-name patterns (e.g. ``Amon``, ``AER*``) to restrict
the check to a subset. Pass show_mapped=True to also report variables that
are cleanly mapped from exactly one component/diagnostic (one-to-one).

Functions
---------
- ``cmor_check_subtool(...)``
"""

import fnmatch
import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Optional, Sequence

import click

from .cmor_config import _load_config_yaml
from .cmor_helpers import get_json_file_data

fre_logger = logging.getLogger(__name__)


def _reference_vars_for_table(table_path: str, mip_era: str) -> set:
    """
    Get the set of variable names a MIP table actually requires, straight
    from its ``variable_entry`` keys.

    :param table_path: path to a MIP table JSON file, e.g. ``CMIP6_Amon.json``
    :type table_path: str
    :param mip_era: MIP era string, e.g. 'cmip6' or 'cmip7'
    :type mip_era: str
    :return: set of variable names required by this table
    :rtype: set
    """
    data = get_json_file_data(table_path)
    variable_entry = data.get('variable_entry', {})
    if mip_era.lower() == 'cmip7':
        # cmip7 tables key on branded variable names, e.g. "tas_tavg-h2m-hxy-u"
        return {key.split('_')[0] for key in variable_entry.keys()}
    return set(variable_entry.keys())


def _select_table_names(table_names: Sequence[str], table_patterns: Sequence[str]) -> list:
    """
    Filter a list of MIP table names down to those matching at least one of the given
    glob-style patterns (e.g. 'Amon', 'AER*'). If no patterns are given, all names are kept.
    """
    if not table_patterns:
        return list(table_names)
    return [
        table_name for table_name in table_names
        if any(fnmatch.fnmatchcase(table_name, pattern) for pattern in table_patterns)
    ]


def _mip_table_paths(mip_tables_dir: str, mip_era: str, table_names: Sequence[str]) -> dict:
    """
    Resolve each of the given MIP table names to its ``{ERA}_{table_name}.json`` path in
    ``mip_tables_dir``.

    :raises FileNotFoundError: if a table name has no corresponding MIP table JSON file.
    :return: table_name -> table_path
    :rtype: dict
    """
    era_upper = mip_era.upper()
    table_paths = {}
    for table_name in table_names:
        table_path = f'{mip_tables_dir}/{era_upper}_{table_name}.json'
        if not Path(table_path).is_file():
            raise FileNotFoundError(f'MIP table for {table_name} not found: {table_path}')
        table_paths[table_name] = table_path
    return table_paths


def _varlists_by_table_from_yaml(table_targets: Sequence[dict]) -> dict:
    """
    Group per-component variable lists by MIP table name, reading the ``variable_list``
    paths straight out of a cmor yaml's ``table_targets`` (as written by ``fremor config``)
    instead of globbing a directory for files matching a naming convention.

    :return: table_name -> list of (component_name, variable_list_path, data) tuples
    :rtype: dict
    """
    grouped = defaultdict(list)
    for table_target in table_targets:
        table_name = table_target['table_name']
        for comp in table_target.get('target_components') or []:
            component_name = comp['component_name']
            variable_list_path = os.path.expandvars(comp['variable_list'])
            try:
                data = get_json_file_data(variable_list_path)
            except FileNotFoundError:
                fre_logger.warning('variable_list not found, treating as empty: %s',
                                   variable_list_path)
                data = {}
            grouped[table_name].append((component_name, variable_list_path, data))
    return grouped


def _build_table_report(table_path: str, mip_era: str, varlists_by_table: dict,
                        show_mapped: bool = False) -> dict:
    """Build the unmapped / multiply-mapped / unknown-mapped report for one MIP table."""
    table_name = Path(table_path).stem.split('.')[0].split('_')[1]
    reference_vars = _reference_vars_for_table(table_path, mip_era)

    mapped = defaultdict(list)  # cmip_var -> [(component, gfdl_diag_key), ...]
    for component, _fname, data in varlists_by_table.get(table_name, []):
        for gfdl_key, cmip_var in data.items():
            if cmip_var:
                mapped[cmip_var].append((component, gfdl_key))

    unmapped = sorted(reference_vars - set(mapped))
    multiply_mapped = {
        var: sorted(entries) for var, entries in mapped.items() if len(entries) > 1
    }
    unknown_mapped = sorted(set(mapped) - reference_vars)

    report_entry = {
        'table_name': table_name,
        'reference_var_count': len(reference_vars),
        'unmapped': unmapped,
        'multiply_mapped': multiply_mapped,
        'unknown_mapped': unknown_mapped,
    }

    if show_mapped:
        report_entry['one_to_one_mapped'] = {
            var: entries[0] for var, entries in mapped.items()
            if len(entries) == 1 and var in reference_vars
        }

    return report_entry


def _print_report(report: dict, show_mapped: bool = False) -> None:
    for table_name in sorted(report):
        entry = report[table_name]
        click.echo(f'\n[{table_name}]  ({entry["reference_var_count"]} variables required by table)')

        if entry['unmapped']:
            click.echo(f'  UNMAPPED ({len(entry["unmapped"])}): variables required by the table '
                       'but not mapped from any component')
            for var in entry['unmapped']:
                click.echo(f'    - {var}')
        else:
            click.echo('  UNMAPPED: none')

        if entry['multiply_mapped']:
            click.echo(f'  MULTIPLY-MAPPED ({len(entry["multiply_mapped"])}): variables mapped from '
                       'more than one component/diagnostic')
            for var in sorted(entry['multiply_mapped']):
                locs = ', '.join(f'{comp}:{key}' for comp, key in entry['multiply_mapped'][var])
                click.echo(f'    - {var}: {locs}')
        else:
            click.echo('  MULTIPLY-MAPPED: none')

        if entry['unknown_mapped']:
            click.echo(f'  UNKNOWN ({len(entry["unknown_mapped"])}): mapped values that are not '
                       'variables in this MIP table (possible typos)')
            for var in entry['unknown_mapped']:
                click.echo(f'    - {var}')

        if show_mapped:
            one_to_one = entry.get('one_to_one_mapped', {})
            if one_to_one:
                click.echo(f'  MAPPED ({len(one_to_one)}): variables mapped from exactly one '
                           'component/diagnostic')
                for var in sorted(one_to_one):
                    comp, key = one_to_one[var]
                    click.echo(f'    - {var}: {comp}:{key}')
            else:
                click.echo('  MAPPED: none')


def cmor_check_subtool(
        yamlfile: str,
        table_patterns: Sequence[str] = (),
        show_mapped: bool = False,
        json_output: bool = False,
        output_report: Optional[str] = None
) -> dict:
    """
    Cross-reference per-component varlist files against MIP table JSON files
    and report unmapped, multiply-mapped, and unrecognized variable mappings
    per MIP table.

    pp_dir, the MIP tables directory, the MIP era, and each component's variable_list path
    are all derived from ``yamlfile``, a self-contained CMOR YAML file as written by
    ``fremor config`` -- no separate varlist_dir/mip_tables_dir/mip_era flags are needed.

    :param yamlfile: path to a CMOR YAML file produced by ``fremor config``.
    :type yamlfile: str
    :param table_patterns: optional glob-style patterns (e.g. 'Amon', 'AER*') selecting which MIP
        tables to check by name. If empty, every MIP table in yamlfile's table_targets is checked.
    :type table_patterns: Sequence[str]
    :param show_mapped: if True, also report variables mapped from exactly one component/diagnostic.
    :type show_mapped: bool
    :param json_output: if True, print the report as JSON instead of a text summary.
    :type json_output: bool
    :param output_report: optional path to also write the JSON report to.
    :type output_report: str or None
    :raises FileNotFoundError: if yamlfile, its pp_dir, or its table_dir do not exist, or a
        table_target's MIP table JSON file is missing.
    :raises ValueError: if yamlfile has no table_targets, or none of the given table_patterns
        match any table_target.
    :return: table_name -> report dict, with keys 'reference_var_count', 'unmapped',
             'multiply_mapped', 'unknown_mapped', and (if show_mapped) 'one_to_one_mapped'.
    :rtype: dict
    """
    cmor_yaml_ctx = _load_config_yaml(yamlfile)
    mip_era = cmor_yaml_ctx['mip_era']
    mip_tables_dir = cmor_yaml_ctx['mip_tables_dir']
    table_targets = cmor_yaml_ctx['table_targets']

    all_table_names = sorted({table_target['table_name'] for table_target in table_targets})
    if not all_table_names:
        raise ValueError(f'no table_targets found in {yamlfile}')

    table_names = _select_table_names(all_table_names, table_patterns)
    if not table_names:
        raise ValueError(
            f'no table_targets in {yamlfile} matched table_patterns {list(table_patterns)}')

    table_paths = _mip_table_paths(mip_tables_dir, mip_era, table_names)
    varlists_by_table = _varlists_by_table_from_yaml(table_targets)

    report = {}
    for table_name in table_names:
        table_entry = _build_table_report(table_paths[table_name], mip_era, varlists_by_table,
                                          show_mapped=show_mapped)
        report[table_entry.pop('table_name')] = table_entry

    if json_output:
        click.echo(json.dumps(report, indent=2))
    else:
        _print_report(report, show_mapped=show_mapped)

    if output_report is not None:
        with open(output_report, 'w', encoding='utf-8') as handle:
            json.dump(report, handle, indent=2)
        fre_logger.info('wrote check report to %s', output_report)

    return report
