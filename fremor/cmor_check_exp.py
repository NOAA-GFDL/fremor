"""
``fremor check``: Experiment-Config and Grid-Label Checks
=========================================================

Checks backing ``fremor check --check-exp-config``, which looks at the experiment configuration
JSON (the cmor yaml's ``exp_json``, CMOR's "input metadata" file) against the controlled
vocabulary CMOR will load, and the CMIP7 grid-label check that ``--check-dims`` runs against
each variable's input file.

The experiment-config check reports, as a list of ``{'level', 'attribute', 'message'}``
findings (``level`` is ``error`` for what CMOR or ESGF publication will reject, ``warning``
for what is likely wrong or rejected only by some downstream checkers):

- whether the file parses, and its ``mip_era`` matches the cmor yaml's,
- whether the CV and the auxiliary tables it names (``_controlled_vocabulary_file``,
  ``_AXIS_ENTRY_FILE``, ``_FORMULA_VAR_FILE``) exist where CMOR will look for them,
- CV-required attributes that are absent or blank,
- values not in their CV collection (``activity_id``, ``experiment_id``, ``source_id``,
  ``grid_label``, ``nominal_resolution``, ...),
- cross-consistency with the CV's ``experiment_id`` and ``source_id`` entries (activity,
  parent experiment, sub-experiment, institution),
- the ``license`` text against the CV's license pattern/template,
- the ``calendar``, and
- whether ``further_info_url`` can actually be written (CMOR only writes it from a
  ``_further_info_url_tmpl`` in the config).

The grid-label check compares a representative input file's 1-D latitude/longitude against
the grid label CMOR will write, as registered in the Essential Model Documentation (EMD,
https://wcrp-cmip.github.io/Essential-Model-Documentation/docs/grid_viewer/horizontal/): the
spacing, the first cell centres and the cell count. The EMD entry is read from the local copy
``fremor init --mip_era cmip7`` saves beside the tables, else downloaded; failing both, only the
spacing parsed from the CV's description of the label is checked.

Functions
---------
- ``load_cv(mip_tables_dir, exp_config_data, mip_era)``
- ``check_exp_config(json_exp_config, mip_tables_dir, mip_era)``
- ``find_emd_grid_cells_dir(mip_tables_dir)``
- ``load_emd_grid_cell(grid_label, grid_cells_dir, download)``
- ``grid_label_spec(grid_label, cv, grid_cells_dir, download)``
- ``grid_finding(nc_path, local_var, grid_label, spec)``
"""

import json
import logging
import re
import urllib.request
from pathlib import Path
from typing import Optional, Union

import numpy as np
from netCDF4 import Dataset

from .cmor_constants import ( CF_CALENDARS, EMD_GRID_CELL_DIRNAME, EMD_HORIZONTAL_GRID_CELL_URL,
                              GRID_SPEC_TOLERANCE_DEG, MIP_ERA_RESOURCES )
from .cmor_validate import find_unset_required_attributes

fre_logger = logging.getLogger(__name__)

# exp-config attributes checked for membership in the CV collection of the same name
CV_MEMBERSHIP_ATTRIBUTES = [
    'mip_era', 'activity_id', 'experiment_id', 'sub_experiment_id', 'institution_id',
    'source_id', 'source_type', 'grid_label', 'nominal_resolution', 'product', 'region',
    'license_id',
]
# of those, attributes holding several space-separated CV terms
MULTI_TERM_ATTRIBUTES = ['activity_id', 'source_type']

# the auxiliary tables CMOR resolves relative to the directory of the MIP table it loads
AUX_TABLE_KEYS = {
    '_controlled_vocabulary_file': 'cv',
    '_AXIS_ENTRY_FILE': 'coordinate',
    '_FORMULA_VAR_FILE': 'formula_terms',
}

_REGULAR_LAT_LON_DESCRIPTION = re.compile(
    r'regular (?:latitude longitude|lat lon) grid type and ([\d.]+) x ([\d.]+) degree')


def _posix_bre_to_python(pattern: str) -> str:
    """Translate the POSIX basic regular expressions CMOR's CVs use (``\\(``, ``\\{1,\\}``,
    ``[[:digit:]]``, literal ``(``/``)``) into Python ``re`` syntax."""
    out = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == '\\' and i + 1 < len(pattern):
            nxt = pattern[i + 1]
            out.append(nxt if nxt in '(){}|' else char + nxt)
            i += 2
            continue
        if pattern.startswith('[[:digit:]]', i):
            out.append(r'\d')
            i += len('[[:digit:]]')
            continue
        out.append('\\' + char if char in '(){}|+?' else char)
        i += 1
    return ''.join(out)


def _finding(level: str, attribute: str, message: str) -> dict:
    return {'level': level, 'attribute': attribute, 'message': message}


def load_cv(mip_tables_dir: str, exp_config_data: dict, mip_era: str) -> tuple:
    """
    Load the CV CMOR would load: the experiment config's ``_controlled_vocabulary_file``
    resolved against the MIP tables directory, else the era's default.

    :return: ``(cv, cv_path)``; cv is the ``CV`` mapping, or None if the file is missing or unreadable.
    :rtype: tuple
    """
    default_name = MIP_ERA_RESOURCES.get(mip_era.upper(), {}).get('cv', 'CMIP6_CV.json')
    cv_name = exp_config_data.get('_controlled_vocabulary_file') or default_name
    cv_path = Path(mip_tables_dir) / cv_name
    try:
        with open(cv_path, 'r', encoding='utf-8') as cv_file:
            return json.load(cv_file)['CV'], cv_path
    except (OSError, ValueError, KeyError, TypeError) as exc:
        fre_logger.debug('could not load CV %s: %s', cv_path, exc)
        return None, cv_path


def _cv_terms(collection) -> Optional[list]:
    """Allowed terms of a CV collection, or None if it is not a plain list of terms."""
    if isinstance(collection, dict):
        return list(collection)
    if isinstance(collection, str):
        return [collection]
    if isinstance(collection, list) and all(isinstance(term, str) for term in collection):
        # a list of regexes (e.g. the index patterns) is not a list of terms
        if any(term.startswith('^') or '\\' in term or '.*' in term for term in collection):
            return None
        return collection
    return None


def _check_membership(exp_config_data: dict, cv: dict) -> list:
    findings = []
    for attribute in CV_MEMBERSHIP_ATTRIBUTES:
        value = exp_config_data.get(attribute)
        if value is None or not str(value).strip():
            continue
        cv_key = 'license' if attribute == 'license_id' else attribute
        collection = cv.get(cv_key)
        if attribute == 'license_id':
            collection = collection.get('license_id') if isinstance(collection, dict) else None
        terms = _cv_terms(collection)
        if terms is None:
            continue
        values = str(value).split() if attribute in MULTI_TERM_ATTRIBUTES else [str(value)]
        bad = [term for term in values if term not in terms]
        if bad:
            findings.append(_finding('error', attribute,
                                     f'{", ".join(repr(term) for term in bad)} not in the CV\'s '
                                     f'{cv_key} collection'))
    return findings


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _check_consistency(exp_config_data: dict, cv: dict) -> list:
    """Cross-check against the CV's entries for the chosen experiment_id and source_id."""
    findings = []
    experiment_id = exp_config_data.get('experiment_id')
    experiment = (cv.get('experiment_id') or {}).get(experiment_id)
    if isinstance(experiment, dict):
        allowed_activities = _as_list(experiment.get('activity_id'))
        activities = str(exp_config_data.get('activity_id') or '').split()
        if allowed_activities and activities and not set(activities) & set(allowed_activities):
            findings.append(_finding(
                'error', 'activity_id',
                f'{" ".join(activities)!r} is not an activity of experiment {experiment_id} '
                f'(CV allows {allowed_activities})'))

        allowed_parents = _as_list(experiment.get('parent_experiment_id'))
        parent = exp_config_data.get('parent_experiment_id')
        no_parent = parent in (None, '', 'no parent')
        if allowed_parents and parent not in allowed_parents:
            findings.append(_finding(
                'error', 'parent_experiment_id',
                f'{parent!r} is not a parent of experiment {experiment_id} '
                f'(CV allows {allowed_parents})'))
        elif not allowed_parents and not no_parent:
            findings.append(_finding(
                'error', 'parent_experiment_id',
                f'experiment {experiment_id} has no parent in the CV, but the config sets {parent!r}'))

        if (allowed_parents in ([], ['no parent'])) and no_parent:
            set_parent_fields = [
                key for key in ('parent_variant_label', 'parent_source_id', 'parent_activity_id',
                                'parent_time_units', 'parent_mip_era')
                if str(exp_config_data.get(key, 'no parent')).strip() not in ('', 'no parent')]
            if set_parent_fields:
                findings.append(_finding(
                    'warning', 'parent_experiment_id',
                    f'experiment {experiment_id} has no parent, but {", ".join(set_parent_fields)} '
                    'describe one'))

        allowed_subs = _as_list(experiment.get('sub_experiment_id'))
        sub = exp_config_data.get('sub_experiment_id')
        if allowed_subs and sub is not None and sub not in allowed_subs:
            findings.append(_finding(
                'error', 'sub_experiment_id',
                f'{sub!r} is not a sub-experiment of {experiment_id} (CV allows {allowed_subs})'))

    source_id = exp_config_data.get('source_id')
    source = (cv.get('source_id') or {}).get(source_id)
    if isinstance(source, dict):
        institutions = _as_list(source.get('institution_id'))
        institution = exp_config_data.get('institution_id')
        if institutions and institution and institution not in institutions:
            findings.append(_finding(
                'error', 'institution_id',
                f'{institution!r} is not an institution of source {source_id} (CV allows {institutions})'))
        participation = _as_list(source.get('activity_participation'))
        activities = str(exp_config_data.get('activity_id') or '').split()
        if participation and activities and not set(activities) <= set(participation):
            findings.append(_finding(
                'warning', 'activity_id',
                f'source {source_id} is not registered for activity '
                f'{" ".join(sorted(set(activities) - set(participation)))} (CV lists {participation})'))
    return findings


def _check_license(exp_config_data: dict, cv: dict) -> list:
    license_text = exp_config_data.get('license')
    license_cv = cv.get('license')
    if not license_text or license_cv is None:
        return []

    if isinstance(license_cv, list):  # CMIP6 / CMIP6Plus: regex patterns
        patterns = [_posix_bre_to_python(pattern) for pattern in license_cv]
        if not any(re.match(pattern, license_text) for pattern in patterns):
            return [_finding('error', 'license',
                             'license text does not match the CV\'s license pattern:\n'
                             f'  {license_cv[0]}')]
        return []

    if isinstance(license_cv, dict) and 'license_template' in license_cv:  # CMIP7: a template
        license_id = exp_config_data.get('license_id')
        license_info = (license_cv.get('license_id') or {}).get(license_id)
        if not isinstance(license_info, dict):
            return []  # an unknown license_id is already reported by the membership check
        expected = license_cv['license_template']
        for key, value in (('license_id', license_id),
                           ('institution_id', exp_config_data.get('institution_id', '')),
                           ('license_type', license_info.get('license_type', '')),
                           ('license_url', license_info.get('license_url', ''))):
            expected = expected.replace(f'<{key}>', str(value))
        if license_text.strip() != expected.strip():
            return [_finding('warning', 'license',
                             'license text differs from the CV\'s template for '
                             f'{license_id}; expected:\n  {expected}')]
    return []


def _check_calendar(exp_config_data: dict, mip_era: str) -> list:
    calendar = exp_config_data.get('calendar')
    if calendar is None or not str(calendar).strip():
        return [_finding('error', 'calendar', 'calendar is not set; fremor run needs it to check '
                                              'the input data\'s calendar')]
    if str(calendar).lower() not in CF_CALENDARS:
        return [_finding('error', 'calendar', f'{calendar!r} is not a CF calendar ({", ".join(CF_CALENDARS)})')]
    if str(calendar).lower() == 'julian' and mip_era.upper() in ('CMIP6PLUS', 'CMIP7'):
        return [_finding('warning', 'calendar',
                         "'julian' is valid CF, but the esgf-qa CMIP6Plus/CMIP7 checks only allow "
                         'standard/gregorian/proleptic_gregorian/noleap/365_day/all_leap/366_day/360_day')]
    return []


def _check_further_info_url(exp_config_data: dict, cv: dict) -> list:
    if 'further_info_url' not in (cv.get('required_global_attributes') or []):
        return []
    if str(exp_config_data.get('_further_info_url_tmpl', '')).strip():
        return []
    return [_finding('error', 'further_info_url',
                     'the CV requires further_info_url, but CMOR only writes it from a '
                     '_further_info_url_tmpl in the experiment config, e.g. "https://furtherinfo.es-doc.org/'
                     '<mip_era><institution_id><source_id><experiment_id><sub_experiment_id><variant_label>"')]


def _check_aux_tables(exp_config_data: dict, mip_tables_dir: str) -> list:
    findings = []
    for key in AUX_TABLE_KEYS:
        name = exp_config_data.get(key)
        if name and not (Path(mip_tables_dir) / name).is_file():
            findings.append(_finding('error', key,
                                     f'{name} not found relative to the MIP tables directory '
                                     f'{mip_tables_dir}, where CMOR will look for it'))
    return findings


def check_exp_config( json_exp_config: Optional[str],
                      mip_tables_dir: str,
                      mip_era: str ) -> dict:
    """
    Check the experiment configuration JSON against the CV CMOR will load, see the module docstring.

    :param json_exp_config: Path to the experiment configuration JSON (the cmor yaml's ``exp_json``).
    :type json_exp_config: str or None
    :param mip_tables_dir: The MIP tables directory, which CMOR resolves the CV against.
    :type mip_tables_dir: str
    :param mip_era: The cmor yaml's mip_era.
    :type mip_era: str
    :return: ``{'file', 'cv', 'status', 'findings'}``; status is 'error', 'warning' or 'ok'.
    :rtype: dict
    """
    report = {'file': json_exp_config, 'cv': None, 'status': 'ok', 'findings': []}
    findings = report['findings']

    if not json_exp_config:
        findings.append(_finding('error', 'exp_json', 'the cmor yaml has no exp_json set'))
    elif not Path(json_exp_config).is_file():
        findings.append(_finding('error', 'exp_json', f'{json_exp_config} does not exist'))
    else:
        try:
            with open(json_exp_config, 'r', encoding='utf-8') as handle:
                exp_config_data = json.load(handle)
        except ValueError as exc:
            exp_config_data = None
            findings.append(_finding('error', 'exp_json', f'{json_exp_config} is not valid JSON: {exc}'))

        if isinstance(exp_config_data, dict):
            _check_exp_config_data(exp_config_data, mip_tables_dir, mip_era, report)

    levels = {finding['level'] for finding in findings}
    report['status'] = 'error' if 'error' in levels else 'warning' if 'warning' in levels else 'ok'
    return report


def _check_exp_config_data(exp_config_data: dict, mip_tables_dir: str, mip_era: str,
                           report: dict) -> None:
    findings = report['findings']
    config_era = str(exp_config_data.get('mip_era', ''))
    if config_era.upper() != mip_era.upper():
        findings.append(_finding('error', 'mip_era',
                                 f'{config_era!r} does not match the cmor yaml\'s mip_era {mip_era!r}'))

    findings.extend(_check_aux_tables(exp_config_data, mip_tables_dir))
    findings.extend(_check_calendar(exp_config_data, mip_era))

    cv, cv_path = load_cv(mip_tables_dir, exp_config_data, mip_era)
    report['cv'] = str(cv_path)
    if cv is None:
        if any(finding['attribute'] == '_controlled_vocabulary_file' for finding in findings):
            return  # already reported missing by _check_aux_tables
        findings.append(_finding('warning', '_controlled_vocabulary_file',
                                 f'could not read the CV at {cv_path}, skipping the CV checks'))
        return

    missing, blank = find_unset_required_attributes(exp_config_data, cv.get('required_global_attributes') or [])
    for attribute in missing:
        findings.append(_finding('error', attribute, 'required by the CV, but absent'))
    for attribute in blank:
        findings.append(_finding('error', attribute,
                                 'required by the CV, but blank (CMOR discards empty values)'))

    findings.extend(_check_membership(exp_config_data, cv))
    findings.extend(_check_consistency(exp_config_data, cv))
    findings.extend(_check_license(exp_config_data, cv))
    findings.extend(_check_further_info_url(exp_config_data, cv))


# ---------------------------------------------------------------------------
# CMIP7 grid label vs. the input grid
# ---------------------------------------------------------------------------
# EMD grid types whose layout fremor can check from 1-D lat/lon: regular lat-lon grids fully,
# regular gaussian grids on everything but the (uneven) latitude spacing
CHECKABLE_EMD_GRID_TYPES = ('regular-latitude-longitude', 'regular-gaussian')

_EMD_CACHE: dict = {}


def find_emd_grid_cells_dir(mip_tables_dir: Optional[str]) -> Optional[Path]:
    """
    Locate the EMD horizontal grid cells ``fremor init`` saves beside the MIP tables: the
    ``emd_horizontal_grid_cell`` directory in the tables directory or up to two levels above it
    (``fremor init`` writes it at the top of --tables_dir, above the repo's ``tables/``).

    :return: The directory, or None if there is no local copy.
    :rtype: Path or None
    """
    if not mip_tables_dir:
        return None
    tables_path = Path(mip_tables_dir).resolve()
    for directory in (tables_path, *list(tables_path.parents)[:2]):
        candidate = directory / EMD_GRID_CELL_DIRNAME
        if candidate.is_dir():
            return candidate
    return None


def load_emd_grid_cell(grid_label: str, grid_cells_dir: Optional[Path] = None,
                       download: bool = True) -> Optional[dict]:
    """
    Load a grid label's Essential Model Documentation (EMD) horizontal grid cell entry: from the
    local copy ``fremor init`` saves if there is one, else downloaded (once per process).

    :return: The EMD entry, or None if it is neither available locally nor downloadable.
    :rtype: dict or None
    """
    if grid_cells_dir is not None:
        local = Path(grid_cells_dir) / f'{grid_label}.json'
        if local.is_file():
            try:
                return json.loads(local.read_text(encoding='utf-8'))
            except ValueError as exc:
                fre_logger.warning('could not parse %s: %s', local, exc)
    if not download:
        return None
    if grid_label not in _EMD_CACHE:
        url = f'{EMD_HORIZONTAL_GRID_CELL_URL}/{grid_label}.json'
        try:
            with urllib.request.urlopen(url, timeout=10) as response:  # nosec - fixed https host
                _EMD_CACHE[grid_label] = json.loads(response.read().decode('utf-8'))
        except (OSError, ValueError) as exc:
            fre_logger.warning('could not download the EMD grid definition %s (%s); run '
                               '"fremor init --mip_era cmip7 --tables_dir ..." for a local copy',
                               url, exc)
            _EMD_CACHE[grid_label] = None
    return _EMD_CACHE[grid_label]


def _number(value) -> Optional[float]:
    return None if value in (None, '') else float(value)


def _spec_from_emd(entry: dict) -> dict:
    grid_type = entry.get('grid_type', '')
    spec = {'grid_type': grid_type, 'source': 'emd', 'description': entry.get('ui_label', '')}
    if grid_type not in CHECKABLE_EMD_GRID_TYPES or entry.get('units') != 'degree':
        spec['checkable'] = False
        return spec
    spec.update(checkable=True,
                dlon=_number(entry.get('x_resolution')),
                first_lon=_number(entry.get('westernmost_longitude')),
                first_lat=_number(entry.get('southernmost_latitude')),
                n_cells=int(entry['n_cells']) if entry.get('n_cells') not in (None, '') else None,
                region=entry.get('region') or [])
    if grid_type == 'regular-latitude-longitude':
        spec['dlat'] = _number(entry.get('y_resolution'))
    return {key: value for key, value in spec.items() if value is not None}


def grid_label_spec(grid_label: Optional[str], cv: Optional[dict],
                    grid_cells_dir: Optional[Path] = None, download: bool = True) -> Optional[dict]:
    """
    The checkable layout of a CMIP7 grid label, from its Essential Model Documentation (EMD)
    horizontal grid cell entry (see ``load_emd_grid_cell``): the spacing, the first cell centres
    (EMD's ``westernmost_longitude``/``southernmost_latitude``) and the cell count. If the EMD
    entry is unavailable, only the spacing parsed from the CV's description of a regular
    latitude-longitude label.

    :return: a spec dict with ``grid_type``, ``checkable``, ``source`` ('emd' or 'cv'), and for a
             checkable label some of ``dlon``, ``dlat``, ``first_lon``, ``first_lat``, ``n_cells``;
             None for a label in neither the EMD nor the CV.
    :rtype: dict or None
    """
    if not grid_label:
        return None
    entry = load_emd_grid_cell(grid_label, grid_cells_dir, download)
    if entry is not None:
        return _spec_from_emd(entry)

    description = ((cv or {}).get('grid_label') or {}).get(grid_label)
    if description is None:
        return None
    match = _REGULAR_LAT_LON_DESCRIPTION.search(description)
    if match:
        return {'grid_type': 'regular-latitude-longitude', 'checkable': True, 'source': 'cv',
                'description': description, 'dlon': float(match[1]), 'dlat': float(match[2])}
    return {'grid_type': 'unknown', 'checkable': False, 'source': 'cv', 'description': description}


def _coordinate_kind(variable) -> Optional[str]:
    """'lon', 'lat', or None for a 1-D coordinate variable, from its CF metadata."""
    units = str(getattr(variable, 'units', '')).lower().replace(' ', '')
    standard_name = str(getattr(variable, 'standard_name', '')).lower()
    axis = str(getattr(variable, 'axis', '')).upper()
    if standard_name == 'longitude' or units in ('degrees_east', 'degree_east', 'degrees_e', 'degree_e') or \
            (axis == 'X' and units.startswith('degree')):
        return 'lon'
    if standard_name == 'latitude' or units in ('degrees_north', 'degree_north', 'degrees_n', 'degree_n') or \
            (axis == 'Y' and units.startswith('degree')):
        return 'lat'
    return None


def _input_lat_lon(nc_path: str, local_var: str) -> Union[tuple, str]:
    """The 1-D longitude and latitude coordinate values of ``local_var``, or a reason string."""
    try:
        with Dataset(nc_path, 'r') as dataset:
            if local_var not in dataset.variables:
                return f'{local_var} not found in {nc_path}'
            coords = {}
            for dim in dataset.variables[local_var].dimensions:
                coord = dataset.variables.get(dim)
                if coord is None or coord.ndim != 1:
                    continue
                kind = _coordinate_kind(coord)
                if kind is not None:
                    coords[kind] = np.asarray(coord[:], dtype=float)
    except Exception as exc:  # pylint: disable=broad-except
        return f'could not read {nc_path} ({exc})'
    if 'lon' not in coords or 'lat' not in coords:
        return (f'{local_var} has no 1-D latitude/longitude coordinates (e.g. a native ocean '
                'grid), so the grid label cannot be checked')
    return coords['lon'], coords['lat']


def _spacing(values: np.ndarray) -> Optional[float]:
    """The spacing of evenly spaced values, or None if they are not evenly spaced."""
    if values.size < 2:
        return None
    diffs = np.abs(np.diff(values))
    spacing = float(np.median(diffs))
    if np.max(np.abs(diffs - spacing)) > GRID_SPEC_TOLERANCE_DEG:
        return None
    return spacing


def grid_finding(nc_path: str, local_var: str, grid_label: str, spec: Optional[dict]) -> dict:
    """
    Compare a representative input file's latitude/longitude against a grid label's spec
    (see ``grid_label_spec``). Longitudes are compared in file order (CMOR keeps it); latitudes
    south-to-north (CMOR writes them increasing).

    :return: ``{'status', 'grid_label', ...}``; status is 'ok', 'mismatch', 'unknown'
             (unreadable file, no 1-D lat/lon, or a label unknown to the EMD and the CV), or
             'not_checked' (a grid type with no checkable 1-D layout, e.g. tripolar).
    :rtype: dict
    """
    finding = {'grid_label': grid_label, 'file': nc_path}
    if spec is None:
        return dict(finding, status='unknown',
                    reason=f'grid label {grid_label!r} is in neither the EMD nor the CV')
    if not spec['checkable']:
        return dict(finding, status='not_checked',
                    reason=f'{grid_label} is a {spec["grid_type"]} grid with no checkable 1-D layout')

    lat_lon = _input_lat_lon(nc_path, local_var)
    if isinstance(lat_lon, str):
        return dict(finding, status='unknown', reason=lat_lon)
    lon, lat = lat_lon

    tol = GRID_SPEC_TOLERANCE_DEG
    actual = {'dlon': _spacing(lon), 'dlat': _spacing(lat),
              'first_lon': float(lon[0] % 360.0), 'first_lat': float(np.min(lat)),
              'n_cells': int(lon.size * lat.size), 'nlon': int(lon.size), 'nlat': int(lat.size)}
    expected = {key: spec[key] for key in ('dlon', 'dlat', 'first_lon', 'first_lat', 'n_cells') if key in spec}
    finding.update(status='ok', grid_type=spec['grid_type'], spec_source=spec['source'],
                   expected=expected, input=actual)

    problems = []
    for key, name in (('dlon', 'longitude'), ('dlat', 'latitude')):
        if key in spec and (actual[key] is None or abs(actual[key] - spec[key]) > tol):
            shown = 'is uneven' if actual[key] is None else f'{actual[key]:g}'
            problems.append(f'{name} spacing {shown}, expected {spec[key]:g}')
    if 'first_lon' in spec and abs(actual['first_lon'] - spec['first_lon'] % 360.0) > tol:
        problems.append(f'first longitude {actual["first_lon"]:g}, expected {spec["first_lon"]:g}')
    if 'first_lat' in spec and abs(actual['first_lat'] - spec['first_lat']) > tol:
        problems.append(f'southernmost latitude {actual["first_lat"]:g}, expected {spec["first_lat"]:g}')
    if 'n_cells' in spec and actual['n_cells'] != spec['n_cells']:
        problems.append(f'{actual["nlon"]} x {actual["nlat"]} = {actual["n_cells"]} cells, '
                        f'expected {spec["n_cells"]}')

    if problems:
        finding.update(status='mismatch', problems=problems)
    return finding
