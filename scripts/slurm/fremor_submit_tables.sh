#!/bin/bash
# ==============================================================================
# fremor_submit_tables.sh -- split a fremor workflow into one slurm job per MIP
# table and submit them with sbatch.
#
# Each table's job stages and CMORizes in one go: it lists the table's input
# files, verifies they exist, dmgets them from tape to disk, verifies (dmls)
# they are disk-resident, then immediately runs `fremor yaml` (MODE=yaml) or
# `fremor run` (MODE=run). Keeping both in one job means staged files are
# processed right away, instead of waiting in the queue for a separate CMOR job
# while they risk being purged from the disk cache.
#
# Run this on a login / analysis node (NOT inside sbatch):
#   ./fremor_submit_tables.sh                 # all tables from the config below
#   ./fremor_submit_tables.sh Amon Omon       # only these tables (overrides TABLES)
#   DRY_RUN=1 ./fremor_submit_tables.sh       # print sbatch commands, submit nothing
#   ./fremor_submit_tables.sh --continue=~/fremor_jobs/20260929_101500
#                                             # resubmit the tables of that earlier
#                                             # run that have no DONE marker yet
#   ./fremor_submit_tables.sh --continue      # same, for the WORK_DIR set below
#                                             # (CONTINUE=1 in the env works too)
#   CASE_NAME=esm4_hist_r1 FREMOR_YAML=... ./fremor_submit_tables.sh
#                                             # one case of many: its own work dir,
#                                             # archive dir and slurm job names
#
# Settings marked [env] below can also be set in the environment, which is how
# fremor_make_cases.py's generated submit_all.sh runs one submission per case.
#
# The per-table job body lives in fremor_table_job.sh (same directory).
# ==============================================================================
set -euo pipefail

# ==============================================================================
# USER CONFIG -- edit this block. [env] -> the environment overrides the value
# ==============================================================================

## [env] short name telling cases (experiments / ensemble members) apart, e.g.
## esm4_hist_r1. goes into the default WORK_DIR and ARCHIVE_DIR and into the
## slurm job names (fremor_<CASE_NAME>_<table>). letters, digits, . _ - only.
## empty -> single-case behaviour
CASE_NAME=${CASE_NAME:-}

## how to make `fremor` available inside the batch jobs (eval'd in each job)
ENV_SETUP='module load fremor'
#ENV_SETUP='source /path/to/miniforge3/etc/profile.d/conda.sh && conda activate fremor'

## [env] workflow mode: "yaml" -> fremor yaml, "run" -> fremor run
MODE=${MODE:-yaml}

## [env] scratch area for per-table yamls, file lists, env files and slurm logs.
## must not exist yet (an empty directory is fine) unless resuming it with --continue
WORK_DIR=${WORK_DIR:-${HOME}/fremor_jobs/${CASE_NAME:+${CASE_NAME}/}$(date +%Y%m%d_%H%M%S)}

## 1 -> resume an earlier run in the existing WORK_DIR: skip tables that have a
## DONE marker or whose previous job is still queued/running, and (MODE=yaml)
## add --continue so chunks already CMORized are not redone. set a fixed
## ARCHIVE_TMP_ROOT, or leave it empty (-> WORK_DIR), so those chunks are found.
## MODE=run has no --continue, so unfinished tables are CMORized from scratch
CONTINUE=${CONTINUE:-0}

## [env] optional year bounds (YYYY), passed as --start/--stop. empty -> use yaml / all
START=${START:-}
STOP=${STOP:-}

## ---------------------------- MODE=yaml ----------------------------
## [env] self-contained CMOR yaml (as written by `fremor config`)
FREMOR_YAML=${FREMOR_YAML:-/path/to/cmor.yaml}
## tables to process. empty -> every enabled table_target in FREMOR_YAML
TABLES=()
## extra flags for `fremor yaml`, e.g. (--run_strict), or (--continue) to resubmit
## a failed/timed-out table and only CMORize the chunks with no output yet
YAML_EXTRA_ARGS=()
## run `fremor check <table> --check-inputs --check-dims` after staging (1=yes)
PRECHECK=1
## run `fremor check <table> --check-outputs` after CMORizing (1=yes)
POSTCHECK=1

## ---------------------------- MODE=run -----------------------------
## [env] experiment config json and CMOR output root, shared by all targets
EXP_CONFIG=${EXP_CONFIG:-/path/to/CMOR_input.json}
OUTDIR=${OUTDIR:-/path/to/cmorized_output${CASE_NAME:+/${CASE_NAME}}}
## one entry per table:
##   "label|table_json|indir|varlist_json|extra fremor run args (optional)"
RUN_TARGETS=(
    "Amon|/path/to/tables/CMIP6_Amon.json|/path/to/pp/atmos_cmip/ts/monthly/5yr|/path/to/varlist_Amon.json|--grid_label gr1 --calendar noleap"
    # "Omon|/path/to/tables/CMIP6_Omon.json|/path/to/pp/ocean_monthly/ts/monthly/5yr|/path/to/varlist_Omon.json|"
)

## ---------------------------- staging ------------------------------
## [env] max table jobs running at once (each recalls from tape then CMORizes);
## keep small to be kind to the tape system. 1 -> strictly serial, 0 -> no limit.
## the limit covers this submission only, unless JOB_QUEUE_FILE is set
MAX_CONCURRENT=${MAX_CONCURRENT:-4}
## [env] file shared by several submissions (e.g. one per case) that each appends
## its job ids to; MAX_CONCURRENT then limits the jobs of all of them together,
## by chaining new jobs behind the still-queued jobs listed there. empty -> off
JOB_QUEUE_FILE=${JOB_QUEUE_FILE:-}
DMGET_BATCH=500       # files per dmget call
STAGE_RETRIES=3       # dmget + verify attempts before giving up
## 1 -> copy staged inputs to node-local ${LOCAL_ROOT} before running CMOR
COPY_TO_LOCAL=0
LOCAL_ROOT='${TMPDIR}' # expanded inside the job, e.g. '/vftmp/${USER}/${SLURM_JOB_ID}'

## ---------------------------- archive ------------------------------
## 1 -> CMORize into a per-table temporary outdir (overriding the yaml's outdir /
## OUTDIR), then move the finished .nc files into ARCHIVE_DIR. MODE=yaml writes
## <outdir>/<component>/<table>/<CMIP dirs>/*.nc; those first two levels are
## dropped, so ARCHIVE_DIR gets <CMIP dirs>/*.nc. CMOR's *.log files in CMOR_tmp
## are moved to the table's logs/ directory
## [env] ARCHIVE and ARCHIVE_DIR. the default ARCHIVE_DIR keeps cases apart; drop
## the CASE_NAME part to collect all cases in one CMIP directory tree
ARCHIVE=${ARCHIVE:-0}
ARCHIVE_DIR=${ARCHIVE_DIR:-/path/to/archive${CASE_NAME:+/${CASE_NAME}}}
## parent of the per-table temporary outdirs (<root>/<table>/outdir).
## empty -> WORK_DIR. set a fixed path to resume with --continue: outputs of a
## failed job are not archived and stay there for the next submission to reuse [env]
ARCHIVE_TMP_ROOT=${ARCHIVE_TMP_ROOT:-}

## ---------------------------- slurm --------------------------------
SLURM_ACCOUNT=         # --account, empty -> default
## each job covers tape recall + CMOR, so JOB_TIME must allow for both
JOB_PARTITION=batch
JOB_TIME=16:00:00
JOB_MEM=16G
JOB_CPUS=1
MAIL_USER=             # empty -> no mail
SBATCH_EXTRA_ARGS=()   # e.g. (--qos=normal --constraint=bigmem)

# ==============================================================================
# END USER CONFIG
# ==============================================================================

DRY_RUN=${DRY_RUN:-0}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
JOB_SCRIPT=${SCRIPT_DIR}/fremor_table_job.sh

HISTORY=''
# hist <text> -> append a timestamped line to ${WORK_DIR}/HISTORY (once it exists)
hist() {
    [[ -n ${HISTORY} ]] || return 0
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "${HISTORY}"
}
die() { echo "ERROR: $*" >&2; hist "  aborted: $*"; exit 1; }

[[ -f ${JOB_SCRIPT} ]] || die "job script not found: ${JOB_SCRIPT}"
[[ ${MODE} == yaml || ${MODE} == run ]] || die "MODE must be yaml or run, got '${MODE}'"
[[ ${MAX_CONCURRENT} =~ ^[0-9]+$ ]] || die "MAX_CONCURRENT must be a non-negative integer"
[[ -z ${CASE_NAME} || ${CASE_NAME} =~ ^[A-Za-z0-9._-]+$ ]] \
    || die "CASE_NAME may only hold letters, digits, '.', '_' and '-', got '${CASE_NAME}'"
# slurm job names: fremor_<CASE_NAME>_<table>, or fremor_<table> without a case
JOB_PREFIX=fremor_${CASE_NAME:+${CASE_NAME}_}
CMD_LINE=$(printf '%q ' "$0" "$@")
# command line: [--continue[=WORK_DIR]] [TABLE ...]
ARG_TABLES=()
for arg in "$@"; do
    case ${arg} in
        --continue)   CONTINUE=1 ;;
        --continue=*) CONTINUE=1; WORK_DIR=${arg#--continue=}
                      WORK_DIR=${WORK_DIR/#\~/${HOME}}
                      [[ -n ${WORK_DIR} ]] || die "--continue= needs a WORK_DIR" ;;
        -*)           die "unknown option: ${arg}" ;;
        *)            ARG_TABLES+=("${arg}") ;;
    esac
done
[[ ${#ARG_TABLES[@]} -gt 0 ]] && TABLES=("${ARG_TABLES[@]}")

# fremor must be importable here too (yaml mode splits the yaml with its python env)
eval "${ENV_SETUP}"
command -v fremor >/dev/null || die "fremor not found after ENV_SETUP"
PYTHON=$(dirname "$(command -v fremor)")/python
[[ -x ${PYTHON} ]] || PYTHON=python3

if [[ ${CONTINUE} != 1 && -n $(ls -A "${WORK_DIR}" 2>/dev/null) ]]; then
    die "WORK_DIR already exists: ${WORK_DIR}
       use --continue=${WORK_DIR} to resume that run, or pick a new WORK_DIR"
fi
if [[ ${CONTINUE} == 1 ]]; then
    [[ -d ${WORK_DIR} ]] || die "CONTINUE=1 needs an existing WORK_DIR, not found: ${WORK_DIR}"
    if [[ ${MODE} == yaml && " ${YAML_EXTRA_ARGS[*]:-} " != *" --continue "* ]]; then
        YAML_EXTRA_ARGS+=(--continue)
    fi
fi
mkdir -p "${WORK_DIR}"
WORK_DIR=$(cd "${WORK_DIR}" && pwd)
echo "work dir: ${WORK_DIR}"

# append-only record of every submission into this WORK_DIR, so rerunning the
# script here (e.g. to resubmit failed tables) keeps the earlier records
HISTORY=${WORK_DIR}/HISTORY
dry=''
[[ ${DRY_RUN} == 1 ]] && dry=' (dry run, nothing submitted)'
resume=''
[[ ${CONTINUE} == 1 ]] && resume=' (continue)'
hist "submit${resume}${dry}: ${CMD_LINE% }"
hist "  cwd: ${PWD}, MODE=${MODE}, case: ${CASE_NAME:-none}, years: ${START:-first}-${STOP:-last}"
if [[ ${MODE} == yaml ]]; then
    hist "  yaml: ${FREMOR_YAML}, extra args: ${YAML_EXTRA_ARGS[*]:-none}"
else
    hist "  exp config: ${EXP_CONFIG}, outdir: ${OUTDIR}"
fi
hist "  slurm: ${JOB_PARTITION}, ${JOB_TIME}, ${JOB_MEM}, ${JOB_CPUS} cpu, max concurrent ${MAX_CONCURRENT}${JOB_QUEUE_FILE:+ (shared via ${JOB_QUEUE_FILE})}"

if [[ ${ARCHIVE} == 1 ]]; then
    mkdir -p "${ARCHIVE_DIR}" || die "could not create ARCHIVE_DIR ${ARCHIVE_DIR}"
    ARCHIVE_DIR=$(cd "${ARCHIVE_DIR}" && pwd)
    ARCHIVE_TMP_ROOT=${ARCHIVE_TMP_ROOT:-${WORK_DIR}}
    mkdir -p "${ARCHIVE_TMP_ROOT}"
    ARCHIVE_TMP_ROOT=$(cd "${ARCHIVE_TMP_ROOT}" && pwd)
    echo "archive dir: ${ARCHIVE_DIR} (temporary outdirs under ${ARCHIVE_TMP_ROOT})"
    hist "  archive: ${ARCHIVE_DIR}, temporary outdirs under ${ARCHIVE_TMP_ROOT}"
fi

# ------------------------------------------------------------------------------
# build the list of per-table targets: LABELS[i] and, for yaml mode, one
# single-table yaml per label (all other table_targets marked disabled: true,
# so named ps_component lookups across targets keep working). with ARCHIVE=1,
# each yaml's outdir points at that table's temporary outdir
# ------------------------------------------------------------------------------
LABELS=()
if [[ ${MODE} == yaml ]]; then
    [[ -f ${FREMOR_YAML} ]] || die "FREMOR_YAML not found: ${FREMOR_YAML}"
    tmp_root=''
    [[ ${ARCHIVE} == 1 ]] && tmp_root=${ARCHIVE_TMP_ROOT}
    table_list=$("${PYTHON}" - "${FREMOR_YAML}" "${WORK_DIR}" "${tmp_root}" "${TABLES[@]}" \
        <<'PYEOF'

import copy, os, sys, yaml
yamlfile, work_dir, tmp_root, wanted = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
with open(yamlfile, encoding='utf-8') as handle:
    doc = yaml.safe_load(handle)
targets = doc['cmor']['table_targets']
enabled = [t['table_name'] for t in targets if not t.get('disabled')]
names = list(dict.fromkeys(wanted or enabled))
missing = [n for n in names if n not in enabled]
if missing:
    sys.exit(f'tables not found (or disabled) in {yamlfile}: {missing}')
for name in names:
    sub = copy.deepcopy(doc)
    for target in sub['cmor']['table_targets']:
        if target['table_name'] != name:
            target['disabled'] = True
    if tmp_root:
        sub['cmor']['directories']['outdir'] = f'{tmp_root}/{name}/outdir'
    out = f'{work_dir}/{name}/fremor_{name}.yaml'
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as handle:
        yaml.safe_dump(sub, handle, sort_keys=False)
    print(name)
PYEOF
    ) || die "could not split ${FREMOR_YAML} into per-table yamls"
    mapfile -t LABELS <<< "${table_list}"
else
    RUN_ENTRIES=()
    for entry in "${RUN_TARGETS[@]}"; do
        label=${entry%%|*}
        if [[ ${#TABLES[@]} -gt 0 ]] && [[ ! " ${TABLES[*]} " == *" ${label} "* ]]; then
            continue
        fi
        LABELS+=("${label}")
        RUN_ENTRIES+=("${entry}")
    done
fi
[[ ${#LABELS[@]} -gt 0 ]] || die "no tables selected"

# CONTINUE=1: keep only tables that are neither finished nor still in the queue
if [[ ${CONTINUE} == 1 ]]; then
    keep_labels=() keep_entries=() finished=() queued=()
    for i in "${!LABELS[@]}"; do
        label=${LABELS[$i]}
        if [[ -e ${WORK_DIR}/${label}/DONE ]]; then
            finished+=("${label}")
            continue
        fi
        prev_job=$(cat "${WORK_DIR}/${label}/JOBID" 2>/dev/null || true)
        if [[ -n ${prev_job} && ${prev_job} != DRYRUN_* ]] \
           && [[ -n $(squeue -h -j "${prev_job}" -o %i 2>/dev/null || true) ]]; then
            queued+=("${label}(${prev_job})")
            continue
        fi
        keep_labels+=("${label}")
        [[ ${MODE} == run ]] && keep_entries+=("${RUN_ENTRIES[$i]}")
    done
    echo "already done (${#finished[@]}): ${finished[*]:-none}"
    echo "still queued/running (${#queued[@]}): ${queued[*]:-none}"
    hist "  skipped, already done (${#finished[@]}): ${finished[*]:-none}"
    hist "  skipped, still queued/running (${#queued[@]}): ${queued[*]:-none}"
    if [[ ${#keep_labels[@]} -eq 0 ]]; then
        echo "nothing left to submit"
        hist "  nothing left to submit"
        exit 0
    fi
    LABELS=("${keep_labels[@]}")
    [[ ${MODE} == run ]] && RUN_ENTRIES=("${keep_entries[@]}")
fi
echo "tables (${#LABELS[@]}): ${LABELS[*]}"
hist "  tables (${#LABELS[@]}): ${LABELS[*]}"

# ------------------------------------------------------------------------------
# submit helpers
# ------------------------------------------------------------------------------
common_sbatch_args() {
    local args=(--parsable)
    [[ -n ${SLURM_ACCOUNT} ]] && args+=(--account="${SLURM_ACCOUNT}")
    [[ -n ${MAIL_USER} ]] && args+=(--mail-user="${MAIL_USER}" --mail-type=FAIL)
    args+=("${SBATCH_EXTRA_ARGS[@]}")
    printf '%s\n' "${args[@]}"
}

# submit <label> <env_file> <dependency or ''> -> prints job id
submit() {
    local label=$1 env_file=$2 dep=$3
    local args
    mapfile -t args < <(common_sbatch_args)
    args+=(--job-name="${JOB_PREFIX}${label}"
           --output="${WORK_DIR}/${label}/logs/%x.%j.out"
           --export=ALL,JOB_ENV="${env_file}"
           --partition="${JOB_PARTITION}" --time="${JOB_TIME}" --mem="${JOB_MEM}"
           --ntasks=1 --cpus-per-task="${JOB_CPUS}")
    [[ -n ${dep} ]] && args+=(--dependency="${dep}")

    if [[ ${DRY_RUN} == 1 ]]; then
        echo "sbatch ${args[*]} ${JOB_SCRIPT}" >&2
        echo "DRYRUN_${label}"
    else
        sbatch "${args[@]}" "${JOB_SCRIPT}"
    fi
}

# still_queued <job id> -> true if the job is pending or running (dry-run ids count)
still_queued() {
    [[ $1 == DRYRUN_* ]] && return 0
    [[ -n $(squeue -h -j "$1" -o %i 2>/dev/null || true) ]]
}

# ------------------------------------------------------------------------------
# per-table: write env file, submit one stage+cmor job. with MAX_CONCURRENT=N,
# job n waits (afterany) for job n-N, so at most N chains run side by side.
# with JOB_QUEUE_FILE, n counts the jobs of earlier submissions listed there too;
# a job that has already left the queue needs no waiting for
# ------------------------------------------------------------------------------
JOB_IDS=()
QUEUE_IDS=()   # earlier submissions' job ids, followed by this one's
if [[ -n ${JOB_QUEUE_FILE} ]]; then
    mkdir -p "$(dirname "${JOB_QUEUE_FILE}")"
    [[ -s ${JOB_QUEUE_FILE} ]] && mapfile -t QUEUE_IDS < "${JOB_QUEUE_FILE}"
fi

for i in "${!LABELS[@]}"; do
    LABEL=${LABELS[$i]}
    TABLE_WORK=${WORK_DIR}/${LABEL}
    mkdir -p "${TABLE_WORK}/logs"
    ENV_FILE=${TABLE_WORK}/job.env

    TABLE_YAML='' TABLE_JSON='' INDIR='' VARLIST='' RUN_ARGS=''
    if [[ ${MODE} == yaml ]]; then
        TABLE_YAML=${TABLE_WORK}/fremor_${LABEL}.yaml
    else
        IFS='|' read -r _ TABLE_JSON INDIR VARLIST RUN_ARGS <<< "${RUN_ENTRIES[$i]}"
    fi

    TMP_OUTDIR=''
    [[ ${ARCHIVE} == 1 ]] && TMP_OUTDIR=${ARCHIVE_TMP_ROOT}/${LABEL}/outdir

    # everything the job needs, safely quoted
    SUBMIT_DIR=${PWD}
    {
        declare -p MODE CASE_NAME LABEL TABLE_WORK SUBMIT_DIR ENV_SETUP START STOP \
                   TABLE_YAML YAML_EXTRA_ARGS PRECHECK POSTCHECK \
                   TABLE_JSON INDIR VARLIST RUN_ARGS EXP_CONFIG OUTDIR \
                   DMGET_BATCH STAGE_RETRIES COPY_TO_LOCAL LOCAL_ROOT \
                   ARCHIVE ARCHIVE_DIR TMP_OUTDIR
    } > "${ENV_FILE}"

    dep=''
    n=${#QUEUE_IDS[@]}
    if (( MAX_CONCURRENT > 0 && n >= MAX_CONCURRENT )); then
        prev_job=${QUEUE_IDS[n - MAX_CONCURRENT]}
        still_queued "${prev_job}" && dep="afterany:${prev_job}"
    fi
    job_id=$(submit "${LABEL}" "${ENV_FILE}" "${dep}") || die "sbatch failed for ${LABEL}"
    JOB_IDS+=("${job_id}")
    QUEUE_IDS+=("${job_id}")
    [[ -n ${JOB_QUEUE_FILE} && ${DRY_RUN} != 1 ]] && echo "${job_id}" >> "${JOB_QUEUE_FILE}"
    # lets a later CONTINUE=1 run tell whether this job is still queued/running
    echo "${job_id}" > "${TABLE_WORK}/JOBID"

    printf '%s\t%s\n' "${LABEL}" "${job_id}"
    hist "  ${LABEL}: job ${job_id}${dep:+ (${dep})}"
done
hist "  submitted ${#JOB_IDS[@]} jobs"

echo "job ids appended to ${HISTORY}"
echo "monitor with: squeue -u ${USER} -o '%.10i %.40j %.9T %.10M %R' | grep ${JOB_PREFIX}"
