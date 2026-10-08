#!/usr/bin/env python3
"""
fremor_make_cases.py -- generate per-case fremor inputs for many experiments /
ensemble members from one working setup, plus a script submitting them all.

Start from ONE case that works (an experiment config json and a CMOR yaml as
written by ``fremor config``) and a CSV listing the cases, one row per case::

    case_name,pp_dir,experiment_id,realization_index
    esm4_hist_r1,/archive/me/esm4_hist_ens01/pp,historical,1
    esm4_hist_r2,/archive/me/esm4_hist_ens02/pp,historical,2

Columns:

- ``case_name`` (required): tells the cases apart -- names the case's directory,
  work dir, archive dir and slurm jobs (``CASE_NAME`` in fremor_submit_tables.sh).
  Letters, digits, ``.``, ``_`` and ``-`` only.
- ``pp_dir``, ``outdir``: the yaml's ``directories`` entries. Missing or empty
  -> ``--pp-dir`` / ``--outdir``; with no ``--outdir``, the template yaml's outdir
  plus ``/<case_name>``.
- ``archive_dir``, ``start``, ``stop``: passed to the submitter as ARCHIVE_DIR,
  START and STOP. Missing or empty -> ``--archive-dir`` / the submitter's own value.
- any other column: a key of the experiment config json to set, e.g.
  ``experiment_id``, ``realization_index``, ``branch_time_in_parent``. The value
  takes the type of the template's value (int / float / str). An empty cell keeps
  the template's value.
- helper columns: a column that is not a key of the template json but is used as
  ``{column}`` in some value or pattern (e.g. ``case`` in the ``--pp-dir`` example
  below) only fills patterns.
  Any other column not in the template json is an error (catches typos), unless
  ``--allow-new-keys`` adds it to the json.

Every value (and every ``--pp-dir``/``--outdir``/``--archive-dir`` pattern) may
refer to the row's columns as ``{column}``, with Python format specs, so regular
layouts need no per-row paths::

    --pp-dir '/archive/me/{case}_ens{realization_index:0>2}/pp'

Writes, under ``--out-dir``::

    <case_name>/exp_config.json   template json with the row's keys set
    <case_name>/fremor.yaml       template yaml with pp_dir / outdir / exp_json set
    submit_all.sh                 runs fremor_submit_tables.sh (MODE=yaml) per case

``submit_all.sh`` gives each case a fixed work dir, ``<jobs-root>/<case_name>``, so
``./submit_all.sh --continue`` resumes every case, and shares one job queue file
so the submitter's MAX_CONCURRENT limits the jobs of all cases together. Its
arguments go to every submission (e.g. table names); ``CASES="a b"`` in the
environment restricts it to those cases, and ``DRY_RUN=1`` works as usual.

Usage::

    python fremor_make_cases.py cases.csv --exp-template CMOR_input.json \\
        --yaml-template cmor.yaml --out-dir ~/fremor_cases/esm4
    ~/fremor_cases/esm4/submit_all.sh
"""

import argparse
import copy
import csv
import json
import re
import shlex
import string
import sys
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
CASE_NAME_RE = re.compile(r'^[A-Za-z0-9._-]+$')
# CSV columns that are not experiment config keys
DIR_COLUMNS = ('pp_dir', 'outdir')
SUBMIT_COLUMNS = {'archive_dir': 'ARCHIVE_DIR', 'start': 'START', 'stop': 'STOP'}
RESERVED = {'case_name', *DIR_COLUMNS, *SUBMIT_COLUMNS}


def fill(pattern, row, what):
    """ format ``pattern`` with the row's columns, naming the case in any error """
    try:
        return pattern.format_map(row)
    except (KeyError, IndexError, ValueError) as exc:
        sys.exit(f'case {row.get("case_name")}: cannot fill {what} {pattern!r}: {exc!r}')


def dump_yaml(doc):
    """
    ``doc`` as block-style yaml text, keys in their original order. PyYAML < 5.1 (e.g. a
    system python3.6) has no ``sort_keys`` and always sorts, so it gets a dumper whose
    mappings are written from item lists, which PyYAML leaves in the order given
    """
    try:
        return yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)
    except TypeError:
        class OrderedDumper(yaml.SafeDumper): # pylint: disable=too-many-ancestors
            """ SafeDumper keeping dict insertion order """
        OrderedDumper.add_representer(
            dict, lambda dumper, data: dumper.represent_mapping(
                'tag:yaml.org,2002:map', list(data.items())))
        return yaml.dump(doc, Dumper=OrderedDumper, default_flow_style=False)


def fields(pattern):
    """ the column names a pattern refers to, e.g. {'case'} for '/pp/{case}_{x:0>2}' """
    names = set()
    for _, field, _, _ in string.Formatter().parse(pattern or ''):
        if field:
            names.add(re.split(r'[.\[]', field, maxsplit=1)[0])
    return names


def typed(value, like, key, case_name):
    """ convert the CSV string ``value`` to the type of the template's value ``like`` """
    try:
        if isinstance(like, bool):
            return value.strip().lower() in ('1', 'true', 'yes')
        if isinstance(like, int):
            return int(value)
        if isinstance(like, float):
            return float(value)
    except ValueError:
        sys.exit(f'case {case_name}: {key}={value!r} is not a {type(like).__name__} '
                 f'like the template value {like!r}')
    return value


def read_cases(csv_path):
    """ read the CSV rows, dropping blank cells and checking case names """
    with open(csv_path, newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(
            line for line in handle if line.strip() and not line.lstrip().startswith('#'))
        if not reader.fieldnames or 'case_name' not in reader.fieldnames:
            sys.exit(f'{csv_path}: needs a header row with a case_name column')
        rows = []
        for row in reader:
            row = {k.strip(): v.strip() for k, v in row.items() if k and v and v.strip()}
            name = row.get('case_name', '')
            if not CASE_NAME_RE.match(name):
                sys.exit(f'{csv_path}: bad case_name {name!r} '
                         "(letters, digits, '.', '_' and '-' only)")
            rows.append(row)
    names = [row['case_name'] for row in rows]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        sys.exit(f'{csv_path}: duplicate case_name(s): {dupes}')
    if not rows:
        sys.exit(f'{csv_path}: no cases')
    return rows


def main(): # pylint: disable=too-many-locals,too-many-statements,too-many-branches
    """ parse the arguments, write every case's json and yaml, then submit_all.sh """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('cases', help='CSV with one row per case')
    parser.add_argument('--exp-template', required=True,
                        help='experiment config json of a working case')
    parser.add_argument('--yaml-template', required=True,
                        help='CMOR yaml of a working case (as written by fremor config)')
    parser.add_argument('--out-dir', required=True,
                        help='where to write <case_name>/ directories and submit_all.sh')
    parser.add_argument('--pp-dir', help='pp_dir pattern for rows without a pp_dir column')
    parser.add_argument('--outdir',
                        help='CMOR outdir pattern for rows without an outdir column '
                             '(default: the template outdir + /{case_name})')
    parser.add_argument('--archive-dir',
                        help='ARCHIVE_DIR pattern for rows without an archive_dir column')
    parser.add_argument('--jobs-root', default='${HOME}/fremor_jobs',
                        help='parent of the per-case work dirs (default: %(default)s); '
                             'a relative path is taken from the current directory')
    parser.add_argument('--submitter', default=str(SCRIPT_DIR / 'fremor_submit_tables.sh'),
                        help='fremor_submit_tables.sh to call (default: next to this script)')
    parser.add_argument('--allow-new-keys', action='store_true',
                        help='allow CSV columns that are not keys of the template json')
    parser.add_argument('--force', action='store_true',
                        help='overwrite existing generated files')
    args = parser.parse_args()

    with open(args.exp_template, encoding='utf-8') as handle:
        exp_template = json.load(handle)
    with open(args.yaml_template, encoding='utf-8') as handle:
        yaml_template = yaml.safe_load(handle)
    if 'cmor' not in (yaml_template or {}):
        sys.exit(f'{args.yaml_template}: no top-level "cmor:" section')
    submitter = Path(args.submitter).expanduser().resolve()
    if not submitter.is_file():
        sys.exit(f'submitter not found: {submitter}')

    rows = read_cases(args.cases)
    columns = {k for row in rows for k in row} - RESERVED
    referenced = set().union(*(fields(p) for p in (args.pp_dir, args.outdir, args.archive_dir)),
                             *(fields(v) for row in rows for v in row.values()))
    unknown = sorted(k for k in columns if k not in exp_template and k not in referenced)
    if unknown and not args.allow_new_keys:
        sys.exit(f'CSV columns neither in {args.exp_template} nor used as {{column}}: '
                 f'{unknown} (typo? pass --allow-new-keys to add them to the json anyway)')
    helpers = {k for k in columns if k not in exp_template and k in referenced}
    exp_keys = sorted(columns - helpers)

    out_dir = Path(args.out_dir).expanduser().resolve()
    # left as given when it starts with $ (expanded by submit_all.sh), else made absolute
    # so the work dirs do not depend on where submit_all.sh is run from
    jobs_root = args.jobs_root.rstrip('/') or '/'
    if not jobs_root.startswith('$'):
        jobs_root = str(Path(jobs_root).expanduser().resolve())
    template_outdir = yaml_template['cmor']['directories']['outdir'].rstrip('/')
    patterns = {'pp_dir': args.pp_dir,
                'outdir': args.outdir or template_outdir + '/{case_name}'}

    submit_lines = []
    for row in rows:
        name = row['case_name']
        case_dir = out_dir / name
        exp_path = case_dir / 'exp_config.json'
        yaml_path = case_dir / 'fremor.yaml'
        if not args.force:
            existing = [str(p) for p in (exp_path, yaml_path) if p.exists()]
            if existing:
                sys.exit(f'already exist (use --force to overwrite): {existing}')

        # experiment config: the template with this row's keys set
        exp = copy.deepcopy(exp_template)
        for key in exp_keys:
            if key in row:
                exp[key] = typed(fill(row[key], row, key), exp_template.get(key, ''), key, name)

        # yaml: directories and exp_json point at this case
        doc = copy.deepcopy(yaml_template)
        directories = doc['cmor']['directories']
        for col in DIR_COLUMNS:
            pattern = row.get(col) or patterns[col]
            if pattern is None:
                sys.exit(f'case {name}: no {col} column value and no --{col.replace("_", "-")}')
            directories[col] = fill(pattern, row, col)
        doc['cmor']['exp_json'] = str(exp_path)

        # serialize first, so a failure cannot leave half-written files behind
        exp_text = json.dumps(exp, indent=4) + '\n'
        yaml_text = dump_yaml(doc)
        case_dir.mkdir(parents=True, exist_ok=True)
        exp_path.write_text(exp_text, encoding='utf-8')
        yaml_path.write_text(yaml_text, encoding='utf-8')

        # env for this case's submission. WORK_DIR keeps ${HOME} etc. unexpanded
        env = {'CASE_NAME': name, 'FREMOR_YAML': str(yaml_path)}
        for col, var in SUBMIT_COLUMNS.items():
            value = row.get(col) or (args.archive_dir if col == 'archive_dir' else None)
            if value:
                env[var] = fill(value, row, col)
        assigns = ' '.join(f'{var}={shlex.quote(val)}' for var, val in env.items())
        submit_lines.append(
            f'run_case {shlex.quote(name)} {assigns} WORK_DIR="{jobs_root}/{name}"')

        changed = ', '.join(f'{k}={exp[k]!r}' for k in exp_keys if k in row)
        print(f'{name}: pp_dir={directories["pp_dir"]}  {changed}')

    write_submit_all(out_dir / 'submit_all.sh', submitter, submit_lines)
    print(f'\nwrote {len(rows)} cases under {out_dir}')
    print(f'check with:  DRY_RUN=1 {out_dir}/submit_all.sh')
    print(f'submit with: {out_dir}/submit_all.sh')


def write_submit_all(path, submitter, submit_lines):
    """ write the driver running the submitter once per case """
    script = f'''#!/bin/bash
# generated by fremor_make_cases.py -- runs fremor_submit_tables.sh once per case.
#   ./submit_all.sh [--continue] [TABLE ...]   args go to every submission
#   CASES="a b" ./submit_all.sh                 only these cases
#   DRY_RUN=1 ./submit_all.sh                   print sbatch commands, submit nothing
# all cases share JOB_QUEUE_FILE, so the submitter's MAX_CONCURRENT limits their
# jobs together. a case that fails to submit is reported and the rest go on.
set -uo pipefail

SUBMITTER={shlex.quote(str(submitter))}
export MODE=yaml
export JOB_QUEUE_FILE=${{JOB_QUEUE_FILE:-{shlex.quote(str(path.parent / 'job_queue.txt'))}}}
CASES=${{CASES:-}}
failed=()

# run_case <case_name> VAR=value ... -> run the submitter with those variables set
run_case() {{
    local name=$1
    shift
    if [[ -n ${{CASES}} && " ${{CASES}} " != *" ${{name}} "* ]]; then
        return 0
    fi
    echo "=== ${{name}}"
    env "$@" "${{SUBMITTER}}" ${{ARGS[@]+"${{ARGS[@]}}"}} || failed+=("${{name}}")
}}

ARGS=("$@")
{chr(10).join(submit_lines)}

if [[ ${{#failed[@]}} -gt 0 ]]; then
    echo "FAILED (${{#failed[@]}}): ${{failed[*]}}" >&2
    exit 1
fi
'''
    path.write_text(script, encoding='utf-8')
    path.chmod(0o755)


if __name__ == '__main__':
    main()
