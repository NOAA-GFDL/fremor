#!/bin/bash
set -euo pipefail
source "${FREMOR_TEST_CONDA_SH:-/opt/conda/etc/profile.d/conda.sh}"
conda activate "${FREMOR_TEST_CONDA_ENV:-/opt/conda/envs/fremor}"
exec fremor "$@"
