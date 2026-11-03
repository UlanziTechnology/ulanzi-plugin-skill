"""Encoder state machines for timeline and adjustment controls."""

from dataclasses import dataclass
from copy import deepcopy
import json
import os
import sys
from threading import RLock, Timer
import time

from .base import BaseAction
from color_wheel import normalize_wheel_mode
from shortcut_catalog import resolve_timeline_input


@dataclass(frozen=True)
class Parameter:
    key: str
    label: str
    minimum: float = -100.0
    maximum: float = 100.0
    step: float = 1.0
    default: float = 0.0
    unit: str = ""
    group: str = ""


BASIC_PARAMETERS = (
    Parameter("temperature", "Temperature", group="Color"),
    Parameter("tint", "Tint", group="Color"),
    Parameter("saturation", "Saturation", group="Color"),
    Parameter("vibrance", "Vibrance", group="Color"),
    Parameter("exposure", "Exposure", -5, 5, 0.1, 0, " EV", "Light"),
    Parameter("brightness", "Brightness", group="Light"),
    Parameter("contrast", "Contrast", group="Light"),
    Parameter("highlights", "Highlights", group="Light"),
    Parameter("shadows", "Shadows", group="Light"),
    Parameter("whites", "Whites", group="Light"),
    Parameter("blacks", "Blacks", group="Light"),
    Parameter("sharpen", "Sharpen", 0, 100, 1, 0, "", "Effect"),
    Parameter("clarity", "Clarity", group="Effect"),
    Parameter("fade", "Fade", 0, 100, 1, 0, "", "Effect"),
    Parameter("vignette", "Vignette", group="Effect"),
    Parameter("grain", "Grain", 0, 100, 1, 0, "", "Effect"),
)

BASIC_HOVER_PARAMETERS = BASIC_PARAMETERS

HSL_PARAMETERS = (
    Parameter("hue", "Hue"),
    Parameter("saturation", "Saturation"),
    Parameter("luminance", "Luminance"),
)
HSL_HOVER_PARAMETERS = HSL_PARAMETERS

COLOR_WHEEL_PARAMETERS = (
    Parameter("intensity", "Intensity", 0, 100, 1, 100),
) + tuple(
    Parameter(f"{wheel}.{axis}", f"{wheel.title()} {label}")
    for wheel in ("shadows", "midtones", "highlights", "global")
    for axis, label in (("x", "Color X"), ("y", "Color Y"), ("luma", "Luminance"))
)


@dataclass(frozen=True)
class TimelineMode:
    key: str
    label: str


TIMELINE_MODES = (
    TimelineMode("frame_step", "Previous / next frame"),
    TimelineMode("track_height", "Track height"),
    TimelineMode("timeline_zoom", "Timeline zoom"),
    TimelineMode("vertical_scroll", "Timeline vertical scroll"),
    TimelineMode("horizontal_scroll", "Timeline horizontal scroll"),
    TimelineMode("large_seek", "Large timeline seek"),
    TimelineMode("marker", "Previous / next marker"),
    TimelineMode("split_point", "Previous / next split point"),
)
TIMELINE_MODE_IDS = tuple(mode.key for mode in TIMELINE_MODES)
TIMELINE_MODE_BY_ID = {mode.key: mode for mode in TIMELINE_MODES}
TIMELINE_FEEDBACK_ICON = "resources/icons/timeline.svg"


class PressableEncoderAction(BaseAction):
    long_press_seconds = 0.65
    # Some Windows Ulanzi Studio builds report one encoder press through more
    # than one host event path (run/keydown as well as dialdown/dialup).  Only
    # the hover-reset Actions opt into joining that event burst; timeline
    # buttons keep their existing rapid-press behaviour.
    dedupe_windows_host_press_events = False
    windows_press_dedupe_seconds = 0.35

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pressed_at = None
        self._rotated_while_pressed = False
        self._last_press_action_at = 0.0
        self._press_action_running = False
        self._dial_press_prehandled = False
        self._press_action_lock = RLock()

    def _windows_press_dedupe_enabled(self):
        return os.name == "nt" and self.dedupe_windows_host_press_events

    def _log_windows_press_event(self, source, state, reason="", elapsed=None):
        if not self._windows_press_dedupe_enabled():
            return
        elapsed_text = "-" if elapsed is None else f"{max(0.0, elapsed) * 1000.0:.0f}"
        print(
            "windows press event: "
            f"context={self.context} source={source} state={state} "
            f"reason={reason or '-'} elapsedMs={elapsed_text}"
        )

    def _perform_press_action(self, source, callback):
        if not self._windows_press_dedupe_enabled():
            result = callback()
            self._last_press_action_at = time.monotonic()
            return result

        now = time.monotonic()
        with self._press_action_lock:
            elapsed = now - self._last_press_action_at
            if self._press_action_running:
                self._log_windows_press_event(
                    source, "deduplicated", "action-running", elapsed
                )
                return False
            if elapsed < self.windows_press_dedupe_seconds:
                self._log_windows_press_event(
                    source, "deduplicated", "recent-action", elapsed
                )
                return False
            # Reserve the press before entering the reset callback. This also
            # closes the race where another host callback arrives while the
            # native helper is still running.
            self._press_action_running = True
            self._last_press_action_at = now
        self._log_windows_press_event(source, "started")
        failed = False
        try:
            return callback()
        except Exception:
            failed = True
            raise
        finally:
            with self._press_action_lock:
                self._last_press_action_at = time.monotonic()
                self._press_action_running = False
            self._log_windows_press_event(
                source, "failed" if failed else "completed"
            )

    def on_dial_down(self):
        now = time.monotonic()
        self._pressed_at = now
        self._rotated_while_pressed = False
        self._dial_press_prehandled = False
        if self._windows_press_dedupe_enabled():
            with self._press_action_lock:
                elapsed = now - self._last_press_action_at
                self._dial_press_prehandled = (
                    self._press_action_running
                    or elapsed < self.windows_press_dedupe_seconds
                )
            self._log_windows_press_event(
                "dialdown",
                "joined" if self._dial_press_prehandled else "armed",
                "prior-host-path" if self._dial_press_prehandled else "",
                elapsed,
            )
        return True

    def on_dial_up(self):
        if self._pressed_at is None:
            return self._perform_press_action("dialup", self.on_short_press)
        duration = time.monotonic() - self._pressed_at
        self._pressed_at = None
        if self._rotated_while_pressed:
            self._rotated_while_pressed = False
            self._dial_press_prehandled = False
            self._last_press_action_at = time.monotonic()
            self._log_windows_press_event(
                "dialup", "ignored", "rotated-while-pressed"
            )
            return True
        if self._dial_press_prehandled and self._windows_press_dedupe_enabled():
            self._dial_press_prehandled = False
            self._last_press_action_at = time.monotonic()
            self._log_windows_press_event(
                "dialup", "deduplicated", "handled-by-prior-host-path"
            )
            return True
        if duration >= self.long_press_seconds:
            callback = self.on_long_press
            source = "dialup-long"
        else:
            callback = self.on_short_press
            source = "dialup-short"
        return self._perform_press_action(source, callback)

    def execute(self):
        return self.execute_press_event("execute")

    def execute_press_event(self, source):
        now = time.monotonic()
        if self._pressed_at is not None:
            self._log_windows_press_event(
                source, "deduplicated", "dial-active",
                now - self._last_press_action_at,
            )
            return False
        if not self._windows_press_dedupe_enabled():
            # Preserve the original macOS/timeline semantics exactly: their
            # debounce timestamp is the time at which execute was received,
            # not the time at which the callback completed.
            if now - self._last_press_action_at < 0.18:
                return False
            result = self.on_short_press()
            self._last_press_action_at = now
            return result
        return self._perform_press_action(source, self.on_short_press)

    def on_short_press(self):
        return False

    def on_long_press(self):
        return False


class TimelineControlAction(PressableEncoderAction):
    """Eight-mode timeline control with press-and-turn mode selection."""

    # Some Ulanzi host/firmware combinations send only hold-left/hold-right
    # and omit dialdown or dialup. A rotated selection therefore commits after
    # a short idle window; an idle press is cancelled without changing mode.
    selection_auto_commit_seconds = 0.50
    selection_auto_cancel_seconds = 1.50
    defaults = {
        "requireActive": True,
        "timelineMode": TIMELINE_MODE_IDS[0],
    }

    def __init__(self, context, api, backend, settings=None):
        self._timeline_lock = RLock()
        self._timeline_diag_lock = RLock()
        self._timeline_diag_sequence = 0
        self._selection_active = False
        self._selection_rotated = False
        self._preview_mode_index = 0
        self._selection_timer = None
        self._selection_generation = 0
        self._last_feedback_signature = None
        self._destroyed = False
        self._initializing_timeline = True
        super().__init__(context, api, backend, settings)
        self._initializing_timeline = False
        with self._timeline_lock:
            self._normalize_timeline_settings_locked()
            self._preview_mode_index = self._current_mode_index_locked()
        self._update_feedback()
        self._log_timeline(
            "telemetry",
            event="ready",
            platform=sys.platform,
            mode=self.settings.get("timelineMode"),
            autoCommitMs=round(self.selection_auto_commit_seconds * 1000),
            autoCancelMs=round(self.selection_auto_cancel_seconds * 1000),
        )

    @staticmethod
    def _diagnostic_value(value):
        if value is None:
            return "-"
        if isinstance(value, bool):
            return "true" if value else "false"
        text = str(value).replace("\r", "\\r").replace("\n", "\\n")[:160]
        if not text:
            return "''"
        return repr(text) if any(character.isspace() for character in text) else text

    def _log_timeline(self, stage, **fields):
        details = " ".join(
            f"{key}={self._diagnostic_value(value)}"
            for key, value in fields.items()
        )
        suffix = f" {details}" if details else ""
        with self._timeline_diag_lock:
            self._timeline_diag_sequence += 1
            print(
                "timeline diag: "
                f"seq={self._timeline_diag_sequence} "
                f"monotonicMs={int(time.monotonic() * 1000)} "
                f"stage={stage} "
                f"context={self._diagnostic_value(self.context)}{suffix}"
            )

    def log_host_dial_event(
        self,
        event,
        ticks=None,
        raw_ticks=None,
        rotate_event="",
        fine=None,
    ):
        """Log the compact host event fields used by the timeline state machine."""
        with self._timeline_lock:
            mode = self.settings.get("timelineMode")
            selection_active = self._selection_active
            selection_rotated = self._selection_rotated
            pressed = self._pressed_at is not None
        self._log_timeline(
            "host-event",
            event=event,
            ticks=ticks,
            rawTicks=raw_ticks,
            rotateEvent=rotate_event or "-",
            fine=fine,
            mode=mode,
            selectionActive=selection_active,
            selectionRotated=selection_rotated,
            pressed=pressed,
        )

    def _diagnostic_pointer(self):
        try:
            position = self.backend.pointer_position()
        except Exception as exc:
            return "-", f"{type(exc).__name__}:{str(exc)[:100]}"
        if isinstance(position, dict):
            x = position.get("x")
            y = position.get("y")
            if x is not None and y is not None:
                return f"{x},{y}", "-"
        if position is None:
            return "-", "-"
        return str(position)[:100], "-"

    def _normalize_timeline_settings_locked(self):
        mode = str(self.settings.get("timelineMode") or "")
        if mode not in TIMELINE_MODE_BY_ID:
            mode = TIMELINE_MODE_IDS[0]

        self.settings["requireActive"] = True
        self.settings["timelineMode"] = mode
        # Earlier builds let the PI restrict press-and-turn selection. The
        # control now always cycles through all eight modes, so never keep or
        # write that retired per-action setting.
        self.settings.pop("enabledTimelineModes", None)

    def _current_mode_index_locked(self):
        mode = self.settings.get("timelineMode")
        try:
            return TIMELINE_MODE_IDS.index(mode)
        except ValueError:
            return 0

    def _cancel_selection_timer_locked(self):
        self._selection_generation += 1
        timer = self._selection_timer
        self._selection_timer = None
        if timer is not None:
            timer.cancel()

    def _schedule_selection_timeout_locked(self, delay):
        self._cancel_selection_timer_locked()
        generation = self._selection_generation
        timer = Timer(delay, self._selection_timeout, args=(generation,))
        timer.daemon = True
        self._selection_timer = timer
        timer.start()

    def _start_selection_locked(self):
        if not self._selection_active:
            self._selection_active = True
            self._selection_rotated = False
            self._preview_mode_index = self._current_mode_index_locked()

    def _reset_selection_locked(self, clear_pressed=True):
        self._cancel_selection_timer_locked()
        self._selection_active = False
        self._selection_rotated = False
        self._preview_mode_index = self._current_mode_index_locked()
        if clear_pressed:
            self._pressed_at = None
            self._rotated_while_pressed = False
            self._dial_press_prehandled = False
            self._last_press_action_at = time.monotonic()

    def _finish_selection(
        self, commit, expected_generation=None, source="explicit"
    ):
        settings = None
        with self._timeline_lock:
            if (
                expected_generation is not None
                and (
                    self._destroyed
                    or expected_generation != self._selection_generation
                )
            ):
                self._log_timeline(
                    "selection",
                    event="finish-ignored",
                    source=source,
                    reason="stale-generation",
                    expectedGeneration=expected_generation,
                    currentGeneration=self._selection_generation,
                    destroyed=self._destroyed,
                )
                return False
            if not self._selection_active:
                mode = self.settings.get("timelineMode")
                self._reset_selection_locked(clear_pressed=True)
                self._log_timeline(
                    "selection",
                    event="finish-ignored",
                    source=source,
                    reason="inactive",
                    mode=mode,
                )
                return False
            previous_mode = self.settings.get("timelineMode")
            preview_mode = TIMELINE_MODE_IDS[
                self._preview_mode_index % len(TIMELINE_MODE_IDS)
            ]
            selection_rotated = self._selection_rotated
            should_commit = bool(commit and self._selection_rotated)
            if should_commit:
                self.settings["timelineMode"] = preview_mode
                settings = deepcopy(self.settings)
            self._reset_selection_locked(clear_pressed=True)

        persistence_result = "not-requested"
        if settings is not None:
            try:
                api_result = self.api.set_settings(settings, self.context)
                persistence_result = (
                    "accepted" if api_result is not False else "rejected"
                )
            except Exception as exc:
                persistence_result = f"exception:{type(exc).__name__}"
                print(f"timeline mode persistence failed for {self.context}: {exc}")
        self._update_feedback()
        self._log_timeline(
            "selection",
            event="commit" if should_commit else "cancel",
            source=source,
            requestedCommit=bool(commit),
            rotated=selection_rotated,
            previousMode=previous_mode,
            previewMode=preview_mode,
            mode=self.settings.get("timelineMode"),
            persistence=persistence_result,
        )
        return should_commit

    def _selection_timeout(self, generation):
        self._log_timeline(
            "selection",
            event="timeout",
            generation=generation,
        )
        self._finish_selection(
            commit=True,
            expected_generation=generation,
            source="timeout",
        )

    def apply_settings(self, settings):
        incoming = dict(settings or {})
        incoming.pop("enabledTimelineModes", None)
        legacy_mode = incoming.get("mode")
        if "timelineMode" not in incoming and legacy_mode in TIMELINE_MODE_IDS:
            incoming["timelineMode"] = legacy_mode
        if (
            "timelineMode" not in incoming
            and incoming.get("pressCommand") == "zoom_fit"
        ):
            incoming["timelineMode"] = "timeline_zoom"
        super().apply_settings(incoming)
        with self._timeline_lock:
            self._normalize_timeline_settings_locked()
            if self._initializing_timeline:
                return
            self._reset_selection_locked(clear_pressed=True)
        self._update_feedback()

    def _display_mode_locked(self):
        if self._selection_active and self._selection_rotated:
            return TIMELINE_MODE_IDS[
                self._preview_mode_index % len(TIMELINE_MODE_IDS)
            ], True
        return self.settings["timelineMode"], False

    def _update_feedback(self):
        with self._timeline_lock:
            mode, preview = self._display_mode_locked()
            try:
                indicator = TIMELINE_MODE_IDS.index(mode) + 1
            except ValueError:
                indicator = 1
            label = self.api.t(TIMELINE_MODE_BY_ID[mode].label)
            title = f"‹ {label} ›" if preview else label
            signature = (title, indicator)
            if signature == self._last_feedback_signature:
                return False

        layout = {
            "title": {"text": title, "enabled": True},
            "icon": {"value": TIMELINE_FEEDBACK_ICON, "enabled": True},
            "indicator": {"value": indicator, "enabled": True},
        }
        try:
            sent = self.api.set_feedback(self.context, layout)
        except Exception as exc:
            print(f"timeline feedback failed for {self.context}: {exc}")
            return False
        if sent is False:
            return False
        with self._timeline_lock:
            self._last_feedback_signature = signature
        return True

    def on_dial_down(self):
        super().on_dial_down()
        with self._timeline_lock:
            self._start_selection_locked()
            self._schedule_selection_timeout_locked(
                self.selection_auto_cancel_seconds
            )
            mode = self.settings.get("timelineMode")
            generation = self._selection_generation
        self._log_timeline(
            "selection",
            event="armed",
            source="dialdown",
            mode=mode,
            generation=generation,
            timeoutMs=round(self.selection_auto_cancel_seconds * 1000),
        )
        return True

    def on_dial_up(self):
        return self._finish_selection(commit=True, source="dialup")

    def _select_mode(self, ticks):
        with self._timeline_lock:
            self._start_selection_locked()
            previous_preview_mode = TIMELINE_MODE_IDS[
                self._preview_mode_index % len(TIMELINE_MODE_IDS)
            ]
            self._selection_rotated = True
            self._rotated_while_pressed = self._pressed_at is not None
            self._preview_mode_index = (
                self._preview_mode_index + int(ticks)
            ) % len(TIMELINE_MODE_IDS)
            preview_mode = TIMELINE_MODE_IDS[self._preview_mode_index]
            self._schedule_selection_timeout_locked(
                self.selection_auto_commit_seconds
            )
            generation = self._selection_generation
            pressed = self._pressed_at is not None
        self._log_timeline(
            "selection",
            event="preview",
            source="rotate",
            ticks=ticks,
            previousPreviewMode=previous_preview_mode,
            previewMode=preview_mode,
            pressed=pressed,
            generation=generation,
            timeoutMs=round(self.selection_auto_commit_seconds * 1000),
        )
        self._update_feedback()
        return True

    def _execute_timeline_input(self, ticks):
        with self._timeline_lock:
            mode = self.settings["timelineMode"]
        try:
            resolved = resolve_timeline_input(mode, ticks, platform=sys.platform)
        except Exception as exc:
            self._log_timeline(
                "resolve",
                mode=mode,
                ticks=ticks,
                result="exception",
                error=f"{type(exc).__name__}:{str(exc)[:100]}",
            )
            print(f"timeline input resolution failed: mode={mode} error={exc}")
            return False

        if not isinstance(resolved, dict):
            self._log_timeline(
                "resolve",
                mode=mode,
                ticks=ticks,
                result="invalid-data",
                resolvedType=type(resolved).__name__,
            )
            print(f"timeline input resolution returned invalid data: mode={mode}")
            return False
        kind = str(resolved.get("kind") or "")
        value = str(resolved.get("value") or "")
        command = str(resolved.get("command") or mode)
        repeats = min(30, abs(int(ticks)))
        self._log_timeline(
            "resolve",
            mode=mode,
            ticks=ticks,
            direction=resolved.get("direction"),
            command=command,
            kind=kind or "-",
            token=value or "-",
            profile=resolved.get("profile") or "-",
            assigned=resolved.get("assigned"),
            detected=resolved.get("detected"),
            repeats=repeats,
        )
        if resolved.get("assigned") is False or kind == "unassigned" or not value:
            print(f"timeline input is unassigned: mode={mode} command={command}")
            try:
                self.api.show_alert(self.context)
            except Exception:
                pass
            return False
        if kind not in {"hotkey", "scroll"}:
            print(f"unsupported timeline input kind: mode={mode} kind={kind}")
            return False

        performed = False
        for attempt in range(1, repeats + 1):
            timeline_sender = (
                getattr(self.backend, "execute_timeline_shortcut", None)
                if kind == "hotkey"
                else None
            )
            native_timeline_sender = callable(timeline_sender)
            marker_sender = (
                kind == "hotkey"
                and mode == "marker"
                and not native_timeline_sender
            )
            if kind == "scroll":
                sender = getattr(
                    self.backend,
                    "execute_timeline_scroll",
                    self.backend.execute_shortcut,
                )
            elif native_timeline_sender:
                sender = timeline_sender
            elif marker_sender:
                sender = getattr(
                    self.backend,
                    "execute_marker_shortcut",
                    self.backend.execute_shortcut,
                )
            else:
                sender = self.backend.execute_shortcut
            try:
                backend_result = (
                    sender(value, mode=mode)
                    if kind == "scroll" or native_timeline_sender
                    else sender(value)
                )
            except Exception as exc:
                transport = (
                    getattr(
                        self.backend,
                        "_last_timeline_scroll_transport",
                        "unavailable",
                    )
                    if kind == "scroll"
                    else getattr(
                        self.backend,
                        "_last_timeline_shortcut_transport",
                        "win32.SendInput",
                    )
                    if native_timeline_sender
                    else getattr(
                        self.backend,
                        "_last_marker_shortcut_transport",
                        "ud.hotkey",
                    )
                    if marker_sender
                    else "ud.hotkey"
                )
                transport_result = (
                    getattr(
                        self.backend,
                        "_last_timeline_scroll_result",
                        "unavailable",
                    )
                    if kind == "scroll"
                    else getattr(
                        self.backend,
                        "_last_timeline_shortcut_result",
                        "unavailable",
                    )
                    if native_timeline_sender
                    else getattr(
                        self.backend,
                        "_last_marker_shortcut_result",
                        getattr(
                            self.backend,
                            "_last_shortcut_api_result",
                            "unavailable",
                        ),
                    )
                    if marker_sender
                    else getattr(
                        self.backend, "_last_shortcut_api_result", "unavailable"
                    )
                )
                self._log_timeline(
                    "send",
                    mode=mode,
                    command=command,
                    kind=kind,
                    token=value,
                    attempt=f"{attempt}/{repeats}",
                    transport=transport,
                    transportResult=transport_result,
                    backendResult="exception",
                    apiResult=getattr(
                        self.backend, "_last_shortcut_api_result", "unavailable"
                    ),
                    error=f"{type(exc).__name__}:{str(exc)[:100]}",
                )
                raise
            transport = (
                getattr(
                    self.backend,
                    "_last_timeline_scroll_transport",
                    "unavailable",
                )
                if kind == "scroll"
                else getattr(
                    self.backend,
                    "_last_timeline_shortcut_transport",
                    "win32.SendInput",
                )
                if native_timeline_sender
                else getattr(
                    self.backend,
                    "_last_marker_shortcut_transport",
                    "ud.hotkey",
                )
                if marker_sender
                else "ud.hotkey"
            )
            transport_result = (
                getattr(
                    self.backend,
                    "_last_timeline_scroll_result",
                    backend_result,
                )
                if kind == "scroll"
                else getattr(
                    self.backend,
                    "_last_timeline_shortcut_result",
                    backend_result,
                )
                if native_timeline_sender
                else getattr(
                    self.backend,
                    "_last_marker_shortcut_result",
                    getattr(
                        self.backend, "_last_shortcut_api_result", backend_result
                    ),
                )
                if marker_sender
                else getattr(
                    self.backend, "_last_shortcut_api_result", backend_result
                )
            )
            self._log_timeline(
                "send",
                mode=mode,
                command=command,
                kind=kind,
                token=value,
                attempt=f"{attempt}/{repeats}",
                transport=transport,
                transportResult=transport_result,
                backendResult=backend_result,
                apiResult=getattr(
                    self.backend, "_last_shortcut_api_result", "unavailable"
                ),
            )
            if not backend_result:
                return performed
            performed = True
        return performed

    def on_rotate(self, ticks, fine=False):
        try:
            ticks = int(ticks)
        except (TypeError, ValueError):
            self._log_timeline(
                "route",
                ticks=ticks,
                fine=bool(fine),
                decision="reject",
                reason="invalid-ticks",
            )
            return False
        if not ticks:
            self._log_timeline(
                "route",
                ticks=ticks,
                fine=bool(fine),
                decision="reject",
                reason="zero-ticks",
            )
            return False
        with self._timeline_lock:
            mode = self.settings.get("timelineMode")
            selection_active = self._selection_active
            selection_rotated = self._selection_rotated
            pressed = self._pressed_at is not None
            selecting = bool(fine or pressed)
            commit_before_execute = bool(selection_active and not selecting)
        self._log_timeline(
            "route",
            ticks=ticks,
            fine=bool(fine),
            decision=(
                "select"
                if selecting
                else "commit-execute"
                if commit_before_execute
                else "execute"
            ),
            mode=mode,
            selectionActive=selection_active,
            selectionRotated=selection_rotated,
            pressed=pressed,
        )
        if selecting:
            return self._select_mode(ticks)
        if commit_before_execute:
            self._finish_selection(commit=True, source="normal-rotate")
            with self._timeline_lock:
                mode = self.settings.get("timelineMode")
        target_ready = self.ensure_target()
        pointer, pointer_error = self._diagnostic_pointer()
        self._log_timeline(
            "target",
            mode=mode,
            requireActive=bool(self.settings.get("requireActive", True)),
            targetActive=self._last_target_active,
            result="allowed" if target_ready else "blocked",
            pointer=pointer,
            pointerError=pointer_error,
        )
        if not target_ready:
            return False
        return self._execute_timeline_input(ticks)

    def on_short_press(self):
        # A plain press only arms mode selection; it intentionally has no
        # timeline command of its own.
        return True

    def on_long_press(self):
        return True

    def destroy(self):
        with self._timeline_lock:
            self._destroyed = True
            self._reset_selection_locked(clear_pressed=True)


class AdjustmentEncoderAction(PressableEncoderAction):
    defaults = {
        "requireActive": True,
        "parameterIndex": 0,
        "sensitivity": 1.0,
        "hslColor": "red",
    }

    def __init__(self, context, api, backend, kind, parameters, settings=None):
        self.kind = kind
        self.feedback_icon = (
            "resources/icons/hsl.svg"
            if kind == "hsl"
            else "resources/icons/basic-adjustments.svg"
        )
        self.parameters = tuple(parameters)
        self.values = (
            {}
            if kind == "hsl"
            else {parameter.key: parameter.default for parameter in self.parameters}
        )
        self.last_automation_reason = ""
        super().__init__(context, api, backend, settings)
        self._normalize_index()
        self._update_feedback()

    def _normalize_index(self):
        parameters = self.active_parameters()
        if not parameters:
            self.settings["parameterIndex"] = 0
            return
        try:
            index = int(self.settings.get("parameterIndex", 0))
        except (TypeError, ValueError):
            index = 0
        self.settings["parameterIndex"] = index % len(parameters)

    def active_parameters(self):
        """Return the configured press-cycle subset in its canonical order."""
        enabled = self.settings.get("enabledParameters")
        if not isinstance(enabled, (list, tuple)) or not enabled:
            return self.parameters
        enabled_keys = {str(key) for key in enabled}
        selected = tuple(
            parameter for parameter in self.parameters if parameter.key in enabled_keys
        )
        return selected or self.parameters

    def apply_settings(self, settings):
        settings = dict(settings or {})
        super().apply_settings(settings)
        if hasattr(self, "parameters"):
            self._normalize_index()

    @property
    def parameter(self):
        return self.active_parameters()[self.settings["parameterIndex"]]

    def target_key(self):
        if self.kind == "hsl":
            return f"{self.settings.get('hslColor', 'red')}.{self.parameter.key}"
        return self.parameter.key

    def parameter_label(self):
        if self.kind == "hsl":
            color = self.api.t(str(self.settings.get("hslColor", "red")).title())
            return f"{color}·{self.api.t(self.parameter.label)}"
        if self.kind == "color_wheels":
            if "." not in self.parameter.key:
                return self.api.t(self.parameter.label)
            wheel, _, axis = self.parameter.key.partition(".")
            axis_label = {"x": "Color X", "y": "Color Y", "luma": "Luminance"}.get(
                axis, self.parameter.label
            )
            return f"{self.api.t(wheel.title())}·{self.api.t(axis_label)}"
        if self.parameter.group:
            return f"{self.api.t(self.parameter.group)}·{self.api.t(self.parameter.label)}"
        return self.api.t(self.parameter.label)

    def value_key(self):
        return self.target_key()

    def current_value(self):
        key = self.value_key()
        return self.values.setdefault(key, self.parameter.default)

    def calibration(self):
        def add_panel_target(calibration):
            calibration = deepcopy(calibration)
            panel = self.settings.get("panelTarget") or {}
            if panel.get("x") not in (None, "") and panel.get("y") not in (None, ""):
                calibration["preClickX"] = panel.get("x")
                calibration["preClickY"] = panel.get("y")
                calibration["preClickDelay"] = panel.get("delay", 0.12)
            return calibration

        calibrations = self.settings.get("calibrations") or {}
        selected = calibrations.get(self.target_key())
        if not isinstance(selected, dict) and self.kind == "color_wheels":
            wheel, _, axis = self.parameter.key.partition(".")
            if axis in ("x", "y"):
                sibling = "y" if axis == "x" else "x"
                selected = calibrations.get(f"{wheel}.{sibling}")
        if isinstance(selected, dict):
            calibration = deepcopy(selected)
            if self.kind == "color_wheels":
                wheel, _, axis = self.parameter.key.partition(".")
                if axis in ("x", "y"):
                    try:
                        radius = float(calibration.get("wheelRadius", 45))
                    except (TypeError, ValueError):
                        radius = 45.0
                    x_value = self.values.get(f"{wheel}.x", 0.0)
                    y_value = self.values.get(f"{wheel}.y", 0.0)
                    calibration.update({
                        "dragMode": "absoluteWheel",
                        "offsetX": x_value / 100.0 * radius,
                        "offsetY": -y_value / 100.0 * radius,
                    })
            return add_panel_target(calibration)
        x = self.settings.get("targetX")
        y = self.settings.get("targetY")
        if x in (None, "") or y in (None, ""):
            return None
        return add_panel_target({
            "x": x,
            "y": y,
            "pixelsPerStep": self.settings.get("pixelsPerStep", 2),
            "axis": self.settings.get("axis", "horizontal"),
        })

    def _update_feedback(self):
        self.feedback(self.parameter_label())

    def _change_virtual_value(self, ticks, fine):
        parameter = self.parameter
        try:
            sensitivity = float(self.settings.get("sensitivity", 1.0))
        except (TypeError, ValueError):
            sensitivity = 1.0
        scale = 0.25 if fine else 1.0
        key = self.value_key()
        current = self.current_value()
        value = current + float(ticks) * parameter.step * sensitivity * scale
        self.values[key] = min(parameter.maximum, max(parameter.minimum, value))

    def on_rotate(self, ticks, fine=False):
        if not ticks or not self.ensure_target():
            return False
        if self._pressed_at is not None:
            self._rotated_while_pressed = True
        if self._pressed_at is not None:
            fine = True
        self._change_virtual_value(ticks, fine)

        calibration = self.calibration()
        result = self.backend.adjust_parameter(calibration, ticks, fine=fine)
        self.last_automation_reason = result.reason

        self._update_feedback()
        return True

    def on_short_press(self):
        parameters = self.active_parameters()
        self.settings["parameterIndex"] = (
            self.settings["parameterIndex"] + 1
        ) % len(parameters)
        try:
            self.api.set_settings(self.settings, self.context)
        except Exception:
            pass
        self._update_feedback()
        return True

    def on_long_press(self):
        parameter = self.parameter
        if self.kind == "color_wheels" and parameter.key.endswith((".x", ".y")):
            wheel = parameter.key.split(".", 1)[0]
            self.values[f"{wheel}.x"] = 0.0
            self.values[f"{wheel}.y"] = 0.0
        else:
            self.values[self.value_key()] = parameter.default
        if self.ensure_target():
            result = self.backend.reset_parameter(self.calibration())
            self.last_automation_reason = result.reason
        else:
            self.last_automation_reason = "Jianying Pro is not frontmost"
        self._update_feedback()
        return True


class SmartSelectedSliderAction(AdjustmentEncoderAction):
    """Adjust the Basic or HSL slider currently recognized under the pointer."""

    dedupe_windows_host_press_events = True

    def __init__(self, context, api, backend, settings=None):
        self._hover_enabled = backend.enable_slider_hover(context)
        super().__init__(
            context,
            api,
            backend,
            "selected_slider",
            BASIC_HOVER_PARAMETERS,
            settings,
        )

    def _hover_target_and_parameter(self):
        target = self.backend.slider_hover_target()
        if not isinstance(target, dict):
            return None, None
        kind = target.get("kind", "basic")
        parameters = {
            "basic": BASIC_HOVER_PARAMETERS,
            "hsl": HSL_HOVER_PARAMETERS,
        }.get(kind, ())
        parameter = next(
            (item for item in parameters if item.key == target.get("key")),
            None,
        )
        return (target, parameter) if parameter is not None else (None, None)

    def _hover_calibration(self, target, reset=False):
        return {
            "x": target["resetX"] if reset else target["x"],
            "y": target["resetY"] if reset else target["y"],
            "axis": "horizontal",
            # Jianying's numeric scrubber maps one macOS logical point to one
            # normal parameter step. Logical points stay stable across Retina
            # scale factors, display resolutions and window positions.
            "pixelsPerStep": 1.0,
            "source": f"{target.get('kind') or 'basic'}-hover",
            "targetKey": target.get("key"),
            "kind": target.get("kind") or "basic",
            "hoverTarget": deepcopy(target),
        }

    @staticmethod
    def _diagnostic_rect(rect):
        if not isinstance(rect, dict):
            return None
        try:
            return {
                name: round(float(rect[name]), 2)
                for name in ("x", "y", "w", "h")
            }
        except (KeyError, TypeError, ValueError):
            return None

    def _log_slider_route(self, calibration, target, ticks, fine):
        hover_rect = self._diagnostic_rect(target.get("hoverRect"))
        overlay_rect = self._diagnostic_rect(
            target.get("overlayRect") or target.get("hoverRect")
        )
        try:
            target_x = round(float(calibration.get("x")), 2)
        except (TypeError, ValueError):
            target_x = None
        overlay_right_gap = None
        if target_x is not None and overlay_rect is not None:
            overlay_right_gap = round(
                target_x - overlay_rect["x"] - overlay_rect["w"],
                2,
            )
        payload = {
            "stage": "route",
            "requestId": calibration.get("_sliderDiagRequestId"),
            "context": str(self.context),
            "kind": calibration.get("kind"),
            "key": calibration.get("targetKey"),
            "ticks": ticks,
            "fine": bool(fine),
            "pressed": self._pressed_at is not None,
            "target": {
                "x": target_x,
                "y": calibration.get("y"),
            },
            "hoverRect": hover_rect,
            "overlayRect": overlay_rect,
            "targetToOverlayRight": overlay_right_gap,
        }
        print(
            "slider diag: "
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )

    def _log_slider_reset(
        self,
        stage,
        request_id,
        target=None,
        performed=None,
        reason=None,
    ):
        target = target if isinstance(target, dict) else {}
        reset_target = None
        try:
            reset_target = {
                "x": round(float(target["resetX"]), 2),
                "y": round(float(target["resetY"]), 2),
            }
        except (KeyError, TypeError, ValueError):
            pass
        payload = {
            "stage": stage,
            "requestId": request_id,
            "context": str(self.context),
            "kind": target.get("kind"),
            "key": target.get("key"),
            "valueSource": target.get("valueSource"),
            "resetSource": target.get("resetSource"),
            "resetAvailable": target.get("resetAvailable"),
            "resetTarget": reset_target,
            "hoverRect": self._diagnostic_rect(target.get("hoverRect")),
            "overlayRect": self._diagnostic_rect(
                target.get("overlayRect") or target.get("hoverRect")
            ),
        }
        if performed is not None:
            payload["performed"] = bool(performed)
        if reason is not None:
            payload["reason"] = str(reason)
        print(
            "slider diag: "
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )

    def _hover_status(self):
        return self.backend.slider_hover_status()

    def _update_feedback(self):
        # Keep the default $UA1 title/icon. Hover recognition must not push
        # parameter names such as "Temperature" back to the device.
        return None

    def on_rotate(self, ticks, fine=False):
        if not ticks or not self.ensure_target():
            return False
        target, parameter = self._hover_target_and_parameter()
        if target is None or parameter is None:
            self.last_automation_reason = self._hover_status()
            return False
        if self._pressed_at is not None:
            self._rotated_while_pressed = True
        calibration = self._hover_calibration(target)
        request_id = f"{time.monotonic_ns():x}"
        calibration["_sliderDiagRequestId"] = request_id
        calibration["_sliderDiagRequestIds"] = [request_id]
        self._log_slider_route(calibration, target, ticks, fine)
        result = self.backend.adjust_parameter(
            calibration,
            ticks,
            fine=fine,
        )
        self.last_automation_reason = result.reason
        return bool(result.performed)

    def _reset_hovered(self):
        request_id = f"{time.monotonic_ns():x}"
        if not self.ensure_target():
            self._log_slider_reset(
                "reset_result",
                request_id,
                performed=False,
                reason="Jianying Pro is not frontmost",
            )
            return False
        target, parameter = self._hover_target_and_parameter()
        if target is None or parameter is None:
            self.last_automation_reason = self._hover_status()
            self._log_slider_reset(
                "reset_result",
                request_id,
                target=target,
                performed=False,
                reason=self.last_automation_reason,
            )
            return False
        self._log_slider_reset("reset_route", request_id, target=target)
        if (
            target.get("resetAvailable") is False
            or target.get("resetX") is None
            or target.get("resetY") is None
        ):
            self.last_automation_reason = "parameter reset label is not recognized"
            self._log_slider_reset(
                "reset_result",
                request_id,
                target=target,
                performed=False,
                reason=self.last_automation_reason,
            )
            return False
        calibration = self._hover_calibration(target, reset=True)
        calibration["_sliderDiagRequestId"] = request_id
        result = self.backend.reset_parameter(calibration)
        self.last_automation_reason = result.reason
        self._log_slider_reset(
            "reset_result",
            request_id,
            target=target,
            performed=result.performed,
            reason=result.reason,
        )
        return bool(result.performed)

    def on_short_press(self):
        return self._reset_hovered()

    def on_long_press(self):
        return self._reset_hovered()

    def destroy(self):
        self.backend.disable_slider_hover(self.context)


class SmartColorWheelAction(PressableEncoderAction):
    """Adjust the Jianying color-wheel control currently under the pointer."""

    dedupe_windows_host_press_events = True

    defaults = {
        "requireActive": True,
        "dialMode": "diameter",
        "holdDialMode": "orbit",
        "sensitivity": 1.0,
    }

    def __init__(self, context, api, backend, settings=None):
        self.last_automation_reason = ""
        self._hover_enabled = backend.enable_color_wheel_hover(context)
        super().__init__(context, api, backend, settings)

    def apply_settings(self, settings):
        super().apply_settings(settings)
        self.settings["requireActive"] = True
        self.settings["dialMode"] = normalize_wheel_mode(
            self.settings.get("dialMode"), "diameter"
        )
        self.settings["holdDialMode"] = normalize_wheel_mode(
            self.settings.get("holdDialMode"), "orbit"
        )
        try:
            sensitivity = float(self.settings.get("sensitivity", 1.0))
        except (TypeError, ValueError):
            sensitivity = 1.0
        self.settings["sensitivity"] = min(4.0, max(0.25, sensitivity))

    def _target(self):
        target = self.backend.color_wheel_hover_target()
        return target if isinstance(target, dict) else None

    def _slider_calibration(self, target):
        return {
            "x": target.get("x"),
            "y": target.get("y"),
            "axis": "horizontal",
            "pixelsPerStep": 1.0,
            "source": "color-wheel-hover",
            "targetKey": target.get("key"),
            "kind": "color_wheels",
            "hoverTarget": deepcopy(target),
        }

    def on_rotate(self, ticks, fine=False):
        if not ticks or not self.ensure_target():
            return False
        target = self._target()
        if target is None:
            self.last_automation_reason = self.backend.color_wheel_hover_status()
            return False

        held = self._pressed_at is not None or bool(fine)
        if held:
            self._rotated_while_pressed = True
        if target.get("controlType") == "slider":
            result = self.backend.adjust_parameter(
                self._slider_calibration(target),
                ticks,
                fine=held,
            )
        else:
            mode = self.settings["holdDialMode"] if held else self.settings["dialMode"]
            options = {}
            if getattr(self.backend, "supports_wheel_motion_profile", False):
                # The Windows response picker was removed. Older saved
                # accelerated settings must also use the fixed-step path.
                options = {"motion_profile": "fixed",
                           "motion_context": self.context}
            result = self.backend.adjust_color_wheel(
                target,
                ticks,
                mode=mode,
                sensitivity=self.settings["sensitivity"],
                **options,
            )
        self.last_automation_reason = result.reason
        return bool(result.performed)

    def _reset_hovered(self):
        if not self.ensure_target():
            return False
        target = self._target()
        if target is None:
            self.last_automation_reason = self.backend.color_wheel_hover_status()
            return False
        result = self.backend.reset_color_wheel(target)
        self.last_automation_reason = result.reason
        return bool(result.performed)

    def on_short_press(self):
        return self._reset_hovered()

    def on_long_press(self):
        return self._reset_hovered()

    def destroy(self):
        self.backend.disable_color_wheel_hover(self.context)


def create_adjustment_action(context, api, backend, kind, settings=None):
    if kind == "selected_slider":
        if (
            getattr(backend, "supports_basic_hover", False)
            or getattr(backend, "supports_hsl_hover", False)
        ):
            return SmartSelectedSliderAction(context, api, backend, settings)
        parameters = BASIC_PARAMETERS
    elif kind == "color_wheels":
        if getattr(backend, "supports_color_wheel_hover", False):
            return SmartColorWheelAction(context, api, backend, settings)
        parameters = COLOR_WHEEL_PARAMETERS
    else:
        raise ValueError(f"unsupported adjustment kind: {kind}")
    return AdjustmentEncoderAction(context, api, backend, kind, parameters, settings)
