#!/bin/bash
# ==============================================================================
# fremor_submit_tables.sh -- split a fremor workflow into one slurm job pair per
# MIP table and submit them with sbatch.
#
# For every MIP table this submits:
#   1. a STAGE job : list the table's input files, verify they exist, dmget them
#                    from tape to disk and verify (dmls) they are disk-resident
#   2. a CMOR  job : depends on (1) with afterok, re-checks residency, then runs
#                    `fremor yaml` (MODE=yaml) or `fremor run` (MODE=run)
#
# Run this on a login / analysis node (NOT inside sbatch):
#   ./fremor_submit_tables.sh                 # all tables from the config below
#   ./fremor_submit_tables.sh Amon Omon       # only these tables (overrides TABLES)
#   DRY_RUN=1 ./fremor_submit_tables.sh       # print sbatch commands, submit nothing
#
# The per-table job body lives in fremor_table_job.sh (same directory).
# ==============================================================================
set -euo pipefail

# ==============================================================================
# USER CONFIG -- edit this block
# ==============================================================================

## how to make `fremor` available inside the batch jobs (eval'd in each job)
ENV_SETUP='module load fremor'
#ENV_SETUP='source /path/to/miniforge3/etc/profile.d/conda.sh && conda activate fremor'

## workflow mode: "yaml" -> fremor yaml, "run" -> fremor run
MODE=yaml

## scratch area for per-table yamls, file lists, env files and slurm logs
WORK_DIR=${HOME}/fremor_jobs/$(date +%Y%m%d_%H%M%S)

## optional year bounds (YYYY), passed as --start/--stop. empty -> use yaml / all
START=
STOP=

## ---------------------------- MODE=yaml ----------------------------
## self-contained CMOR yaml (as written by `fremor config`)
FREMOR_YAML=/path/to/cmor.yaml
## tables to process. empty -> every enabled table_target in FREMOR_YAML
TABLES=()
## extra flags for `fremor yaml`, e.g. (--run_strict)
YAML_EXTRA_ARGS=()
## run `fremor check <table> --check-inputs --check-dims` in the stage job (1=yes)
PRECHECK=1
## run `fremor check <table> --check-outputs` after the cmor job (1=yes)
POSTCHECK=1

## ---------------------------- MODE=run -----------------------------
## experiment config json and CMOR output root, shared by all targets
EXP_CONFIG=/path/to/CMOR_input.json
OUTDIR=/path/to/cmorized_output
## one entry per table:
##   "label|table_json|indir|varlist_json|extra fremor run args (optional)"
RUN_TARGETS=(
    "Amon|/path/to/tables/CMIP6_Amon.json|/path/to/pp/atmos_cmip/ts/monthly/5yr|/path/to/varlist_Amon.json|--grid_label gr1 --calendar noleap"
    # "Omon|/path/to/tables/CMIP6_Omon.json|/path/to/pp/ocean_monthly/ts/monthly/5yr|/path/to/varlist_Omon.json|"
)

## ---------------------------- staging ------------------------------
SKIP_STAGE=0          # 1 -> no stage job; cmor job still checks/dmgets inputs
STAGE_ONLY=0          # 1 -> submit stage jobs only
SERIAL_STAGE=1        # 1 -> stage jobs run one after another (be kind to the tape system)
SERIAL_CMOR=0         # 1 -> cmor jobs run one after another
DMGET_BATCH=500       # files per dmget call
STAGE_RETRIES=3       # dmget + verify attempts before giving up
## 1 -> copy staged inputs to node-local ${LOCAL_ROOT} before running CMOR
COPY_TO_LOCAL=0
LOCAL_ROOT='${TMPDIR}' # expanded inside the job, e.g. '/vftmp/${USER}/${SLURM_JOB_ID}'

## ---------------------------- slurm --------------------------------
SLURM_ACCOUNT=         # --account, empty -> default
STAGE_PARTITION=batch
STAGE_TIME=04:00:00
STAGE_MEM=2G
CMOR_PARTITION=batch
CMOR_TIME=12:00:00
CMOR_MEM=16G
CMOR_CPUS=1
MAIL_USER=             # empty -> no mail
SBATCH_EXTRA_ARGS=()   # e.g. (--qos=normal --constraint=bigmem)

# ==============================================================================
# END USER CONFIG
# ==============================================================================

DRY_RUN=${DRY_RUN:-0}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
JOB_SCRIPT=${SCRIPT_DIR}/fremor_table_job.sh

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -f ${JOB_SCRIPT} ]] || die "job script not found: ${JOB_SCRIPT}"
[[ ${MODE} == yaml || ${MODE} == run ]] || die "MODE must be yaml or run, got '${MODE}'"
[[ $# -gt 0 ]] && TABLES=("$@")

# fremor must be importable here too (yaml mode splits the yaml with its python env)
eval "${ENV_SETUP}"
command -v fremor >/dev/null || die "fremor not found after ENV_SETUP"
PYTHON=$(dirname "$(command -v fremor)")/python
[[ -x ${PYTHON} ]] || PYTHON=python3

mkdir -p "${WORK_DIR}"
WORK_DIR=$(cd "${WORK_DIR}" && pwd)
echo "work dir: ${WORK_DIR}"

# ------------------------------------------------------------------------------
# build the list of per-table targets: LABELS[i] and, for yaml mode, one
# single-table yaml per label (all other table_targets marked disabled: true,
# so named ps_component lookups across targets keep working)
# ------------------------------------------------------------------------------
LABELS=()
if [[ ${MODE} == yaml ]]; then
    [[ -f ${FREMOR_YAML} ]] || die "FREMOR_YAML not found: ${FREMOR_YAML}"
    "${PYTHON}" - "${FREMOR_YAML}" "${WORK_DIR}" "${TABLES[@]}" > "${WORK_DIR}/tables.txt" <<'PYEOF' \
        || die "could not split ${FREMOR_YAML} into per-table yamls"
import copy, os, sys, yaml
yamlfile, work_dir, wanted = sys.argv[1], sys.argv[2], sys.argv[3:]
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
    out = f'{work_dir}/{name}/fremor_{name}.yaml'
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as handle:
        yaml.safe_dump(sub, handle, sort_keys=False)
    print(name)
PYEOF
    mapfile -t LABELS < "${WORK_DIR}/tables.txt"
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
echo "tables (${#LABELS[@]}): ${LABELS[*]}"

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

# submit <step> <label> <env_file> <dependency or ''> -> prints job id
submit() {
    local step=$1 label=$2 env_file=$3 dep=$4
    local args
    mapfile -t args < <(common_sbatch_args)
    args+=(--job-name="fremor_${step}_${label}"
           --output="${WORK_DIR}/${label}/logs/%x.%j.out"
           --export=ALL,JOB_ENV="${env_file}",STEP="${step}")
    if [[ ${step} == stage ]]; then
        args+=(--partition="${STAGE_PARTITION}" --time="${STAGE_TIME}" --mem="${STAGE_MEM}" --ntasks=1)
    else
        args+=(--partition="${CMOR_PARTITION}" --time="${CMOR_TIME}" --mem="${CMOR_MEM}"
               --ntasks=1 --cpus-per-task="${CMOR_CPUS}")
    fi
    [[ -n ${dep} ]] && args+=(--dependency="${dep}" --kill-on-invalid-dep=yes)

    if [[ ${DRY_RUN} == 1 ]]; then
        echo "sbatch ${args[*]} ${JOB_SCRIPT}" >&2
        echo "DRYRUN_${step}_${label}"
    else
        sbatch "${args[@]}" "${JOB_SCRIPT}"
    fi
}

# ------------------------------------------------------------------------------
# per-table: write env file, submit stage + cmor
# ------------------------------------------------------------------------------
SUMMARY=${WORK_DIR}/submitted_jobs.tsv
printf 'label\tstage_job\tcmor_job\n' > "${SUMMARY}"
prev_stage='' prev_cmor=''

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

    # everything the job needs, safely quoted
    SUBMIT_DIR=${PWD}
    {
        declare -p MODE LABEL TABLE_WORK SUBMIT_DIR ENV_SETUP START STOP \
                   TABLE_YAML YAML_EXTRA_ARGS PRECHECK POSTCHECK \
                   TABLE_JSON INDIR VARLIST RUN_ARGS EXP_CONFIG OUTDIR \
                   DMGET_BATCH STAGE_RETRIES COPY_TO_LOCAL LOCAL_ROOT
    } > "${ENV_FILE}"

    stage_id=''
    if [[ ${SKIP_STAGE} != 1 ]]; then
        dep=''
        [[ ${SERIAL_STAGE} == 1 && -n ${prev_stage} ]] && dep="afterany:${prev_stage}"
        stage_id=$(submit stage "${LABEL}" "${ENV_FILE}" "${dep}")
        prev_stage=${stage_id}
    fi

    cmor_id='-'
    if [[ ${STAGE_ONLY} != 1 ]]; then
        deps=()
        [[ -n ${stage_id} ]] && deps+=("afterok:${stage_id}")
        [[ ${SERIAL_CMOR} == 1 && -n ${prev_cmor} ]] && deps+=("afterany:${prev_cmor}")
        dep=$(IFS=,; echo "${deps[*]}")
        cmor_id=$(submit cmor "${LABEL}" "${ENV_FILE}" "${dep}")
        prev_cmor=${cmor_id}
    fi

    printf '%s\t%s\t%s\n' "${LABEL}" "${stage_id:--}" "${cmor_id}" | tee -a "${SUMMARY}"
done

echo "job ids written to ${SUMMARY}"
echo "monitor with: squeue -u ${USER} -o '%.10i %.40j %.9T %.10M %R' | grep fremor_"
