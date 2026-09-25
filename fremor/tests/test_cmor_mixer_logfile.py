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

    assert caplog.messages == []
