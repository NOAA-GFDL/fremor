# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import sys
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path('..').resolve()))

import importlib.util

# Load _version.py directly to avoid triggering the full package init
# (which imports heavy optional dependencies like cmor, netCDF4, etc.)
_ver_spec = importlib.util.spec_from_file_location(
    "fremor._version",
    Path('..').resolve() / 'fremor' / '_version.py'
)
_ver_mod = importlib.util.module_from_spec(_ver_spec)  # type: ignore[arg-type]
_ver_spec.loader.exec_module(_ver_mod)  # type: ignore[union-attr]
pkg_version = _ver_mod.__version__

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'fremor'
copyright = f'{dt.datetime.now().year}, NOAA-GFDL MSD Workflow Team'
author = 'NOAA-GFDL MSD Workflow Team'
release = pkg_version   # type: ignore

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration
extensions = ['sphinx.ext.autodoc']
exclude_patterns = []

# Mock imports for dependencies not needed during doc build
# This allows Sphinx to build docs without installing heavy dependencies
autodoc_mock_imports = [
    'click',
    'cmor',
    'netCDF4',
    'numpy',
    'yaml',
    'pytest',
]

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output
html_theme = 'renku'
