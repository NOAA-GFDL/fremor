# Running fremor on Slurm

The scripts in this folder run fremor CMORization as Slurm batch jobs, with **one job per
MIP table** (Amon, Omon, day, ...). Each job recalls its input files from tape, checks
them, and CMORizes them straight away. The scripts can also set up and submit many
experiments or ensemble members from one working example.

| File | Role |
| --- | --- |
| `fremor_submit_tables.sh` | **The submitter.** You edit its config block and run it on a login node. It splits the work into per-table jobs and `sbatch`es them. |
| `fremor_table_job.sh` | The body of one per-table job. The submitter submits it; you don't edit or run it yourself. |
| `fremor_make_cases.py` | Generates per-case inputs for many cases, plus a `submit_all.sh` that runs the submitter once per case. |

Contents:

1. [Requirements](#requirements)
2. [What a table job does](#what-a-table-job-does)
3. [Quick start: one case](#quick-start-one-case)
4. [Configuration reference](#configuration-reference)
5. [Command line](#command-line)
6. [The work directory](#the-work-directory)
7. [Monitoring, failures and resuming](#monitoring-failures-and-resuming)
8. [Archiving outputs](#archiving-outputs)
9. [MODE=run: without a CMOR yaml](#moderun-without-a-cmor-yaml)
10. [Many cases: experiments and ensemble members](#many-cases-experiments-and-ensemble-members)
11. [Limiting concurrent jobs](#limiting-concurrent-jobs)
12. [Troubleshooting](#troubleshooting)

---

## Requirements

- **bash 4 or newer** for both shell scripts. They use `mapfile` and `declare -p` on
  arrays. macOS's built-in `/bin/bash` 3.2 is too old, but HPC login nodes are fine.
- **Slurm** commands `sbatch` and `squeue`.
- **fremor** installed as an environment module or a conda environment. The submitter
  loads it through `ENV_SETUP`, both on the login node and inside every job.
- **PyYAML**, which comes with fremor. The submitter splits the yaml with the Python
  from the fremor environment. Run `fremor_make_cases.py` with that Python too, for
  example after `module load fremor`.
- *Optional:* the DMF tape tools **`dmget`** and **`dmls`**. If they're missing, jobs
  skip the tape recall and treat all inputs as ordinary disk files.

Always run the submitter on a **login or analysis node**, never inside `sbatch`.

## What a table job does

Staging and CMORization happen in **the same job**. A file recalled from tape is
processed right away, so it can't be purged from the disk cache while a separate CMOR
job waits in the queue. Each table's job does the following:

1. **Lists its input files**, including any `ps` files that hybrid-sigma variables
   need. It writes the list to `input_files.txt`. In `MODE=yaml` the list comes from
   `fremor stage --dry_run`.
2. **Checks that every file exists**, whether on disk or as a tape stub. Missing files
   go to `missing_files.txt` and the job stops.
3. **Recalls offline files from tape** with `dmget`, `DMGET_BATCH` files per call. It
   re-checks with `dmls -l` until every file is disk-resident (state `REG` or `DUL`),
   for up to `STAGE_RETRIES` attempts.
4. *(MODE=yaml, `PRECHECK=1`)* runs `fremor check <table> --check-inputs --check-dims`.
   This check only warns and never stops the job.
5. *(`COPY_TO_LOCAL=1`)* copies the inputs to node-local storage and runs from there.
6. **CMORizes** with `fremor yaml` (MODE=yaml) or `fremor run` (MODE=run).
7. *(MODE=yaml, `POSTCHECK=1`)* runs `fremor check <table> --check-outputs`. Like the
   pre-check, it only warns.
8. *(`ARCHIVE=1`)* moves the finished `.nc` files into `ARCHIVE_DIR` (see
   [Archiving outputs](#archiving-outputs)).
9. **Writes a `DONE` marker.** This marker is how a resubmission tells finished tables
   apart.

Each job runs in the directory you submitted from, so relative paths in the yaml
resolve the same way they did on the login node.

## Quick start: one case

You need two working inputs.

- **An experiment configuration JSON**, the CMOR "input" file. It holds global
  metadata such as `experiment_id`, `realization_index`, `source_id`,
  `_controlled_vocabulary_file`, and so on.
- **A CMOR yaml**, as written by `fremor config`. The scripts rely on this part of it:

  ```yaml
  cmor:
    start: null                  # optional year bounds
    stop: null
    mip_era: 'CMIP6'
    exp_json: '/path/to/CMOR_input.json'   # the experiment configuration above
    directories:
      pp_dir: '/archive/me/my_exp/pp'      # post-processing root: <pp_dir>/<component>/ts/<freq>/<chunk>/
      table_dir: '/path/to/cmip6-cmor-tables/Tables'
      outdir: '/work/me/cmor_out'
    table_targets:               # one or more entries per MIP table
      - table_name: Amon
        freq: monthly
        # ... target components and variable lists
      - table_name: Omon
        # ...
  ```

  `pp_dir`, `table_dir`, `outdir`, `exp_json` and the variable-list paths may contain
  environment variables such as `${HOME}`. fremor expands them when it runs.

Then:

```bash
# 1. edit the USER CONFIG block of fremor_submit_tables.sh, at least:
#      ENV_SETUP='module load fremor'     # how jobs get fremor
#      MODE=yaml
#      FREMOR_YAML=/path/to/cmor.yaml
#      JOB_PARTITION / JOB_TIME / JOB_MEM / SLURM_ACCOUNT for your site
# 2. see what would be submitted
DRY_RUN=1 ./fremor_submit_tables.sh
# 3. submit
./fremor_submit_tables.sh
```

The submitter prints the work directory and one `<table>  <job id>` line per table.
It also prints an `squeue` command for monitoring.

Settings can also be given on the command line instead of editing the file, for
example `FREMOR_YAML=/path/to/cmor.yaml ./fremor_submit_tables.sh`. The settings that
allow this are marked [env] in the [reference](#configuration-reference).

## Configuration reference

All settings live in the `USER CONFIG` block at the top of `fremor_submit_tables.sh`.
Settings marked **[env]** can also be set in the environment, and the environment wins.
Every other setting has to be edited in the file.

### General

| Setting | Default | Meaning |
| --- | --- | --- |
| `CASE_NAME` [env] | *(empty)* | Short name telling cases (experiments, ensemble members) apart, e.g. `esm4_hist_r1`. It's added to the default `WORK_DIR`, `ARCHIVE_DIR` and `OUTDIR`, to Slurm job names (`fremor_<CASE_NAME>_<table>`) and to log lines. Allowed characters: letters, digits, `.`, `_`, `-`. If empty, it's left out everywhere. |
| `ENV_SETUP` | `module load fremor` | Shell code that makes `fremor` available. It's `eval`'d on the login node and in every job. For conda: `'source /path/to/miniforge3/etc/profile.d/conda.sh && conda activate fremor'`. |
| `MODE` [env] | `yaml` | `yaml`: run `fremor yaml` on per-table copies of a CMOR yaml. `run`: run `fremor run` on explicit per-table targets ([see below](#moderun-without-a-cmor-yaml)). |
| `WORK_DIR` [env] | `~/fremor_jobs/[<CASE_NAME>/]<timestamp>` | Scratch area for per-table yamls, file lists, env files and logs ([layout](#the-work-directory)). It must be new or empty, unless you're resuming it. |
| `CONTINUE` [env] | `0` | `1` means resume `WORK_DIR`. The same as `--continue`. |
| `START`, `STOP` [env] | *(empty)* | Year bounds (YYYY) passed as `--start` / `--stop`. If empty, the yaml's bounds are used, or all years. |

### MODE=yaml

| Setting | Default | Meaning |
| --- | --- | --- |
| `FREMOR_YAML` [env] | — | The CMOR yaml to process. |
| `TABLES` | `()` = every enabled `table_target` | Tables to process. Table names on the command line override this. |
| `YAML_EXTRA_ARGS` | `()` | Extra flags for `fremor yaml`, e.g. `(--run_strict)`. `--continue` is added automatically when resuming. |
| `PRECHECK` | `1` | Run `fremor check --check-inputs --check-dims` after staging. |
| `POSTCHECK` | `1` | Run `fremor check --check-outputs` after CMORizing. |

### MODE=run

| Setting | Default | Meaning |
| --- | --- | --- |
| `EXP_CONFIG` [env] | — | Experiment configuration JSON shared by all targets. |
| `OUTDIR` [env] | `/path/to/cmorized_output[/<CASE_NAME>]` | CMOR output root. |
| `RUN_TARGETS` | — | One entry per table, written as `"label\|table_json\|indir\|varlist_json\|extra fremor run args"`. |

### Staging and concurrency

| Setting | Default | Meaning |
| --- | --- | --- |
| `MAX_CONCURRENT` [env] | `4` | At most this many table jobs run at once. `1` means strictly one after another, `0` means no limit. Keep it small to spare the tape system. |
| `JOB_QUEUE_FILE` [env] | *(empty)* | A file shared by several submissions, so `MAX_CONCURRENT` limits all of them together ([details](#limiting-concurrent-jobs)). |
| `DMGET_BATCH` | `500` | Files per `dmget` / `dmls` call. |
| `STAGE_RETRIES` | `3` | `dmget` + verify rounds before giving up. |
| `COPY_TO_LOCAL` | `0` | `1` copies staged inputs to node-local `LOCAL_ROOT` before CMORizing. |
| `LOCAL_ROOT` | `'${TMPDIR}'` | Node-local directory, expanded inside the job. Keep it single-quoted, e.g. `'/vftmp/${USER}/${SLURM_JOB_ID}'`. |

### Archive

| Setting | Default | Meaning |
| --- | --- | --- |
| `ARCHIVE` [env] | `0` | `1` CMORizes into a temporary outdir, then moves the results into `ARCHIVE_DIR`. |
| `ARCHIVE_DIR` [env] | `/path/to/archive[/<CASE_NAME>]` | Final home of the CMORized files. Remove the `CASE_NAME` part of the default to put all cases into one shared directory tree. |
| `ARCHIVE_TMP_ROOT` [env] | *(empty)* = `WORK_DIR` | Parent of the per-table temporary outdirs (`<root>/<table>/outdir`). |

### Slurm

| Setting | Default | Meaning |
| --- | --- | --- |
| `SLURM_ACCOUNT` | *(empty)* | `--account`. If empty, your default account is used. |
| `JOB_PARTITION` | `batch` | `--partition`. |
| `JOB_TIME` | `16:00:00` | `--time`. Allow for **both** the tape recall and the CMORization. |
| `JOB_MEM` | `16G` | `--mem`. |
| `JOB_CPUS` | `1` | `--cpus-per-task`. |
| `MAIL_USER` | *(empty)* | Mail address for `--mail-type=FAIL`. |
| `SBATCH_EXTRA_ARGS` | `()` | Anything else, e.g. `(--qos=normal --constraint=bigmem)`. |

## Command line

```
fremor_submit_tables.sh [--continue | --continue=WORK_DIR] [TABLE ...]
```

| Form | Effect |
| --- | --- |
| `./fremor_submit_tables.sh` | Submit every selected table. |
| `./fremor_submit_tables.sh Amon Omon` | Only these tables. This overrides `TABLES` (and `RUN_TARGETS` labels in MODE=run). |
| `DRY_RUN=1 ./fremor_submit_tables.sh` | Print the `sbatch` commands and submit nothing. The work directory is still created. |
| `./fremor_submit_tables.sh --continue=~/fremor_jobs/20260929_101500` | Resume that earlier run ([details](#monitoring-failures-and-resuming)). |
| `./fremor_submit_tables.sh --continue` | Resume the `WORK_DIR` set in the config or environment. |
| `CASE_NAME=esm4_hist_r1 FREMOR_YAML=... ./fremor_submit_tables.sh` | Submit one case of many. |

## The work directory

```
WORK_DIR/
├── HISTORY                     # append-only record of every submission into this directory
└── <table>/                    # one per table, e.g. Amon/
    ├── fremor_<table>.yaml     # MODE=yaml: copy of FREMOR_YAML with every other table disabled
    ├── job.env                 # everything the job needs, written by the submitter
    ├── JOBID                   # Slurm job id of the latest submission
    ├── input_files.txt         # inputs found for this table
    ├── missing_files.txt       # inputs that do not exist (job stops if non-empty)
    ├── offline_files.txt       # inputs still on tape after the last check
    ├── STAGED                  # marker: staging finished
    ├── DONE                    # marker: CMORization (and archiving) finished
    ├── fremor_<table>.log      # fremor's own log
    ├── precheck_report.json    # fremor check --check-inputs --check-dims (PRECHECK=1)
    ├── postcheck_report.json   # fremor check --check-outputs (POSTCHECK=1)
    ├── archive_overwritten.txt # ARCHIVE=1: archive files that were replaced
    ├── outdir/                 # ARCHIVE=1 with ARCHIVE_TMP_ROOT empty: temporary outdir
    └── logs/
        ├── fremor_[<case>_]<table>.<jobid>.out   # Slurm stdout/stderr of each attempt
        └── *.log                                 # ARCHIVE=1: CMOR's own logs
```

`HISTORY` records the command line, settings, tables and job ids for every submission,
including resumed ones. It's the first place to look for what happened in a work
directory.

## Monitoring, failures and resuming

Monitor with the command the submitter prints, for example:

```bash
squeue -u $USER -o '%.10i %.40j %.9T %.10M %R' | grep fremor_
```

When a table fails, the reason is in the last lines of
`WORK_DIR/<table>/logs/*.<jobid>.out`. For CMOR errors, see `fremor_<table>.log` and
CMOR's `*.log` files. Typical causes are missing inputs, files still offline after
`STAGE_RETRIES`, a timeout, or a CMOR error.

**To resubmit what didn't finish**, resume the same work directory:

```bash
./fremor_submit_tables.sh --continue=/path/to/WORK_DIR
```

When resuming, the submitter:

- **skips** tables that have a `DONE` marker;
- **skips** tables whose previous job (from `JOBID`) is still queued or running;
- resubmits everything else. In MODE=yaml it adds `fremor yaml --continue`, so chunks
  that were already CMORized aren't redone. In MODE=run the table starts over;
- appends to `HISTORY`.

Without `--continue`, the submitter refuses to reuse a non-empty `WORK_DIR`, so you
can't overwrite an earlier run by accident.

With `ARCHIVE=1`, finished outputs are moved out of the temporary outdir, and
`--continue` can only skip chunks that are still in that outdir. When a job fails, its
outputs stay there for the next submission. Leave `ARCHIVE_TMP_ROOT` empty (it then
lives inside `WORK_DIR`) or set a fixed path. Don't change it between submissions.

## Archiving outputs

With `ARCHIVE=1`, each table CMORizes into `<ARCHIVE_TMP_ROOT>/<table>/outdir`, which
overrides the yaml's `outdir` or `OUTDIR`. After a successful run and post-check:

- the `.nc` files move into `ARCHIVE_DIR`. The leading directories are dropped, so
  only the CMIP directory structure remains. MODE=yaml writes
  `<outdir>/<component>/<table>/<CMIP dirs>/*.nc`, so `ARCHIVE_DIR` receives
  `<CMIP dirs>/*.nc`;
- existing archive files are overwritten and listed in `archive_overwritten.txt`;
- CMOR's `*.log` files are moved from `CMOR_tmp/` to the table's `logs/`, prefixed
  with component and table (e.g. `atmos.Amon.cmor_tas.log`). This also happens when
  fremor failed, since they contain the real error;
- empty directories left in the temporary outdir are removed.

## MODE=run: without a CMOR yaml

Set `MODE=run` to call `fremor run` directly. There's one `RUN_TARGETS` entry per
table:

```bash
EXP_CONFIG=/path/to/CMOR_input.json
OUTDIR=/path/to/cmorized_output
RUN_TARGETS=(
    "Amon|/path/to/tables/CMIP6_Amon.json|/path/to/pp/atmos_cmip/ts/monthly/5yr|/path/to/varlist_Amon.json|--grid_label gr1 --calendar noleap"
    "Omon|/path/to/tables/CMIP6_Omon.json|/path/to/pp/ocean_monthly/ts/monthly/5yr|/path/to/varlist_Omon.json|"
)
```

The fields are: the label (used for the job name and work subdirectory), the MIP
table JSON, the input directory, the variable list JSON (its keys are the local
variable names), and optional extra `fremor run` arguments.

Inputs are the `*.nc` files in the input directory named like
`<prefix>.<YYYY[MM]-YYYY[MM]>.<variable>.nc` whose variable is in the list, limited by
`START`/`STOP`. A matching `<prefix>.<dates>.ps.nc` is picked up automatically.
MODE=run has no pre- or post-checks and no `--continue`.

## Many cases: experiments and ensemble members

Say you want to CMORize 8 experiments × 5 ensemble members. Everything is the same
across them except the post-processing directory and a few metadata fields.
`fremor_make_cases.py` turns **one working case** plus a **CSV of cases** into
ready-to-submit inputs.

### 1. Write the case list

Use one row per case. `#` lines and blank lines are ignored.

```csv
case_name,case,experiment_id,realization_index
esm4_hist_r1,esm4_hist,historical,1
esm4_hist_r2,esm4_hist,historical,2
esm4_ssp585_r1,esm4_ssp585,ssp585,1
```

| Column | Meaning |
| --- | --- |
| `case_name` | **Required**, unique. It names the case's files, work directory, archive directory and Slurm jobs, and it becomes `CASE_NAME`. Allowed characters: letters, digits, `.`, `_`, `-`. |
| `pp_dir`, `outdir` | Set the yaml's `directories.pp_dir` / `outdir`. If missing, `--pp-dir` / `--outdir` are used; if there's no `--outdir` either, the template's outdir + `/<case_name>`. |
| `archive_dir`, `start`, `stop` | Passed to the submitter as `ARCHIVE_DIR`, `START`, `STOP`. If missing, `--archive-dir` or the submitter's own setting is used. |
| any key of the experiment JSON | Sets that key, e.g. `experiment_id`, `realization_index`, `branch_time_in_parent`, `parent_variant_label`. The value is converted to the type of the template's value (number or string). An empty cell keeps the template's value. |
| helper columns | A column that isn't a JSON key but appears as `{column}` in some value or pattern (like `case` above). It only fills in patterns. |

Any other column is rejected as a probable typo. `--allow-new-keys` adds such columns to
the JSON instead.

**Patterns.** Every value, and the `--pp-dir` / `--outdir` / `--archive-dir` options,
may refer to the row's columns as `{column}` with Python format specs. If the paths
follow a regular layout, you don't need a path per row:

```bash
--pp-dir '/archive/me/{case}_ens{realization_index:0>2}/pp'
# esm4_hist, realization_index 1 -> /archive/me/esm4_hist_ens01/pp
```

### 2. Generate

```bash
python fremor_make_cases.py cases.csv \
    --exp-template /path/to/CMOR_input.json \
    --yaml-template /path/to/cmor.yaml \
    --out-dir ~/fremor_cases/esm4 \
    --pp-dir '/archive/me/{case}_ens{realization_index:0>2}/pp' \
    --archive-dir '/archive/cmor/{case}'
```

| Option | Meaning |
| --- | --- |
| `--exp-template` | Experiment configuration JSON of a working case (required). |
| `--yaml-template` | CMOR yaml of a working case (required). Its table targets and variable lists are reused unchanged. |
| `--out-dir` | Where the generated files go (required). |
| `--pp-dir`, `--outdir`, `--archive-dir` | Patterns for rows without that column. |
| `--jobs-root` | Parent of the per-case work directories. Default `${HOME}/fremor_jobs`. |
| `--submitter` | The `fremor_submit_tables.sh` to call. Default: the one next to the script. |
| `--allow-new-keys` | Allow CSV columns that aren't keys of the template JSON. |
| `--force` | Overwrite previously generated files. |

It prints one line per case with the resulting `pp_dir` and metadata, and writes:

```
~/fremor_cases/esm4/
├── submit_all.sh
├── esm4_hist_r1/
│   ├── exp_config.json   # template JSON with this row's keys set
│   └── fremor.yaml       # template yaml; pp_dir, outdir, exp_json point at this case
├── esm4_hist_r2/
└── ...
```

Check a couple of generated files before submitting.

### 3. Submit

`submit_all.sh` runs `fremor_submit_tables.sh` once per case in MODE=yaml, setting
`CASE_NAME`, `FREMOR_YAML`, a fixed `WORK_DIR=<jobs-root>/<case_name>`, and any
`ARCHIVE_DIR`/`START`/`STOP`. The Slurm, staging and archive settings still come from
the submitter's config block, so set those there first.

```bash
DRY_RUN=1 ~/fremor_cases/esm4/submit_all.sh    # check what would be submitted
~/fremor_cases/esm4/submit_all.sh              # submit every case
~/fremor_cases/esm4/submit_all.sh --continue   # later: resume every case
~/fremor_cases/esm4/submit_all.sh Amon         # arguments go to every submission
CASES="esm4_hist_r1 esm4_hist_r2" ~/fremor_cases/esm4/submit_all.sh   # only these cases
```

- Jobs are named `fremor_<case_name>_<table>`, so `squeue ... | grep fremor_esm4_hist_r1_`
  shows a single case.
- Because each case's work directory is fixed, `submit_all.sh --continue` resumes all
  cases at once.
- If one case fails to submit, the others still go ahead, and the failed cases are
  listed at the end (exit status 1). One way this happens is rerunning without
  `--continue`, which leaves existing work directories untouched and reports those
  cases as failed.
- All cases share one `JOB_QUEUE_FILE` (`<out-dir>/job_queue.txt`), so `MAX_CONCURRENT`
  limits the jobs of **all** cases together, not per case.

## Limiting concurrent jobs

Within one submission, job *n* gets `--dependency=afterany:<job n − MAX_CONCURRENT>`.
Each job waits for an earlier one to end, whether it succeeded or failed, so at most
`MAX_CONCURRENT` jobs run at once. The jobs form `MAX_CONCURRENT` parallel chains.

Without `JOB_QUEUE_FILE`, that limit only covers the jobs of one submission, so 40 case
submissions with `MAX_CONCURRENT=4` could hit tape with 160 jobs at once. With
`JOB_QUEUE_FILE` set, every submission appends its job ids to that file and counts the
ids already there. New jobs then chain behind the other submissions' jobs, and the
limit covers all of them. A listed job that has already left the queue is not waited
for. `submit_all.sh` sets this up for you. To share a limit between separate manual
submissions, set the same `JOB_QUEUE_FILE` for each. Dry runs don't write to the file.

## Troubleshooting

| Message | Cause and fix |
| --- | --- |
| `WORK_DIR already exists: ...` | The directory holds an earlier run. Resume it with `--continue=<dir>`, or pick a new `WORK_DIR`. |
| `CONTINUE=1 needs an existing WORK_DIR` | `--continue` was given for a directory that doesn't exist. Check the path in `HISTORY` or in the submitter's output. |
| `fremor not found after ENV_SETUP` | `ENV_SETUP` didn't put `fremor` on `PATH`, either on the login node or inside the job. Test it in a fresh shell. |
| `tables not found (or disabled) in ...` | A table named on the command line or in `TABLES` isn't an enabled `table_target` of the yaml. |
| `no input files found for <table>` | Nothing matched in `pp_dir` for that table's components, variables and years. Check `pp_dir`, `freq`/chunk and `START`/`STOP`. |
| `N input files missing, see missing_files.txt` | The listed files don't exist, not even on tape. |
| `N files still offline, see offline_files.txt` | The tape recall didn't finish within `STAGE_RETRIES`. Resubmit with `--continue`, or raise `STAGE_RETRIES`. |
| `fremor exited with N, see fremor_<table>.log` | CMORization failed. Read that log and CMOR's `*.log` files (in `logs/` with `ARCHIVE=1`, otherwise under the outdir's `CMOR_tmp/`). |
| `unexpected output layout ...` | `ARCHIVE=1` found files where it didn't expect them. MODE=yaml expects `<outdir>/<component>/<table>/<CMIP dirs>/`. |
| `CSV columns neither in ... nor used as {column}` | `fremor_make_cases.py`: a CSV column is misspelled, or is meant to be a new JSON key (`--allow-new-keys`). |
| `already exist (use --force to overwrite)` | `fremor_make_cases.py` was run again into the same `--out-dir`. |
| `mapfile: command not found` | bash is older than 4 (e.g. macOS `/bin/bash`). Run on the cluster, or with a newer bash. |
