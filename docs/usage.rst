.. _usage:

=====
Usage
=====

``fremor`` is the CLI entry point for rewriting climate model output with CMIP-compliant metadata,
a process known as "CMORization". This set of tools leverages the external ``cmor`` python API within
the FRE ecosystem.

.. note::

   ``fremor`` is an independent package extracted from the ``fre.cmor`` submodule of
   `fre-cli <https://github.com/NOAA-GFDL/fre-cli>`_. The ``fre cmor`` subcommand maps
   directly to ``fremor``:

   .. code-block:: text

      fre -vv -l logfile.txt cmor run [OPTIONS]   # fre-cli
      fremor -vv -l logfile.txt run [OPTIONS]      # fremor

Background
----------

``cmor`` is an acronym for "climate model output rewriter". The process of rewriting model-specific output
files for model intercomparisons (MIPs) using the ``cmor`` module is referred to as "CMORizing".

The ``fremor`` tools are designed to work with any MIP project (CMIP6, CMIP6Plus, CMIP7, etc.) by simply changing
the table configuration files and controlled vocabulary as appropriate for the target MIP.

Getting Started
---------------

``fremor`` provides several subcommands:

* ``fremor init`` — Initialize CMOR resources: generate config templates and fetch MIP tables
* ``fremor run`` — Core engine for rewriting individual directories of netCDF files according to a MIP table
* ``fremor yaml`` — Higher-level tool for processing multiple directories / MIP tables using YAML configuration
* ``fremor find`` — Helper for exploring MIP table configurations for information on a specific variable
* ``fremor varlist`` — Helper for generating variable lists from directories of netCDF files
* ``fremor config`` — Generate a CMOR YAML configuration file from a post-processing directory tree

To see all available subcommands:

.. code-block:: bash

   fremor --help

Verbosity and Logging
---------------------

``fremor`` supports multiple verbosity levels and optional log-file output. These
flags are global options on the top-level ``fremor`` command, so they must appear
before the subcommand they modify:

.. code-block:: bash

   fremor -v run ...                   # INFO level logging
   fremor -vv run ...                  # DEBUG level logging
   fremor -vvv run ...                 # DDEBUG for large data-structure dumps
   fremor -q run ...                   # ERROR level only (quiet)
   fremor -l fremor.log run ...        # Append fremor logs to file
   fremor --log-file fremor.log run ...  # Same as -l; --log_file also works

* ``-v`` / ``--verbose`` is count-based. ``-v`` enables ``INFO``, ``-vv`` enables
  ``DEBUG``, and ``-vvv`` enables the custom ``DDEBUG`` level used for large
  arrays, dictionaries, and other high-volume data-structure dumps.
* ``-q`` / ``--quiet`` forces ``ERROR`` logging and overrides any ``-v`` flags.
* ``-l`` / ``--log-file`` / ``--log_file`` appends to the named file while still
  leaving normal screen output enabled. Place this option before the subcommand;
  for example, after ``run`` the short ``-l`` flag belongs to ``fremor run``'s
  varlist argument instead of the global log-file setting.

CMOR Runtime Logfiles
~~~~~~~~~~~~~~~~~~~~~

When ``fremor run`` (or a ``fremor yaml`` call that dispatches to ``run``) enters
the CMOR rewrite path, it gives CMOR a logfile path. If
``fremor.cmor_constants.CMOR_LOG`` is set, that explicit path is used; otherwise
``fremor`` falls back to a per-file ``.log`` path derived from the temporary
``.nc`` file being rewritten.

After ``cmor.close()`` fully tears down the CMOR module, ``fremor`` re-reads that
CMOR logfile for ``INFO``-or-more-verbose runs (``-v``, ``-vv``, ``-vvv``) and
forwards each line through the standard ``fremor`` logger. It then renames the
CMOR logfile to match the produced NetCDF filename (``*.nc`` → ``*.log``), and if
the output first landed under ``CMOR_tmp/``, the ``.log`` file is moved alongside
the final CMORized output file.

Additional Resources
--------------------

* `CMIP6 Tables <https://github.com/pcmdi/cmip6-cmor-tables>`_
* `CMIP6Plus / MIP Tables <https://github.com/PCMDI/mip-cmor-tables>`_
* `CMIP7 Tables <https://github.com/WCRP-CMIP/cmip7-cmor-tables>`_
* `CMIP6 Controlled Vocabulary <https://github.com/WCRP-CMIP/CMIP6_CVs>`_
* `CMIP6Plus Controlled Vocabulary <https://github.com/WCRP-CMIP/CMIP6Plus_CVs>`_ (not shipped with the CMIP6Plus tables)
* `PCMDI CMOR User Guide <http://cmor.llnl.gov/>`_
* `fremor on GitHub <https://github.com/NOAA-GFDL/fremor>`_
* `fre-cli (upstream) <https://github.com/NOAA-GFDL/fre-cli>`_
