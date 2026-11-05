"""Shared configuration helpers for CMOR tests."""

import json
from pathlib import Path


def write_table(tables_dir, table_name, var_names):
    variable_entry = {name: {'standard_name': name} for name in var_names}
    (Path(tables_dir) / f'CMIP6_{table_name}.json').write_text(
        json.dumps({'Header': {'table_id': f'Table {table_name}'}, 'variable_entry': variable_entry}),
        encoding='utf-8'
    )


def component_entry(component_name, variable_list_path, chunk='P5Y'):
    return {
        'component_name': component_name,
        'variable_list': str(variable_list_path),
        'data_series_type': 'ts',
        'chunk': chunk,
    }


def table_target(table_name, components, freq='monthly'):
    return {
        'table_name': table_name,
        'freq': freq,
        'gridding': {'grid_label': 'gn', 'grid_desc': 'd', 'nom_res': '100 km'},
        'target_components': components,
    }


def minimal_cmor_yaml_doc(root_dir, pp_dir, tables_dir, table_targets, mip_era):
    root_dir = Path(root_dir)
    return {
        'cmor': {
            'start': None,
            'stop': None,
            'calendar_type': 'noleap',
            'mip_era': mip_era,
            'exp_json': str(root_dir / 'exp.json'),
            'directories': {
                'pp_dir': str(pp_dir),
                'table_dir': str(tables_dir),
                'outdir': str(root_dir / 'out'),
            },
            'table_targets': table_targets,
        }
    }
