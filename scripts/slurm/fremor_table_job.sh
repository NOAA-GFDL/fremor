#!/bin/bash
# ==============================================================================
# fremor_table_job.sh -- slurm job body for ONE MIP table. Submitted by
# fremor_submit_tables.sh; not meant to be edited per run (edit the submitter).
#
# Environment passed by sbatch --export:
#   JOB_ENV : env file written by the submitter (MODE, LABEL, TABLE_YAML, ...)
#   STEP    : "stage" -> list inputs, check existence, dmget, verify on disk
#             "cmor"  -> re-verify inputs on disk, then fremor yaml / fremor run
#
# The #SBATCH lines are fallbacks only; the submitter overrides them.
# ==============================================================================
#SBATCH --ntasks=1
#SBATCH --time=04:00:00
#SBATCH --output=fremor_%x.%j.out

set -euo pipefail

: "${JOB_ENV:?JOB_ENV not set, submit via fremor_submit_tables.sh}"
: "${STEP:?STEP not set (stage|cmor)}"
# shellcheck source=/dev/null
source "${JOB_ENV}"   # sourced at top level so declared arrays stay global

log() { echo "[$(date '+%F %T')] [${STEP}:${LABEL}] $*"; }
die() { log "ERROR: $*" >&2; exit 1; }

log "host=$(hostname) job=${SLURM_JOB_ID:-none} mode=${MODE}"
cd "${SUBMIT_DIR}"    # relative paths inside the yaml resolve from here
set +u; eval "${ENV_SETUP}"; set -u
command -v fremor >/dev/null || die "fremor not found after ENV_SETUP"
PYTHON=$(dirname "$(command -v fremor)")/python
[[ -x ${PYTHON} ]] || PYTHON=python3

INPUT_LIST=${TABLE_WORK}/input_files.txt
YEAR_ARGS=()
[[ -n ${START} ]] && YEAR_ARGS+=(--start "${START}")
[[ -n ${STOP} ]] && YEAR_ARGS+=(--stop "${STOP}")

# ------------------------------------------------------------------------------
# input discovery: write the table's input files (one per line) to INPUT_LIST
# ------------------------------------------------------------------------------
list_inputs() {
    if [[ ${MODE} == yaml ]]; then
        # fremor stage --dry_run prints every mapped input (+ ps companions),
        # then a "Would stage N files" summary line
        fremor stage -y "${TABLE_YAML}" "${YEAR_ARGS[@]}" --dry_run \
            | grep -v '^Would stage' > "${INPUT_LIST}"
    else
        # same selection rules as fremor stage, for a single fremor run target
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
print('\n'.join(sorted(map(str, files))))
PYEOF
    fi
    sed -i '/^$/d' "${INPUT_LIST}"
    [[ -s ${INPUT_LIST} ]] || die "no input files found for ${LABEL}"
    log "found $(wc -l < "${INPUT_LIST}") input files -> ${INPUT_LIST}"
}

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
OFFLINE_LIST=${TABLE_WORK}/offline_files.txt
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

# optionally copy staged inputs to node-local storage and point the job at it
copy_to_local() {
    local local_root
    local_root=$(eval echo "${LOCAL_ROOT}")/fremor_${LABEL}
    mkdir -p "${local_root}"
    log "copying inputs to ${local_root}"
    if [[ ${MODE} == yaml ]]; then
        local pp_dir
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
    else
        xargs -a "${INPUT_LIST}" -d '\n' cp -p -t "${local_root}"
        INDIR=${local_root}
    fi
    log "copied $(du -sh "${local_root}" | cut -f1)"
}

# ------------------------------------------------------------------------------
# steps
# ------------------------------------------------------------------------------
do_stage() {
    list_inputs
    check_exist
    stage_inputs
    if [[ ${MODE} == yaml && ${PRECHECK} == 1 ]]; then
        log "fremor check --check-inputs --check-dims"
        fremor check "${LABEL}" -y "${TABLE_YAML}" --check-inputs --check-dims \
            -o "${TABLE_WORK}/precheck_report.json" \
            || log "WARNING: fremor check reported problems, see log above"
    fi
    touch "${TABLE_WORK}/STAGED"
}

do_cmor() {
    # inputs may have been purged from the disk cache while this job was queued
    [[ -s ${INPUT_LIST} ]] || list_inputs
    check_exist
    stage_inputs
    [[ ${COPY_TO_LOCAL} == 1 ]] && copy_to_local

    local fremor_log=${TABLE_WORK}/fremor_${LABEL}.log
    local rc=0
    if [[ ${MODE} == yaml ]]; then
        log "fremor yaml -y ${TABLE_YAML} ${YEAR_ARGS[*]} ${YAML_EXTRA_ARGS[*]}"
        fremor -v -l "${fremor_log}" yaml -y "${TABLE_YAML}" \
            "${YEAR_ARGS[@]}" "${YAML_EXTRA_ARGS[@]}" || rc=$?
    else
        local extra=()
        read -r -a extra <<< "${RUN_ARGS}"
        log "fremor run -d ${INDIR} -l ${VARLIST} -r ${TABLE_JSON} ${YEAR_ARGS[*]} ${extra[*]}"
        fremor -v -l "${fremor_log}" run \
            -d "${INDIR}" -l "${VARLIST}" -r "${TABLE_JSON}" \
            -p "${EXP_CONFIG}" -o "${OUTDIR}" \
            "${YEAR_ARGS[@]}" "${extra[@]}" || rc=$?
    fi
    [[ ${rc} -eq 0 ]] || die "fremor exited with ${rc}, see ${fremor_log}"

    if [[ ${MODE} == yaml && ${POSTCHECK} == 1 ]]; then
        log "fremor check --check-outputs"
        # checks the original per-table yaml, whose outdir is unchanged by copy_to_local
        fremor check "${LABEL}" -y "${TABLE_WORK}/fremor_${LABEL}.yaml" --check-outputs \
            -o "${TABLE_WORK}/postcheck_report.json" \
            || log "WARNING: fremor check reported problems, see log above"
    fi
    touch "${TABLE_WORK}/DONE"
    log "done"
}

case ${STEP} in
    stage) do_stage ;;
    cmor)  do_cmor ;;
    *)     die "unknown STEP '${STEP}'" ;;
esac
