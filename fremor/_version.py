"""
version info for fremor, isolated to avoid importing heavy dependencies at build time
"""

import os
version = os.getenv("GIT_DESCRIBE_TAG", "1.0.0")
__version__ = version
