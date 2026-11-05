"""Shared configuration helpers for CMOR tests."""

import glob
import json
from pathlib import Path


def write_table(tables_dir, table_name, var_names):
    """Write a minimal CMIP6 table containing the requested variables."""
    variable_entry = {name: {'standard_name': name} for name in var_names}
    (Path(tables_dir) / f'CMIP6_{table_name}.json').write_text(
        json.dumps({'Header': {'table_id': f'Table {table_name}'}, 'variable_entry': variable_entry}),
        encoding='utf-8'
    )


def component_entry(component_name, variable_list_path, chunk='P5Y'):
    """Build a CMOR component configuration entry for tests."""
    return {
        'component_name': component_name,
        'variable_list': str(variable_list_path),
        'data_series_type': 'ts',
        'chunk': chunk,
    }


def table_target(table_name, components, freq='monthly'):
    """Build a CMOR table target using the supplied components."""
    return {
        'table_name': table_name,
        'freq': freq,
        'gridding': {'grid_label': 'gn', 'grid_desc': 'd', 'nom_res': '100 km'},
        'target_components': components,
    }


def minimal_cmor_yaml_doc(root_dir, pp_dir, tables_dir, table_targets, mip_era):
    """Create the minimal CMOR YAML document used by tests."""
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


def ncgen_for_case(testfile_dir, opt_var_name, ncgen):
    """Convert test CDL files to NetCDF, including variable-specific ancillary files."""
    cdl_files = glob.glob(f'{testfile_dir}*.{opt_var_name}.cdl')
    assert len(cdl_files) >= 1, (
        f'no CDL file found for variable {opt_var_name} in {testfile_dir}'
    )
    cdl_file = cdl_files[0]
    nc_file = cdl_file.replace('.cdl', '.nc')
    ncgen(cdl_file, nc_file)

    if opt_var_name in ('cl', 'mc'):
        ps_cdl = cdl_file.replace(f'{opt_var_name}.cdl', 'ps.cdl')
        assert Path(ps_cdl).exists(), f'ps CDL not found: {ps_cdl}'
        ncgen(ps_cdl, ps_cdl.replace('.cdl', '.nc'))
    elif opt_var_name == 'sos':
        static_cdl = testfile_dir.replace(
            'ts/monthly/5yr/', 'ocean_monthly.static.cdl'
        )
        if Path(static_cdl).exists():
            ncgen(static_cdl, static_cdl.replace('.cdl', '.nc'))

    return nc_file
