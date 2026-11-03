"""Create and route Action instances by Studio context."""

from threading import RLock

from action_ids import action_kind
from actions.encoder import TimelineControlAction, create_adjustment_action
from actions.shortcut import ShortcutAction
from context_store import ContextStore


class ActionRouter:
    def __init__(self, api, backend):
        self.api = api
        self.backend = backend
        self.store = ContextStore()
        self.instances = {}
        self.kinds = {}
        self._lock = RLock()

    def _create(self, kind, context, settings):
        if kind == "shortcut":
            return ShortcutAction(context, self.api, self.backend, settings)
        if kind == "timeline_control":
            return TimelineControlAction(context, self.api, self.backend, settings)
        if kind in ("selected_slider", "color_wheels"):
            return create_adjustment_action(
                context, self.api, self.backend, kind, settings
            )
        raise ValueError(f"unknown action kind: {kind}")

    def add(self, message):
        context = (message or {}).get("context")
        kind = action_kind(message, self.api.decode_context)
        if not context or not kind:
            print(f"ignored add without action identity: {message}")
            return None
        settings = (
            message.get("settings")
            or message.get("param")
            or self.store.get(context)
            or {}
        )
        with self._lock:
            existing = self.instances.get(context)
            if existing is not None and self.kinds.get(context) == kind:
                existing.apply_settings(settings)
                instance = existing
            else:
                if existing is not None:
                    existing.destroy()
                instance = self._create(kind, context, settings)
                self.instances[context] = instance
                self.kinds[context] = kind
            self.store.set(context, settings)
        try:
            self.api.get_settings(context)
        except Exception:
            pass
        return instance

    def get(self, context):
        with self._lock:
            return self.instances.get(context)

    def ensure(self, message):
        context = (message or {}).get("context")
        return self.get(context) or self.add(message)

    def apply_settings(self, message):
        message = message or {}
        context = message.get("context")
        settings = message.get("settings") or message.get("param") or {}
        if not context:
            return None
        self.store.update(context, settings)
        instance = self.get(context)
        if instance is not None:
            instance.apply_settings(settings)
            if hasattr(instance, "_update_feedback"):
                instance._update_feedback()
        return instance

    def set_active(self, message):
        instance = self.get((message or {}).get("context"))
        if instance is not None:
            instance.set_active((message or {}).get("active", False))

    def remove(self, context):
        with self._lock:
            instance = self.instances.pop(context, None)
            self.kinds.pop(context, None)
            self.store.remove(context)
        if instance is not None:
            instance.destroy()

    def clear(self, message):
        items = (message or {}).get("param") or []
        for item in items:
            if isinstance(item, dict):
                self.remove(item.get("context"))
