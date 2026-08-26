"""
fremor CLI entry point: ``fremor``
==================================

All ``fremor <command>`` call routines start here.

each ``fremor <command>`` has it's own, similarly named python function.
"""

import logging

import click
import yaml as pyyaml

from . import __version__ as version, FORMAT
from .cmor_finder import cmor_find_subtool, make_simple_varlist
from .cmor_mixer import cmor_run_subtool
from .cmor_yamler import cmor_yaml_subtool
from .cmor_resolver import resolve_fremor_yaml
from .cmor_config import cmor_config_subtool
from .cmor_check import cmor_check_subtool
from .cmor_map import cmor_map_subtool
from .cmor_init import cmor_init_subtool
from .cmor_stage import cmor_stage_subtool

fre_logger = logging.getLogger(__name__)

OPT_VAR_NAME_HELP='optional, specify a variable name to specifically process only filenames ' + \
                  'matching that variable name. I.e., this string help target local_vars, not ' + \
                  'target_vars.'
VARLIST_HELP='path pointing to a json file containing directory of key/value pairs. ' + \
             'the keys are the modeler\'s variable names used in the filename and ' + \
             'expected as the variable name within the targeted files. the values ' + \
             'pointed to by those keys are strings representing the corresponding ' + \
             'MIP table variable name. the key and value are often the same, ' + \
             'but it is not required.'
RUN_STRICT_HELP='exit when a cmor_run_subtool call throws an exception'
RUN_ONE_HELP='process only one file, then exit. mostly for debugging and isolating issues.'
DRY_RUN_HELP='don\'t call the cmor_mixer subtool, just printout what would be called and move on until natural exit'
START_YEAR_HELP = 'string representing the minimum calendar year CMOR should start processing for. ' + \
                  'currently, only YYYY format is supported.'
STOP_YEAR_HELP = 'string representing the maximum calendar year CMOR should stop processing for. ' + \
                  'currently, only YYYY format is supported.'
VARLIST_STRICT_MODE_HELP='if indicated, and given a table and variable names found in filenames, if none of the ' + \
                         'found variable names are in the table (sans brand if cmip7), do not write the list.'

@click.version_option(
    package_name = 'fremor',
    version = version
)
@click.group(
    help = click.style(
        'fremor is the main CLI for fremor. it houses the cmor subcommands.',
        fg = 'cyan')
)
@click.option( '-v', '--verbose',
               default = 0,
               required = False,
               count = True,
               type = click.IntRange(0, 2, clamp=True), # Replaced int with click.IntRange
               help = 'Increment logging verbosity from default (logging.WARNING) to logging.INFO. ' + \
                      'use -vv for logging.DEBUG. will be overridden by -q/--quiet' )
@click.option( '-q', '--quiet',
               default = False,
               required = False,
               is_flag = True,
               type = bool,
               help = 'Set logging verbosity from default (logging.WARNING) to logging.ERROR, printing ' + \
                      'less output to screen. overrides -v[v]/--verbose' )
@click.option( '-l', '--log_file',
               default = None,
               required = False,
               type = str,
               help = 'Path to log file for all fremor calls, the output to screen will still print with the ' + \
                      'path specified. If the log file already exists, it is appended to.' )
def fremor(verbose = 0, quiet = False, log_file = None):
    """
    entry point function to subgroup functions, setting global verbosity/logging formats that all
    other routines will utilize
    """
    log_level = logging.WARNING # default
    if verbose == 1:
        log_level = logging.INFO # -v, more verbose than default
    elif verbose == 2:
        log_level = logging.DEBUG # -vv most verbose

    if quiet:
        log_level = logging.ERROR # least verbose

    base_fre_logger=fre_logger.parent
    base_fre_logger.setLevel(level = log_level)
    fre_logger.debug('root fre_logger level set')

    # check if log_file arg was used
    if log_file is not None:
        fre_logger.debug('creating fre_file_handler for fre_logger')
        fre_file_handler=logging.FileHandler(log_file,
                                             mode='a',encoding='utf-8',
                                             delay=False)

        fre_logger.debug('setting fre_file_handler logging format:')
        fre_log_file_formatter=logging.Formatter(fmt=FORMAT)
        fre_file_handler.setFormatter(fre_log_file_formatter)

        base_fre_logger.addHandler(fre_file_handler)
        # first message that will appear in the log file if used
        fre_logger.info('fre_file_handler added to base_fre_logger')

    fre_logger.debug('click entry-point function call done.')


@fremor.command()
@click.option('-y', '--yamlfile', type = str,
              help = 'YAML file to be used for parsing',
              required = True )
@click.option('--run_strict', is_flag = True, default = False,
              help=RUN_STRICT_HELP,
              required = False)
@click.option('--run_one', is_flag = True, default = False,
              help=RUN_ONE_HELP,
              required = False)
@click.option('--dry_run', is_flag = True, default = False,
              help=DRY_RUN_HELP,
              required = False)
@click.option('--start', type=str, default=None,
              help = START_YEAR_HELP,
              required = False)
@click.option('--stop', type=str, default=None,
              help = STOP_YEAR_HELP,
              required = False)
@click.option('--print_cli_call/--no-print_cli_call', default=True,
              help = 'In dry-run mode, print the equivalent CLI invocation (default) '
                     'or the Python cmor_run_subtool() call.',
              required = False)
def yaml(yamlfile, run_strict, run_one, dry_run, start, stop, print_cli_call):
    """Process a self-contained CMOR YAML file and run the requested CMORization steps."""
    cmor_yaml_subtool(
        yamlfile = yamlfile,
        run_strict_mode = run_strict,
        run_one_mode = run_one,
        dry_run_mode = dry_run,
        start = start,
        stop = stop,
        print_cli_call = print_cli_call
    )


@fremor.command()
@click.option('-y', '--yamlfile', type=str, required=True,
              help='Self-contained CMOR YAML file whose mapped input files should be staged.')
@click.option('--start', type=str, default=None, help=START_YEAR_HELP)
@click.option('--stop', type=str, default=None, help=STOP_YEAR_HELP)
@click.option('--dmget_bin', type=str, default='dmget', show_default=True,
              help='dmget executable name or path.')
@click.option('--dry_run', is_flag=True, default=False,
              help='List the selected files without invoking dmget.')
def stage(yamlfile, start, stop, dmget_bin, dry_run):
    """Stage all mapped archive inputs for a YAML-driven run in one dmget batch."""
    input_files = cmor_stage_subtool(
        yamlfile=yamlfile,
        start=start,
        stop=stop,
        dmget_bin=dmget_bin,
        dry_run=dry_run,
    )
    if dry_run:
        for input_file in input_files:
            click.echo(input_file)
        click.echo(f'Would stage {len(input_files)} files in one dmget batch.')
    else:
        click.echo(f'Staged {len(input_files)} files in one dmget batch.')


@fremor.command()
@click.option('-y', '--yamlfile', type=str,
              help='Model YAML file to resolve',
              required=True)
@click.option('-e', '--experiment', type=str,
              help='Experiment name to resolve',
              required=True)
@click.option('-o', '--output', type=str, default=None,
              help='Optional output file for the resolved YAML',
              required=False)
def resolve(yamlfile, experiment, output):
    """Resolve one model-YAML experiment into a combined YAML document for inspection."""
    resolved_yaml = resolve_fremor_yaml(
        yamlfile=yamlfile,
        experiment=experiment,
        output=output,
    )
    if output is None:
        click.echo(pyyaml.safe_dump(resolved_yaml, sort_keys=False))


@fremor.command()
@click.option('-l', '--varlist', type = str,
              help=VARLIST_HELP,
              required=False)
@click.option('-r', '--table_config_dir', type = str,
              help='directory holding MIP tables to search for variables in var list',
              required=True)
@click.option('-v', '--opt_var_name', type = str,
              help=OPT_VAR_NAME_HELP,
              required=False)
def find(varlist, table_config_dir, opt_var_name):
    """
    loop over json table files in config_dir and show which tables contain variables in var list/
    the tool will also print what that table entry is expecting of that variable as well. if given
    an opt_var_name in addition to varlist, only that variable name will be printed out.
    accepts 3 arguments, two of the three required.
    """
    cmor_find_subtool(
        json_var_list = varlist,
        json_table_config_dir = table_config_dir,
        opt_var_name = opt_var_name
    )


@fremor.command()
@click.option('-d', '--indir', type = str,
              help='directory containing netCDF files. keys specified in json_var_list are local ' + \
                   'variable names used for targeting specific files in this directory',
              required=True)
@click.option('-l', '--varlist', type = str,
              help=VARLIST_HELP,
              required=True)
@click.option('-r', '--table_config', type = str,
              help='json file containing CMIP-compliant per-variable/metadata for specific ' + \
                   'MIP table. The MIP table can generally be identified by the specific ' + \
                   'filename (e.g. \'Omon\')',
              required=True)
@click.option('-p', '--exp_config', type = str,
              help='json file containing metadata dictionary for CMORization. this metadata is ' + \
                   'effectively appended to the final output file\'s header',
              required=True)
@click.option('-o', '--outdir', type = str,
              help='directory root that will contain the full output and output directory ' + \
                   'structure generated by the cmor module upon request.',
              required=True)
@click.option('--run_one', is_flag = True, default = False,
              help=RUN_ONE_HELP,
              required = False)
@click.option('-v', '--opt_var_name', type = str, default = None,
              help=OPT_VAR_NAME_HELP,
              required=False)
@click.option('-g', '--grid_label', type = str, default = None,
              help = 'label representing grid type of input data, e.g. gn for native or gr for regridded, ' + \
                     'replaces the grid_label field in the CMOR experiment configuration file. The label must ' + \
                     'be one of the entries in the MIP controlled-vocab file.',
              required = False)
@click.option('--grid_desc', type = str, default = None,
              help = 'description of grid indicated by grid label, replaces the grid field in the CMOR ' + \
                     'experiment configuration file.',
              required = False)
@click.option('--nom_res', type = str, default = None,
              help = 'nominal resolution indicated by grid and/or grid label, replaces the nominal_resolution, ' + \
                     'replaces the grid field in the CMOR experiment configuration file. The entered string ' + \
                     'must be one of the entries in the MIP controlled-vocab file.',
              required = False)
@click.option('--start', type=str, default=None,
              help = START_YEAR_HELP,
              required = False)
@click.option('--stop', type=str, default=None,
              help = STOP_YEAR_HELP,
              required = False)
@click.option('--calendar', type=str, default=None,
              help = 'calendar type, e.g. 360_day, noleap, gregorian... etc',
              required = False)
def run(indir, varlist, table_config, exp_config, outdir, run_one, opt_var_name,
        grid_label, grid_desc, nom_res, start, stop, calendar):
    """
    Rewrite climate model output files with CMIP-compliant metadata for down-stream publishing
    """
    cmor_run_subtool(
        indir = indir,
        json_var_list = varlist,
        json_table_config = table_config,
        json_exp_config = exp_config,
        outdir = outdir,
        run_one_mode = run_one,
        opt_var_name = opt_var_name,
        grid = grid_desc,
        grid_label = grid_label,
        nom_res = nom_res,
        start = start,
        stop = stop,
        calendar_type = calendar
    )


@fremor.command('varlist')
@click.option('-d', '--dir_targ', type=str, required=True, help='Target directory')
@click.option('--strict_mode', is_flag = True, default = False,
              help=VARLIST_STRICT_MODE_HELP,
              required=False)
@click.option('-o', '--output_variable_list', type=str, required=True, help='Output variable list file')
@click.option('-t', '--mip_table', type=str, required=False, default=None,
              help='Target MIP table for making variable list')
def varlist_(dir_targ, strict_mode, output_variable_list, mip_table):
    """
    Create a simple variable list from netCDF files in the target directory.
    """
    make_simple_varlist(dir_targ = dir_targ,
                        return_none_if_no_mip_vars= strict_mode,
                        output_variable_list = output_variable_list,
                        json_mip_table = mip_table)


@fremor.command()
@click.option('-p', '--pp_dir', type=str, required=True,
              help='Root post-processing directory containing per-component subdirectories.')
@click.option('-t', '--mip_tables_dir', type=str, required=True,
              help='Directory containing MIP table JSON files.')
@click.option('-m', '--mip_era', type=str, required=True,
              help='MIP era identifier, e.g. cmip6 or cmip7.')
@click.option('-e', '--exp_config', type=str, required=True,
              help='Path to JSON experiment/input configuration file expected by CMOR.')
@click.option('-o', '--output_yaml', type=str, required=True,
              help='Path for the output CMOR YAML configuration file.')
@click.option('-d', '--output_dir', type=str, required=True,
              help='Root output directory for CMORized data.')
@click.option('-l', '--varlist_dir', type=str, required=True,
              help='Directory in which per-component variable list JSON files are written.')
@click.option('-g', '--pp_comp_glob', type=str, required=False, default = '*',
              help="glob pattern to use for selecting pp component directory names. default '*'")
@click.option('--strict_varlist', is_flag=True, default=False,
              help='pass strict_mode flag to fremor varlist')
@click.option('--freq', type=str, default='monthly',
              help='Temporal frequency string, e.g. monthly, daily. Default monthly.')
@click.option('--chunk', type=str, default='5yr',
              help='Time chunk string, e.g. 5yr, 10yr. Default 5yr.')
@click.option('--grid', type=str, default='g999',
              help='Grid label anchor name, e.g. g999, gn. Default g999.')
@click.option('--overwrite', is_flag=True, default=False,
              help='Overwrite existing variable list files.')
@click.option('--calendar', type=str, default='noleap',
              help='Calendar type, e.g. noleap, 360_day. Default noleap.')
def config(pp_dir, mip_tables_dir, mip_era, exp_config, output_yaml,
           output_dir, pp_comp_glob, strict_varlist, varlist_dir, freq, chunk, grid, overwrite, calendar):
    """
    Generate a CMOR YAML configuration file from a post-processing directory tree.
    Scans pp_dir for components and time-series data, cross-references against MIP tables,
    and writes a YAML configuration that 'fremor yaml' can consume.
    """
    cmor_config_subtool(
        pp_dir=pp_dir,
        mip_tables_dir=mip_tables_dir,
        mip_era=mip_era,
        exp_config=exp_config,
        output_yaml=output_yaml,
        output_dir=output_dir,
        varlist_dir=varlist_dir,
        pp_comp_glob=pp_comp_glob,
        strict_varlist=strict_varlist,
        freq=freq,
        chunk=chunk,
        grid=grid,
        overwrite=overwrite,
        calendar_type=calendar
    )


@fremor.command()
@click.argument('tables', nargs=-1)
@click.option('-y', '--yamlfile', type=str, required=True,
              help='Self-contained CMOR YAML file, as written by \'fremor config\'. pp_dir, '
                   'the MIP tables directory, the MIP era, and each component\'s variable_list '
                   'path are all derived from it.')
@click.option('--show_mapped', is_flag=True, default=False,
              help='Also report variables mapped from exactly one component/diagnostic (one-to-one).')
@click.option('--staging', 'check_staging', is_flag=True, default=False,
              help='For every one-to-one-mapped variable, also check whether its input files '
                   'exist under pp_dir and whether they are staged/disk-resident (best-effort, '
                   'via dmls if available, else a stat-only heuristic -- never reads file '
                   'content), plus a filename-only scan for gaps between chunk date ranges.')
@click.option('--dims', 'check_dims', is_flag=True, default=False,
              help='For every one-to-one-mapped variable, also check whether a representative '
                   'input file\'s vertical dimension matches what the MIP table declares (e.g. '
                   'distinguishing model-level "alevel" output from fixed "plevNN" pressure '
                   'levels), and whether hybrid-sigma variables have their companion .ps.nc '
                   'file present. Only inspects one file\'s header per variable.')
@click.option('--dmls_bin', type=str, default=None,
              help='Path to the dmls binary for the --staging check. If omitted, looks for '
                   '\'dmls\' on PATH; if not found either, falls back to a stat-only residency '
                   'heuristic.')
@click.option('--json', 'json_output', is_flag=True, default=False,
              help='Print the report as JSON instead of a text summary.')
@click.option('-o', '--output_report', type=str, default=None,
              help='Optional path to also write the JSON report to.')
def check(tables, yamlfile, show_mapped, check_staging, check_dims, dmls_bin,
          json_output, output_report):
    """
    Check variable-mapping coverage of varlist files against MIP tables, and optionally
    the actual pp_dir input files those mappings resolve to.

    For each MIP table in yamlfile's table_targets, reports CMIP variables required
    by the table but not mapped from any component, variables mapped from more than
    one component/diagnostic, and mapped values that don't correspond to any variable
    actually defined in that table.

    Pass --staging and/or --dims to additionally check, for every one-to-one-mapped
    variable, whether its pp_dir input files are present and staged, and whether their
    vertical dimension matches what the MIP table expects.

    TABLES is an optional list of MIP table names to check, e.g. 'Amon' or
    'Lmon'. Shell-style wildcards are supported, e.g. 'AER*'. If omitted,
    every MIP table in yamlfile's table_targets is checked.
    """
    cmor_check_subtool(
        yamlfile=yamlfile,
        table_patterns=tables,
        show_mapped=show_mapped,
        json_output=json_output,
        output_report=output_report,
        check_staging=check_staging,
        check_dims=check_dims,
        dmls_bin=dmls_bin
    )


@fremor.command('map')
@click.argument('tables', nargs=-1)
@click.option('-y', '--yamlfile', type=str, required=True,
              help='Self-contained CMOR YAML file, as written by \'fremor config\'. pp_dir, '
                   'the MIP tables directory, the MIP era, and each component\'s variable_list '
                   'path are all derived from it; mapping edits are staged in memory and only '
                   'written back to the variable_list files referenced there once you save.')
@click.option('--ncinfo_bin', type=str, required=False, default=None,
              help='Path to the ncinfo binary for richer NetCDF file previews. If omitted, '
                   'looks for \'ncinfo\' on PATH; if not found either, falls back to a plain '
                   'netCDF4-based preview.')
def map_(tables, yamlfile, ncinfo_bin):
    """
    Open an interactive TUI to review and edit variable-mapping varlist files.

    Shows each selected MIP table as a tree of variables alongside their current mapping
    status (unmapped / mapped / multiply-mapped / unknown, as reported by 'fremor check'),
    and lets you browse time-series files under pp_dir to assign or fix a mapping. When
    selecting a file, a preview panel shows its variable's dimensions/attributes via ncinfo
    (if available) or netCDF4 as a fallback; the preview loads in the background (showing a
    loading message meanwhile) so the UI stays responsive, and switching to another file
    before it finishes discards the outdated result.

    Pressing 'm'/'d' only stages a mapping/clear in memory, marking the affected node in
    place (a newly (re)mapped variable shows '<- component:local_key', a cleared mapping is
    struck through and labeled '(deleted)') so you can batch edits across many variables
    without the tree collapsing; press 's' to write all staged changes to disk. Press 'q' to
    quit; if there are unsaved staged changes, 'q' warns first and requires a second 'q' to
    confirm quitting without saving.

    TABLES is an optional list of MIP table names to load, e.g. 'Amon' or 'Lmon'. Shell-style
    wildcards are supported, e.g. 'AER*'. If omitted, every MIP table in yamlfile's
    table_targets is loaded.
    """
    cmor_map_subtool(
        yamlfile=yamlfile,
        table_patterns=tables,
        ncinfo_bin=ncinfo_bin
    )


@fremor.command()
@click.option('-m', '--mip_era', type=click.Choice(['cmip6', 'cmip7'], case_sensitive=False),
              required=True,
              help='MIP era for the template: cmip6 or cmip7.')
@click.option('-e', '--exp_config', type=str, default=None,
              help='Output path for the template experiment-config JSON file. '
                   'When omitted and --tables_dir is also omitted, a default '
                   'filename is used.')
@click.option('-t', '--tables_dir', type=str, default=None,
              help='Directory into which MIP tables will be fetched from '
                   'trusted sources. Omit to skip table retrieval.')
@click.option('--tag', type=str, default=None,
              help='Specific git tag or release for the MIP tables repository.')
@click.option('--fast', is_flag=True, default=False,
              help='Use curl to download a tarball instead of git clone.')
def init(mip_era, exp_config, tables_dir, tag, fast):
    """
    Initialise CMOR resources: write an empty experiment-config JSON template
    and/or fetch MIP tables from trusted sources.
    """
    cmor_init_subtool(
        mip_era=mip_era,
        exp_config=exp_config,
        tables_dir=tables_dir,
        tag=tag,
        fast=fast
    )
