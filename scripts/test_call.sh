#!/bin/bash
# test_call.sh — manual/smoke-test call examples for fremor ported from NOAA-GFDL/fre-cli and updated
# Lines are commented out by default; uncomment and edit paths as needed.
#
# Command map (fre-cli → fremor):
#   fre [-vv, -q] [-l LOGFILE] cmor X → fremor [-vv, -q] [-l LOGFILE] X
#
# Command list:
#   fremor [-vv, -q] [-l LOGIFLE] init
#   fremor [-vv, -q] [-l LOGIFLE] varlist (optional, create variable lists)
#   fremor [-vv, -q] [-l LOGIFLE] find    (optional, *basic* search of tables for variables)
#   fremor [-vv, -q] [-l LOGIFLE] resolve (optional, for working with multiple yamls in the FRE-universe)
#   fremor [-vv, -q] [-l LOGIFLE] config
#   fremor [-vv, -q] [-l LOGIFLE] yaml
#   fremor [-vv, -q] [-l LOGIFLE] run


# ─────────────────────────────────────────────────────────────────────────────
# init — generate an experiment config template and/or fetch MIP tables
# ─────────────────────────────────────────────────────────────────────────────
#fremor -v init \
#    --mip_era cmip6 \
#    --exp_config /path/to/exp_config.json \
#    --tables_dir /path/to/cmip6-cmor-tables

#fremor -v init \
#    --mip_era cmip7 \
#    --exp_config /path/to/exp_config.json \
#    --tables_dir /path/to/cmip7-cmor-tables \
#    --fast


# ─────────────────────────────────────────────────────────────────────────────
# config — scan a pp directory tree, generate CMOR YAML + per-component varlists
# ─────────────────────────────────────────────────────────────────────────────
#fremor -v -v config \
#    --pp_dir /path/to/pp \
#    --mip_tables_dir /path/to/cmip7-cmor-tables/tables \
#    --mip_era cmip7 \
#    --exp_config /path/to/CMOR_CMIP7_input_example.json \
#    --output_yaml /path/to/output/cmor_config.yaml \
#    --output_dir /path/to/output/cmorized \
#    --varlist_dir /path/to/output/varlists \
#    --freq monthly \
#    --chunk 5yr \
#    --grid g99 \
#    --calendar noleap


# ─────────────────────────────────────────────────────────────────────────────
# resolve — combine model + grids + cmor YAMLs into one resolved document
#           replaces `fre yamltools combine` from fre-cli
# ─────────────────────────────────────────────────────────────────────────────
#fremor -v resolve \
#    --yamlfile /path/to/model.yaml \
#    --experiment ESM4_historical_D1 \
#    --output /path/to/resolved.yaml


# ─────────────────────────────────────────────────────────────────────────────
# yaml — bulk CMORization from a self-contained CMOR YAML config
# ─────────────────────────────────────────────────────────────────────────────
#fremor -v -v yaml \
#    --yamlfile /path/to/cmor_config.yaml
##    --run_one
##    --dry_run
##    --start 0001
##    --stop 0005


# ─────────────────────────────────────────────────────────────────────────────
# run — lowest-level single-directory CMORization (CMIP7)
# ─────────────────────────────────────────────────────────────────────────────
#fremor -v -v run \
#    --run_one \
#    --indir /path/to/pp/ocean_monthly/ts/monthly/5yr \
#    --varlist /path/to/varlists/ocean_monthly_varlist.list \
#    --table_config /path/to/cmip7-cmor-tables/tables/CMIP7_ocean.json \
#    --exp_config /path/to/CMOR_CMIP7_input_example.json \
#    --outdir /path/to/cmorized_output \
#    --grid_desc "placeholder grid label for CMIP7, not for publishing" \
#    --grid_label g99 \
#    --nom_res "10000 km" \
#    --start 0001 \
#    --stop 0005 \
#    --calendar noleap


# ─────────────────────────────────────────────────────────────────────────────
# run — lowest-level single-directory CMORization (CMIP6)
# ─────────────────────────────────────────────────────────────────────────────
#fremor -v -v run \
#    --run_one \
#    --indir fre/tests/test_files/ocean_sos_var_file \
#    --varlist fre/tests/test_files/varlist \
#    --table_config fre/tests/test_files/cmip6-cmor-tables/Tables/CMIP6_Omon.json \
#    --exp_config fre/tests/test_files/CMOR_input_example.json \
#    --outdir outdir \
#    --calendar julian \
#    --grid_label gr \
#    --grid_desc "foo bar placeholder" \
#    --nom_res "10000 km"
##   --opt_var_name sos
