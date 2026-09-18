#!/bin/bash
set -euo pipefail
source "${FREMOR_TEST_CONDA_SH:?}"
conda activate "${FREMOR_TEST_CONDA_ENV:?}"
exec fremor "$@"
