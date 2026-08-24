#!/bin/bash -u
# this script should be sourced

# piControl results --> /net2/inl/Working/fremor_testing_June8_2026_piControl_output
# piControl script/config --> /net2/inl/Working/fremor_testing_June8_2026_piControl_output

# for historical, we are going to test targeting archive files for e.g. variable list, configuration writing, etc.



#### INPUT CONFIG
#### ------------
## check flags, 0 --> yes, 1 --> no
CHECK_INIT=1 # GOOD
CHECK_VARLIST=1 # GOOD
CHECK_FIND=1 # GOOD
CHECK_CONFIG=1 # GOOD
CHECK_YAML=0 #
CHECK_RUN=1 #
CHECK_RESOLVE=1 #


## FYI which fremor i'm using, not strictly used nor necessary.
FREMOR_INSTALL_E=/home/inl/Working/fremor
echo "fremor editably installed in ${FREMOR_INSTALL_E}"

## starting directory
WORKING_CWD=/home/inl/Working/fremor_testing_forcmip6plus_July6_2026/

## output for CMORized data, do not use home nor nbhome as it's a lot
OUTPUT_CMORIZED_DATA_DIR=/net2/inl/Working/fremor_testing_forcmip6plus_July6_2026/

## input directory stuff
# /archive/c1f/am5/2022.01/c96L33_am5a0_ceresmip/gfdl.ncrc5-intel23-classic-prod-openmp/pp
BASE_SRC_DIR=/archive/c1f/
CMIP7_ESM_DECK_PATH_GUTS=am5/2022.01/c96L33_am5a0_ceresmip
ESM_KIND=
TAIL_TARG_DIR=/gfdl.ncrc5-intel23-classic-prod-openmp/pp/
COMPONENT_DIR_STUB_VARLIST_ONLY=atmos_cmip/ts/monthly/43yr/

PP_START=1979
PP_STOP=2021



#### DERIVED CONFIG
#### --------------
BASE_TARG_DIR=${BASE_SRC_DIR}${CMIP7_ESM_DECK_PATH_GUTS}
echo "base target directory is: ${BASE_TARG_DIR}"

TARG_FREBRONX_PPDIR=${BASE_TARG_DIR}${ESM_KIND}${TAIL_TARG_DIR}
echo "target FREBRONX pp dir will be : ${TARG_FREBRONX_PPDIR}"

TEST_COMPONENT_DIR=${TARG_FREBRONX_PPDIR}${COMPONENT_DIR_STUB_VARLIST_ONLY} # for varlist testing only, random
echo "test component(s) for fremor variable listing will be : ${TEST_COMPONENT_DIR}"

#### ACTION
#### ------
# from ~/Working, this is not technically required, but assists with org
echo "cd'ing to working dir ${WORKING_CWD}"
cd "${WORKING_CWD}" || return



#### INIT
#### ----
# NOTE: the required input data is not required for this step, and neither is the CWD/editable info above, it's just convenience scaffolding
FREMOR_INIT_OUTDIR=${WORKING_CWD}/fremor_init_outdir
USER_CONFIG=${FREMOR_INIT_OUTDIR}/CMIP6plus_user_input.json
CMIP6PLUS_TABLES=${FREMOR_INIT_OUTDIR}/mip-cmor-tables-main/Tables
if [[ "${CHECK_INIT}" -eq 1 ]]; then
    echo "not checking fremor init"
else
    # fremor init - works, check!
    echo "setting up fremor init check, clobbering any prev made output"
    rm -rf "${FREMOR_INIT_OUTDIR}" || echo "no init output to remove, OK!" && mkdir "${FREMOR_INIT_OUTDIR}" && mkdir "${CMIP6PLUS_TABLES}"

    echo "running fremor init"
    echo "fremor init --mip_era cmip6plus --exp_config ${USER_CONFIG} -t ${FREMOR_INIT_OUTDIR} --fast"
    fremor -vv init \
           --mip_era cmip6plus \
           --exp_config "${USER_CONFIG}" \
           -t "${FREMOR_INIT_OUTDIR}" \
		   --fast

    echo "checking that fremor init's output exists, return if not"
    ls -l "${USER_CONFIG}" && echo "found user config!" || return
    ls -l "${CMIP6PLUS_TABLES}" && echo "found a tabledir with contents!" || return
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
    echo "fremor -vv varlist --dir_targ ${TARG_FREBRONX_PPDIR} -o ${FREMOR_VARLIST_OUTPUT}"
    fremor -vv varlist \
           --dir_targ "${TEST_COMPONENT_DIR}" \
           -o "${FREMOR_VARLIST_OUTPUT}"

    echo "checking that fremor varlist's output exists, return if not"
    ls -l "${FREMOR_VARLIST_OUTPUT}" || return
    #ls -ld
fi



#### FIND
#### ----
if [[ "${CHECK_FIND}" -eq 1 ]]; then
    echo "not checking fremor find"
else
    echo "setting up fremor find check, which does not produce any output (no dir setup necessary)"

    echo "running fremor find"
    echo "fremor -v find --table_config_dir ${CMIP6PLUS_TABLES} --varlist ${FREMOR_VARLIST_OUTPUT}"
    fremor -v find \
           --table_config_dir "${CMIP6PLUS_TABLES}" \
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
    echo "fremor -v config --pp_dir ${TARG_FREBRONX_PPDIR} --mip_tables_dir ${CMIP6PLUS_TABLES} --exp_config ${USER_CONFIG} --mip_era cmip6plus --freq monthly --chunk 5yr --grid g999 --calendar noleap --output_yaml ${FREMOR_CONFIG_OUTYAML} --output_dir ${OUTPUT_CMORIZED_DATA_DIR} --varlist_dir ${FREMOR_VARLIST_OUTDIR} --strict_varlist --overwrite"

    fremor -vv config \
           --pp_dir "${TARG_FREBRONX_PPDIR}" \
           --mip_tables_dir "${CMIP6PLUS_TABLES}" \
           --exp_config "${USER_CONFIG}" \
           --mip_era "cmip6plus" \
           --freq "monthly" \
           --chunk "43yr" \
           --grid "g999" \
           --calendar "julian" \
           --output_yaml "${FREMOR_CONFIG_OUTYAML}" \
           --output_dir "${OUTPUT_CMORIZED_DATA_DIR}" \
           --varlist_dir "${FREMOR_VARLIST_OUTDIR}" \
           --strict_varlist \
           --pp_comp_glob "*_cmip*" \
           --overwrite


    echo "checking that fremor config's output exists, return if not"
    ls -l "${FREMOR_CONFIG_OUTYAML}" || return
fi


#### YAML
#### ----
# fremor yaml itself doesn't really create output, fremor run does
# that output directory is passed through the yaml to fremor run
#FREMOR_YAML_OUTDIR=${OUTPUT_CMORIZED_DATA_DIR}/fremor_yaml_outdir
if [[ "${CHECK_YAML}" -eq 1 ]]; then
    echo "not checking fremor yaml"
else
    ## lets not do this for this part yet
    #echo "setting up fremor yaml check, clobbering any prev made output"
    #rm -rf "${FREMOR_YAML_OUTDIR}" || echo "no yaml output to remove, OK!" && mkdir "${FREMOR_YAML_OUTDIR}"


    echo "running fremor yaml"
    echo "fremor -vv yaml --yamlfile ${FREMOR_CONFIG_OUTYAML} --start ${PP_START} --stop ${PP_STOP} --print_cli_call --run_strict --run_one --dry_run"
    fremor -vv yaml \
           --yamlfile "${FREMOR_CONFIG_OUTYAML}" \
           --start "${PP_START}" \
           --stop "${PP_STOP}"
#           --run_strict \
           --run_one
#           --dry_run

    echo "checking the output cmorized data directory for successfully created output"
    tree ${OUTPUT_CMORIZED_DATA_DIR}/*/*/CMIP/

    echo "checking the output cmorized data directory for created output"
    echo "number of left-behind tmp outputs (without interpolated pressure style coordinate vars is:"
    ls ${OUTPUT_CMORIZED_DATA_DIR}/*/*/CMOR_tmp/*nc  | grep -v '\.ps\.' | grep -v '\.phalf\.' | grep -v -c '\.pfull\.'
fi
#
#
#
##### RESOLVE
##### -------
#FREMOR_RESOLVE_OUTDIR=${WORKING_CWD}/fremor_resolve_outdir
#if [[ "${CHECK_RESOLVE}" -eq 1 ]]; then
#    echo "not checking fremor resolve"
#else
#    echo "setting up fremor resolve check, clobbering any prev made output"
#    rm -rf "${FREMOR_RESOLVE_OUTDIR}" || echo "no resolve output to remove, OK!" && mkdir "${FREMOR_RESOLVE_OUTDIR}"
#
#    echo "running fremor resolve"
#    echo "fremor resolve <ARGS>"
#
#    #echo "checking that fremor resolve's output exists"
#    #ls -l
#fi
#
#
#
#
##### RUN
##### ---
#FREMOR_RUN_OUTDIR=${WORKING_CWD}/fremor_run_outdir
#if [[ "${CHECK_RUN}" -eq 1 ]]; then
#    echo "not checking fremor run"
#else
#    echo "setting up fremor run check, clobbering any prev made output"
#    rm -rf "${FREMOR_RUN_OUTDIR}" || echo "no run output to remove, OK!" && mkdir "${FREMOR_RUN_OUTDIR}"
#
#    echo "running fremor run"
#    echo "fremor run <ARGS>"
#
#    #echo "checking that fremor run's output exists"
#    #ls -l
#fi





# end where we began
cd "${WORKING_CWD}" || return

