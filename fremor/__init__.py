"""
``fremor``: CMORization for FRE output
==========================================

This module provides routines which rewrite post-processed FRE/FMS model output in a community-driven, standardized way.
This module relies heavily on PCMDI's CMOR module and it's ``python`` API. It is the core implementation for
``fremor run`` operations- mixing and matching GFDL's and FRE's conventions to CMOR's expectations, so that
participation in model-intercomparison projects may be eased. For more usage details, see the project README.md, the
FRE documentation at https://noaa-gfdl.readthedocs.io/projects/fre-cli/en/latest/, PCMDI's CMOR module documentation at
https://cmor.llnl.gov/, and of course ``fremor``'s documentation at https://fremor.readthedocs.io/en/stable/.

.. note:: this text is set by ``fremor/__init__.py``'s docstring. Importing ``fremor`` sets the
          version attribute, and sets up a ``fre_logger``
"""

import logging

from ._version import __version__, version

fre_logger = logging.getLogger(__name__)

FORMAT = '[%(levelname)5s:%(filename)24s:%(funcName)24s] %(message)s'
logging.basicConfig( level = logging.WARNING,
                     format = FORMAT,
                     filename = None,
                     encoding = 'utf-8' )

# these need to be here for the base logger configuration, i think
from .cmor_mixer import cmor_run_subtool # pylint: disable=wrong-import-position
from .cmor_finder import cmor_find_subtool, make_simple_varlist # pylint: disable=wrong-import-position
from .cmor_yamler import cmor_yaml_subtool # pylint: disable=wrong-import-position
from .cmor_resolver import resolve_fremor_yaml # pylint: disable=wrong-import-position
from .cmor_config import cmor_config_subtool # pylint: disable=wrong-import-position
from .cmor_init import cmor_init_subtool # pylint: disable=wrong-import-position
from .cmor_stage import cmor_stage_subtool # pylint: disable=wrong-import-position
