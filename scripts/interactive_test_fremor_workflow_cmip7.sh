#!/bin/bash -u

# this script should be sourced

#### INPUT CONFIG
## check flags, 0 --> yes, 1 --> no
CHECK_INIT=1
CHECK_VARLIST=1
CHECK_FIND=1
CHECK_CONFIG=1
CHECK_CHECK=1
CHECK_MAP=1
CHECK_STAGE=1
CHECK_YAML=0

## someday
#CHECK_RESOLVE=1 # WHEN FRE-CLI INTEGRATION POSSIBLE TODO
#CHECK_RUN=1 # NO NEED, YAML calls RUN


echo_and_run() {
	local i=0
	for arg in "$@"; do
		((i++))

		# For display: wrap the argument in quotes if it contains spaces
		local display_arg="$arg"
		if [[ "$display_arg" == *[[:space:]]* ]]; then
			display_arg="\"$display_arg\""
		fi

		if [[ $i -eq 1 ]]; then
			# First argument (the command itself)
			printf "%s" "$display_arg"
		elif [[ "$display_arg" == -* ]]; then
			# If it's a flag (starts with '-'), wrap to a new line with a backslash
			printf " \\\\\n    %s" "$display_arg"
		else
			# Otherwise, append it to the current line (e.g., subcommand or flag value)
			printf " %s" "$display_arg"
		fi
	done
	printf "\n"

	# Execute the actual command safely preserving all elements
	"$@"
}

rm_then_mkdir(){
	local dir="${1}"
	rm -rf "${dir}" || echo "no output to remove, OK!" && mkdir "${dir}"
}


FREMOR_INSTALL_E=/home/$USER/Working/fremor
echo "fremor installed (with -e) in ${FREMOR_INSTALL_E}"

WORKING_CWD=$PWD


## INPUT DIRECTORY DETAILS
BASE_SRC_DIR=/archive/oar.gfdl.bgrp-account/
#BASE_SRC_DIR=/work/$USER/ # copy over and use this for no archive dependence

CMIP7_ESM_DECK_PATH_GUTS=CMIP7/ESM4/DECK/ESM4.5-

#ESM_KIND=historical
#ESM_KIND=historical-defobbfix
ESM_KIND=picontrol

TAIL_TARG_DIR=/gfdl.ncrc6-intel25-prod-openmp/pp/

BASE_TARG_DIR=${BASE_SRC_DIR}${CMIP7_ESM_DECK_PATH_GUTS}
TARG_FREBRONX_PPDIR=${BASE_TARG_DIR}${ESM_KIND}${TAIL_TARG_DIR}

PP_START=0001
PP_STOP=0006

CHUNK=5yr
#CHUNK=4yr
#CHUNK=1yr
FREQ=monthly
#FREQ=annual
COMPONENT_DIR_STUB_VARLIST_ONLY=atmos_cmip/ts/${FREQ}/${CHUNK}/
TEST_COMPONENT_DIR=${TARG_FREBRONX_PPDIR}${COMPONENT_DIR_STUB_VARLIST_ONLY} # for varlist testing only, random

## OUTPUT CMORIZED DATA DIR
OUTPUT_CMORIZED_DATA_DIR=/net2/$USER/Working/fremor_testing_cmip7_${ESM_KIND}

# I don't always want to remove the logging output because sometimes i need to look at it.
FREMOR_LOGFILE_OUTDIR=fremor_log_output_${ESM_KIND}_dir/
rm_then_mkdir "${FREMOR_LOGFILE_OUTDIR}"
#if [ ! -d $FREMOR_LOGFILE_DIR ]; then
#   mkdir $FREMOR_LOGFILE_DIR
#fi


#### ACTION
echo "cd'ing to working dir ${WORKING_CWD}"
cd "${WORKING_CWD}" || return

#### INIT
FREMOR_INIT_OUTDIR=${WORKING_CWD}/fremor_init_${ESM_KIND}_outdir
FREMOR_INIT_LOGFILE=${FREMOR_LOGFILE_OUTDIR}/CHECK_INIT.log
USER_CONFIG=${FREMOR_INIT_OUTDIR}/CMIP7_user_input.json
CMIP7_TABLES=${FREMOR_INIT_OUTDIR}/cmip7-cmor-tables-main/tables
if [[ "${CHECK_INIT}" -eq 1 ]]; then
	echo "not checking fremor init"
else
	echo "setting up fremor init check, clobbering any prev made output"
	rm_then_mkdir "${FREMOR_INIT_OUTDIR}"

	echo "running fremor init"
	echo_and_run fremor -vvv -l "${FREMOR_INIT_LOGFILE}" init \
				 --mip_era cmip7 \
				 --exp_config "${USER_CONFIG}" \
				 -t "${FREMOR_INIT_OUTDIR}" \
				 --fast

	echo "checking that fremor init's output exists, return if not"
	ls -l "${USER_CONFIG}" || return
	ls -l "${CMIP7_TABLES}" || return
fi


#### VARLIST
FREMOR_VARLIST_OUTDIR=${WORKING_CWD}/fremor_varlist_${ESM_KIND}_outdir
FREMOR_VARLIST_OUTPUT=${FREMOR_VARLIST_OUTDIR}/foo.list
FREMOR_VARLIST_LOGFILE=${FREMOR_LOGFILE_OUTDIR}/CHECK_VARLIST.log
if [[ "${CHECK_VARLIST}" -eq 1 ]]; then
	echo "not checking fremor varlist"
else
	echo "setting up fremor varlist check, clobbering any prev made output"
	rm_then_mkdir "${FREMOR_VARLIST_OUTDIR}"

	echo "running fremor varlist"
	echo_and_run fremor -vvv -l "${FREMOR_VARLIST_LOGFILE}" varlist \
				 --dir_targ "${TEST_COMPONENT_DIR}" \
				 -o "${FREMOR_VARLIST_OUTPUT}"

	echo "checking that fremor varlist's output exists, return if not"
	ls -l "${FREMOR_VARLIST_OUTPUT}" || return
	ls -ld
fi



#### FIND
FREMOR_FIND_LOGFILE=${FREMOR_LOGFILE_OUTDIR}/CHECK_FIND.log
if [[ "${CHECK_FIND}" -eq 1 ]]; then
	echo "not checking fremor find"
else
	echo "setting up fremor find check, which does not produce any output (no dir setup necessary)"

	echo "running fremor find"
	echo_and_run fremor -vvv -l "${FREMOR_FIND_LOGFILE}" find \
				 --table_config_dir "${CMIP7_TABLES}" \
				 --varlist "${FREMOR_VARLIST_OUTPUT}"
fi



#### CONFIG
FREMOR_CONFIG_OUTDIR=${WORKING_CWD}/fremor_config_${ESM_KIND}_outdir
FREMOR_CONFIG_OUTYAML=${FREMOR_CONFIG_OUTDIR}/cmor.yaml
FREMOR_CONFIG_LOGFILE=${FREMOR_LOGFILE_OUTDIR}/CHECK_CONFIG.log
if [[ "${CHECK_CONFIG}" -eq 1 ]]; then
	echo "not checking fremor config"
else
	echo "setting up fremor config check, clobbering any prev made output"
	rm_then_mkdir "${FREMOR_CONFIG_OUTDIR}"
	rm_then_mkdir "${FREMOR_VARLIST_OUTDIR}"

	echo "running fremor config"
	echo_and_run fremor -vvv -l "${FREMOR_CONFIG_LOGFILE}" config \
				 --pp_dir "${TARG_FREBRONX_PPDIR}" \
				 --mip_tables_dir "${CMIP7_TABLES}" \
				 --exp_config "${USER_CONFIG}" \
				 --mip_era "cmip7" \
				 --freq "${FREQ}" \
				 --chunk "${CHUNK}" \
				 --grid "g225" \
				 --calendar "noleap" \
				 --output_yaml "${FREMOR_CONFIG_OUTYAML}" \
				 --output_dir "${OUTPUT_CMORIZED_DATA_DIR}" \
				 --varlist_dir "${FREMOR_VARLIST_OUTDIR}" \
				 --strict_varlist \
				 --overwrite

#				 --pp_comp_glob "*land*" \


	echo "checking that fremor config's output exists, return if not"
	ls -l "${FREMOR_CONFIG_OUTYAML}" || return
fi



#### CHECK
FREMOR_CHECK_OUTDIR=${WORKING_CWD}/fremor_check_${ESM_KIND}_outdir
FREMOR_CHECK_OUTREPORT=${FREMOR_CHECK_OUTDIR}/report.out
FREMOR_CHECK_LOGFILE=${FREMOR_LOGFILE_OUTDIR}/CHECK_CHECK.log
DMLS_BIN=$(which dmls)
if [[ "${CHECK_CHECK}" -eq 1 ]]; then
	echo "not checking fremor check"
else
	echo "setting up fremor check check"
	rm_then_mkdir "${FREMOR_CHECK_OUTDIR}"

	echo "running fremor check"
	echo_and_run fremor -vvv -l "${FREMOR_CHECK_LOGFILE}" check \
				 --yamlfile "${FREMOR_CONFIG_OUTYAML}" \
				 --show-mapped \
				 --show-unmapped \
				 --show-multi-mapped \
				 --check-inputs \
				 --check-dims \
				 --check-outputs \
				 --check-attrs \
				 --check-range \
				 --dmls_bin "${DMLS_BIN}" \
				 --output_report "${FREMOR_CHECK_OUTREPORT}"

#				 --json \

	echo "checking that fremor config's output exists, return if not"
	ls -l "${FREMOR_CHECK_OUTREPORT}" || return
fi



#### MAP
NCINFO_BIN=$(which ncinfo)
FREMOR_MAP_LOGFILE=${FREMOR_LOGFILE_OUTDIR}/CHECK_MAP.log
if [[ "${CHECK_MAP}" -eq 1 ]]; then
	echo "not checking fremor map"
else
	echo "setting up fremor map check"

	echo "running fremor map"
	echo_and_run fremor -vvv -l "${FREMOR_MAP_LOGFILE}" map \
				 --yamlfile "${FREMOR_CONFIG_OUTYAML}" \
				 --dmls_bin "${DMLS_BIN}" \
				 --ncinfo_bin "${NCINFO_BIN}"
fi

#### STAGE
DMGET_BIN=$(which dmget)
FREMOR_STAGE_LOGFILE=${FREMOR_LOGFILE_OUTDIR}/CHECK_STAGE.log
if [[ "${CHECK_STAGE}" -eq 1 ]]; then
	echo "not checking fremor stage"
else
	echo "setting up fremor stage check"

	echo "running fremor stage"
	echo_and_run fremor -vvv -l "${FREMOR_STAGE_LOGFILE}" stage \
				 --yamlfile "${FREMOR_CONFIG_OUTYAML}" \
				 --start "${PP_START}" \
				 --stop "${PP_STOP}" \
				 --dmget_bin "${DMGET_BIN}"
#				 --dry_run \

fi



#### YAML, also RUN, because YAML calls RUN
FREMOR_YAML_LOGFILE=${FREMOR_LOGFILE_OUTDIR}/CHECK_YAML.log
if [[ "${CHECK_YAML}" -eq 1 ]]; then
	echo "not checking fremor yaml"
else

	echo "setting up fremor yaml check"

	echo "running fremor yaml"
	echo_and_run fremor -vv -l "${FREMOR_YAML_LOGFILE}" yaml \
				 --yamlfile "${FREMOR_CONFIG_OUTYAML}" \
				 --start "${PP_START}" \
				 --stop "${PP_STOP}" \
				 --print_cli_call \
                 --run_one \
				 --dry_run
#                --run_strict \

	echo "checking the output cmorized data directory for successfully created output"
	tree ${OUTPUT_CMORIZED_DATA_DIR}/*/*/CMIP/

	echo "checking the output cmorized data directory for created output"
	echo "number of left-behind tmp outputs (without interpolated pressure style coordinate vars is:"
	ls ${OUTPUT_CMORIZED_DATA_DIR}/*/*/CMOR_tmp/*nc  | wc -l | grep -v '\.ps\.' | grep -v '\.phalf\.' | grep -v -c '\.pfull\.'
fi


# end where we began
cd "${WORKING_CWD}" || return
