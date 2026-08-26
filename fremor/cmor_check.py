"""
``fremor check``: Variable Mapping Coverage Check
==================================================

This module powers the ``fremor check`` command. It cross-references the
per-component variable list files (as written by ``fremor config`` /
``fremor varlist``) against the authoritative MIP table JSON files fetched
by ``fremor init`` (e.g. the ``cmip6-cmor-tables`` / ``cmip7-cmor-tables``
repos) and reports, per MIP table:

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
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional, Sequence

import click

from .cmor_config import _filter_mip_tables
from .cmor_helpers import get_json_file_data

fre_logger = logging.getLogger(__name__)

VARLIST_FILENAME_RE = re.compile(
    r'^(?P<era>[A-Za-z0-9]+)_(?P<table>[A-Za-z0-9]+)_(?P<component>.+)\.list$'
)


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


def _load_varlists_by_table(varlist_dir: str, era_upper: str) -> dict:
    """
    Group varlist JSON files in ``varlist_dir`` by MIP table name.

    Expects filenames of the form ``{ERA}_{table_name}_{component_name}.list``,
    matching what ``fremor config`` / ``fremor varlist`` write.

    :return: table_name -> list of (component_name, filename, data) tuples
    :rtype: dict
    """
    grouped = defaultdict(list)
    for path in sorted(Path(varlist_dir).glob(f'{era_upper}_*.list')):
        match = VARLIST_FILENAME_RE.match(path.name)
        if not match or match.group('era') != era_upper:
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            fre_logger.warning('failed to parse %s: %s', path.name, exc)
            continue
        grouped[match.group('table')].append((match.group('component'), path.name, data))
    return grouped


def _select_mip_tables(mip_tables: list, table_patterns: Sequence[str]) -> list:
    """
    Filter a list of MIP table JSON paths down to those whose table name
    (e.g. 'Amon' from 'CMIP6_Amon.json') matches at least one of the given
    glob-style patterns. If no patterns are given, all tables are kept.
    """
    if not table_patterns:
        return mip_tables
    selected = []
    for table_path in mip_tables:
        table_name = Path(table_path).stem.split('.')[0].split('_')[1]
        if any(fnmatch.fnmatchcase(table_name, pattern) for pattern in table_patterns):
            selected.append(table_path)
    return selected


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
        varlist_dir: str,
        mip_tables_dir: str,
        mip_era: str,
        table_patterns: Sequence[str] = (),
        show_mapped: bool = False,
        json_output: bool = False,
        output_report: Optional[str] = None
) -> dict:
    """
    Cross-reference per-component varlist files against MIP table JSON files
    and report unmapped, multiply-mapped, and unrecognized variable mappings
    per MIP table.

    :param varlist_dir: directory containing ``{ERA}_{table}_{component}.list`` files.
    :type varlist_dir: str
    :param mip_tables_dir: directory containing MIP table JSON files (e.g. fetched via ``fremor init``).
    :type mip_tables_dir: str
    :param mip_era: MIP era identifier, e.g. 'cmip6' or 'cmip7'.
    :type mip_era: str
    :param table_patterns: optional glob-style patterns (e.g. 'Amon', 'AER*') selecting which MIP
        tables to check by name. If empty, every MIP table found in mip_tables_dir is checked.
    :type table_patterns: Sequence[str]
    :param show_mapped: if True, also report variables mapped from exactly one component/diagnostic.
    :type show_mapped: bool
    :param json_output: if True, print the report as JSON instead of a text summary.
    :type json_output: bool
    :param output_report: optional path to also write the JSON report to.
    :type output_report: str or None
    :raises FileNotFoundError: if varlist_dir or mip_tables_dir do not exist.
    :raises ValueError: if no MIP tables are found for the given era after filtering, or if none
        of the given table_patterns match any MIP table found.
    :return: table_name -> report dict, with keys 'reference_var_count', 'unmapped',
             'multiply_mapped', 'unknown_mapped', and (if show_mapped) 'one_to_one_mapped'.
    :rtype: dict
    """
    if not Path(varlist_dir).is_dir():
        raise FileNotFoundError(f'varlist_dir does not exist: {varlist_dir}')
    if not Path(mip_tables_dir).is_dir():
        raise FileNotFoundError(f'mip_tables_dir does not exist: {mip_tables_dir}')

    mip_tables = _filter_mip_tables(mip_tables_dir, mip_era)
    if not mip_tables:
        raise ValueError(
            f'no MIP tables found in {mip_tables_dir} for era {mip_era} after filtering')

    mip_tables = _select_mip_tables(mip_tables, table_patterns)
    if not mip_tables:
        raise ValueError(
            f'no MIP tables in {mip_tables_dir} matched table_patterns {list(table_patterns)}')

    era_upper = mip_era.upper()
    varlists_by_table = _load_varlists_by_table(varlist_dir, era_upper)

    report = {}
    for table_path in sorted(mip_tables):
        table_entry = _build_table_report(table_path, mip_era, varlists_by_table,
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
