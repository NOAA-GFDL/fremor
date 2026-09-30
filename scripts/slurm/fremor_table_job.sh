#!/bin/bash
# ==============================================================================
# fremor_table_job.sh -- slurm job body for ONE MIP table. Submitted by
# fremor_submit_tables.sh; not meant to be edited per run (edit the submitter).
#
# Stages and CMORizes in the same job, so recalled files are processed right
# away instead of sitting in the disk cache (and risking a purge) while a
# separate CMOR job waits in the queue:
#   1. list the table's input files and check they exist
#   2. dmget offline files from tape and verify (dmls) they are disk-resident
#   3. run `fremor yaml` (MODE=yaml) or `fremor run` (MODE=run)
#   4. with ARCHIVE=1: move the CMORized .nc files from the temporary outdir
#      into ARCHIVE_DIR, and CMOR's log files into the table's logs/ directory
#
# Environment passed by sbatch --export:
#   JOB_ENV : env file written by the submitter (MODE, LABEL, TABLE_YAML, ...)
#
# The #SBATCH lines are fallbacks only; the submitter overrides them.
# ==============================================================================
#SBATCH --ntasks=1
#SBATCH --time=16:00:00
#SBATCH --output=fremor_%x.%j.out

set -euo pipefail

: "${JOB_ENV:?JOB_ENV not set, submit via fremor_submit_tables.sh}"
# shellcheck source=/dev/null
source "${JOB_ENV}"   # sourced at top level so declared arrays stay global

STEP=stage
log() { echo "[$(date '+%F %T')] [${STEP}:${CASE_NAME:+${CASE_NAME}/}${LABEL}] $*"; }
die() { log "ERROR: $*" >&2; exit 1; }

log "host=$(hostname) job=${SLURM_JOB_ID:-none} mode=${MODE}"
# markers from an earlier submission into this WORK_DIR no longer apply
rm -f "${TABLE_WORK}/STAGED" "${TABLE_WORK}/DONE"
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
# archiving (ARCHIVE=1). the temporary outdir holds
#   MODE=yaml: <tmp>/<component>/<table>/<CMIP dirs>/*.nc  (+ .../CMOR_tmp/)
#   MODE=run : <tmp>/<CMIP dirs>/*.nc                      (+ <tmp>/CMOR_tmp/)
# ARCHIVE_LEVELS is how many leading directories to drop so only <CMIP dirs> remain
# ------------------------------------------------------------------------------
ARCHIVE_LEVELS=0
[[ ${MODE} == yaml ]] && ARCHIVE_LEVELS=2

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
            -p "${EXP_CONFIG}" -o "${TMP_OUTDIR:-${OUTDIR}}" \
            "${YEAR_ARGS[@]}" "${extra[@]}" || rc=$?
    fi
    # keep CMOR's logs even when fremor failed, they hold the real error messages
    [[ ${ARCHIVE} == 1 ]] && collect_cmor_logs
    [[ ${rc} -eq 0 ]] || die "fremor exited with ${rc}, see ${fremor_log}"

    if [[ ${MODE} == yaml && ${POSTCHECK} == 1 ]]; then
        log "fremor check --check-outputs"
        # checks the original per-table yaml, whose outdir is unchanged by copy_to_local
        fremor check "${LABEL}" -y "${TABLE_WORK}/fremor_${LABEL}.yaml" --check-outputs \
            -o "${TABLE_WORK}/postcheck_report.json" \
            || log "WARNING: fremor check reported problems, see log above"
    fi
    # after the post-check, which looks for outputs in the (temporary) outdir
    if [[ ${ARCHIVE} == 1 ]]; then
        STEP=archive
        archive_outputs
    fi
    touch "${TABLE_WORK}/DONE"
    log "done"
}

# stage then cmor back to back, so recalled files are used before they can be purged
do_stage
STEP=cmor
do_cmor
