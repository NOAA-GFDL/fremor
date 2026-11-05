"""
Calendar-type integration tests for cmor_run_subtool
=====================================================

These tests verify that cmor_run_subtool correctly handles the
``calendar_type`` parameter:

- When a calendar_type is provided  → it is passed on, normalized, as a dataset override.
- When calendar_type is None        → no calendar override is passed on.

Either way the experiment config file itself is left untouched.

Heavy internal work (file globbing, CMORization, outpath updating) is
mocked so the tests focus exclusively on the calendar-type routing logic.
"""

import json
from typing import NamedTuple
from unittest.mock import patch

from fremor.cmor_mixer import cmor_run_subtool


class CalendarTestInputs(NamedTuple):
    """Files and mock inputs shared by the calendar-routing tests."""

    exp_config_file: str
    var_list_file: str
    table_config_file: str
    fake_nc_filenames: list[str]


# ---------------------------------------------------------------------------
# shared input builder – minimal JSON configs written to tmp_path
# ---------------------------------------------------------------------------

def _make_calendar_test_inputs(tmp_path):
    """Write the config files and fake NetCDF paths used by both calendar tests."""
    exp_config = {
        "mip_era": "cmip6",
        "calendar": "360_day",
        "grid": "test_grid",
        "grid_label": "gn",
        "nominal_resolution": "1 km",
        "outpath": ".",
    }
    exp_config_file = tmp_path / "exp_config.json"
    exp_config_file.write_text(json.dumps(exp_config))

    var_list_file = tmp_path / "var_list.json"
    var_list_file.write_text(json.dumps({"temp": "temp", "salt": "salt"}))

    table_config = {
        "variable_entry": {
            "temp": {"frequency": "mon"},
            "salt": {"frequency": "mon"},
        }
    }
    table_config_file = tmp_path / "table_config.json"
    table_config_file.write_text(json.dumps(table_config))

    fake_nc_filenames = [
        str(tmp_path / "mock_test_file.00010101-00041231.temp.nc"),
        str(tmp_path / "mock_test_file.00010101-00041231.salt.nc"),
    ]
    return CalendarTestInputs(
        str(exp_config_file),
        str(var_list_file),
        str(table_config_file),
        fake_nc_filenames,
    )


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

# Shared set of mocks – everything that would touch the filesystem or CMOR
_MOCKS = [
    "fremor.cmor_mixer.cmorize_all_variables_in_dir",
    "fremor.cmor_mixer.glob.glob",
]


@patch(_MOCKS[0])
@patch(_MOCKS[1])
def test_cmor_run_w_cal_type(
    mock_glob,
    mock_cmorize,
    tmp_path
):
    """When calendar_type is provided, it is passed on as a dataset override."""
    calendar_test_inputs = _make_calendar_test_inputs(tmp_path)

    mock_glob.return_value = calendar_test_inputs.fake_nc_filenames
    mock_cmorize.return_value = 0
    calendar_type = "noleap"

    cmor_run_subtool(
        indir            = str(tmp_path),
        json_var_list    = calendar_test_inputs.var_list_file,
        json_table_config = calendar_test_inputs.table_config_file,
        json_exp_config  = calendar_test_inputs.exp_config_file,
        outdir           = str(tmp_path / "output"),
        calendar_type    = calendar_type
    )

    assert mock_cmorize.call_args.kwargs["exp_overrides"] == {"calendar": "365_day"}
    with open(calendar_test_inputs.exp_config_file, encoding="utf-8") as handle:
        assert json.load(handle)["calendar"] == "360_day"


@patch(_MOCKS[0])
@patch(_MOCKS[1])
def test_cmor_run_no_cal_type(
    mock_glob,
    mock_cmorize,
    tmp_path
):
    """When calendar_type is None (default), no calendar override is passed on."""
    calendar_test_inputs = _make_calendar_test_inputs(tmp_path)

    mock_glob.return_value = calendar_test_inputs.fake_nc_filenames
    mock_cmorize.return_value = 0

    cmor_run_subtool(
        indir            = str(tmp_path),
        json_var_list    = calendar_test_inputs.var_list_file,
        json_table_config = calendar_test_inputs.table_config_file,
        json_exp_config  = calendar_test_inputs.exp_config_file,
        outdir           = str(tmp_path / "output"),
        calendar_type    = None
    )

    assert "calendar" not in mock_cmorize.call_args.kwargs["exp_overrides"]
