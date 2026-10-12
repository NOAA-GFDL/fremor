#!/bin/bash
set -euo pipefail
user_name="${USER:-${LOGNAME:-$(id -un)}}"
export USER="${user_name}"
export LOGNAME="${LOGNAME:-${user_name}}"
set +u
source "${FREMOR_TEST_CONDA_SH:-/opt/conda/etc/profile.d/conda.sh}"
conda activate "${FREMOR_TEST_CONDA_ENV:-/opt/conda/envs/fremor}"
set -u
exec fremor "$@"
