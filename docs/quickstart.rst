.. _quickstart:

============================
CMOR Quickstart (``fremor``)
============================

This guide adapts the ``README`` for ``fre.cmor`` in ``NOAA-GFDL/fre-cli`` for the
standalone ``fremor`` package. The ``fremor`` CLI rewrites climate model output
with CMIP-compliant metadata (\"CMORization\") and supports both CMIP6 and CMIP7
workflows.

Comprehensive API and CLI reference material lives in :ref:`usage` and
:ref:`commands`. Use this page when you want a concise, end-to-end reminder of
what configuration is required and how to invoke each subcommand.

Documentation and References
----------------------------

* `fremor docs (latest) <https://fremor.readthedocs.io/en/latest/>`_
* `fre-cli CMOR docs <https://noaa-gfdl.readthedocs.io/projects/fre-cli/en/latest/usage.html#cmorize-postprocessed-output>`_
* `PCMDI cmor documentation <http://cmor.llnl.gov/>`_

Getting Started
---------------

Initialize CMOR resources
~~~~~~~~~~~~~~~~~~~~~~~~~

Before CMORizing data, use ``fremor init`` to set up required resources:

.. code-block:: bash

   # Generate a CMIP6 config template and fetch CMIP6 tables
   fremor init -m cmip6 -e exp_config.json -t cmip6-tables

   # Generate a CMIP7 config template and fetch CMIP7 tables (fast mode)
   fremor init -m cmip7 -e exp_config.json -t cmip7-tables --fast

   # Only generate a config template (skip table fetching)
   fremor init -m cmip6 -e exp_config.json

   # Only fetch tables (skip config template)
   fremor init -m cmip6 -t cmip6-tables

   # Fetch a specific release tag
   fremor init -m cmip6 -t cmip6-tables --tag 6.9.33

The ``init`` command:

* Generates experiment configuration JSON templates with required CMIP metadata fields
* Fetches official MIP tables from trusted GitHub repositories:
   - CMIP6: `pcmdi/cmip6-cmor-tables <https://github.com/pcmdi/cmip6-cmor-tables>`_
   - CMIP7: `WCRP-CMIP/cmip7-cmor-tables <https://github.com/WCRP-CMIP/cmip7-cmor-tables>`_
* Supports both git clone (default) and tarball download (``--fast``) methods

External configuration
~~~~~~~~~~~~~~~~~~~~~~

``fremor`` relies on external CMIP metadata:

* MIP tables (for example the `cmip6-cmor-tables <https://github.com/pcmdi/cmip6-cmor-tables>`_)
* Controlled vocabularies (for example `CMIP6_CVs <https://github.com/WCRP-CMIP/CMIP6_CVs>`_)

Required user inputs
~~~~~~~~~~~~~~~~~~~~

* **Variable list** (JSON) that maps local variable names to MIP names. A small
  example lives in the repository at
  ``fremor/tests/test_files/CMORbite_var_list.json``.
* **Experiment configuration** (JSON) supplying metadata such as ``calendar``,
  ``grid``, and the desired output directory structure. See
  ``fremor/tests/test_files/CMOR_input_example.json`` for CMIP6 or
  ``fremor/tests/test_files/CMOR_CMIP7_input_example.json`` for CMIP7.
* **Optional CMOR YAML** if you want to batch multiple ``run`` calls via
  ``fremor yaml``. These YAML files are part of the larger FRE workflow and are
  not shipped here; point ``-y/--yamlfile`` at your project-specific YAMLs.

Subcommands and Examples
------------------------

The entry point to all subcommands is ``fremor``:

.. code-block:: bash

   fremor --help

``init``
~~~~~~~~

Initialize CMOR resources by generating experiment configuration templates and/or
fetching MIP tables from trusted sources.

.. code-block:: bash

   # Generate config template and fetch tables
   fremor init -m cmip6 -e exp_config.json -t cmip6-tables

   # Use fast mode (tarball download instead of git clone)
   fremor init -m cmip7 -e exp_config.json -t cmip7-tables --fast

   # Fetch a specific release tag
   fremor init -m cmip6 -t cmip6-tables --tag 6.9.33

``run``
~~~~~~~

Rewrite NetCDF files in a directory using a specific MIP table and experiment
configuration.

.. code-block:: bash

   fremor run --run_one --grid_label gr --grid_desc FOO_BAR_PLACEHOLD --nom_res "10000 km" \
       -d /path/to/input/netcdf/dir \
       -l fremor/tests/test_files/CMORbite_var_list.json \
       -r fremor/tests/test_files/cmip6-cmor-tables/Tables/CMIP6_Omon.json \
       -p fremor/tests/test_files/CMOR_input_example.json \
       -o /tmp/cmorized_output

``yaml``
~~~~~~~~

Process multiple directories/tables using FRE-flavored YAML configuration.
This is most useful inside a full FRE workflow.

.. code-block:: bash

   fremor -v yaml --run_one --dry_run --output combined.yaml \
       --yamlfile /path/to/model.yaml \
       --experiment c96L65_am5f7b12r1_amip \
       --platform ncrc5.intel \
       --target prod-openmp

``find``
~~~~~~~~

Search MIP tables for variable definitions.

.. code-block:: bash

   fremor -v find --table_config_dir fremor/tests/test_files/cmip6-cmor-tables/Tables/ \
       --opt_var_name sos

``varlist``
~~~~~~~~~~~

Generate a variable list from a directory of NetCDF files. Optionally filter
against a MIP table.

.. code-block:: bash

   fremor varlist --dir_targ /path/to/data_dir \
       --output_variable_list simple_varlist.json \
       --mip_table fremor/tests/test_files/cmip6-cmor-tables/Tables/CMIP6_Omon.json

``config``
~~~~~~~~~~

Scan a post-processing directory tree and emit the CMOR YAML plus per-component
variable lists that ``fremor yaml`` consumes.

.. code-block:: bash

   fremor config --pp_dir /path/to/pp \
       --mip_tables_dir /path/to/cmip7-cmor-tables/tables \
       --mip_era cmip7 \
       --exp_config /path/to/CMOR_CMIP7_input_example.json \
       --output_yaml cmor_config.yaml \
       --output_dir /path/to/cmor_output \
       --varlist_dir /path/to/varlists \
       --freq monthly --chunk 5yr --grid gn \
       --calendar noleap

In ``--dry_run`` mode, ``fremor yaml`` prints the generated ``fremor run`` calls
without executing them. Pass ``--no-print_cli_call`` to print the equivalent
Python ``cmor_run_subtool(...)`` invocation instead of the CLI command.
