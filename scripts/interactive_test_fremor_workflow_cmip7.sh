#!/bin/bash -u

# this script should be sourced

#### INPUT CONFIG
## check flags, 0 --> yes, 1 --> no
CHECK_INIT=1
CHECK_VARLIST=1
CHECK_FIND=1
CHECK_CONFIG=1
CHECK_MAP=1
CHECK_STAGE=1
CHECK_YAML=0
CHECK_CHECK=1

# TODO requires fre-cli integration
#CHECK_RESOLVE=1

# no need for this, because using 'fremor run' helps with isolating 'fremor yaml' problems, see '--print-cli-call'
#CHECK_RUN=1 


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
			# First argument, the command itself
			printf "%s" "$display_arg"
		elif [[ "$display_arg" == -* ]]; then
			# If it starts with '-', it's a flag, wrap to a new line with a backslash
			printf " \\\\\n    %s" "$display_arg"
		else
			# If not above two, it's a subcommand or flag value, append to the line
			printf " %s" "$display_arg"
		fi
	done
	printf "\n"

	# Execute the command
	"$@"
}

rm_then_mkdir(){
	local dir="${1}"
	rm -rf "${dir}" || echo "no output to remove, OK!" && mkdir "${dir}"
}


FREMOR_INSTALL_E=/home/$USER/Working/fremor
echo "fremor installed (with -e) in ${FREMOR_INSTALL_E}"

WORKING_CWD=$PWD


## INPUTS most files copied over from /archive/oar.gfdl.bgrp-account/
BASE_SRC_DIR=/work/$USER/
CMIP7_ESM_DECK_PATH_GUTS=CMIP7/ESM4/DECK/ESM4.5-
BASE_TARG_DIR=${BASE_SRC_DIR}${CMIP7_ESM_DECK_PATH_GUTS}

ESM_KIND=historical-defobbfix #picontrol #historical #
TAIL_TARG_DIR=/gfdl.ncrc6-intel25-prod-openmp/pp/
TARG_FREBRONX_PPDIR=${BASE_TARG_DIR}${ESM_KIND}${TAIL_TARG_DIR}

# years to target for beginning/ending of processing, used for filtering files
PP_START=1869
PP_STOP=1869


## MAIN OUTPUTS: for CMORIZED OUTPUT FILES /net2 can be a good choice, upwards of 1 TB of storage
OUTPUT_CMORIZED_DATA_DIR=/net2/$USER/Working/fremor_testing_cmip7_${ESM_KIND}

#### ACTION
echo "cd'ing to working dir ${WORKING_CWD}"
cd "${WORKING_CWD}" || return

#### INIT
FREMOR_INIT_OUTDIR=${WORKING_CWD}/fremor_init_${ESM_KIND}_outdir
FREMOR_INIT_LOGFILE=${FREMOR_INIT_OUTDIR}/CHECK_INIT.log
CMIP7_TABLES=${FREMOR_INIT_OUTDIR}/cmip7-cmor-tables-main/tables
USER_CONFIG=${FREMOR_INIT_OUTDIR}/CMIP7_user_input.json
DONT_REMOVE_THISONE=${FREMOR_INIT_OUTDIR}/CMIP7_user_input_${ESM_KIND}.json
if [[ "${CHECK_INIT}" -eq 1 ]]; then
	echo "not checking fremor init"
else

	# so i don't have to keep filling this out every iteration
	echo "attempting to spare ${DONT_REMOVE_THISONE} from cleanup..."
	mv ${DONT_REMOVE_THISONE} .. || echo "${DONT_REMOVE_THISONE} does not exist"

	echo "setting up fremor init check, clobbering any prev made output [tables, user config template, and logfile]"
	rm_then_mkdir "${FREMOR_INIT_OUTDIR}"

	# so i don't have to keep filling this out every iteration
	echo "attempting to restore ${DONT_REMOVE_THISONE} post-cleanup..."
	mv ../CMIP7_user_input_${ESM_KIND}.json ${FREMOR_INIT_OUTDIR} || echo "DNE: ../CMIP7_user_input_${ESM_KIND}.json"

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
CHUNK=1yr #4yr #5yr #
FREQ=monthly #annual #
PPCOMP_VARLIST_ONLY=atmos_cmip
COMPONENT_DIR_STUB_VARLIST_ONLY=${PPCOMP_VARLIST_ONLY}/ts/${FRE}/${CHUNK}/
TEST_COMPONENT_DIR=${TARG_FREBRONX_PPDIR}${COMPONENT_DIR_STUB_VARLIST_ONLY} # for varlist testing only, random

FREMOR_VARLIST_OUTDIR=${WORKING_CWD}/fremor_varlist_${ESM_KIND}_outdir
FREMOR_VARLIST_OUTPUT=${FREMOR_VARLIST_OUTDIR}/foo.list
FREMOR_VARLIST_LOGFILE=${FREMOR_VARLIST_OUTDIR}/CHECK_VARLIST.log
if [[ "${CHECK_VARLIST}" -eq 1 ]]; then
	echo "not checking fremor varlist"
else
	echo "setting up fremor varlist check, clobbering any prev made output [one pp component variable list, and logfile]"
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
FREMOR_FIND_OUTDIR=${WORKING_CWD}/fremor_find_${ESM_KIND}_outdir
FREMOR_FIND_LOGFILE=${FREMOR_FIND_OUTDIR}/CHECK_FIND.log
if [[ "${CHECK_FIND}" -eq 1 ]]; then
	echo "not checking fremor find"
else
	echo "setting up fremor find check, clobbering any prev made output [logfile only]"
	rm_then_mkdir "${FREMOR_FIND_OUTDIR}"

	echo "running fremor find"
	echo_and_run fremor -vvv -l "${FREMOR_FIND_LOGFILE}" find \
				 --table_config_dir "${CMIP7_TABLES}" \
				 --varlist "${FREMOR_VARLIST_OUTPUT}"
fi



#### CONFIG
FREMOR_CONFIG_OUTDIR=${WORKING_CWD}/fremor_config_${ESM_KIND}_outdir
FREMOR_CONFIG_OUTYAML=${FREMOR_CONFIG_OUTDIR}/cmor.yaml
FREMOR_CONFIG_LOGFILE=${FREMOR_CONFIG_OUTDIR}/CHECK_CONFIG.log
FREMOR_CONFIG_VARLISTOUTDIR=${FREMOR_CONFIG_OUTDIR}/config_varlistoutdir
if [[ "${CHECK_CONFIG}" -eq 1 ]]; then
	echo "not checking fremor config"
else
	echo "setting up fremor config check, clobbering any prev made output [cmor.yaml, multiple variable lists, logfile]"
	rm_then_mkdir "${FREMOR_CONFIG_OUTDIR}"

	echo "running fremor config"
	echo_and_run fremor -vvv -l "${FREMOR_CONFIG_LOGFILE}" config \
				 --pp_dir "${TARG_FREBRONX_PPDIR}" \
				 --mip_tables_dir "${CMIP7_TABLES}" \
				 --exp_config "${DONT_REMOVE_THISONE}" \
				 --output_yaml "${FREMOR_CONFIG_OUTYAML}" \
				 --output_dir "${OUTPUT_CMORIZED_DATA_DIR}" \
				 --varlist_dir "${FREMOR_CONFIG_VARLISTOUTDIR}" \
				 --strict_varlist \
				 --overwrite

#				 --grid "g225" \
#				 --calendar "julian" \
#				 --pp_comp_glob "*land*" \


	echo "checking that fremor config's output exists, return if not"
	ls -l "${FREMOR_CONFIG_OUTYAML}" || return
fi



#### MAP
NCINFO_BIN=$(which ncinfo)
FREMOR_MAP_OUTDIR=${WORKING_CWD}/fremor_map_${ESM_KIND}_outdir
FREMOR_MAP_LOGFILE=${FREMOR_MAP_OUTDIR}/CHECK_MAP.log
if [[ "${CHECK_MAP}" -eq 1 ]]; then
	echo "not checking fremor map"
else
	echo "setting up fremor map check, clobbering any prev made output [logfile]"	
	rm_then_mkdir "${FREMOR_MAP_OUTDIR}"

	echo "running fremor map"
	echo_and_run fremor -vv -l "${FREMOR_MAP_LOGFILE}" map \
				 --yamlfile "${FREMOR_CONFIG_OUTYAML}" \
				 --dmls_bin "${DMLS_BIN}" \
				 --ncinfo_bin "${NCINFO_BIN}"
fi

#### STAGE
DMGET_BIN=$(which dmget)
FREMOR_STAGE_OUTDIR=${WORKING_CWD}/fremor_stage_${ESM_KIND}_outdir
FREMOR_STAGE_LOGFILE=${FREMOR_STAGE_OUTDIR}/CHECK_STAGE.log
if [[ "${CHECK_STAGE}" -eq 1 ]]; then
	echo "not checking fremor stage"
else
	echo "setting up fremor stage check, clobbering any prev made output [logfile]"	
	rm_then_mkdir "${FREMOR_STAGE_OUTDIR}"

	echo "running fremor stage"
	echo_and_run fremor -vvv -l "${FREMOR_STAGE_LOGFILE}" stage \
				 --yamlfile "${FREMOR_CONFIG_OUTYAML}" \
				 --start "${PP_START}" \
				 --stop "${PP_STOP}" \
				 --dmget_bin "${DMGET_BIN}"
#				 --dry_run \

fi



#### YAML, also RUN, because YAML calls RUN
FREMOR_YAML_OUTDIR=${WORKING_CWD}/fremor_yaml_${ESM_KIND}_outdir
FREMOR_YAML_LOGFILE=${FREMOR_YAML_OUTDIR}/CHECK_YAML.log
if [[ "${CHECK_YAML}" -eq 1 ]]; then
	echo "not checking fremor yaml"
else
	echo "setting up fremor yaml check, clobbering any prev made LOGGING output [logfile]"	
	rm_then_mkdir "${FREMOR_YAML_OUTDIR}"

	echo "running fremor yaml"
	echo_and_run fremor -vv -l "${FREMOR_YAML_LOGFILE}" yaml \
				 --yamlfile "${FREMOR_CONFIG_OUTYAML}" \
				 --start "${PP_START}" \
				 --stop "${PP_STOP}" \
				 --print_cli_call
#                 --run_one
#                 --run_strict \
#				 --dry_run

	echo "checking the output cmorized data directory for successfully created output"
	tree ${OUTPUT_CMORIZED_DATA_DIR}/*/*/CMIP/ || echo "problem!"

	echo "checking the output cmorized data directory for created output"
	echo "number of left-behind tmp outputs (without interpolated pressure style coordinate vars is:"
	ls ${OUTPUT_CMORIZED_DATA_DIR}/*/*/CMOR_tmp/*nc && echo "some variables didn't process completely or errored"
fi

#### CHECK
FREMOR_CHECK_OUTDIR=${WORKING_CWD}/fremor_check_${ESM_KIND}_outdir
FREMOR_CHECK_OUTREPORT=${FREMOR_CHECK_OUTDIR}/report.out
FREMOR_CHECK_LOGFILE=${FREMOR_CHECK_OUTDIR}/CHECK_CHECK.log
DMLS_BIN=$(which dmls)
if [[ "${CHECK_CHECK}" -eq 1 ]]; then
	echo "not checking fremor check"
else
	echo "setting up fremor check check, clobbering any prev made output [report.out, and logfile]"	
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








# end where we began
cd "${WORKING_CWD}" || return
