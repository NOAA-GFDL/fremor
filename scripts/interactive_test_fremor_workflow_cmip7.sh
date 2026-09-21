#!/bin/bash -u

# this script should be sourced

#### INPUT CONFIG
## check flags, 0 --> yes, 1 --> no
CHECK_INIT=0
CHECK_VARLIST=1
CHECK_FIND=1
#CHECK_RESOLVE=1 # WHEN FRE-CLI INTEGRATION POSSIBLE TODO
CHECK_CONFIG=1
#CHECK_CHECK=1 # NEW TODO
#CHECK_MAP=1 # NEW TODO
#CHECK_STAGE=1 # NEW TODO
CHECK_YAML=1
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


FREMOR_INSTALL_E=/home/$USER/Working/fremor
echo "fremor installed (with -e) in ${FREMOR_INSTALL_E}"

WORKING_CWD=$PWD

## OUTPUT CMORIZED DATA DIR
OUTPUT_CMORIZED_DATA_DIR=/net2/$USER/Working/fremor_testing_cmip7

## INPUT DIRECTORY DETAILS
BASE_SRC_DIR=/archive/oar.gfdl.bgrp-account/
#BASE_SRC_DIR=/work/$USER/ # copied over, no archive dependence

CMIP7_ESM_DECK_PATH_GUTS=CMIP7/ESM4/DECK/ESM4.5-
ESM_KIND=historical #picontrol #
TAIL_TARG_DIR=/gfdl.ncrc6-intel25-prod-openmp/pp/

BASE_TARG_DIR=${BASE_SRC_DIR}${CMIP7_ESM_DECK_PATH_GUTS}
TARG_FREBRONX_PPDIR=${BASE_TARG_DIR}${ESM_KIND}${TAIL_TARG_DIR}

COMPONENT_DIR_STUB_VARLIST_ONLY=atmos_cmip/ts/monthly/5yr/
TEST_COMPONENT_DIR=${TARG_FREBRONX_PPDIR}${COMPONENT_DIR_STUB_VARLIST_ONLY} # for varlist testing only, random


#### ACTION
echo "cd'ing to working dir ${WORKING_CWD}"
cd "${WORKING_CWD}" || return

PP_START=0001
PP_STOP=0006



#### INIT
FREMOR_INIT_OUTDIR=${WORKING_CWD}/fremor_init_outdir
USER_CONFIG=${FREMOR_INIT_OUTDIR}/CMIP7_user_input.json
CMIP7_TABLES=${FREMOR_INIT_OUTDIR}/cmip7-cmor-tables-main/tables
if [[ "${CHECK_INIT}" -eq 1 ]]; then
	echo "not checking fremor init"
else
	echo "setting up fremor init check, clobbering any prev made output"
	rm -rf "${FREMOR_INIT_OUTDIR}" || echo "no init output to remove, OK!" && mkdir "${FREMOR_INIT_OUTDIR}"

	echo "running fremor init"
	echo_and_run fremor -v init \
				 --mip_era cmip7 \
				 --exp_config "${USER_CONFIG}" \
				 -t "${FREMOR_INIT_OUTDIR}" \
				 --fast

	echo "checking that fremor init's output exists, return if not"
	ls -l "${USER_CONFIG}" || return
	ls -l "${CMIP7_TABLES}" || return
fi


#### VARLIST
FREMOR_VARLIST_OUTDIR=${WORKING_CWD}/fremor_varlist_outdir
FREMOR_VARLIST_OUTPUT=${FREMOR_VARLIST_OUTDIR}/foo.list
if [[ "${CHECK_VARLIST}" -eq 1 ]]; then
	echo "not checking fremor varlist"
else
	echo "setting up fremor varlist check, clobbering any prev made output"
	rm -rf "${FREMOR_VARLIST_OUTDIR}" || echo "no varlist output to remove, OK!" && mkdir "${FREMOR_VARLIST_OUTDIR}"

	echo "running fremor varlist"
	echo_and_run fremor -vv varlist \
				 --dir_targ "${TEST_COMPONENT_DIR}" \
				 -o "${FREMOR_VARLIST_OUTPUT}"

	echo "checking that fremor varlist's output exists, return if not"
	ls -l "${FREMOR_VARLIST_OUTPUT}" || return
	ls -ld
fi



#### FIND
if [[ "${CHECK_FIND}" -eq 1 ]]; then
	echo "not checking fremor find"
else
	echo "setting up fremor find check, which does not produce any output (no dir setup necessary)"

	echo "running fremor find"
	echo_and_run fremor -v find \
				 --table_config_dir "${CMIP7_TABLES}" \
				 --varlist "${FREMOR_VARLIST_OUTPUT}"
fi



#### CONFIG
FREMOR_CONFIG_OUTDIR=${WORKING_CWD}/fremor_config_outdir
FREMOR_CONFIG_OUTYAML=${FREMOR_CONFIG_OUTDIR}/cmor.yaml
if [[ "${CHECK_CONFIG}" -eq 1 ]]; then
	echo "not checking fremor config"
else
	echo "setting up fremor config check, clobbering any prev made output"
	rm -rf "${FREMOR_CONFIG_OUTDIR}" || echo "no config output to remove, OK!" && mkdir "${FREMOR_CONFIG_OUTDIR}"
	rm -rf "${FREMOR_VARLIST_OUTDIR}" || echo "no varlist output to remove, OK!" && mkdir "${FREMOR_VARLIST_OUTDIR}"

	echo "running fremor config"
	echo_and_run fremor -v config \
				 --pp_dir "${TARG_FREBRONX_PPDIR}" \
				 --mip_tables_dir "${CMIP7_TABLES}" \
				 --exp_config "${USER_CONFIG}" \
				 --mip_era "cmip7" \
				 --freq "monthly" \
				 --chunk "5yr" \
				 --grid "g999" \
				 --calendar "noleap" \
				 --output_yaml "${FREMOR_CONFIG_OUTYAML}" \
				 --output_dir "${OUTPUT_CMORIZED_DATA_DIR}" \
				 --varlist_dir "${FREMOR_VARLIST_OUTDIR}" \
				 --strict_varlist \
				 --pp_comp_glob "*land*" \
				 --overwrite


	echo "checking that fremor config's output exists, return if not"
	ls -l "${FREMOR_CONFIG_OUTYAML}" || return
fi


#### YAML, also RUN, because YAML calls RUN
if [[ "${CHECK_YAML}" -eq 1 ]]; then
	echo "not checking fremor yaml"
else

	echo "setting up fremor yaml check"

	echo "running fremor yaml"
	echo_and_run fremor -vv yaml \
				 --yamlfile "${FREMOR_CONFIG_OUTYAML}" \
				 --start "${PP_START}" \
				 --stop "${PP_STOP}" \
				 --print_cli_call \
	             --dry_run
	#           --run_strict
	#           --run_one

	echo "checking the output cmorized data directory for successfully created output"
	tree ${OUTPUT_CMORIZED_DATA_DIR}/*/*/CMIP/

	echo "checking the output cmorized data directory for created output"
	echo "number of left-behind tmp outputs (without interpolated pressure style coordinate vars is:"
	ls ${OUTPUT_CMORIZED_DATA_DIR}/*/*/CMOR_tmp/*nc  | wc -l # | grep -v '\.ps\.' | grep -v '\.phalf\.' | grep -v -c '\.pfull\.'
fi


# end where we began
cd "${WORKING_CWD}" || return


