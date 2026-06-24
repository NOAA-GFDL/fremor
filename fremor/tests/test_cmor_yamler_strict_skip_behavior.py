import pytest
import logging
from fremor import cmor_yamler



@pytest.fixture
def mock_yaml_environment(tmp_path):
    """Fixture to set up a minimal valid file structure and YAML for cmor_yaml_subtool."""
    yaml_file = tmp_path / "test.yaml"
    pp_dir = tmp_path / "pp"
    table_dir = tmp_path / "tables"
    outdir = tmp_path / "out"
    exp_json = tmp_path / "exp.json"
    table_json = table_dir / "CMIP6_Amon.json"

    # Create dummy files and directories so check_path_existence passes
    pp_dir.mkdir()
    table_dir.mkdir()
    outdir.mkdir()
    exp_json.touch()
    table_json.touch()

    # Create a minimal YAML configuration
    yaml_content = f"""
    cmor:
      mip_era: CMIP6
      directories:
        pp_dir: {pp_dir}
        table_dir: {table_dir}
        outdir: {outdir}
      exp_json: {exp_json}
      table_targets:
        - table_name: Amon
          freq: monthly
          gridding: null
          target_components:
            - component_name: atmos
              chunk: "P5Y"
              data_series_type: ts
              variable_list: "varlist.json"
    """
    yaml_file.write_text(yaml_content)
    return str(yaml_file)

@pytest.fixture
def mock_badyaml_environment(tmp_path):
    """Fixture to set up a minimal valid file structure and YAML for cmor_yaml_subtool. with no toplevel cmor key"""
    yaml_file = tmp_path / "test.yaml"
    pp_dir = tmp_path / "pp"
    table_dir = tmp_path / "tables"
    outdir = tmp_path / "out"
    exp_json = tmp_path / "exp.json"
    table_json = table_dir / "CMIP6_Amon.json"

    # Create dummy files and directories so check_path_existence passes
    pp_dir.mkdir()
    table_dir.mkdir()
    outdir.mkdir()
    exp_json.touch()
    table_json.touch()

    # Create a minimal YAML configuration
    yaml_content = f"""
    mip_era: CMIP6
    directories:
      pp_dir: {pp_dir}
      table_dir: {table_dir}
      outdir: {outdir}
    exp_json: {exp_json}
    table_targets:
      - table_name: Amon
        freq: monthly
        gridding: null
        target_components:
          - component_name: atmos
            chunk: "P5Y"
            data_series_type: ts
            variable_list: "varlist.json"
    """
    yaml_file.write_text(yaml_content)
    return str(yaml_file)

def test_cmor_yaml_subtool_exception_no_cmor_key(mock_badyaml_environment):
    # Run the function and capture the logs
    err_str_match=f"Invalid CMOR YAML file '{mock_badyaml_environment}': expected a top-level mapping containing a 'cmor' section."
    with pytest.raises(ValueError, match=err_str_match):
        cmor_yamler.cmor_yaml_subtool(yamlfile=mock_badyaml_environment, run_strict_mode=False)


def test_cmor_yaml_subtool_exception_non_strict(monkeypatch, mock_yaml_environment, caplog):
    """
    Cover the exception block where cmor_run_subtool fails,
    but run_strict_mode=False (the default), so it just logs a warning.
    """
    # Force cmor_run_subtool to raise an Exception
    def mock_run_subtool(*args, **kwargs):
        raise Exception("simulated run_subtool failure")
    monkeypatch.setattr(cmor_yamler, "cmor_run_subtool", mock_run_subtool)

    # Run the function and capture the logs
    with caplog.at_level(logging.WARNING):
        cmor_yamler.cmor_yaml_subtool(yamlfile=mock_yaml_environment, run_strict_mode=False)

    # Verify the uncovered warning line was hit
    assert "cmor_run_subtool failed for (Amon, atmos), skipping: simulated run_subtool failure" in caplog.text

def test_cmor_yaml_subtool_exception_strict_mode(monkeypatch, mock_yaml_environment):
    """
    Cover the exception block where cmor_run_subtool fails,
    and run_strict_mode=True, forcing it to re-raise the exception.
    """
    # Force cmor_run_subtool to raise an Exception
    def mock_run_subtool(*args, **kwargs):
        raise Exception("simulated strict failure")
    monkeypatch.setattr(cmor_yamler, "cmor_run_subtool", mock_run_subtool)

    # Assert that the exception actually bubbles up and stops execution
    with pytest.raises(Exception, match="simulated strict failure"):
        cmor_yamler.cmor_yaml_subtool(yamlfile=mock_yaml_environment, run_strict_mode=True)
