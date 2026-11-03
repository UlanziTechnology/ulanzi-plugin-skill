"""Backend contracts shared by macOS and Windows implementations."""

from dataclasses import dataclass
from collections import deque
from copy import deepcopy
from threading import Condition, Thread


@dataclass(frozen=True)
class AdjustmentResult:
    performed: bool
    approximate: bool = True
    reason: str = ""


class CoalescingAdjustmentQueue:
    """Serialize mouse drags and merge adjacent dial ticks to avoid UI lag."""

    def __init__(self, performer):
        self.performer = performer
        self._condition = Condition()
        self._pending = deque()
        self._worker = Thread(target=self._run, name="jianying-mouse", daemon=True)
        self._worker.start()

    @staticmethod
    def _identity(calibration, fine):
        calibration = calibration or {}
        hover = calibration.get("hoverTarget")
        hover = hover if isinstance(hover, dict) else {}

        def rect_identity(name):
            rect = hover.get(name)
            if not isinstance(rect, dict):
                return None
            return tuple(rect.get(key) for key in ("x", "y", "w", "h"))

        return (
            calibration.get("x"),
            calibration.get("y"),
            calibration.get("axis", "horizontal"),
            calibration.get("pixelsPerStep", 2),
            calibration.get("dragMode", "relative"),
            calibration.get("preClickX"),
            calibration.get("preClickY"),
            calibration.get("targetKey"),
            calibration.get("wheelMode"),
            hover.get("kind"),
            hover.get("key"),
            hover.get("controlType"),
            hover.get("windowHwnd"),
            hover.get("processId"),
            hover.get("dpi"),
            hover.get("scanVersion"),
            rect_identity("windowRect"),
            rect_identity("trackRect"),
            bool(calibration.get("_preserveTickOrder")),
            bool(fine),
        )

    def submit(self, calibration, ticks, fine=False, replace_pending_hover=False):
        try:
            ticks = float(ticks)
        except (TypeError, ValueError):
            return
        if abs(ticks) < 1e-9:
            return
        task = {
            "calibration": deepcopy(calibration or {}),
            "ticks": ticks,
            "fine": bool(fine),
        }
        with self._condition:
            same_target = bool(self._pending) and self._identity(
                self._pending[-1]["calibration"], self._pending[-1]["fine"]
            ) == self._identity(task["calibration"], task["fine"])
            preserve_order = bool(task["calibration"].get("_preserveTickOrder"))
            same_direction = same_target and self._pending[-1]["ticks"] * ticks > 0
            if same_target and (not preserve_order or same_direction):
                if task["calibration"].get("dragMode") == "absoluteWheel":
                    self._pending[-1] = task
                else:
                    # Preserve every originating encoder-event id while still
                    # coalescing the drag exactly as before. These private
                    # fields are diagnostic only and are ignored by identity.
                    incoming_ids = task["calibration"].get(
                        "_sliderDiagRequestIds", []
                    )
                    if incoming_ids:
                        existing_ids = self._pending[-1]["calibration"].setdefault(
                            "_sliderDiagRequestIds", []
                        )
                        existing_ids.extend(incoming_ids)
                    self._pending[-1]["ticks"] += task["ticks"]
                    if abs(self._pending[-1]["ticks"]) < 1e-9:
                        self._pending.pop()
            else:
                # Reversing a slider is not a target change. At a slider's
                # limit, +1 followed by -1 differs from a net zero adjustment.
                if replace_pending_hover and not same_target:
                    self._pending = deque(
                        pending for pending in self._pending
                        if not isinstance(
                            pending.get("calibration", {}).get("hoverTarget"), dict
                        )
                    )
                self._pending.append(task)
            while not preserve_order and len(self._pending) > 32:
                self._pending.popleft()
            self._condition.notify()

    def clear(self):
        with self._condition:
            self._pending.clear()

    def _run(self):
        while True:
            with self._condition:
                while not self._pending:
                    self._condition.wait()
                task = self._pending.popleft()
            try:
                self.performer(**task)
            except Exception as exc:
                print(f"mouse adjustment failed: {exc}")


class AutomationBackend:
    target_bundle_id = ""
    supports_basic_hover = False
    supports_hsl_hover = False
    supports_color_wheel_hover = False

    def __init__(self, api):
        self.api = api
        # Retain the transport acknowledgement for diagnostic callers.  The
        # public return value of execute_shortcut intentionally stays exactly
        # as before: a non-empty token is accepted even when the SDK send call
        # reports False.
        self._last_shortcut_api_result = None
        self._last_timeline_scroll_transport = None
        self._last_timeline_scroll_result = None

    def target_is_active(self):
        return True

    def target_is_running(self):
        """Return whether the target app is running, independent of focus."""
        return self.target_is_active()

    def target_version(self):
        return ""

    def automation_permission(self):
        return True

    def pointer_position(self):
        return None

    def enable_basic_hover(self, context=None):
        return False

    def disable_basic_hover(self, context=None):
        return None

    def basic_hover_target(self):
        return None

    def basic_hover_status(self):
        return "unsupported"

    def enable_hsl_hover(self, context=None):
        return False

    def disable_hsl_hover(self, context=None):
        return None

    def hsl_hover_target(self):
        return None

    def hsl_hover_status(self):
        return "unsupported"

    def enable_slider_hover(self, context=None):
        """Enable the unified Basic/HSL slider recognizer."""
        basic_enabled = self.enable_basic_hover(context)
        hsl_enabled = self.enable_hsl_hover(context)
        return bool(basic_enabled or hsl_enabled)

    def disable_slider_hover(self, context=None):
        self.disable_basic_hover(context)
        self.disable_hsl_hover(context)

    def slider_hover_target(self):
        return self.basic_hover_target() or self.hsl_hover_target()

    def slider_hover_status(self):
        statuses = (self.basic_hover_status(), self.hsl_hover_status())
        return next((status for status in statuses if status != "unsupported"), "unsupported")

    def enable_color_wheel_hover(self, context=None):
        return False

    def disable_color_wheel_hover(self, context=None):
        return None

    def color_wheel_hover_target(self):
        return None

    def color_wheel_hover_status(self):
        return "unsupported"

    def screen_capture_permission(self):
        return None

    def execute_shortcut(self, hotkey):
        if not hotkey:
            self._last_shortcut_api_result = None
            return False
        try:
            self._last_shortcut_api_result = self.api.hotkey(hotkey)
        except Exception as exc:
            self._last_shortcut_api_result = (
                f"exception:{type(exc).__name__}:{str(exc)[:80]}"
            )
            raise
        return True

    def execute_timeline_scroll(self, token, mode=None):
        """Send a timeline wheel token through the host on generic backends."""
        self._last_timeline_scroll_transport = "ud.hotkey"
        try:
            performed = self.execute_shortcut(token)
        except Exception:
            self._last_timeline_scroll_result = self._last_shortcut_api_result
            raise
        self._last_timeline_scroll_result = self._last_shortcut_api_result
        return performed

    def adjust_parameter(self, calibration, ticks, fine=False):
        return AdjustmentResult(False, reason="mouse automation unavailable")

    def reset_parameter(self, calibration):
        return AdjustmentResult(False, reason="mouse automation unavailable")

    def adjust_color_wheel(self, target, ticks, mode="diameter", sensitivity=1.0):
        return AdjustmentResult(False, reason="color wheel automation unavailable")

    def reset_color_wheel(self, target):
        return AdjustmentResult(False, reason="color wheel automation unavailable")
