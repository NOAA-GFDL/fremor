.. _commands:

=====================
Subcommands Reference
=====================

``fremor`` rewrites climate model output files with CMIP-compliant metadata. CMIP6, CMIP6Plus, and CMIP7
workflows are supported. Available subcommands:

* ``fremor init`` — Initialize CMOR resources: generate config templates and fetch MIP tables
* ``fremor run`` — Rewrite individual directories of netCDF files
* ``fremor yaml`` — Process multiple directories/tables using YAML configuration
* ``fremor resolve`` — Combine model + grids + cmor YAMLs into one resolved document for inspection
* ``fremor find`` — Search MIP tables for variable definitions
* ``fremor varlist`` — Generate variable lists from netCDF files
* ``fremor config`` — Generate a CMOR YAML configuration from a post-processing directory tree

``init``
--------

* Initializes CMOR resources by generating experiment configuration templates and/or fetching MIP tables
* Fetches tables from trusted GitHub repositories (CMIP6: ``PCMDI/cmip6-cmor-tables``, CMIP6Plus: ``PCMDI/mip-cmor-tables``, CMIP7: ``WCRP-CMIP/cmip7-cmor-tables``)
* Minimal Syntax: ``fremor init -m [mip_era] [options]``
* Required Options:
   - ``-m, --mip_era TEXT`` — MIP era: ``cmip6``, ``cmip6plus``, or ``cmip7``
* Optional:
   - ``-e, --exp_config TEXT`` — Output path for experiment config JSON template
   - ``-t, --tables_dir TEXT`` — Directory to fetch MIP tables into
   - ``--tag TEXT`` — Specific git tag or release for MIP tables (e.g., ``6.9.33``)
   - ``--fast`` — Use curl to download tarball instead of git clone (faster)
* Examples:
   - ``fremor init -m cmip6 -e exp_config.json -t cmip6-tables``
   - ``fremor init -m cmip6plus -e exp_config.json -t mip-cmor-tables --fast``
   - ``fremor init -m cmip7 -e exp_config.json -t cmip7-tables --fast``
   - ``fremor init -m cmip6 -t cmip6-tables --tag 6.9.33``

``run``
-------

* Rewrites netCDF files in a directory to be CMIP-compliant
* Requires MIP tables and controlled vocabulary configuration
* Minimal Syntax: ``fremor run -d [indir] -l [varlist] -r [table_config] -p [exp_config] -o [outdir] [options]``
* Required Options:
   - ``-d, --indir TEXT`` — Input directory with netCDF files
   - ``-l, --varlist TEXT`` — Variable list dictionary mapping modeler variable names to MIP table variable names
   - ``-r, --table_config TEXT`` — MIP table JSON configuration
   - ``-p, --exp_config TEXT`` — Experiment/model metadata JSON
   - ``-o, --outdir TEXT`` — Output directory prefix
* Optional:
   - ``-v, --opt_var_name TEXT`` — Target specific variable
   - ``--run_one`` — Process one file for testing
   - ``-g, --grid_label TEXT`` — Grid type (e.g. ``gn``, ``gr``)
   - ``--grid_desc TEXT`` — Grid description
   - ``--nom_res TEXT`` — Nominal resolution
   - ``--start TEXT`` — Minimum year (``YYYY``)
   - ``--stop TEXT`` — Maximum year (``YYYY``)
   - ``--calendar TEXT`` — Calendar type
* Example: ``fremor run --run_one -g gr --nom_res "10000 km" -d input/ -l varlist.json -r CMIP6_Omon.json -p exp_config.json -o output/``

``yaml``
--------

* Processes YAML configuration to CMORize multiple directories/tables
* Expects a self-contained CMOR YAML file
* Minimal Syntax: ``fremor yaml -y [yamlfile] [options]``
* Required Options:
   - ``-y, --yamlfile TEXT`` — YAML file to parse
* Optional:
   - ``--run_strict`` — Exit immediately when a ``fremor run`` call raises an exception, rather than logging a warning and continuing to the next component
   - ``--run_one`` — Process one file for testing
   - ``--dry_run`` — Print planned calls without executing
   - ``--print_cli_call/--no-print_cli_call`` — In dry-run mode, print the equivalent CLI invocation (default) or the Python ``cmor_run_subtool()`` call
   - ``--start TEXT`` — Minimum year (YYYY)
   - ``--stop TEXT`` — Maximum year (YYYY)
* Example: ``fremor yaml -y cmor.yaml --dry_run``

``resolve``
-----------

* Resolves a FRE model YAML plus referenced CMOR/grids YAML files into one combined YAML document
* Useful for inspecting how anchors and merge keys from the model and grids files expand into the CMOR section
* Minimal Syntax: ``fremor resolve -y [model_yaml] -e [experiment] [options]``
* Required Options:
   - ``-y, --yamlfile TEXT`` — Model YAML file to resolve
   - ``-e, --experiment TEXT`` — Experiment name
* Optional:
   - ``-o, --output TEXT`` — Write the resolved YAML to a file instead of stdout
* Example: ``fremor resolve -y am5.yaml -e c96L65_am5f7b12r1_amip --output resolved.yaml``

``find``
--------

* Searches MIP tables for variable definitions
* Minimal Syntax: ``fremor find -r [table_config_dir] [options]``
* Required Options:
   - ``-r, --table_config_dir TEXT`` — Directory with MIP tables
* Optional:
   - ``-l, --varlist TEXT`` — Variable list file
   - ``-v, --opt_var_name TEXT`` — Specific variable to search
* Example: ``fremor find -r cmip6-cmor-tables/Tables/ -v sos``

``varlist``
-----------

* Generates variable list from netCDF files in a directory
* Scans filenames (``component.YYYYMMDD.variable.nc``) and extracts variable names; deduplicates across datetimes
* When a MIP table is provided, variables that match a MIP entry are self-mapped (key == value); variables not found in the table receive an empty-string value signalling that manual mapping is required
* Variable name matching is case-insensitive (e.g., ``LWP`` matches ``lwp`` in the MIP table)
* Minimal Syntax: ``fremor varlist -d [dir_targ] -o [output_file]``
* Required Options:
   - ``-d, --dir_targ TEXT`` — Target directory
   - ``-o, --output_variable_list TEXT`` — Output file path
* Optional:
   - ``-t, --mip_table TEXT`` — MIP table JSON file to cross-reference variables against
   - ``--strict_mode`` — If a MIP table is provided and none of the found variable names match any MIP entry, do not write the output file (return nothing instead of a file full of empty-value entries)
* Examples:
   - ``fremor varlist -d ocean_data/ -o varlist.json``
   - ``fremor varlist -d ocean_data/ -t CMIP6_Omon.json -o varlist.json``
   - ``fremor varlist -d ocean_data/ -t CMIP6_Omon.json --strict_mode -o varlist.json``

``config``
----------

* Generates a CMOR YAML configuration file by scanning a post-processing directory tree and cross-referencing against MIP tables
* Creates per-component variable list JSON files and the structured YAML that ``fremor yaml`` consumes
* Minimal Syntax: ``fremor config -p [pp_dir] -t [mip_tables_dir] -m [mip_era] -e [exp_config] -o [output_yaml] -d [output_dir] -l [varlist_dir]``
* Required Options:
   - ``-p, --pp_dir TEXT`` — Root post-processing directory
   - ``-t, --mip_tables_dir TEXT`` — Directory containing MIP table JSON files
   - ``-m, --mip_era TEXT`` — MIP era identifier (e.g. ``cmip6``, ``cmip7``)
   - ``-e, --exp_config TEXT`` — Path to experiment configuration JSON
   - ``-o, --output_yaml TEXT`` — Path for the output CMOR YAML file
   - ``-d, --output_dir TEXT`` — Root output directory for CMORized data
   - ``-l, --varlist_dir TEXT`` — Directory for per-component variable list files
* Optional:
   - ``-g, --pp_comp_glob TEXT`` — Glob pattern for selecting pp component directory names (default: ``*``)
   - ``--strict_varlist`` — When generating per-component variable lists, apply ``--strict_mode``: if none of a component's variables match any MIP entry, skip that component entirely (no varlist file, no entry in the generated YAML)
   - ``--freq TEXT`` — Temporal frequency (default: ``monthly``)
   - ``--chunk TEXT`` — Time chunk string (default: ``5yr``)
   - ``--grid TEXT`` — Grid label anchor name (default: ``g999``; the previous documentation incorrectly listed ``g99``)
   - ``--overwrite`` — Overwrite existing variable list files
   - ``--calendar TEXT`` — Calendar type (default: ``noleap``)
* Example: ``fremor config -p /path/to/pp -t /path/to/tables -m cmip7 -e exp_config.json -o cmor.yaml -d /path/to/output -l /path/to/varlists``
