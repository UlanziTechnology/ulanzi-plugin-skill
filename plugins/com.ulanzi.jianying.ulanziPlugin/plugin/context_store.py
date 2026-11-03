"""Thread-safe per-slot settings storage."""

from copy import deepcopy
from threading import RLock


class ContextStore:
    def __init__(self):
        self._lock = RLock()
        self._settings = {}

    def set(self, context, settings):
        if not context:
            return {}
        with self._lock:
            self._settings[context] = deepcopy(settings or {})
            return deepcopy(self._settings[context])

    def update(self, context, settings):
        if not context:
            return {}
        with self._lock:
            current = self._settings.setdefault(context, {})
            current.update(deepcopy(settings or {}))
            return deepcopy(current)

    def get(self, context, default=None):
        with self._lock:
            return deepcopy(self._settings.get(context, default or {}))

    def remove(self, context):
        with self._lock:
            return self._settings.pop(context, None)
