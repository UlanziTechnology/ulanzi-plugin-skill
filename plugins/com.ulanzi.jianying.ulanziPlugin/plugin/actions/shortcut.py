"""Configurable keypad shortcut Action."""

from .base import BaseAction
from shortcut_catalog import resolve_shortcut, shortcut_icon_path


class ShortcutAction(BaseAction):
    defaults = {"requireActive": True, "command": "split"}

    def apply_settings(self, settings):
        super().apply_settings(settings)
        self._update_icon()

    def _update_icon(self):
        icon_path = shortcut_icon_path(self.settings.get("command"))
        try:
            self.api.set_path_icon(self.context, icon_path)
        except Exception as exc:
            print(f"shortcut icon update failed for {self.context}: {exc}")

    def execute(self):
        if not self.ensure_target():
            return False
        command = resolve_shortcut(self.settings.get("command"))
        hotkey = command.for_current_os()
        if not hotkey:
            self.api.show_alert(self.context)
            return False
        sender = self.backend.execute_shortcut
        if command.key in {"previous_marker", "next_marker"}:
            sender = getattr(self.backend, "execute_marker_shortcut", sender)
        return sender(hotkey)
