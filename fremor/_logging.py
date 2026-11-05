"""Configure the package logging level and default output format."""

import logging


DDEBUG_LEVEL_NUM = 5
logging.DDEBUG = DDEBUG_LEVEL_NUM
logging.addLevelName(DDEBUG_LEVEL_NUM, 'DDEBUG')


def ddebug(self, message, *args, **kws):
    """Deep-debug logging for large arrays and dictionaries."""
    self.log(DDEBUG_LEVEL_NUM, message, *args, **kws)


logging.Logger.ddebug = ddebug

FORMAT = '[%(levelname)5s:%(filename)24s:%(funcName)24s] %(message)s'
logging.basicConfig(
    level=logging.WARNING,
    format=FORMAT,
    filename=None,
    encoding='utf-8',
)
