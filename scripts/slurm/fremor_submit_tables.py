#!/usr/bin/env python3
"""
fremor_submit_tables.py -- split a fremor workflow into one slurm job per MIP
table, write each table's job script and submit them with sbatch.

Each table gets a self-contained bash job script, <WORK_DIR>/<table>/job.sh,
that stages and CMORizes in one go: it lists the table's input files, verifies
they exist, dmgets them from tape to disk, verifies (dmls) they are
disk-resident, then immediately runs `fremor yaml` (MODE=yaml) or `fremor run`
(MODE=run). Keeping both in one job means staged files are processed right
away, instead of waiting in the queue for a separate CMOR job while they risk
being purged from the disk cache. The job scripts are rewritten on every
submission, so edit the settings here, not there.

Run this on a login / analysis node (NOT inside sbatch), with a python that has
PyYAML (e.g. the fremor environment's):
  ./fremor_submit_tables.py                 # all tables from the config below
  ./fremor_submit_tables.py Amon Omon       # only these tables (overrides TABLES)
  DRY_RUN=1 ./fremor_submit_tables.py       # write the job scripts, print the
                                            # sbatch commands, submit nothing
  ./fremor_submit_tables.py --continue=~/fremor_jobs/20260929_101500
                                            # resubmit the tables of that earlier
                                            # run that have no DONE marker yet
  ./fremor_submit_tables.py --continue      # same, for the WORK_DIR set below
                                            # (CONTINUE=1 in the env works too)
  WORK_DIR=~/fremor_jobs/20260929_101500 ./fremor_submit_tables.py --overwrite
                                            # rerun the tables from scratch in that
                                            # existing WORK_DIR, rewriting its files
                                            # (OVERWRITE=1 in the env works too)
  CASE_NAME=esm4_hist_r1 FREMOR_YAML=... ./fremor_submit_tables.py
                                            # one case of many: its own work dir,
                                            # archive dir and slurm job names

Settings marked [env] below can also be set in the environment, which is how
fremor_make_cases.py's generated submit_all.sh runs one submission per case.
"""

import copy
import os
import re
import shlex
import subprocess
import sys
import time


def env(name, default):
    """ the environment's value of ``name`` if set and non-empty, else ``default`` """
    return os.environ.get(name) or default


def in_case(root):
    """ ``root``/<CASE_NAME>, or ``root`` without a case """
    return f'{root}/{CASE_NAME}' if CASE_NAME else root


# ==============================================================================
# USER CONFIG -- edit this block. [env] -> the environment overrides the value
# ==============================================================================

## [env] short name telling cases (experiments / ensemble members) apart, e.g.
## esm4_hist_r1. goes into the default WORK_DIR and ARCHIVE_DIR and into the
## slurm job names (fremor_<CASE_NAME>_<table>). letters, digits, . _ - only.
## empty -> single-case behaviour
CASE_NAME = env('CASE_NAME', '')

## how to make `fremor` available inside the batch jobs (bash code, copied into
## each job script; also run once here to check that it works)
ENV_SETUP = 'module load fremor'
#ENV_SETUP = 'source /path/to/miniforge3/etc/profile.d/conda.sh && conda activate fremor'

## [env] workflow mode: "yaml" -> fremor yaml, "run" -> fremor run
MODE = env('MODE', 'yaml')

## [env] scratch area for per-table yamls, job scripts, file lists and slurm logs.
## must not exist yet (an empty directory is fine) unless resuming it with --continue
WORK_DIR = env('WORK_DIR', in_case('~/fremor_jobs') + time.strftime('/%Y%m%d_%H%M%S'))

## [env] 1 -> resume an earlier run in the existing WORK_DIR: skip tables that have a
## DONE marker or whose previous job is still queued/running, and (MODE=yaml)
## add --continue so chunks already CMORized are not redone. set a fixed
## ARCHIVE_TMP_ROOT, or leave it empty (-> WORK_DIR), so those chunks are found.
## MODE=run has no --continue, so unfinished tables are CMORized from scratch
CONTINUE = env('CONTINUE', '0') == '1'

## [env] 1 -> start a fresh run in an existing, non-empty WORK_DIR: every selected
## table is resubmitted from scratch, rewriting its yaml, job script, file lists and
## markers (no --continue, so chunks already CMORized are redone). refused while a
## job of that WORK_DIR is still queued/running. cannot be combined with CONTINUE
OVERWRITE = env('OVERWRITE', '0') == '1'

## [env] optional year bounds (YYYY), passed as --start/--stop. empty -> use yaml / all
START = env('START', '')
STOP = env('STOP', '')

## ---------------------------- MODE=yaml ----------------------------
## [env] self-contained CMOR yaml (as written by `fremor config`)
FREMOR_YAML = env('FREMOR_YAML', '/path/to/cmor.yaml')
## tables to process. empty -> every enabled table_target in FREMOR_YAML
TABLES = []
## extra flags for `fremor yaml`, e.g. ['--run_strict'], or ['--continue'] to
## resubmit a failed/timed-out table and only CMORize the chunks with no output yet
YAML_EXTRA_ARGS = []
## run `fremor check <table> --check-inputs --check-dims` after staging
PRECHECK = True
## run `fremor check <table> --check-outputs` after CMORizing
POSTCHECK = True

## ---------------------------- MODE=run -----------------------------
## [env] experiment config json and CMOR output root, shared by all targets
EXP_CONFIG = env('EXP_CONFIG', '/path/to/CMOR_input.json')
OUTDIR = env('OUTDIR', in_case('/path/to/cmorized_output'))
## one entry per table. label: job name and work subdirectory, table_json: MIP
## table, indir: input directory, varlist: variable list json, args: extra
## `fremor run` arguments (optional)
RUN_TARGETS = [
    {'label': 'Amon',
     'table_json': '/path/to/tables/CMIP6_Amon.json',
     'indir': '/path/to/pp/atmos_cmip/ts/monthly/5yr',
     'varlist': '/path/to/varlist_Amon.json',
     'args': '--grid_label gr1 --calendar noleap'},
    # {'label': 'Omon',
    #  'table_json': '/path/to/tables/CMIP6_Omon.json',
    #  'indir': '/path/to/pp/ocean_monthly/ts/monthly/5yr',
    #  'varlist': '/path/to/varlist_Omon.json'},
]

## ---------------------------- staging ------------------------------
## [env] max table jobs running at once (each recalls from tape then CMORizes);
## keep small to be kind to the tape system. 1 -> strictly serial, 0 -> no limit.
## the limit covers this submission only, unless JOB_QUEUE_FILE is set
MAX_CONCURRENT = env('MAX_CONCURRENT', '4')
## [env] file shared by several submissions (e.g. one per case) that each appends
## its job ids to; MAX_CONCURRENT then limits the jobs of all of them together,
## by chaining new jobs behind the still-queued jobs listed there. empty -> off
JOB_QUEUE_FILE = env('JOB_QUEUE_FILE', '')
DMGET_BATCH = 500       # files per dmget call
STAGE_RETRIES = 3       # dmget + verify attempts before giving up
## True -> copy staged inputs to node-local LOCAL_ROOT before running CMOR
COPY_TO_LOCAL = False
LOCAL_ROOT = '${TMPDIR}'  # expanded inside the job, e.g. '/vftmp/${USER}/${SLURM_JOB_ID}'

## ---------------------------- archive ------------------------------
## 1 -> CMORize into a per-table temporary outdir (overriding the yaml's outdir /
## OUTDIR), then move the finished .nc files into ARCHIVE_DIR. MODE=yaml writes
## <outdir>/<component>/<table>/<CMIP dirs>/*.nc; those first two levels are
## dropped, so ARCHIVE_DIR gets <CMIP dirs>/*.nc. CMOR's *.log files in CMOR_tmp
## are moved to the table's logs/ directory
## [env] ARCHIVE and ARCHIVE_DIR. the default ARCHIVE_DIR keeps cases apart; drop
## the CASE_NAME part to collect all cases in one CMIP directory tree
ARCHIVE = env('ARCHIVE', '0') == '1'
ARCHIVE_DIR = env('ARCHIVE_DIR', in_case('/path/to/archive'))
## parent of the per-table temporary outdirs (<root>/<table>/outdir).
## empty -> WORK_DIR. set a fixed path to resume with --continue: outputs of a
## failed job are not archived and stay there for the next submission to reuse [env]
ARCHIVE_TMP_ROOT = env('ARCHIVE_TMP_ROOT', '')

## ---------------------------- slurm --------------------------------
SLURM_ACCOUNT = ''      # --account, empty -> default
## each job covers tape recall + CMOR, so JOB_TIME must allow for both
JOB_PARTITION = 'batch'
JOB_TIME = '16:00:00'
JOB_MEM = '16G'
JOB_CPUS = 1
MAIL_USER = ''          # empty -> no mail
## further sbatch options, one per entry in --option=value form, e.g.
## ['--qos=normal', '--constraint=bigmem']; written as #SBATCH lines
SBATCH_EXTRA_ARGS = []

# ==============================================================================
# END USER CONFIG
# ==============================================================================

DRY_RUN = os.environ.get('DRY_RUN') == '1'
CASE_NAME_RE = re.compile(r'^[A-Za-z0-9._-]+$')
HISTORY = ''


def hist(text):
    """ append a timestamped line to ``HISTORY`` (once it is set) """
    if HISTORY:
        with open(HISTORY, 'a', encoding='utf-8') as handle:
            handle.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {text}\n')


def die(text):
    """ report ``text`` as an error, record it in the history and exit """
    sys.stdout.flush()
    print(f'ERROR: {text}', file=sys.stderr)
    hist(f'  aborted: {text}')
    sys.exit(1)


def in_queue(job_id):
    """ true if slurm job ``job_id`` is pending or running (dry-run ids are not) """
    if not job_id or job_id.startswith('DRYRUN_'):
        return False
    try:
        out = subprocess.run(['squeue', '-h', '-j', job_id, '-o', '%i'],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             universal_newlines=True, check=False).stdout
    except OSError:
        return False
    return bool(out.strip())


def read_jobid(table_work):
    """ the job id of the table's latest submission, '' if none """
    try:
        with open(os.path.join(table_work, 'JOBID'), encoding='utf-8') as handle:
            return handle.read().strip()
    except OSError:
        return ''


def dump_yaml(doc):
    """
    ``doc`` as block-style yaml text, keys in their original order. PyYAML < 5.1 (e.g. a
    system python3.6) has no ``sort_keys`` and always sorts, so it gets a dumper whose
    mappings are written from item lists, which PyYAML leaves in the order given
    """
    import yaml # pylint: disable=import-outside-toplevel
    try:
        return yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)
    except TypeError:
        class OrderedDumper(yaml.SafeDumper): # pylint: disable=too-many-ancestors
            """ SafeDumper keeping dict insertion order """
        OrderedDumper.add_representer(
            dict, lambda dumper, data: dumper.represent_mapping(
                'tag:yaml.org,2002:map', list(data.items())))
        return yaml.dump(doc, Dumper=OrderedDumper, default_flow_style=False)


def split_yaml(work_dir, tmp_root, wanted):
    """
    write one single-table yaml per selected table to <work_dir>/<table>/ (all other
    table_targets marked disabled: true, so named ps_component lookups across targets
    keep working; with ``tmp_root``, outdir points at the table's temporary outdir).
    returns the table names
    """
    import yaml # pylint: disable=import-outside-toplevel
    if not os.path.isfile(FREMOR_YAML):
        die(f'FREMOR_YAML not found: {FREMOR_YAML}')
    with open(FREMOR_YAML, encoding='utf-8') as handle:
        doc = yaml.safe_load(handle)
    enabled = [t['table_name'] for t in doc['cmor']['table_targets'] if not t.get('disabled')]
    names = list(dict.fromkeys(wanted or enabled))
    missing = [n for n in names if n not in enabled]
    if missing:
        die(f'tables not found (or disabled) in {FREMOR_YAML}: {missing}')
    for name in names:
        sub = copy.deepcopy(doc)
        for target in sub['cmor']['table_targets']:
            if target['table_name'] != name:
                target['disabled'] = True
        if tmp_root:
            sub['cmor']['directories']['outdir'] = f'{tmp_root}/{name}/outdir'
        os.makedirs(os.path.join(work_dir, name), exist_ok=True)
        with open(os.path.join(work_dir, name, f'fremor_{name}.yaml'), 'w',
                  encoding='utf-8') as handle:
            handle.write(dump_yaml(sub))
    return names


def select_run_targets(wanted):
    """ the RUN_TARGETS entries whose label is in ``wanted`` (all if empty), by label """
    targets = {t['label']: t for t in RUN_TARGETS}
    missing = [n for n in wanted if n not in targets]
    if missing:
        die(f'tables not found in RUN_TARGETS: {missing}')
    return {label: t for label, t in targets.items() if not wanted or label in wanted}


# ------------------------------------------------------------------------------
# job script pieces. the script for one table is the header written by
# job_script() (#SBATCH lines and the table's settings) followed by the pieces
# that apply to its MODE / COPY_TO_LOCAL / ARCHIVE / PRECHECK / POSTCHECK.
# @YEARS@ and @CMOR@ are filled in by job_script()
# ------------------------------------------------------------------------------
JOB_START = r'''
STEP=stage
log() { echo "[$(date '+%F %T')] [${STEP}:${CASE_NAME:+${CASE_NAME}/}${LABEL}] $*"; }
die() { log "ERROR: $*" >&2; exit 1; }
# logrun <command ...> -> log the command line, then run it
logrun() { log "+ $*"; "$@"; }

log "host=$(hostname) job=${SLURM_JOB_ID:-none}"
# markers from an earlier submission into this WORK_DIR no longer apply
rm -f "${TABLE_WORK}/STAGED" "${TABLE_WORK}/DONE"
cd "${SUBMIT_DIR}"    # relative paths inside the yaml resolve from here
'''

JOB_FREMOR = r'''command -v fremor >/dev/null || die "fremor not found after the environment setup"
PYTHON=$(dirname "$(command -v fremor)")/python
[[ -x ${PYTHON} ]] || PYTHON=python3

INPUT_LIST=${TABLE_WORK}/input_files.txt
OFFLINE_LIST=${TABLE_WORK}/offline_files.txt
FREMOR_LOG=${TABLE_WORK}/fremor_${LABEL}.log

# ------------------------------------------------------------------------------
# staging
# ------------------------------------------------------------------------------
'''

LIST_INPUTS_YAML = r'''# write the table's input files (one per line) to INPUT_LIST. fremor stage
# --dry_run prints every mapped input (+ ps companions), then a "Would stage N
# files" summary line
list_inputs() {
    fremor stage -y "${TABLE_YAML}"@YEARS@ --dry_run > "${INPUT_LIST}.tmp" \
        || die "fremor stage --dry_run failed"
    grep -v -e '^Would stage' -e '^$' "${INPUT_LIST}.tmp" > "${INPUT_LIST}" || true
    rm -f "${INPUT_LIST}.tmp"
    [[ -s ${INPUT_LIST} ]] || die "no input files found for ${LABEL}"
    log "found $(wc -l < "${INPUT_LIST}") input files -> ${INPUT_LIST}"
}
'''

LIST_INPUTS_RUN = r'''# write the table's input files (one per line) to INPUT_LIST, by the same
# selection rules as fremor stage
list_inputs() {
    "${PYTHON}" - "${INDIR}" "${VARLIST}" "${START}" "${STOP}" > "${INPUT_LIST}" <<'PYEOF'
import json, sys
from pathlib import Path
indir, varlist, start, stop = sys.argv[1:5]
local_vars = set(json.load(open(varlist, encoding='utf-8')))
start = int(start) if start else None
stop = int(stop) if stop else None
files = set()
for path in Path(indir).glob('*.nc'):
    parts = path.name.split('.')
    if len(parts) < 4 or parts[-2] not in local_vars:
        continue
    first, last = parts[-3].split('-', 1)
    if (start and int(first[:4]) < start) or (stop and int(last[:4]) > stop):
        continue
    files.add(path.resolve())
    ps_path = path.with_name('.'.join((*parts[:-2], 'ps', 'nc')))
    if ps_path.is_file():
        files.add(ps_path.resolve())
for f in sorted(map(str, files)):
    print(f)
PYEOF
    [[ -s ${INPUT_LIST} ]] || die "no input files found for ${LABEL}"
    log "found $(wc -l < "${INPUT_LIST}") input files -> ${INPUT_LIST}"
}
'''

JOB_STAGE = r'''
# every listed file must exist (as a file or an archive stub)
check_exist() {
    local missing=${TABLE_WORK}/missing_files.txt
    : > "${missing}"
    while IFS= read -r f; do
        [[ -e ${f} ]] || echo "${f}" >> "${missing}"
    done < "${INPUT_LIST}"
    [[ -s ${missing} ]] && die "$(wc -l < "${missing}") input files missing, see ${missing}"
    log "all input files exist"
}

# write files NOT disk-resident to OFFLINE_LIST; return 0 if none.
# dmls -l state: REG (regular, on disk) / DUL (dual, on disk) are fine;
# OFL / MIG / UNM / PAR / NMG need (more) dmget.
check_on_disk() {
    : > "${OFFLINE_LIST}"
    if ! command -v dmls >/dev/null; then
        log "dmls not available, treating inputs as regular disk files"
        return 0
    fi
    xargs -a "${INPUT_LIST}" -d '\n' -n "${DMGET_BATCH}" dmls -l \
        | awk '{ st = ""; for (i = 1; i <= NF; i++) if ($i ~ /^\([A-Z]+\)$/) { st = $i; fn = $(i + 1) }
                 if (st != "" && st != "(REG)" && st != "(DUL)") print fn }' > "${OFFLINE_LIST}"
    [[ ! -s ${OFFLINE_LIST} ]]
}

# dmget offline files in batches, retrying until all are on disk
stage_inputs() {
    local attempt
    if ! command -v dmget >/dev/null; then
        log "dmget not available, skipping tape recall"
        return 0
    fi
    for (( attempt = 1; attempt <= STAGE_RETRIES; attempt++ )); do
        if check_on_disk; then
            log "all inputs are on disk"
            return 0
        fi
        log "attempt ${attempt}/${STAGE_RETRIES}: dmget $(wc -l < "${OFFLINE_LIST}") offline files"
        xargs -a "${OFFLINE_LIST}" -d '\n' -n "${DMGET_BATCH}" dmget \
            || log "WARNING: dmget returned non-zero, will re-verify"
    done
    check_on_disk || die "$(wc -l < "${OFFLINE_LIST}") files still offline, see ${OFFLINE_LIST}"
    log "all inputs are on disk"
}
'''

COPY_TO_LOCAL_YAML = r'''
# copy the staged inputs to node-local storage and point TABLE_YAML at them
copy_to_local() {
    local local_root pp_dir
    local_root=$(eval echo "${LOCAL_ROOT}")/fremor_${LABEL}
    mkdir -p "${local_root}"
    log "copying inputs to ${local_root}"
    pp_dir=$("${PYTHON}" -c 'import os, sys, yaml
d = yaml.safe_load(open(sys.argv[1]))["cmor"]["directories"]["pp_dir"]
print(os.path.realpath(os.path.expandvars(d)))' "${TABLE_YAML}")
    while IFS= read -r f; do
        [[ ${f} == "${pp_dir}"/* ]] || die "input ${f} not under pp_dir ${pp_dir}"
        mkdir -p "${local_root}/pp/$(dirname "${f#"${pp_dir}"/}")"
        cp -p "${f}" "${local_root}/pp/${f#"${pp_dir}"/}"
    done < "${INPUT_LIST}"
    # local copy of the yaml with pp_dir redirected
    "${PYTHON}" - "${TABLE_YAML}" "${local_root}/pp" "${local_root}/fremor_${LABEL}.yaml" <<'PYEOF'
import sys, yaml
src, pp_dir, dst = sys.argv[1:4]
doc = yaml.safe_load(open(src))
doc['cmor']['directories']['pp_dir'] = pp_dir
yaml.safe_dump(doc, open(dst, 'w'), sort_keys=False)
PYEOF
    TABLE_YAML=${local_root}/fremor_${LABEL}.yaml
    log "copied $(du -sh "${local_root}" | cut -f1)"
}
'''

COPY_TO_LOCAL_RUN = r'''
# copy the staged inputs to node-local storage and point INDIR at them
copy_to_local() {
    local local_root
    local_root=$(eval echo "${LOCAL_ROOT}")/fremor_${LABEL}
    mkdir -p "${local_root}"
    log "copying inputs to ${local_root}"
    xargs -a "${INPUT_LIST}" -d '\n' cp -p -t "${local_root}"
    INDIR=${local_root}
    log "copied $(du -sh "${local_root}" | cut -f1)"
}
'''

JOB_ARCHIVE = r'''
# ------------------------------------------------------------------------------
# archiving. the temporary outdir holds
#   MODE=yaml: <tmp>/<component>/<table>/<CMIP dirs>/*.nc  (+ .../CMOR_tmp/)
#   MODE=run : <tmp>/<CMIP dirs>/*.nc                      (+ <tmp>/CMOR_tmp/)
# ARCHIVE_LEVELS is how many leading directories to drop so only <CMIP dirs> remain
# ------------------------------------------------------------------------------

# split path $1 (relative to TMP_OUTDIR) into the global array PATH_PARTS
split_rel() { IFS=/ read -r -a PATH_PARTS <<< "${1#"${TMP_OUTDIR}"/}"; }

# move CMOR's log files out of CMOR_tmp into logs/, prefixed with the dropped
# levels (e.g. atmos.Amon.cmor_tas.log) so logs from different components can't clash
collect_cmor_logs() {
    [[ -d ${TMP_OUTDIR} ]] || return 0
    local f prefix count=0
    while IFS= read -r -d '' f; do
        split_rel "${f}"
        prefix=$(IFS=.; echo "${PATH_PARTS[*]:0:ARCHIVE_LEVELS}")
        mv -f "${f}" "${TABLE_WORK}/logs/${prefix:+${prefix}.}$(basename "${f}")"
        count=$((count + 1))
    done < <(find "${TMP_OUTDIR}" -path '*/CMOR_tmp/*' -type f -name '*.log' -print0)
    log "moved ${count} CMOR log files to ${TABLE_WORK}/logs"
}

# move the CMORized .nc files into ARCHIVE_DIR, keeping the CMIP directory
# structure. files already present in the archive are overwritten, and listed
# in archive_overwritten.txt
archive_outputs() {
    local overwritten=${TABLE_WORK}/archive_overwritten.txt
    local f dest count=0
    : > "${overwritten}"
    while IFS= read -r -d '' f; do
        split_rel "${f}"
        (( ${#PATH_PARTS[@]} > ARCHIVE_LEVELS + 1 )) \
            || die "unexpected output layout, expected ${ARCHIVE_LEVELS} levels above the CMIP dirs: ${f}"
        dest=${ARCHIVE_DIR}/$(IFS=/; echo "${PATH_PARTS[*]:ARCHIVE_LEVELS}")
        [[ -e ${dest} ]] && echo "${dest}" >> "${overwritten}"
        mkdir -p "$(dirname "${dest}")"
        mv -f "${f}" "${dest}"
        count=$((count + 1))
    done < <(find "${TMP_OUTDIR}" -type f -name '*.nc' -not -path '*/CMOR_tmp/*' -print0)
    # drop the directory shells left behind (and CMOR_tmp, if nothing else is in it)
    find "${TMP_OUTDIR}" -mindepth 1 -depth -type d -empty -delete
    log "archived ${count} files to ${ARCHIVE_DIR}"
    [[ -s ${overwritten} ]] \
        && log "WARNING: overwrote $(wc -l < "${overwritten}") existing archive files, see ${overwritten}"
    return 0
}
'''

PRECHECK_LINES = r'''    log "fremor check --check-inputs --check-dims"
    fremor check "${LABEL}" -y "${TABLE_YAML}" --check-inputs --check-dims \
        -o "${TABLE_WORK}/precheck_report.json" \
        || log "WARNING: fremor check reported problems, see log above"
'''

POSTCHECK_LINES = r'''    log "fremor check --check-outputs"
    # checks the original per-table yaml, whose outdir is unchanged by copy_to_local
    fremor check "${LABEL}" -y "${TABLE_WORK}/fremor_${LABEL}.yaml" --check-outputs \
        -o "${TABLE_WORK}/postcheck_report.json" \
        || log "WARNING: fremor check reported problems, see log above"
'''

JOB_END = r'''
# stage then cmor back to back, so recalled files are used before they can be purged
do_stage
STEP=cmor
do_cmor
'''


def quoted(args):
    """ ``args`` as shell words, each preceded by a space ('' for none) """
    return ''.join(' ' + shlex.quote(str(a)) for a in args)


def job_script(label, table_work, target, yaml_args, tmp_outdir): # pylint: disable=too-many-branches
    """ the bash job script for table ``label`` (``target``: its RUN_TARGETS entry) """
    yaml_mode = MODE == 'yaml'
    years = quoted((['--start', START] if START else []) + (['--stop', STOP] if STOP else []))

    sbatch = [f'--job-name=fremor_{CASE_NAME + "_" if CASE_NAME else ""}{label}',
              f'--output={table_work}/logs/%x.%j.out',
              f'--partition={JOB_PARTITION}', f'--time={JOB_TIME}', f'--mem={JOB_MEM}',
              '--ntasks=1', f'--cpus-per-task={JOB_CPUS}']
    if SLURM_ACCOUNT:
        sbatch.append(f'--account={SLURM_ACCOUNT}')
    if MAIL_USER:
        sbatch += [f'--mail-user={MAIL_USER}', '--mail-type=FAIL']
    sbatch += SBATCH_EXTRA_ARGS

    settings = {'CASE_NAME': CASE_NAME, 'LABEL': label, 'TABLE_WORK': table_work,
                'SUBMIT_DIR': os.getcwd(), 'START': START, 'STOP': STOP}
    if yaml_mode:
        settings['TABLE_YAML'] = f'{table_work}/fremor_{label}.yaml'
        cmor = f'logrun fremor -v -l "${{FREMOR_LOG}}" yaml -y "${{TABLE_YAML}}"{years}' \
               + quoted(yaml_args)
    else:
        settings.update(TABLE_JSON=target['table_json'], INDIR=target['indir'],
                        VARLIST=target['varlist'], EXP_CONFIG=EXP_CONFIG)
        if not tmp_outdir:
            settings['OUTDIR'] = OUTDIR
        cmor = ('logrun fremor -v -l "${FREMOR_LOG}" run \\\n'
                '        -d "${INDIR}" -l "${VARLIST}" -r "${TABLE_JSON}" -p "${EXP_CONFIG}" '
                f'-o "${{{"TMP_OUTDIR" if tmp_outdir else "OUTDIR"}}}"{years}'
                + quoted(shlex.split(target.get('args') or '')))
    settings.update(DMGET_BATCH=DMGET_BATCH, STAGE_RETRIES=STAGE_RETRIES)
    if COPY_TO_LOCAL:
        settings['LOCAL_ROOT'] = LOCAL_ROOT
    if tmp_outdir:
        settings.update(ARCHIVE_DIR=ARCHIVE_DIR, TMP_OUTDIR=tmp_outdir,
                        ARCHIVE_LEVELS=2 if yaml_mode else 0)

    steps = ['fremor yaml' if yaml_mode else 'fremor run']
    if tmp_outdir:
        steps.append(f'move the CMORized files into {ARCHIVE_DIR}')
    parts = [
        '#!/bin/bash\n',
        f'# fremor job for MIP table {label}{" of case " + CASE_NAME if CASE_NAME else ""}, '
        f'written by fremor_submit_tables.py\n',
        f'# on {time.strftime("%Y-%m-%d %H:%M:%S")}. stages the inputs from tape, then runs '
        f'{" and ".join(steps)}.\n',
        '# rewritten on every submission: edit the submitter, not this file\n',
        ''.join(f'#SBATCH {arg}\n' for arg in sbatch),
        '\nset -euo pipefail\n\n',
        ''.join(f'{name}={shlex.quote(str(value))}\n' for name, value in settings.items()),
        JOB_START,
        '# make fremor available. setup scripts may read unset variables\n',
        f'set +u\n{ENV_SETUP.strip()}\nset -u\n',
        JOB_FREMOR,
        LIST_INPUTS_YAML.replace('@YEARS@', years) if yaml_mode else LIST_INPUTS_RUN,
        JOB_STAGE,
    ]
    if COPY_TO_LOCAL:
        parts.append(COPY_TO_LOCAL_YAML if yaml_mode else COPY_TO_LOCAL_RUN)
    if tmp_outdir:
        parts.append(JOB_ARCHIVE)

    parts.append('\n# ------------------------------------------------------------------------------\n'
                 '# steps\n'
                 '# ------------------------------------------------------------------------------\n'
                 'do_stage() {\n    list_inputs\n    check_exist\n    stage_inputs\n')
    if yaml_mode and PRECHECK:
        parts.append(PRECHECK_LINES)
    parts.append('    touch "${TABLE_WORK}/STAGED"\n}\n\ndo_cmor() {\n')
    if COPY_TO_LOCAL:
        parts.append('    copy_to_local\n')
    parts.append(f'    local rc=0\n    {cmor} || rc=$?\n')
    if tmp_outdir:
        parts.append("    # keep CMOR's logs even when fremor failed, they hold the real error messages\n"
                     '    collect_cmor_logs\n')
    parts.append('    [[ ${rc} -eq 0 ]] || die "fremor exited with ${rc}, see ${FREMOR_LOG}"\n')
    if yaml_mode and POSTCHECK:
        parts.append(POSTCHECK_LINES)
    if tmp_outdir:
        parts.append('    # after the post-check, which looks for outputs in the temporary outdir\n'
                     '    STEP=archive\n    archive_outputs\n')
    parts.append('    touch "${TABLE_WORK}/DONE"\n    log "done"\n}\n')
    parts.append(JOB_END)
    return ''.join(parts)


def submit(label, script, dep):
    """ sbatch the job script ``script`` (after ``dep`` if set) -> its job id """
    cmd = ['sbatch', '--parsable'] + ([f'--dependency={dep}'] if dep else []) + [script]
    if DRY_RUN:
        print(' '.join(shlex.quote(c) for c in cmd))
        return f'DRYRUN_{label}'
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, check=False)
    except OSError as exc:
        die(f'sbatch failed for {label}: {exc}')
    if result.returncode != 0:
        die(f'sbatch failed for {label}: {result.stderr.strip()}')
    # --parsable prints <job id>[;<cluster>]
    return result.stdout.strip().split(';')[0]


def parse_args(argv):
    """ [--continue[=WORK_DIR] | --overwrite] [TABLE ...] -> (continue, overwrite, work_dir, tables) """
    cont, overwrite, work_dir, tables = CONTINUE, OVERWRITE, WORK_DIR, []
    for arg in argv:
        if arg in ('-h', '--help'):
            print(__doc__)
            sys.exit(0)
        elif arg == '--continue':
            cont = True
        elif arg.startswith('--continue='):
            cont, work_dir = True, arg[len('--continue='):]
            if not work_dir:
                die('--continue= needs a WORK_DIR')
        elif arg == '--overwrite':
            overwrite = True
        elif arg.startswith('-'):
            die(f'unknown option: {arg}')
        else:
            tables.append(arg)
    if cont and overwrite:
        die('--continue and --overwrite exclude each other: resume the run, or redo it from scratch')
    return cont, overwrite, work_dir, tables or list(TABLES)


def main(): # pylint: disable=too-many-locals,too-many-statements,too-many-branches
    """ check the settings, write every table's job script and submit them """
    global HISTORY, ARCHIVE_DIR # pylint: disable=global-statement
    if MODE not in ('yaml', 'run'):
        die(f"MODE must be yaml or run, got '{MODE}'")
    if not str(MAX_CONCURRENT).isdigit():
        die('MAX_CONCURRENT must be a non-negative integer')
    max_concurrent = int(MAX_CONCURRENT)
    if CASE_NAME and not CASE_NAME_RE.match(CASE_NAME):
        die(f"CASE_NAME may only hold letters, digits, '.', '_' and '-', got '{CASE_NAME}'")
    cmd_line = ' '.join(shlex.quote(a) for a in sys.argv)
    cont, overwrite, work_dir, tables = parse_args(sys.argv[1:])
    work_dir = os.path.abspath(os.path.expanduser(work_dir))
    if MODE == 'yaml':
        try:
            import yaml # pylint: disable=import-outside-toplevel,unused-import
        except ImportError:
            die(f'PyYAML not found for {sys.executable}; '
                "run this script with the fremor environment's python")

    # the jobs get fremor the same way, so a broken ENV_SETUP shows up here already
    check = subprocess.run(['bash', '-c', f'{ENV_SETUP}\ncommand -v fremor'],
                           stdout=subprocess.PIPE, universal_newlines=True, check=False)
    if check.returncode != 0 or not check.stdout.strip():
        die('fremor not found after ENV_SETUP')

    if not cont and not overwrite and os.path.isdir(work_dir) and os.listdir(work_dir):
        die(f'WORK_DIR already exists: {work_dir}\n'
            f'       use --continue={work_dir} to resume that run, --overwrite to redo it from\n'
            '       scratch, or pick a new WORK_DIR')
    if overwrite and os.path.isdir(work_dir):
        # a queued/running job reads its yaml from here, so don't rewrite it
        busy = []
        for name in sorted(os.listdir(work_dir)):
            prev_job = read_jobid(os.path.join(work_dir, name))
            if in_queue(prev_job):
                busy.append(f'{name}({prev_job})')
        if busy:
            die(f'--overwrite: jobs of {work_dir} are still queued/running: {" ".join(busy)}\n'
                '       wait for them or scancel them first')
    yaml_args = list(YAML_EXTRA_ARGS)
    if cont:
        if not os.path.isdir(work_dir):
            die(f'CONTINUE=1 needs an existing WORK_DIR, not found: {work_dir}')
        if MODE == 'yaml' and '--continue' not in yaml_args:
            yaml_args.append('--continue')
    os.makedirs(work_dir, exist_ok=True)
    print(f'work dir: {work_dir}')

    # append-only record of every submission into this WORK_DIR, so rerunning the
    # script here (e.g. to resubmit failed tables) keeps the earlier records
    HISTORY = os.path.join(work_dir, 'HISTORY')
    resume = ' (continue)' if cont else ' (overwrite)' if overwrite else ''
    hist(f'submit{resume}{" (dry run, nothing submitted)" if DRY_RUN else ""}: {cmd_line}')
    hist(f'  cwd: {os.getcwd()}, MODE={MODE}, case: {CASE_NAME or "none"}, '
         f'years: {START or "first"}-{STOP or "last"}')
    if MODE == 'yaml':
        hist(f'  yaml: {FREMOR_YAML}, extra args: {" ".join(yaml_args) or "none"}')
    else:
        hist(f'  exp config: {EXP_CONFIG}, outdir: {OUTDIR}')
    hist(f'  slurm: {JOB_PARTITION}, {JOB_TIME}, {JOB_MEM}, {JOB_CPUS} cpu, max concurrent '
         f'{max_concurrent}{" (shared via " + JOB_QUEUE_FILE + ")" if JOB_QUEUE_FILE else ""}')

    tmp_root = ''
    if ARCHIVE:
        try:
            os.makedirs(os.path.expanduser(ARCHIVE_DIR), exist_ok=True)
        except OSError as exc:
            die(f'could not create ARCHIVE_DIR {ARCHIVE_DIR}: {exc}')
        ARCHIVE_DIR = os.path.abspath(os.path.expanduser(ARCHIVE_DIR))
        tmp_root = os.path.abspath(os.path.expanduser(ARCHIVE_TMP_ROOT or work_dir))
        os.makedirs(tmp_root, exist_ok=True)
        print(f'archive dir: {ARCHIVE_DIR} (temporary outdirs under {tmp_root})')
        hist(f'  archive: {ARCHIVE_DIR}, temporary outdirs under {tmp_root}')

    # the per-table targets: label -> RUN_TARGETS entry (None in yaml mode, which
    # writes one single-table yaml per label instead)
    if MODE == 'yaml':
        targets = dict.fromkeys(split_yaml(work_dir, tmp_root, tables))
    else:
        targets = select_run_targets(tables)
    if not targets:
        die('no tables selected')

    # CONTINUE: keep only tables that are neither finished nor still in the queue
    if cont:
        finished, queued = [], []
        for label in list(targets):
            table_work = os.path.join(work_dir, label)
            prev_job = read_jobid(table_work)
            if os.path.exists(os.path.join(table_work, 'DONE')):
                finished.append(label)
            elif in_queue(prev_job):
                queued.append(f'{label}({prev_job})')
            else:
                continue
            del targets[label]
        for what, items in (('already done', finished), ('still queued/running', queued)):
            print(f'{what} ({len(items)}): {" ".join(items) or "none"}')
            hist(f'  skipped, {what} ({len(items)}): {" ".join(items) or "none"}')
        if not targets:
            print('nothing left to submit')
            hist('  nothing left to submit')
            return
    print(f'tables ({len(targets)}): {" ".join(targets)}')
    hist(f'  tables ({len(targets)}): {" ".join(targets)}')

    # per table: write the job script and submit it. with MAX_CONCURRENT=N, job n
    # waits (afterany) for job n-N, so at most N chains run side by side. with
    # JOB_QUEUE_FILE, n counts the jobs of earlier submissions listed there too;
    # a job that has already left the queue needs no waiting for
    queue_ids = []   # earlier submissions' job ids, followed by this one's
    if JOB_QUEUE_FILE:
        queue_file = os.path.expanduser(JOB_QUEUE_FILE)
        os.makedirs(os.path.dirname(os.path.abspath(queue_file)), exist_ok=True)
        if os.path.isfile(queue_file):
            with open(queue_file, encoding='utf-8') as handle:
                queue_ids = [line.strip() for line in handle if line.strip()]
    job_ids = []
    for label, target in targets.items():
        table_work = os.path.join(work_dir, label)
        os.makedirs(os.path.join(table_work, 'logs'), exist_ok=True)
        # the job clears them too, but a later --continue must not trust them meanwhile
        if overwrite and not DRY_RUN:
            for marker in ('STAGED', 'DONE'):
                if os.path.exists(os.path.join(table_work, marker)):
                    os.remove(os.path.join(table_work, marker))

        script = os.path.join(table_work, 'job.sh')
        tmp_outdir = f'{tmp_root}/{label}/outdir' if tmp_root else ''
        with open(script, 'w', encoding='utf-8') as handle:
            handle.write(job_script(label, table_work, target, yaml_args, tmp_outdir))
        os.chmod(script, 0o755)

        dep = ''
        n = len(queue_ids)
        if 0 < max_concurrent <= n:
            prev_job = queue_ids[n - max_concurrent]
            if prev_job.startswith('DRYRUN_') or in_queue(prev_job):
                dep = f'afterany:{prev_job}'
        job_id = submit(label, script, dep)
        job_ids.append(job_id)
        queue_ids.append(job_id)
        if JOB_QUEUE_FILE and not DRY_RUN:
            with open(queue_file, 'a', encoding='utf-8') as handle:
                handle.write(f'{job_id}\n')
        # lets a later CONTINUE run tell whether this job is still queued/running
        with open(os.path.join(table_work, 'JOBID'), 'w', encoding='utf-8') as handle:
            handle.write(f'{job_id}\n')

        print(f'{label}\t{job_id}')
        hist(f'  {label}: job {job_id}{" (" + dep + ")" if dep else ""}')
    hist(f'  submitted {len(job_ids)} jobs')

    prefix = f'fremor_{CASE_NAME + "_" if CASE_NAME else ""}'
    print(f'job ids appended to {HISTORY}')
    print(f"monitor with: squeue -u {os.environ.get('USER', '$USER')} "
          f"-o '%.10i %.40j %.9T %.10M %R' | grep {prefix}")


if __name__ == '__main__':
    main()
