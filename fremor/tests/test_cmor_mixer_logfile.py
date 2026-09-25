"""Tests for CMOR logfile screen output handling."""
# pylint: disable=protected-access

import logging

from fremor import cmor_mixer


def test_pprint_cmor_logfile_at_info_level(tmp_path, caplog):
    """Verbose runs log the CMOR logfile contents and rename it beside the output file."""
    logfile = tmp_path / 'cmor_test.log'
    logfile.write_text('first line\nsecond line\n', encoding='utf-8')
    output_nc = tmp_path / 'cmor_output.nc'
    renamed_log = tmp_path / 'cmor_output.log'

    with caplog.at_level(logging.INFO, logger='fremor.cmor_mixer'):
        cmor_mixer._pprint_cmor_logfile(str(logfile), str(output_nc))

    assert 'first line' in caplog.messages
    assert 'second line' in caplog.messages
    assert not logfile.exists()
    assert renamed_log.exists()
    assert renamed_log.read_text(encoding='utf-8') == 'first line\nsecond line\n'


def test_pprint_cmor_logfile_suppressed_at_warning_level(tmp_path, caplog):
    """Default and quiet runs neither log CMOR logfile contents nor rename the file."""
    logfile = tmp_path / 'cmor_test.log'
    logfile.write_text('line\n', encoding='utf-8')
    output_nc = tmp_path / 'cmor_output.nc'
    renamed_log = tmp_path / 'cmor_output.log'

    with caplog.at_level(logging.WARNING, logger='fremor.cmor_mixer'):
        cmor_mixer._pprint_cmor_logfile(str(logfile), str(output_nc))

    assert caplog.messages == []
    assert logfile.exists()
    assert not renamed_log.exists()


def test_pprint_cmor_logfile_skips_none(caplog):
    """A None logfile remains valid and produces no log output."""
    with caplog.at_level(logging.INFO, logger='fremor.cmor_mixer'):
        cmor_mixer._pprint_cmor_logfile(None, None)

def test_pprint_cmor_logfile_missing_file(tmp_path, caplog):
    """A warning is logged if the provided logfile path does not exist."""
    missing_log = tmp_path / 'nonexistent.log'
    
    with caplog.at_level(logging.WARNING, logger='fremor.cmor_mixer'):
        cmor_mixer._pprint_cmor_logfile(str(missing_log), 'dummy_output.nc')
        
    assert 'cmor logfile requested for screen output but not found' in caplog.text


def test_pprint_cmor_logfile_no_filename(tmp_path, caplog):
    """If filename is None, the logfile contents are logged but the file is not renamed."""
    logfile = tmp_path / 'cmor_test.log'
    logfile.write_text('log content\n', encoding='utf-8')
    
    with caplog.at_level(logging.INFO, logger='fremor.cmor_mixer'):
        cmor_mixer._pprint_cmor_logfile(str(logfile), None)
        
    assert logfile.exists()  # Ensure the original file is left intact
    assert caplog.messages == []
