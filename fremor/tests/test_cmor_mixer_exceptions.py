import os
from pathlib import Path

import pytest

from fremor import cmor_mixer

def test_cmorize_target_var_files_chdir_exception(monkeypatch, tmp_path):
    """Cover the exception block where os.chdir fails in cmorize_target_var_files."""
    
    # Force os.chdir to raise an exception
    def mock_chdir(path):
        raise PermissionError("mocked permission denied")
    monkeypatch.setattr(os, 'chdir', mock_chdir)

    # Mock the directory creation and existence checks so it reaches the chdir attempt
    monkeypatch.setattr(cmor_mixer, 'create_tmp_dir', lambda *args: str(tmp_path)+"/mock/tmp" )
    monkeypatch.setattr("pathlib.Path.exists", lambda self: True)

    Path(str(tmp_path)+'/set.20000101.tas.nc').touch() # avoid error condition not trying to test
    Path(str(tmp_path)+'/set.20000101.ps.nc').touch() # avoid error condition not trying to test
    Path(str(tmp_path)+'/mock/tmp/').mkdir(parents=True,exist_ok=True) # avoid a copy error to an area where we can't copy to
    
    # Call the function and assert it catches the PermissionError and raises the OSError
    with pytest.raises(OSError, match="could not chdir to "+str(tmp_path)+"/mock/tmp/"):
        cmor_mixer.cmorize_target_var_files(
            indir=tmp_path, target_var="tas", local_var="tas", 
            iso_datetime_range_arr=["20000101"], name_of_set="set", 
            json_exp_config="dummy.json", outdir="."
        )
