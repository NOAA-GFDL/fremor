#!/bin/bash -u


#INPUT_YAML_PATH=/home/${USER}/Working/fremor/scripts/fremor_config_piControl_outdir/cmor.yaml
INPUT_YAML_PATH=/home/${USER}/Working/fremor/scripts/fremor_config_historical-defobbfix_outdir/cmor.yaml

comps=$(cat "${INPUT_YAML_PATH}" | grep component_name | sed "s/        - component_name: '//g" | sed "s/'//g" | sort -u)
echo "${comps}"

archive_pp_dir=$(cat "${INPUT_YAML_PATH}" | grep -A 1 pp_dir | grep -v pp_dir | sed "s/'//g")
echo ""
echo $archive_pp_dir


pp_dir_no_archive=$(echo ${archive_pp_dir} | cut -d'/' -f4-)
echo ""
echo $pp_dir_no_archive

work_pp_dir="/work/${USER}/${pp_dir_no_archive}"
echo ""
echo $work_pp_dir

# can get this from the yaml in theory but not sold it's worth it atm
DATA_SERIES_TYPE='ts'
CHUNK='1yr'
FREQ='monthly'
YYYYMM='185001'
for comp in $comps; do
	echo ""
	echo "component = ${comp}"
	echo ""
    mkdir --parents "${work_pp_dir}/${comp}/${DATA_SERIES_TYPE}/${FREQ}/${CHUNK}" && echo "dir_made" || "dir not made";
	echo ""	
	echo "listing files on archive for a quick copy..."
    files=$(ls ${archive_pp_dir}/${comp}/${DATA_SERIES_TYPE}/${FREQ}/${CHUNK}/*${YYYYMM}*.nc);
    for file in $files; do
		echo ""
        echo "dmcopy ${file} ${work_pp_dir}/${comp}/${DATA_SERIES_TYPE}/${FREQ}/${CHUNK}/$(basename ${file})"
		dmcopy ${file} ${work_pp_dir}/${comp}/${DATA_SERIES_TYPE}/${FREQ}/${CHUNK}/$(basename ${file})
    done;
	sleep 5s
done;
