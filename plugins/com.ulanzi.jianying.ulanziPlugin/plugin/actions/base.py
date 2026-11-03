"""Common Action lifecycle and feedback helpers."""

from copy import deepcopy


class BaseAction:
    defaults = {"requireActive": True}
    feedback_icon = ""

    def __init__(self, context, api, backend, settings=None):
        self.context = context
        self.api = api
        self.backend = backend
        self.active = True
        # Diagnostic-only snapshot populated by ensure_target().  Timeline
        # logging reads this value so it can report the result without asking
        # the operating system a second time.
        self._last_target_active = None
        self.settings = deepcopy(self.defaults)
        self.apply_settings(settings or {})

    def apply_settings(self, settings):
        self.settings.update(settings or {})

    def set_active(self, active):
        self.active = bool(active)

    def ensure_target(self):
        if not self.settings.get("requireActive", True):
            self._last_target_active = None
            return True
        target_active = self.backend.target_is_active()
        self._last_target_active = bool(target_active)
        if target_active:
            return True
        try:
            self.api.show_alert(self.context)
        except Exception:
            pass
        return False

    def feedback(self, title, value=None):
        try:
            display_text = value if value is not None else title
            layout = {
                "title": {"text": str(display_text), "enabled": True},
            }
            if self.feedback_icon:
                layout["icon"] = {"value": self.feedback_icon, "enabled": True}
            self.api.set_feedback(
                self.context,
                layout,
            )
        except Exception as exc:
            print(f"feedback failed for {self.context}: {exc}")

    def execute(self):
        return False

    def destroy(self):
        return None
