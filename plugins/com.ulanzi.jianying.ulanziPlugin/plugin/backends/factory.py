"""Select the automation backend without leaking platform branches into Actions."""

import sys

from .base import AutomationBackend
from .macos import MacJianyingBackend


def create_backend(api):
    if sys.platform == "darwin":
        return MacJianyingBackend(api)
    if sys.platform == "win32":
        from .windows import WindowsJianyingBackend

        return WindowsJianyingBackend(api)
    return AutomationBackend(api)
