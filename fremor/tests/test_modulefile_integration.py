"""
Integration tests for modulefile-driven fremor CLI jobs.
"""

from datetime import date
import os
from pathlib import Path
import shutil
import subprocess
import textwrap

import pytest

from fremor.tests.conftest import CMIP6_TABLE_CONFIG, EXP_CONFIG, ROOTDIR, VARLIST, ncgen


REPO_ROOT = ROOTDIR.parents[2]
MODULEFILES_ROOT = ROOTDIR / 'modulefiles'
MODULE_VERSION = '0.9.8'
MODULEFILE_PATH = MODULEFILES_ROOT / 'fremor' / f'{MODULE_VERSION}.lua'
MODULE_HOOK_SCRIPT = MODULEFILES_ROOT / 'fremor' / MODULE_VERSION / 'fremor.sh'
INPUT_CDL = ROOTDIR / 'reduced_ascii_files' / 'reduced_ocean_monthly_1x1deg.199301-199302.sos.cdl'
INPUT_FILENAME = 'reduced_ocean_monthly_1x1deg.199301-199302.sos.nc'
EXPECTED_OUTPUT_RELATIVE = Path(
    'CMIP6/CMIP6/ISMIP6/PCMDI/PCMDI-test-1-0/piControl-withism/'
    f'r3i1p1f1/Omon/sos/gr/v{date.today().strftime("%Y%m%d")}/'
    'sos_Omon_PCMDI-test-1-0_piControl-withism_r3i1p1f1_gr_199301-199302.nc'
)
SBATCH_STUB = """#!/usr/bin/env python3
from pathlib import Path
import os
import subprocess
import sys


def resolve_path(path_arg, base_dir):
    path = Path(path_arg)
    if path.is_absolute():
        return path
    return base_dir / path


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: sbatch JOB_SCRIPT')

    job_script = Path(sys.argv[1]).resolve()
    job_id = os.environ.get('FREMOR_TEST_SBATCH_JOB_ID', '4242')
    stdout_path = job_script.parent / f'slurm-{job_id}.out'
    stderr_path = job_script.parent / f'slurm-{job_id}.err'

    for line in job_script.read_text(encoding='utf-8').splitlines():
        if line.startswith('#SBATCH --output='):
            stdout_path = resolve_path(line.split('=', 1)[1].strip(), job_script.parent)
        elif line.startswith('#SBATCH --error='):
            stderr_path = resolve_path(line.split('=', 1)[1].strip(), job_script.parent)

    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    job = subprocess.run(
        [str(job_script)],
        capture_output=True,
        check=False,
        cwd=job_script.parent,
        env=os.environ.copy(),
        text=True,
    )
    stdout_path.write_text(job.stdout, encoding='utf-8')
    stderr_path.write_text(job.stderr, encoding='utf-8')

    print(f'Submitted batch job {job_id}')
    raise SystemExit(job.returncode)


if __name__ == '__main__':
    main()
"""


def _require_binary(binary_name):
    binary_path = shutil.which(binary_name)
    if binary_path is None:
        pytest.skip(f'modulefile integration test requires {binary_name}')
    return Path(binary_path)


@pytest.fixture(scope='module')
def modulefile_runtime():
    """Return the shell/runtime paths required by the modulefile integration tests."""
    _require_binary('ncgen3')
    _require_binary('tcsh')
    conda_exe = _require_binary('conda')

    conda_env = os.environ.get('CONDA_PREFIX')
    if conda_env is None:
        pytest.skip('modulefile integration test requires an activated conda environment')

    conda_base = subprocess.run(
        [str(conda_exe), 'info', '--base'],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    conda_sh = Path(conda_base) / 'etc' / 'profile.d' / 'conda.sh'
    if not conda_sh.exists():
        pytest.skip(f'modulefile integration test could not find conda.sh at {conda_sh}')

    lmod_init = {
        'bash': Path('/usr/share/lmod/lmod/init/bash'),
        'tcsh': Path('/usr/share/lmod/lmod/init/tcsh'),
    }
    for shell_name, init_path in lmod_init.items():
        if not init_path.exists():
            pytest.skip(f'modulefile integration test requires Lmod init script for {shell_name}')

    for required_path in (MODULEFILE_PATH, MODULE_HOOK_SCRIPT, Path(CMIP6_TABLE_CONFIG)):
        if not required_path.exists():
            pytest.skip(f'modulefile integration test requires {required_path}')

    return {
        'conda_env': Path(conda_env),
        'conda_sh': conda_sh,
        'lmod_init': lmod_init,
    }


def _write_sbatch_stub(sbatch_path):
    sbatch_path.write_text(SBATCH_STUB, encoding='utf-8')
    sbatch_path.chmod(0o755)


def _write_job_script(shell_name, shell_root, runtime, job_out, job_err):
    if shell_name == 'bash':
        script_path = shell_root / 'run_script.sh'
        script_text = textwrap.dedent(f"""\
            #!/bin/bash
            #SBATCH --output={job_out}
            #SBATCH --error={job_err}
            set -euo pipefail
            shopt -s expand_aliases
            source "{runtime['lmod_init']['bash']}"
            module use "{MODULEFILES_ROOT}"
            module load fremor/{MODULE_VERSION}
            command -V fremor
            cd "{REPO_ROOT}"
            fremor -vv run \\
              -d "{shell_root / 'input'}" \\
              -l "{Path(VARLIST)}" \\
              -r "{Path(CMIP6_TABLE_CONFIG)}" \\
              -p "{shell_root / 'CMOR_input_example.json'}" \\
              -o "{shell_root / 'output'}" \\
              --run_one \\
              -g gr \\
              --grid_desc "regridded to FOO grid from native" \\
              --nom_res "10000 km" \\
              --calendar julian
        """)
    else:
        script_path = shell_root / 'run_script.tcsh'
        script_text = textwrap.dedent(f"""\
            #!/bin/tcsh
            #SBATCH --output={job_out}
            #SBATCH --error={job_err}
            source "{runtime['lmod_init']['tcsh']}"
            module use "{MODULEFILES_ROOT}"
            module load fremor/{MODULE_VERSION}
            which fremor
            cd "{REPO_ROOT}"
            fremor -vv run \\
              -d "{shell_root / 'input'}" \\
              -l "{Path(VARLIST)}" \\
              -r "{Path(CMIP6_TABLE_CONFIG)}" \\
              -p "{shell_root / 'CMOR_input_example.json'}" \\
              -o "{shell_root / 'output'}" \\
              --run_one \\
              -g gr \\
              --grid_desc "regridded to FOO grid from native" \\
              --nom_res "10000 km" \\
              --calendar julian
        """)

    script_path.write_text(script_text, encoding='utf-8')
    script_path.chmod(0o755)
    return script_path


@pytest.mark.parametrize('shell_name', ['bash', 'tcsh'])
def test_modulefile_sbatch_job_logs_stay_on_stderr(tmp_path, modulefile_runtime, shell_name):
    """
    Run a module-loaded fremor job through an sbatch-style wrapper for both bash and tcsh.
    """
    shell_root = tmp_path / shell_name
    shell_root.mkdir()
    (shell_root / 'input').mkdir()
    (shell_root / 'output').mkdir()

    input_file = shell_root / 'input' / INPUT_FILENAME
    ncgen(INPUT_CDL, input_file)
    shutil.copyfile(EXP_CONFIG, shell_root / 'CMOR_input_example.json')

    sbatch_dir = shell_root / 'bin'
    sbatch_dir.mkdir()
    _write_sbatch_stub(sbatch_dir / 'sbatch')

    job_out = shell_root / f'{shell_name}.out'
    job_err = shell_root / f'{shell_name}.err'
    job_script = _write_job_script(shell_name, shell_root, modulefile_runtime, job_out, job_err)

    shell_env = os.environ.copy()
    shell_env['FREMOR_TEST_CONDA_ENV'] = str(modulefile_runtime['conda_env'])
    shell_env['FREMOR_TEST_CONDA_SH'] = str(modulefile_runtime['conda_sh'])
    shell_env['FREMOR_TEST_SBATCH_JOB_ID'] = f'42{shell_name}'
    shell_env['PATH'] = f"{sbatch_dir}{os.pathsep}{shell_env['PATH']}"

    job = subprocess.run(
        ['sbatch', str(job_script)],
        capture_output=True,
        check=False,
        cwd=shell_root,
        env=shell_env,
        text=True,
    )

    assert job.returncode == 0, job.stderr
    assert job.stdout.strip() == f'Submitted batch job 42{shell_name}'
    assert job_out.exists()
    assert job_err.exists()

    stdout_text = job_out.read_text(encoding='utf-8')
    stderr_text = job_err.read_text(encoding='utf-8')
    expected_alias_target = str(MODULE_HOOK_SCRIPT)

    assert expected_alias_target in stdout_text
    assert 'aliased' in stdout_text
    assert '[DEBUG:' not in stdout_text
    assert 'cmor is opening: json_exp_config' not in stdout_text

    assert '[DEBUG:' in stderr_text
    assert 'cmor is opening: json_exp_config' in stderr_text
    assert 'returned by cmor.close: filename =' in stderr_text
    assert expected_alias_target not in stderr_text

    expected_output = shell_root / 'output' / EXPECTED_OUTPUT_RELATIVE
    assert expected_output.exists()
