"""
Integration tests for modulefile-driven fremor CLI jobs.
"""

from datetime import date
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import uuid

import pytest

from fremor.tests.conftest import CMIP6_TABLE_CONFIG, EXP_CONFIG, ROOTDIR, VARLIST, ncgen


REPO_ROOT = ROOTDIR.parents[2]
MODULEFILES_ROOT = ROOTDIR / 'modulefiles'
MODULE_VERSION = '0.9.8'
MODULEFILE_PATH = MODULEFILES_ROOT / 'fremor' / f'{MODULE_VERSION}.lua'
MODULE_HOOK_SCRIPT = MODULEFILES_ROOT / 'fremor' / MODULE_VERSION / 'fremor.sh'
INPUT_CDL = ROOTDIR / 'reduced_ascii_files' / 'reduced_ocean_monthly_1x1deg.199301-199302.sos.cdl'
INPUT_FILENAME = 'reduced_ocean_monthly_1x1deg.199301-199302.sos.nc'
CLI_LOGFILE_FRAGMENT = 'fre_file_handler added to base_fre_logger'
CLI_DEBUG_FRAGMENT = 'click entry-point function call done.'
CMOR_OPEN_FRAGMENT = 'cmor is opening: json_exp_config'
CMOR_CLOSE_FRAGMENT = 'returned by cmor.close: filename ='
RUN_USAGE_FRAGMENT = 'Usage: fremor run [OPTIONS]'
RUN_ERROR_FRAGMENT = "Error: Missing option '-d' / '--indir'."
PORTABLE_ENV_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
EXPECTED_OUTPUT_RELATIVE = Path(
    'CMIP6/CMIP6/ISMIP6/PCMDI/PCMDI-test-1-0/piControl-withism/'
    f'r3i1p1f1/Omon/sos/gr/v{date.today().strftime("%Y%m%d")}/'
    'sos_Omon_PCMDI-test-1-0_piControl-withism_r3i1p1f1_gr_199301-199302.nc'
)
MODULEFILE_JOB_CASES = (
    {
        'name': 'verbose-info',
        'cli_args': ['-v', 'run'],
        'include_required_run_args': True,
        'expect_success': True,
        'expect_output': True,
        'expect_stderr_contains': ['[ INFO:', CMOR_OPEN_FRAGMENT, CMOR_CLOSE_FRAGMENT],
        'expect_stderr_not_contains': ['[DEBUG:', CLI_LOGFILE_FRAGMENT],
        'expect_stdout_not_contains': ['[ INFO:', '[DEBUG:', CMOR_OPEN_FRAGMENT, CMOR_CLOSE_FRAGMENT],
    },
    {
        'name': 'verbose-debug',
        'cli_args': ['-vv', 'run'],
        'include_required_run_args': True,
        'expect_success': True,
        'expect_output': True,
        'expect_stderr_contains': ['[DEBUG:', CLI_DEBUG_FRAGMENT, '[ INFO:', CMOR_OPEN_FRAGMENT, CMOR_CLOSE_FRAGMENT],
        'expect_stderr_not_contains': [CLI_LOGFILE_FRAGMENT],
        'expect_stdout_not_contains': ['[ INFO:', '[DEBUG:', CMOR_OPEN_FRAGMENT, CMOR_CLOSE_FRAGMENT],
    },
    {
        'name': 'quiet',
        'cli_args': ['-q', 'run'],
        'include_required_run_args': True,
        'expect_success': True,
        'expect_output': True,
        'expect_stderr_empty': False,
        'expect_stderr_contains': ['\n', '! ------\n', '! All files were closed successfully. \n','! ------\n', '! \n'],
        'expect_stdout_not_contains': ['[ INFO:', '[DEBUG:', CMOR_OPEN_FRAGMENT, CMOR_CLOSE_FRAGMENT],
    },
    {
        'name': 'logfile',
        'cli_args': ['-l', '{log_path}', 'run'],
        'include_required_run_args': True,
        'expect_success': True,
        'expect_output': True,
        'expect_log_file': True,
        'expect_stderr_contains': ['[WARNING:', 'run_one_mode is True!!!!'],
        'expect_stderr_not_contains': ['[ INFO:', '[DEBUG:', CLI_LOGFILE_FRAGMENT],
        'expect_log_contains': ['[WARNING:', 'cmor_mixer.py', 'run_one_mode is True!!!!'],
        'expect_log_not_contains': ['[ INFO:', '[DEBUG:', CLI_LOGFILE_FRAGMENT],
        'expect_stdout_not_contains': ['[ INFO:', '[DEBUG:', CMOR_OPEN_FRAGMENT, CMOR_CLOSE_FRAGMENT],
    },
    {
        'name': 'error',
        'cli_args': ['-q', 'run'],
        'include_required_run_args': False,
        'expect_success': False,
        'expect_output': False,
        'expect_stderr_contains': [RUN_USAGE_FRAGMENT, RUN_ERROR_FRAGMENT],
        'expect_stderr_not_contains': ['[ INFO:', '[DEBUG:', '[WARNING:', CMOR_OPEN_FRAGMENT, CMOR_CLOSE_FRAGMENT],
        'expect_stdout_not_contains': ['[ INFO:', '[DEBUG:', CMOR_OPEN_FRAGMENT, CMOR_CLOSE_FRAGMENT],
    },
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


def _skip_or_fail(message):
    if os.environ.get('FREMOR_TEST_REAL_SLURM') == '1':
        pytest.fail(message)
    pytest.skip(message)


def _find_lmod_init(shell_name):
    override = os.environ.get(f'FREMOR_TEST_LMOD_INIT_{shell_name.upper()}')
    if override:
        override_path = Path(override)
        if override_path.exists():
            return override_path

    conda_prefix = os.environ.get('CONDA_PREFIX')
    if conda_prefix:
        prefix_path = Path(conda_prefix)
        for candidate in sorted(prefix_path.glob(f'lmod/*/init/{shell_name}')):
            if candidate.exists():
                return candidate
        share_candidate = prefix_path / 'share' / 'lmod' / 'lmod' / 'init' / shell_name
        if share_candidate.exists():
            return share_candidate

    system_candidate = Path('/usr/local/lmod/lmod/init') / shell_name
    if system_candidate.exists():
        return system_candidate

    _skip_or_fail(f'modulefile integration test could not find Lmod init for {shell_name}')
    return None


def _require_binary(binary_name):
    binary_path = shutil.which(binary_name)
    if binary_path is None:
        _skip_or_fail(f'modulefile integration test requires {binary_name}')
    return Path(binary_path)


@pytest.fixture(scope='module')
def modulefile_runtime():
    """Return the shell/runtime paths required by the modulefile integration tests."""
    _require_binary('ncgen3')
    tcsh_path = _require_binary('tcsh')
    conda_exe = _require_binary('conda')

    conda_env = os.environ.get('CONDA_PREFIX')
    if conda_env is None:
        _skip_or_fail('modulefile integration test requires an activated conda environment')

    conda_base = subprocess.run(
        [str(conda_exe), 'info', '--base'],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    conda_sh = Path(conda_base) / 'etc' / 'profile.d' / 'conda.sh'
    if not conda_sh.exists():
        _skip_or_fail(f'modulefile integration test could not find conda.sh at {conda_sh}')

    lmod_init = {
        'bash': _find_lmod_init('bash'),
        'tcsh': _find_lmod_init('tcsh'),
    }

    for required_path in (MODULEFILE_PATH, MODULE_HOOK_SCRIPT, Path(CMIP6_TABLE_CONFIG)):
        if not required_path.exists():
            _skip_or_fail(f'modulefile integration test requires {required_path}')

    return {
        'conda_env': Path(conda_env),
        'conda_sh': conda_sh,
        'lmod_init': lmod_init,
        'tcsh': tcsh_path,
    }


def _write_sbatch_stub(sbatch_path):
    sbatch_path.write_text(SBATCH_STUB, encoding='utf-8')
    sbatch_path.chmod(0o755)


def _prepare_job_workspace(shell_root):
    shell_root.mkdir(parents=True, exist_ok=True)
    (shell_root / 'input').mkdir(exist_ok=True)
    (shell_root / 'output').mkdir(exist_ok=True)
    ncgen(INPUT_CDL, shell_root / 'input' / INPUT_FILENAME)
    shutil.copyfile(EXP_CONFIG, shell_root / 'CMOR_input_example.json')


def _shell_join(command_args):
    return ' '.join(shlex.quote(arg) for arg in command_args)


def _log_path(shell_root):
    return shell_root / 'LOGFILE.log'


def _build_shell_env(runtime, job_id, sbatch_dir=None):
    env = {
        name: value
        for name, value in os.environ.items()
        if PORTABLE_ENV_NAME.fullmatch(name)
    }
    env['FREMOR_TEST_CONDA_ENV'] = str(runtime['conda_env'])
    env['FREMOR_TEST_CONDA_SH'] = str(runtime['conda_sh'])
    env['FREMOR_TEST_SBATCH_JOB_ID'] = job_id
    if sbatch_dir is not None:
        current_path = env.get('PATH', '')
        env['PATH'] = f'{sbatch_dir}{os.pathsep}{current_path}' if current_path else str(sbatch_dir)
    return env


def _build_case_command(shell_root, case):
    cli_args = [
        arg.format(log_path=_log_path(shell_root))
        for arg in case['cli_args']
    ]
    command_args = ['fremor', *cli_args]
    if case['include_required_run_args']:
        command_args.extend(
            [
                '--indir', str(shell_root / 'input'),
                '--varlist', str(Path(VARLIST)),
                '--table_config', str(Path(CMIP6_TABLE_CONFIG)),
                '--exp_config', str(shell_root / 'CMOR_input_example.json'),
                '--outdir', str(shell_root / 'output'),
                '--run_one',
                '--grid_label', 'gr',
                '--grid_desc', 'regridded to FOO grid from native',
                '--nom_res', '10000 km',
                '--calendar', 'julian',
            ]
        )
    return _shell_join(command_args)


def _write_job_script(shell_name, shell_root, runtime, job_out, job_err, case):
    fremor_command = _build_case_command(shell_root, case)
    if shell_name == 'bash':
        script_path = shell_root / 'run_script.sh'
        script_text = '\n'.join(
            [
                '#!/bin/bash',
                f'#SBATCH --output={job_out}',
                f'#SBATCH --error={job_err}',
                'set -euo pipefail',
                'shopt -s expand_aliases',
                f'source "{runtime["lmod_init"]["bash"]}"',
                f'module use "{MODULEFILES_ROOT}"',
                f'module load fremor/{MODULE_VERSION}',
                'command -V fremor',
                f'cd "{REPO_ROOT}"',
                fremor_command,
            ]
        )
    else:
        script_path = shell_root / 'run_script.tcsh'
        script_text = '\n'.join(
            [
                f'#!{runtime["tcsh"]} -f',
                f'#SBATCH --output={job_out}',
                f'#SBATCH --error={job_err}',
                f'source "{runtime["lmod_init"]["tcsh"]}"',
                f'module use "{MODULEFILES_ROOT}"',
                f'module load fremor/{MODULE_VERSION}',
                'which fremor',
                f'cd "{REPO_ROOT}"',
                fremor_command,
            ]
        )

    script_path.write_text(f'{script_text}\n', encoding='utf-8')
    script_path.chmod(0o755)
    return script_path


def _assert_job_artifacts(shell_root, shell_name, job_out, job_err, case):
    ## helpful debug locally/interactively, please keep. - inl
    #shutil.copy2(job_out, '/home/{os.getuser()}/'+str(job_out.name)+case['name'])
    #shutil.copy2(job_err, '/home/{os.getuser()}/'+str(job_err.name)+case['name'])

    stdout_text = job_out.read_text(encoding='utf-8')
    stderr_text = job_err.read_text(encoding='utf-8')
    expected_alias_target = str(MODULE_HOOK_SCRIPT)

    assert expected_alias_target in stdout_text
    assert 'aliased' in stdout_text
    assert expected_alias_target not in stderr_text

    for expected_fragment in case.get('expect_stdout_contains', []):
        assert expected_fragment in stdout_text
    for rejected_fragment in case.get('expect_stdout_not_contains', []):
        assert rejected_fragment not in stdout_text

    if case.get('expect_stderr_empty'):
        assert stderr_text == ''
    else:
        for expected_fragment in case.get('expect_stderr_contains', []):
            assert expected_fragment in stderr_text
    for rejected_fragment in case.get('expect_stderr_not_contains', []):
        assert rejected_fragment not in stderr_text

    if case['expect_output']:
        expected_output = shell_root / 'output' / EXPECTED_OUTPUT_RELATIVE
        assert expected_output.exists()
    else:
        expected_output = shell_root / 'output' / EXPECTED_OUTPUT_RELATIVE
        assert not expected_output.exists()

    log_path = _log_path(shell_root)
    if case.get('expect_log_file'):
        assert log_path.exists()
        log_text = log_path.read_text(encoding='utf-8')
        for expected_fragment in case.get('expect_log_contains', []):
            assert expected_fragment in log_text
        for rejected_fragment in case.get('expect_log_not_contains', []):
            assert rejected_fragment not in log_text
    else:
        assert not log_path.exists()

    if shell_name == 'bash':
        assert 'fremor is aliased to' in stdout_text
    else:
        assert 'fremor:' in stdout_text


def test_build_case_command_includes_required_run_args_for_success_case(tmp_path):
    """Successful modulefile cases build a complete `fremor run` invocation."""
    shell_root = tmp_path / 'success'
    command = _build_case_command(shell_root, MODULEFILE_JOB_CASES[0])

    assert '--indir' in command
    assert '--varlist' in command
    assert '--table_config' in command
    assert '--exp_config' in command
    assert '--outdir' in command


def test_build_case_command_omits_required_run_args_for_error_case(tmp_path):
    """The intentional error case stays incomplete without relying on `expect_success`."""
    shell_root = tmp_path / 'error'
    command = _build_case_command(shell_root, MODULEFILE_JOB_CASES[-1])

    assert '--indir' not in command
    assert '--varlist' not in command
    assert '--table_config' not in command
    assert '--exp_config' not in command
    assert '--outdir' not in command


@pytest.fixture
def real_slurm_root(tmp_path):
    """Return a Slurm-shared workspace root when real Slurm testing is enabled."""
    if os.environ.get('FREMOR_TEST_REAL_SLURM') != '1':
        pytest.skip('real Slurm integration test not requested')

    shared_root = Path(os.environ.get('FREMOR_TEST_SLURM_SHARED_ROOT', '/data'))
    if not shared_root.exists():
        _skip_or_fail(f'modulefile integration test requires shared Slurm root {shared_root}')

    work_root = shared_root / 'pytest-modulefile-integration' / f'{tmp_path.name}-{uuid.uuid4().hex}'
    shutil.rmtree(work_root, ignore_errors=True)
    work_root.mkdir(parents=True, exist_ok=True)
    try:
        yield work_root
    finally:
        shutil.rmtree(work_root, ignore_errors=True)


@pytest.mark.parametrize('case', MODULEFILE_JOB_CASES, ids=[case['name'] for case in MODULEFILE_JOB_CASES])
@pytest.mark.parametrize('shell_name', ['bash', 'tcsh'])
def test_modulefile_sbatch_job_logs_stay_on_stderr(tmp_path, modulefile_runtime, shell_name, case):
    """
    Run a module-loaded fremor job through an sbatch-style wrapper for both bash and tcsh.
    """
    shell_root = tmp_path / f'{shell_name}-{case["name"]}'
    _prepare_job_workspace(shell_root)

    sbatch_dir = shell_root / 'bin'
    sbatch_dir.mkdir()
    _write_sbatch_stub(sbatch_dir / 'sbatch')

    job_out = shell_root / f'{shell_name}.out'
    job_err = shell_root / f'{shell_name}.err'
    job_script = _write_job_script(
        shell_name,
        shell_root,
        modulefile_runtime,
        job_out,
        job_err,
        case=case,
    )

    shell_env = _build_shell_env(
        modulefile_runtime,
        f'42-{shell_name}-{case["name"]}',
        sbatch_dir=sbatch_dir,
    )

    job = subprocess.run(
        ['sbatch', str(job_script)],
        capture_output=True,
        check=False,
        cwd=shell_root,
        env=shell_env,
        text=True,
    )

    if case['expect_success']:
        assert job.returncode == 0, job.stderr
    else:
        assert job.returncode != 0
    assert job.stdout.strip() == f'Submitted batch job 42-{shell_name}-{case["name"]}'
    assert job_out.exists()
    assert job_err.exists()

    _assert_job_artifacts(shell_root, shell_name, job_out, job_err, case=case)


@pytest.mark.parametrize('case', MODULEFILE_JOB_CASES, ids=[case['name'] for case in MODULEFILE_JOB_CASES])
@pytest.mark.parametrize('shell_name', ['bash', 'tcsh'])
def test_modulefile_real_slurm_jobs_cover_success_and_error_cases(
        real_slurm_root, modulefile_runtime, shell_name, case):
    """
    Run real Slurm jobs that cover normal success, logfile, quiet, and error stream behavior.
    """
    _require_binary('sbatch')
    shell_root = real_slurm_root / shell_name / case['name']
    _prepare_job_workspace(shell_root)

    job_out = shell_root / f'{shell_name}.out'
    job_err = shell_root / f'{shell_name}.err'
    job_script = _write_job_script(
        shell_name,
        shell_root,
        modulefile_runtime,
        job_out,
        job_err,
        case=case,
    )

    shell_env = _build_shell_env(
        modulefile_runtime,
        f'real-{shell_name}-{case["name"]}',
    )

    job = subprocess.run(
        ['sbatch', '--wait', str(job_script)],
        capture_output=True,
        check=False,
        cwd=shell_root,
        env=shell_env,
        text=True,
    )

    if case['expect_success']:
        assert job.returncode == 0, job.stderr
    else:
        assert job.returncode != 0
    assert 'Submitted batch job ' in job.stdout
    assert job_out.exists()
    assert job_err.exists()

    _assert_job_artifacts(shell_root, shell_name, job_out, job_err, case=case)
