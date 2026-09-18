"""Tests for CMOR logfile screen output handling."""
# pylint: disable=protected-access

import logging

from fremor import cmor_mixer


def test_pprint_cmor_logfile_at_info_level(tmp_path, capsys):
    """Verbose runs print the logfile path and contents after CMOR teardown."""
    logfile = tmp_path / 'cmor_test.log'
    logfile.write_text('first line\nsecond line\n', encoding='utf-8')

    original_level = cmor_mixer.fre_logger.level
    cmor_mixer.fre_logger.setLevel(logging.INFO)
    try:
        cmor_mixer._pprint_cmor_logfile(str(logfile))
    finally:
        cmor_mixer.fre_logger.setLevel(original_level)

    out = capsys.readouterr().out
    assert str(logfile.resolve()) in out
    assert 'first line' in out
    assert 'second line' in out


def test_pprint_cmor_logfile_suppressed_at_warning_level(tmp_path, capsys):
    """Default and quiet runs do not print CMOR logfile contents to screen."""
    logfile = tmp_path / 'cmor_test.log'
    logfile.write_text('line\n', encoding='utf-8')

    original_level = cmor_mixer.fre_logger.level
    cmor_mixer.fre_logger.setLevel(logging.WARNING)
    try:
        cmor_mixer._pprint_cmor_logfile(str(logfile))
    finally:
        cmor_mixer.fre_logger.setLevel(original_level)

    assert capsys.readouterr().out == ''


def test_pprint_cmor_logfile_skips_none(capsys):
    """A None logfile remains valid and produces no screen output."""
    cmor_mixer._pprint_cmor_logfile(None)
    assert capsys.readouterr().out == ''
