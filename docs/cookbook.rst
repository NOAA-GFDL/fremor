.. _cookbook:

========
Cookbook
========

This cookbook provides practical examples and procedures for using ``fremor`` to CMORize climate model output.
It demonstrates the relationship between the different subcommands and provides guidance on debugging CMORization processes.

.. contents:: Contents
   :local:
   :depth: 2

Overview
--------

The ``fremor`` process typically follows this pattern:

1. **Initialize Resources** — Use ``fremor init`` to generate config templates and fetch MIP tables
2. **Setup and Configuration** — Customize your experiment configuration, create variable lists, and prepare metadata
3. **CMORization** — Use ``fremor run`` to process individual directories or ``fremor yaml`` for bulk processing
4. **Troubleshooting** — Diagnose issues as needed

Initialize Resources
--------------------

Before beginning CMORization, initialize the required resources:

.. code-block:: bash

   # Generate CMIP6 experiment config template and fetch tables
   fremor init -m cmip6 -e CMOR_cmip6_config.json -t cmip6-tables

   # Generate CMIP7 experiment config template and fetch tables (fast mode)
   fremor init -m cmip7 -e CMOR_cmip7_config.json -t cmip7-tables --fast

The ``init`` command:

* Creates an experiment configuration JSON template with all required CMIP metadata fields
* Fetches official MIP tables from trusted GitHub repositories
* Supports git clone (default) or tarball download (``--fast``) for table retrieval
* Can fetch specific release tags using ``--tag``

After running ``init``, you'll have:

* An experiment configuration JSON file to customize with your experiment metadata
* A directory of MIP tables ready to use for CMORization

Setup and Configuration
-----------------------

Before beginning CMORization, gather the following information:

* **Experiment name** (``-e``) — The name of your experiment as defined in the model YAML
* **Platform** (``-p``) — The platform configuration (e.g., ``gfdl.ncrc6-intel23``, ``ncrc5.intel``)
* **Target** (``-t``) — The compilation target (e.g., ``prod-openmp``, ``debug``)
* **Post-processing directory** — Location of your model's post-processed output (e.g., ``/archive/user/experiment/pp/``)
* **Output directory** — Where CMORized output should be written

Identifying Parameters from FRE Output
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you have existing FRE output, you can extract the required parameters from the directory structure. The post-processing directory is typically located at::

    /archive/username/experiment/platform-target/pp/

From this path, you can identify:

* ``experiment`` = experiment (the experiment name)
* ``platform-target`` = the combined platform and target string (e.g., ``ncrc5.intel-prod-openmp``)

You will need to split the platform-target string appropriately to extract the individual ``platform`` and ``target`` values for use with ``fremor`` commands.

Creating Variable Lists
~~~~~~~~~~~~~~~~~~~~~~~

Variable lists map your modeler variable names to MIP table variable names. Generate a variable list from a directory of netCDF files:

.. code-block:: bash

   fremor varlist \
       -d /path/to/component/output \
       -o generated_varlist.json

This tool examines filenames to extract variable names. It assumes FRE-style naming conventions
(e.g., ``component.YYYYMMDD.variable.nc``). Review the generated file and edit as needed to map
local variable names to target MIP variable names.

When a modeler's variable name differs from the MIP table variable name, the variable list
maps between them. For example, if your model produces ``sea_sfc_salinity`` but the MIP table
expects ``sos``:

.. code-block:: json

   {
       "sea_sfc_salinity": "sos"
   }

The key (``sea_sfc_salinity``) is the modeler's variable name — it must match both the filename
and the variable name inside the netCDF file. The value (``sos``) is the MIP table variable name
used for metadata lookups.

To verify variables exist in MIP tables, search for variable definitions:

.. code-block:: bash

   fremor -v find \
       -r /path/to/cmip6-cmor-tables/Tables/ \
       -v variable_name

Or search for all variables in a varlist:

.. code-block:: bash

   fremor -v find \
       -r /path/to/cmip6-cmor-tables/Tables/ \
       -l /path/to/varlist.json

This displays which MIP table contains the variable and its metadata requirements.

Preparing Experiment Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The experiment configuration JSON file contains required metadata for CMORization (e.g., ``CMOR_input_example.json``).
This file should include:

* Experiment metadata (``experiment_id``, ``activity_id``, ``source_id``, etc.)
* Institution and contact information
* Grid information (``grid_label``, ``nominal_resolution``)
* Variant labels (``realization_index``, ``initialization_index``, etc.)
* Parent experiment information (if applicable)
* Calendar type

Refer to CMIP6 controlled vocabularies and your project's requirements when filling in these fields.

Running Your CMORization
------------------------

CMORizing One Table/Variable List in a Directory
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``fremor run`` command is the fundamental building block for CMORization. It processes netCDF files from a single input directory according to a specified MIP table and variable list.

For processing individual directories or debugging specific issues, use ``fremor run`` directly:

.. code-block:: bash

   fremor -vv run \
       --indir /path/to/component/output \
       --varlist /path/to/varlist.json \
       --table_config /path/to/CMIP6_Table.json \
       --exp_config /path/to/experiment_config.json \
       --outdir /path/to/cmor/output \
       --grid_label gn \
       --grid_desc "native grid description" \
       --nom_res "100 km" \
       --run_one

Required arguments:

* ``--indir``: Directory containing netCDF files to CMORize
* ``--varlist``: JSON file mapping modeler variable names to MIP table variable names
* ``--table_config``: MIP table JSON file (e.g., ``CMIP6_Omon.json``)
* ``--exp_config``: Experiment configuration JSON with metadata
* ``--outdir``: Output directory root for CMORized files

Optional but recommended:

* ``--grid_label``: Grid label (``gn`` for native, ``gr`` for regridded)
* ``--grid_desc``: Description of the grid
* ``--nom_res``: Nominal resolution (must match controlled vocabulary)
* ``--opt_var_name``: Process only files matching this variable name
* ``--run_one``: Process only one file (for testing)
* ``--start``: Start year (``YYYY`` format)
* ``--stop``: Stop year (``YYYY`` format)
* ``--calendar``: Calendar type (e.g., ``julian``, ``noleap``, ``360_day``)

Bulk CMORization Over Many Tables and Directories
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``fremor yaml`` command provides a higher-level interface for CMORizing multiple components and MIP tables.
It parses YAML configuration, then generates and executes a set of ``fremor run`` commands based on that
configuration.

This is the recommended approach for CMORizing multiple components and MIP tables in a systematic way.

**Step 1: Test with Dry Run**

Test the process without actually CMORizing files:

.. code-block:: bash

   fremor -vv yaml \
       -y /path/to/model.yaml \
       -e EXPERIMENT_NAME \
       -p PLATFORM \
       -t TARGET \
       --dry_run \
       --run_one

This prints the ``fremor run`` commands that would be executed, allowing you to verify:

* Input directories are correct
* Output paths are as expected
* Variable lists are found
* MIP tables are accessible

**Step 2: Process One File for Testing**

Process only one file to verify the process:

.. code-block:: bash

   fremor -vv yaml \
       -y /path/to/model.yaml \
       -e EXPERIMENT_NAME \
       -p PLATFORM \
       -t TARGET \
       --run_one

**Step 3: Full CMORization**

Once validated, remove ``--run_one`` for full processing:

.. code-block:: bash

   fremor -v yaml \
       -y /path/to/model.yaml \
       -e EXPERIMENT_NAME \
       -p PLATFORM \
       -t TARGET

Auto-generating CMOR YAML from Post-processing Output
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you have a post-processing directory tree and MIP tables, ``fremor config`` can auto-generate the CMOR
YAML configuration for you:

.. code-block:: bash

   fremor config \
       -p /path/to/pp \
       -t /path/to/mip-tables \
       -m cmip7 \
       -e exp_config.json \
       -o cmor.yaml \
       -d /path/to/output \
       -l /path/to/varlists

This scans the ``pp_dir`` for post-processing components, cross-references found variables against MIP
tables, writes per-component variable list files, and emits a structured YAML that ``fremor yaml`` can
later consume.

Common Issues and Solutions
---------------------------

``fremor yaml`` Fails at YAML Combination Step
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. note::

   This section and general YAML behavior is under-review and being refactored

``fremor yaml`` fails with key errors or anchor errors during the YAML combination step.

.. note::

   ``fremor yaml`` now uses ``fremor``\'s own lightweight YAML loader. It reads the
   model yaml, finds the referenced CMOR yaml and optional grids yaml, and resolves
   only the YAML needed for CMORization.

To debug this issue:

* Verify all referenced YAML files exist and are readable
* Verify anchors referenced in the CMOR YAML are defined in the model YAML
* Verify that the ``cmor:`` section exists in the experiment definition
* Verify the CMOR YAML path is relative to the model YAML location

No Files Found in Input Directory
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``fremor run`` reports no files matching the variable list.

Solutions:

* Verify ``--indir`` points to the correct directory
* Check that files follow expected naming conventions
* Use ``fremor varlist`` to generate a list from actual filenames
* Use ``--opt_var_name`` to target a specific variable for testing

Grid Metadata Issues
~~~~~~~~~~~~~~~~~~~~

Errors about missing or invalid grid labels or nominal resolution.

Solutions:

* Ensure ``--grid_label`` matches controlled vocabulary (typically ``gn`` or ``gr``)
* Verify ``--nom_res`` is in the controlled vocabulary for your MIP
* Check that grid descriptions are provided if overriding experiment config
* Review the experiment configuration JSON for grid-related fields

Calendar or Date Range Issues
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Files are skipped or errors related to calendar types.

Solutions:

* Specify ``--calendar`` if the automatic detection fails
* Use ``--start`` and ``--stop`` to limit the date range processed
* Verify that datetime strings in filenames match expected ISO8601 format
* Check that the calendar type in your data matches the MIP requirements

Example: Ocean Monthly Data CMORization
---------------------------------------

This example demonstrates CMORizing ocean monthly output for multiple components.

Prepare the model YAML (excerpt from ``experiments`` section):

.. code-block:: yaml

   experiments:
     - name: "my_ocean_experiment"
       pp:
         - "pp_yamls/settings.yaml"
         - "pp_yamls/ocean_monthly.yaml"
       cmor:
         - "cmor_yamls/ocean_cmor.yaml"
       grid_yaml:
         - "grid_yamls/ocean_grids.yaml"

Prepare the CMOR YAML (``cmor_yamls/ocean_cmor.yaml``):

.. code-block:: yaml

   cmor:
     start: "1950"
     stop: "2000"
     mip_era: "CMIP6"
     exp_json: "/path/to/experiment_config.json"

     directories:
       pp_dir: "/path/to/pp"
       table_dir: "/path/to/cmip6-cmor-tables/Tables"
       outdir: "/path/to/cmor/output"

     table_targets:
       - table_name: "Omon"
         freq: "monthly"
         gridding:
           grid_label: "gn"
           grid_desc: "native tripolar ocean grid"
           nom_res: "100 km"

         target_components:
           - component_name: "ocean_monthly"
             variable_list: "/path/to/ocean_varlist.json"
             data_series_type: "ts"
             chunk: "P1Y"

Test with dry run:

.. code-block:: bash

   fremor -vv yaml \
       -y model.yaml \
       -e my_ocean_experiment \
       -p ncrc5.intel \
       -t prod-openmp \
       --dry_run

Process one file:

.. code-block:: bash

   fremor -vv yaml \
       -y model.yaml \
       -e my_ocean_experiment \
       -p ncrc5.intel \
       -t prod-openmp \
       --run_one

Full processing:

.. code-block:: bash

   fremor yaml \
       -y model.yaml \
       -e my_ocean_experiment \
       -p ncrc5.intel \
       -t prod-openmp

Tips
----

* Use ``--dry_run`` with ``fremor yaml`` to preview the equivalent ``fremor run`` calls before execution
* Use ``--no-print_cli_call`` with ``--dry_run`` to see the Python ``cmor_run_subtool(...)`` call instead of the CLI invocation — useful for debugging
* Use ``--run_one`` with ``fremor run`` for testing to only process a single file and catch issues early
* Use ``--run_one`` with ``fremor yaml`` to process a single file per ``fremor run`` call for quicker debugging
* Use ``fremor config`` to auto-generate a CMOR YAML configuration from a post-processing directory tree — it scans components, cross-references against MIP tables, and writes both variable lists and the YAML that ``fremor yaml`` expects
* Increase verbosity when debugging — use ``-v`` to see ``INFO`` logging, and ``-vv`` (or ``-v -v``) for ``DEBUG`` logging
* Version control your YAML files — track changes to your CMORization configuration and commit them to git!
* Check controlled vocabulary — verify grid labels and nominal resolutions are CV-compliant
* Review experiment config — ensure all required metadata fields are populated
