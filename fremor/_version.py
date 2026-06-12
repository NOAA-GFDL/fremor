"""
version info for fremor, isolated to avoid importing heavy dependencies at build time
"""

import os
version = os.getenv("GIT_DESCRIBE_TAG", "0.9.6.post")
__version__ = version
