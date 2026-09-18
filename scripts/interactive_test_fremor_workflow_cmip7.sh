#!/bin/bash -u
# this script should be sourced. It's slightly biased towards the fremor author's workflow- mainly the "Working" dir.

#### INPUT CONFIG
#### ------------
## check flags, 0 --> yes, 1 --> no
CHECK_INIT=0
CHECK_VARLIST=0
CHECK_FIND=0
CHECK_CONFIG=0
CHECK_YAML=1
CHECK_RUN=1
CHECK_RESOLVE=1

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
	#"$@"
}



## FYI which fremor i'm using, not strictly used nor necessary.
FREMOR_INSTALL_E=/home/$USER/Working/fremor
echo "fremor installed (with -e) in ${FREMOR_INSTALL_E}"

## starting directory
WORKING_CWD=$PWD

## output for CMORized data, do not use home nor nbhome as it's a lot
OUTPUT_CMORIZED_DATA_DIR=/net2/$USER/Working/fremor_testing_cmip7

## input directory stuff
BASE_SRC_DIR=/archive/oar.gfdl.bgrp-account/ # full original targets
#BASE_SRC_DIR=/work/$USER/ # copied over, first five years, in my area, "shakedown test"
CMIP7_ESM_DECK_PATH_GUTS=CMIP7/ESM4/DECK/ESM4.5-
ESM_KIND=historical #picontrol #
TAIL_TARG_DIR=/gfdl.ncrc6-intel25-prod-openmp/pp/ ## platform x target / pp /
COMPONENT_DIR_STUB_VARLIST_ONLY=atmos_cmip/ts/monthly/5yr/

PP_START=0001
PP_STOP=0006

#### DERIVED CONFIG
#### --------------
BASE_TARG_DIR=${BASE_SRC_DIR}${CMIP7_ESM_DECK_PATH_GUTS}
TARG_FREBRONX_PPDIR=${BASE_TARG_DIR}${ESM_KIND}${TAIL_TARG_DIR}
TEST_COMPONENT_DIR=${TARG_FREBRONX_PPDIR}${COMPONENT_DIR_STUB_VARLIST_ONLY} # for varlist testing only, random


#### ACTION
#### ------
# from ~/Working, this is not technically required, but assists with org
echo "cd'ing to working dir ${WORKING_CWD}"
cd "${WORKING_CWD}" || return



#### INIT
#### ----
# NOTE: the required input data is not required for this step, and neither is the CWD/editable info above, it's just convenience scaffolding
FREMOR_INIT_OUTDIR=${WORKING_CWD}/fremor_init_outdir
USER_CONFIG=${FREMOR_INIT_OUTDIR}/CMIP7_user_input.json
CMIP7_TABLES=${FREMOR_INIT_OUTDIR}/cmip7-cmor-tables-main/tables
if [[ "${CHECK_INIT}" -eq 1 ]]; then
	echo "not checking fremor init"
else
	# fremor init - works, check!
	echo "setting up fremor init check, clobbering any prev made output"
	rm -rf "${FREMOR_INIT_OUTDIR}" || echo "no init output to remove, OK!" && mkdir "${FREMOR_INIT_OUTDIR}"

	echo "running fremor init"
	echo_and_run fremor -v init \
				 --mip_era cmip7 \
				 --exp_config "${USER_CONFIG}" \
				 -t "${FREMOR_INIT_OUTDIR}" \
				 --fast

	#echo "checking that fremor init's output exists, return if not"
	#ls -l "${USER_CONFIG}" || return
	#ls -l "${CMIP7_TABLES}" || return
fi


#### VARLIST
#### -------
FREMOR_VARLIST_OUTDIR=${WORKING_CWD}/fremor_varlist_outdir #DIRECTORY
FREMOR_VARLIST_OUTPUT=${FREMOR_VARLIST_OUTDIR}/foo.list #FULL FILEPATH
if [[ "${CHECK_VARLIST}" -eq 1 ]]; then
	echo "not checking fremor varlist"
else
	# fremor varlist
	echo "setting up fremor varlist check, clobbering any prev made output"
	rm -rf "${FREMOR_VARLIST_OUTDIR}" || echo "no varlist output to remove, OK!" && mkdir "${FREMOR_VARLIST_OUTDIR}"

	echo "running fremor varlist"
	echo_and_run fremor -vv varlist \
				 --dir_targ "${TEST_COMPONENT_DIR}" \
				 -o "${FREMOR_VARLIST_OUTPUT}"

	#echo "checking that fremor varlist's output exists, return if not"
	#ls -l "${FREMOR_VARLIST_OUTPUT}" || return
	#ls -ld
fi



#### FIND
#### ----
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
#### ------
FREMOR_CONFIG_OUTDIR=${WORKING_CWD}/fremor_config_outdir
FREMOR_CONFIG_OUTYAML=${FREMOR_CONFIG_OUTDIR}/cmor.yaml
if [[ "${CHECK_CONFIG}" -eq 1 ]]; then
	echo "not checking fremor config"
else
	echo "setting up fremor config check, clobbering any prev made output"
	rm -rf "${FREMOR_CONFIG_OUTDIR}" || echo "no config output to remove, OK!" && mkdir "${FREMOR_CONFIG_OUTDIR}"
	rm -rf "${FREMOR_VARLIST_OUTDIR}" || echo "no varlist output to remove, OK!" && mkdir "${FREMOR_VARLIST_OUTDIR}"

	echo "running fremor config"
	echo "fremor -v config --pp_dir ${TARG_FREBRONX_PPDIR} --mip_tables_dir ${CMIP7_TABLES} --exp_config ${USER_CONFIG} --mip_era cmip7 --freq monthly --chunk 5yr --grid g999 --calendar noleap --output_yaml ${FREMOR_CONFIG_OUTYAML} --output_dir ${OUTPUT_CMORIZED_DATA_DIR} --varlist_dir ${FREMOR_VARLIST_OUTDIR} --strict_varlist --overwrite"

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


	#echo "checking that fremor config's output exists, return if not"
	#ls -l "${FREMOR_CONFIG_OUTYAML}" || return
fi


#### YAML
#### ----
# fremor yaml itself doesn't really create output, fremor run does
# that output directory is passed through the yaml to fremor run
#FREMOR_YAML_OUTDIR=${OUTPUT_CMORIZED_DATA_DIR}/fremor_yaml_outdir
if [[ "${CHECK_YAML}" -eq 1 ]]; then
	echo "not checking fremor yaml"
else

	#echo "setting up fremor yaml check, clobbering any prev made output"
	rm -rf "${FREMOR_YAML_OUTDIR}" || echo "no yaml output to remove, OK!" && mkdir "${FREMOR_YAML_OUTDIR}"

	echo "running fremor yaml"
	echo "fremor -vv yaml --yamlfile ${FREMOR_CONFIG_OUTYAML} --start ${PP_START} --stop ${PP_STOP} --print_cli_call --run_strict --run_one --dry_run"
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
	ls ${OUTPUT_CMORIZED_DATA_DIR}/*/*/CMOR_tmp/*nc  | grep -v '\.ps\.' | grep -v '\.phalf\.' | grep -v -c '\.pfull\.'
fi


# end where we began
cd "${WORKING_CWD}" || return


##### RUN - NOT NEEDED HERE, use `fremor yaml --print-cli-call --dry-run` and copy-paste the output
##### ---
#FREMOR_RUN_OUTDIR=${WORKING_CWD}/fremor_run_outdir
#if [[ "${CHECK_RUN}" -eq 1 ]]; then
#	echo "not checking fremor run"
#else
#	echo "setting up fremor run check, clobbering any prev made output"
#	rm -rf "${FREMOR_RUN_OUTDIR}" || echo "no run output to remove, OK!" && mkdir "${FREMOR_RUN_OUTDIR}"
#
#	echo "running fremor run"
#	echo "fremor run <ARGS>"
#
#	#echo "checking that fremor run's output exists"
#	#ls -l
#fi

##### RESOLVE - FOR A FUTURE UPDATE TO FRE-CLI TODOTODOTODOTODOTODO
##### -------
#FREMOR_RESOLVE_OUTDIR=${WORKING_CWD}/fremor_resolve_outdir
#if [[ "${CHECK_RESOLVE}" -eq 1 ]]; then
#	echo "not checking fremor resolve"
#else
#	echo "setting up fremor resolve check, clobbering any prev made output"
#	rm -rf "${FREMOR_RESOLVE_OUTDIR}" || echo "no resolve output to remove, OK!" && mkdir "${FREMOR_RESOLVE_OUTDIR}"
#
#	echo "running fremor resolve"
#	echo "fremor resolve <ARGS>"
#
#	#echo "checking that fremor resolve's output exists"
#	#ls -l
#fi
