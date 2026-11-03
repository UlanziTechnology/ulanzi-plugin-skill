"""macOS automation for Jianying Pro 11 using CoreGraphics events."""

import ctypes
from ctypes import (
    c_double,
    c_int32,
    c_int64,
    c_uint32,
    c_uint64,
    c_void_p,
)
from copy import deepcopy
import json
import math
import os
import plistlib
import re
import select
import subprocess
from threading import RLock, Thread, Timer
import time

from .base import AdjustmentResult, AutomationBackend
from .wheel_queue import WheelAdjustmentQueue
from basic_hover import BasicHoverService
from color_wheel import (
    DEFAULT_RESPONSE_GAIN,
    MAX_RESPONSE_GAIN,
    MIN_RESPONSE_GAIN,
    centered_wheel_state,
    normalize_wheel_mode,
    plan_wheel_motion,
    resume_diameter_state,
    resume_orbit_state,
)


class CGPoint(ctypes.Structure):
    _fields_ = [("x", c_double), ("y", c_double)]


class CGSize(ctypes.Structure):
    _fields_ = [("width", c_double), ("height", c_double)]


class CGRect(ctypes.Structure):
    _fields_ = [("origin", CGPoint), ("size", CGSize)]


class CoreGraphicsMouse:
    EVENT_LEFT_DOWN = 1
    EVENT_LEFT_UP = 2
    EVENT_MOUSE_MOVED = 5
    EVENT_LEFT_DRAGGED = 6
    MOUSE_LEFT = 0
    HID_EVENT_TAP = 0
    SCROLL_EVENT_UNIT_PIXEL = 0
    EVENT_SOURCE_USER_DATA = 42
    PLUGIN_EVENT_TAG = 0x554C414E
    EVENT_FLAG_MASK_SHIFT = 0x00020000
    EVENT_FLAG_MASK_CONTROL = 0x00040000
    EVENT_FLAG_MASK_ALTERNATE = 0x00080000
    EVENT_FLAG_MASK_COMMAND = 0x00100000

    def __init__(self):
        path = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        self.cg = ctypes.CDLL(path)
        self.cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")

        self.cg.CGEventCreate.argtypes = [c_void_p]
        self.cg.CGEventCreate.restype = c_void_p
        self.cg.CGEventGetLocation.argtypes = [c_void_p]
        self.cg.CGEventGetLocation.restype = CGPoint
        self.cg.CGEventCreateMouseEvent.argtypes = [c_void_p, c_uint32, CGPoint, c_uint32]
        self.cg.CGEventCreateMouseEvent.restype = c_void_p
        # Event2 is the fixed-arity variant. Avoiding the older variadic API is
        # important on Apple Silicon, where ctypes cannot describe the tail
        # arguments safely across every ABI combination.
        self.cg.CGEventCreateScrollWheelEvent2.argtypes = [
            c_void_p,
            c_uint32,
            c_uint32,
            c_int32,
            c_int32,
            c_int32,
        ]
        self.cg.CGEventCreateScrollWheelEvent2.restype = c_void_p
        self.cg.CGEventPost.argtypes = [c_uint32, c_void_p]
        self.cg.CGEventPost.restype = None
        self.cg.CGEventSetFlags.argtypes = [c_void_p, c_uint64]
        self.cg.CGEventSetFlags.restype = None
        self.cg.CGEventSetIntegerValueField.argtypes = [c_void_p, c_uint32, c_int64]
        self.cg.CGEventSetIntegerValueField.restype = None
        self.cf.CFRelease.argtypes = [c_void_p]
        self.cf.CFRelease.restype = None

        if hasattr(self.cg, "CGPreflightPostEventAccess"):
            self.cg.CGPreflightPostEventAccess.argtypes = []
            self.cg.CGPreflightPostEventAccess.restype = ctypes.c_bool
        self._last_scroll_flags = None
        self.cg.CGGetActiveDisplayList.argtypes = [c_uint32, ctypes.POINTER(c_uint32), ctypes.POINTER(c_uint32)]
        self.cg.CGGetActiveDisplayList.restype = c_int32
        self.cg.CGDisplayBounds.argtypes = [c_uint32]
        self.cg.CGDisplayBounds.restype = CGRect

    def point_on_screen(self, x, y, margin=12.0):
        displays = (c_uint32 * 16)()
        count = c_uint32()
        if self.cg.CGGetActiveDisplayList(16, displays, ctypes.byref(count)) != 0:
            return False
        for display in displays[:count.value]:
            rect = self.cg.CGDisplayBounds(display)
            if (rect.origin.x + margin <= x <= rect.origin.x + rect.size.width - margin
                    and rect.origin.y + margin <= y <= rect.origin.y + rect.size.height - margin):
                return True
        return False

    def has_permission(self):
        check = getattr(self.cg, "CGPreflightPostEventAccess", None)
        return True if check is None else bool(check())

    def position(self):
        event = self.cg.CGEventCreate(None)
        if not event:
            raise RuntimeError("CGEventCreate failed")
        try:
            return self.cg.CGEventGetLocation(event)
        finally:
            self.cf.CFRelease(event)

    def _post(self, event_type, point, click_state=None, flags=None):
        event = self.cg.CGEventCreateMouseEvent(None, event_type, point, self.MOUSE_LEFT)
        if not event:
            raise RuntimeError("CGEventCreateMouseEvent failed")
        try:
            if click_state is not None:
                # kCGMouseEventClickState
                self.cg.CGEventSetIntegerValueField(event, 1, int(click_state))
            if flags is not None:
                # Zero is intentional: it clears modifier state cached by the
                # target beneath the pointer when returning to plain scroll.
                self.cg.CGEventSetFlags(event, int(flags))
            # Let the native input monitor distinguish plugin automation from
            # real Jianying clicks. Otherwise every encoder drag would
            # immediately invalidate the recognition cache it is using.
            self.cg.CGEventSetIntegerValueField(
                event,
                self.EVENT_SOURCE_USER_DATA,
                self.PLUGIN_EVENT_TAG,
            )
            self.cg.CGEventPost(self.HID_EVENT_TAP, event)
        finally:
            self.cf.CFRelease(event)

    def scroll_pixels(self, delta, axis="vertical"):
        """Post one tagged pixel-unit wheel event at the current pointer."""
        delta = int(delta)
        if not delta:
            return True

        # Jianying stores horizontal scrolling as Option+Wheel, but its Qt
        # trackpad path ignores the Option flag on continuous pixel events and
        # reads the event's second scroll axis instead. Convert that binding to
        # a real axis-2 event and do not synthesize a modifier key press.
        horizontal = str(axis or "vertical").lower() == "horizontal"
        event_flags = 0
        if event_flags != self._last_scroll_flags:
            self._post(
                self.EVENT_MOUSE_MOVED,
                self.position(),
                flags=event_flags,
            )

        wheel_count = 2 if horizontal else 1
        axis_1 = 0 if horizontal else delta
        axis_2 = delta if horizontal else 0
        event = self.cg.CGEventCreateScrollWheelEvent2(
            None,
            self.SCROLL_EVENT_UNIT_PIXEL,
            wheel_count,
            axis_1,
            axis_2,
            0,
        )
        if not event:
            raise RuntimeError("CGEventCreateScrollWheelEvent2 failed")
        try:
            self.cg.CGEventSetFlags(event, event_flags)
            self.cg.CGEventSetIntegerValueField(
                event,
                self.EVENT_SOURCE_USER_DATA,
                self.PLUGIN_EVENT_TAG,
            )
            self.cg.CGEventPost(self.HID_EVENT_TAP, event)
            self._last_scroll_flags = event_flags
        finally:
            self.cf.CFRelease(event)
        return True

    def move(self, x, y, event_type=None):
        self._post(event_type or self.EVENT_MOUSE_MOVED, CGPoint(float(x), float(y)))

    def drag(self, x, y, dx, dy, duration=0.08, restore_pointer=True):
        start_x = float(x)
        start_y = float(y)
        end_x = start_x + float(dx)
        end_y = start_y + float(dy)
        distance = abs(float(dx)) + abs(float(dy))
        steps = max(2, min(12, int(distance) // 2 + 1))
        path = [
            (
                start_x + (end_x - start_x) * index / steps,
                start_y + (end_y - start_y) * index / steps,
            )
            for index in range(1, steps + 1)
        ]
        trace = self.drag_path(
            start_x,
            start_y,
            path,
            duration,
            restore_pointer,
        )
        if not isinstance(trace, dict):
            trace = {}
        trace.update({
            "requestedDx": float(dx),
            "requestedDy": float(dy),
            "requestedDistance": distance,
            "steps": steps,
        })
        return trace

    def drag_path(
        self,
        x,
        y,
        path,
        duration=0.08,
        restore_pointer=True,
        press_delay=0.015,
    ):
        points = [(float(px), float(py)) for px, py in path]
        if not points:
            return None
        started_at = time.monotonic()
        original = self.begin_drag(x, y, press_delay=press_delay)
        end = self.continue_drag(points, duration=duration)
        self.end_drag(end[0], end[1], original, restore_pointer=restore_pointer)
        return {
            "originalX": float(original.x),
            "originalY": float(original.y),
            "startX": float(x),
            "startY": float(y),
            "endX": float(end[0]),
            "endY": float(end[1]),
            "pointCount": len(points),
            "durationMs": round((time.monotonic() - started_at) * 1000.0, 2),
            "restorePointer": bool(restore_pointer),
        }

    def begin_drag(self, x, y, press_delay=0.015):
        original = self.position()
        start = CGPoint(float(x), float(y))
        self._post(self.EVENT_MOUSE_MOVED, start)
        time.sleep(0.015)
        self._post(self.EVENT_LEFT_DOWN, start)
        # Jianying's color wheels only accept a drag after the white handle has
        # processed mouse-down. Callers can request a slightly longer dwell.
        time.sleep(max(0.0, float(press_delay)))
        return original

    def continue_drag(self, path, duration=0.08, on_progress=None):
        points = [CGPoint(float(px), float(py)) for px, py in path]
        if not points:
            raise ValueError("drag path is empty")
        if on_progress is not None:
            # Orbit samples have equal angular spacing. Schedule against one
            # clock so event/overlay work doesn't add a sleep to every sample.
            interval = max(0.002, duration / len(points))
            deadline = time.monotonic()
            for index, point in enumerate(points, 1):
                deadline += interval
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
                self._post(self.EVENT_LEFT_DRAGGED, point)
                on_progress(index, len(points))
                # If a system stall puts us behind, don't burst all remaining
                # events at once trying to repay that delay.
                deadline = max(deadline, time.monotonic() - interval + 0.002)
            return points[-1].x, points[-1].y
        for point in points:
            self._post(self.EVENT_LEFT_DRAGGED, point)
            time.sleep(max(0.002, duration / len(points)))
        return points[-1].x, points[-1].y

    def end_drag(self, x, y, original=None, restore_pointer=True):
        end = CGPoint(float(x), float(y))
        self._post(self.EVENT_LEFT_UP, end)
        if restore_pointer:
            time.sleep(0.01)
            if original is None:
                return
            self._post(self.EVENT_MOUSE_MOVED, original)

    def double_click(self, x, y, restore_pointer=True):
        original = self.position()
        point = CGPoint(float(x), float(y))
        self._post(self.EVENT_MOUSE_MOVED, point)
        for click_state in (1, 2):
            self._post(self.EVENT_LEFT_DOWN, point, click_state)
            self._post(self.EVENT_LEFT_UP, point, click_state)
            time.sleep(0.08)
        if restore_pointer:
            self._post(self.EVENT_MOUSE_MOVED, original)

    def click(self, x, y, restore_pointer=True):
        original = self.position()
        point = CGPoint(float(x), float(y))
        self._post(self.EVENT_MOUSE_MOVED, point)
        self._post(self.EVENT_LEFT_DOWN, point, 1)
        self._post(self.EVENT_LEFT_UP, point, 1)
        if restore_pointer:
            self._post(self.EVENT_MOUSE_MOVED, original)


class MacJianyingBackend(AutomationBackend):
    target_bundle_id = "com.lemon.lvpro"
    supports_basic_hover = True
    supports_hsl_hover = True
    supports_color_wheel_hover = True
    timeline_scroll_pixels = 32
    _timeline_scroll_modifier_flags = {
        "alt": CoreGraphicsMouse.EVENT_FLAG_MASK_ALTERNATE,
        "option": CoreGraphicsMouse.EVENT_FLAG_MASK_ALTERNATE,
        "shift": CoreGraphicsMouse.EVENT_FLAG_MASK_SHIFT,
        "ctrl": CoreGraphicsMouse.EVENT_FLAG_MASK_CONTROL,
        "control": CoreGraphicsMouse.EVENT_FLAG_MASK_CONTROL,
        "cmd": CoreGraphicsMouse.EVENT_FLAG_MASK_COMMAND,
        "command": CoreGraphicsMouse.EVENT_FLAG_MASK_COMMAND,
        "meta": CoreGraphicsMouse.EVENT_FLAG_MASK_COMMAND,
        "⌥": CoreGraphicsMouse.EVENT_FLAG_MASK_ALTERNATE,
        "⇧": CoreGraphicsMouse.EVENT_FLAG_MASK_SHIFT,
        "^": CoreGraphicsMouse.EVENT_FLAG_MASK_CONTROL,
        "⌘": CoreGraphicsMouse.EVENT_FLAG_MASK_COMMAND,
    }

    def __init__(self, api):
        super().__init__(api)
        self.mouse = CoreGraphicsMouse()
        self.mouse_lock = RLock()
        self._last_panel_activation = (None, 0.0)
        self.adjustments = WheelAdjustmentQueue(self._perform_adjustment)
        print("color wheel motion: macos-davinci-20260919 frameHz=120 orbitStep=1deg radialStep=1px")
        plugin_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        helper_path = os.path.join(plugin_root, "native", "jianying_hover_helper")
        self._hover_helper_path = helper_path
        self._slider_probe_lock = RLock()
        self._slider_probe_process = None
        # Start the read-only AX probe once with the plugin. Reusing this warm
        # helper avoids adding a native-process cold start before every drag,
        # which could otherwise alter encoder timing while we diagnose it.
        self._start_slider_probe_process()
        self._basic_hover_contexts = set()
        self._color_wheel_states = {}
        self._color_wheel_response_gains = {}
        self._color_wheel_gesture = None
        self._color_wheel_release_timer = None
        self._color_wheel_gesture_generation = 0
        self._color_wheel_feedback_revision = 0
        self._color_wheel_feedback_inflight = False
        self._color_wheel_feedback_pending = None
        self.color_wheel_idle_release_seconds = 0.55
        self.color_wheel_feedback_segments = 3
        self.color_wheel_handle_timeout_seconds = 0.4
        self._basic_hover = BasicHoverService(
            helper_path,
            self.pointer_position,
            self.target_is_active,
            refresh_on_frontmost_return=True,
        )

    @staticmethod
    def frontmost_bundle_id():
        try:
            asn = subprocess.check_output(
                ["/usr/bin/lsappinfo", "front"], text=True, timeout=1
            ).strip()
            result = subprocess.check_output(
                ["/usr/bin/lsappinfo", "info", "-only", "bundleid", asn],
                text=True,
                timeout=1,
            )
            # lsappinfo can report either the plist key or its newer display
            # label. Match a complete field so paths and unrelated metadata
            # cannot be mistaken for the active application's bundle ID.
            match = re.search(
                r'^[ \t]*(?:"CFBundleIdentifier"|CFBundleIdentifier|bundleID)'
                r'[ \t]*=[ \t]*"([^"\r\n]+)"[ \t]*$',
                result,
                re.MULTILINE,
            )
            return match.group(1) if match else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    def target_is_active(self):
        return self.frontmost_bundle_id() == self.target_bundle_id

    @staticmethod
    def target_is_running():
        try:
            result = subprocess.run(
                [
                    "/usr/bin/pgrep",
                    "-f",
                    r"[/]VideoFusion-macOS\.app/Contents/MacOS/VideoFusion-macOS$",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1,
                check=False,
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    @staticmethod
    def target_version():
        plist_path = "/Applications/VideoFusion-macOS.app/Contents/Info.plist"
        try:
            with open(plist_path, "rb") as stream:
                info = plistlib.load(stream)
            return str(info.get("CFBundleShortVersionString") or "")
        except (OSError, ValueError):
            return ""

    def automation_permission(self):
        return self.mouse.has_permission()

    def pointer_position(self):
        point = self.mouse.position()
        return {"x": round(point.x), "y": round(point.y)}

    @classmethod
    def _parse_timeline_scroll_token(cls, token):
        value = str(token or "").strip()
        if not value:
            return None
        upper_value = value.upper()
        direction = next(
            (
                candidate
                for candidate in ("SCROLL UP", "SCROLL DOWN")
                if upper_value.endswith(candidate)
            ),
            None,
        )
        if direction is None:
            return None
        modifier_text = value[: -len(direction)].strip()
        modifiers = [
            part
            for part in re.split(r"(?:\s*\+\s*|\s+)", modifier_text)
            if part
        ]
        flags = 0
        for modifier in modifiers:
            flag = cls._timeline_scroll_modifier_flags.get(modifier.lower())
            if flag is None:
                return None
            flags |= flag
        delta = cls.timeline_scroll_pixels if direction == "SCROLL UP" else -cls.timeline_scroll_pixels
        return delta, flags

    def execute_timeline_scroll(self, token, mode=None):
        parsed = self._parse_timeline_scroll_token(token)
        if parsed is None:
            # Preserve the generic host path for an unexpected custom wheel
            # token instead of silently discarding the user's assignment.
            return super().execute_timeline_scroll(token, mode=mode)

        delta, flags = parsed
        if mode in {"vertical_scroll", "horizontal_scroll"}:
            horizontal = mode == "horizontal_scroll"
        else:
            # Keep direct callers and older action code compatible while the
            # live action passes the semantic timeline mode explicitly.
            horizontal = bool(
                flags & CoreGraphicsMouse.EVENT_FLAG_MASK_ALTERNATE
            )
        axis = "horizontal" if horizontal else "vertical"
        self._last_shortcut_api_result = None
        if horizontal:
            self._last_timeline_scroll_transport = (
                "coregraphics.pixel-scroll.axis2"
            )
        else:
            self._last_timeline_scroll_transport = "coregraphics.pixel-scroll"
        try:
            if not self.mouse.has_permission():
                self._last_timeline_scroll_result = "accessibility-permission-denied"
                print(
                    "timeline native scroll: result=blocked "
                    "reason=accessibility-permission-denied"
                )
                return False
        except Exception as exc:
            self._last_timeline_scroll_result = (
                f"permission-exception:{type(exc).__name__}:{str(exc)[:80]}"
            )
            raise
        try:
            with self.mouse_lock:
                performed = self.mouse.scroll_pixels(delta, axis=axis)
        except Exception as exc:
            self._last_timeline_scroll_result = (
                f"exception:{type(exc).__name__}:{str(exc)[:80]}"
            )
            raise
        self._last_timeline_scroll_result = bool(performed)
        return bool(performed)

    def enable_basic_hover(self, context=None):
        with self.mouse_lock:
            self._basic_hover_contexts.add(f"basic:{context or 'default'}")
            enabled_kinds = self._enabled_hover_kinds_locked()
        self._basic_hover.set_enabled_kinds(enabled_kinds)
        return self._basic_hover.start()

    def disable_basic_hover(self, context=None):
        with self.mouse_lock:
            self._basic_hover_contexts.discard(f"basic:{context or 'default'}")
            should_stop = not self._basic_hover_contexts
            enabled_kinds = self._enabled_hover_kinds_locked()
        self._basic_hover.set_enabled_kinds(enabled_kinds)
        if should_stop:
            self._basic_hover.stop()
            self._color_wheel_states.clear()

    def basic_hover_target(self):
        return self._basic_hover.current_target("basic")

    def basic_hover_status(self):
        return self._basic_hover.status_for("basic")

    def enable_hsl_hover(self, context=None):
        with self.mouse_lock:
            self._basic_hover_contexts.add(f"hsl:{context or 'default'}")
            enabled_kinds = self._enabled_hover_kinds_locked()
        self._basic_hover.set_enabled_kinds(enabled_kinds)
        return self._basic_hover.start()

    def disable_hsl_hover(self, context=None):
        with self.mouse_lock:
            self._basic_hover_contexts.discard(f"hsl:{context or 'default'}")
            should_stop = not self._basic_hover_contexts
            enabled_kinds = self._enabled_hover_kinds_locked()
        self._basic_hover.set_enabled_kinds(enabled_kinds)
        if should_stop:
            self._basic_hover.stop()
            self._color_wheel_states.clear()

    def hsl_hover_target(self):
        return self._basic_hover.current_target("hsl")

    def hsl_hover_status(self):
        return self._basic_hover.status_for("hsl")

    def enable_slider_hover(self, context=None):
        """Atomically enable Basic and HSL for one unified Action context."""
        suffix = context or "default"
        with self.mouse_lock:
            self._basic_hover_contexts.update({f"basic:{suffix}", f"hsl:{suffix}"})
            enabled_kinds = self._enabled_hover_kinds_locked()
        self._basic_hover.set_enabled_kinds(enabled_kinds)
        return self._basic_hover.start()

    def disable_slider_hover(self, context=None):
        suffix = context or "default"
        with self.mouse_lock:
            self._basic_hover_contexts.difference_update(
                {f"basic:{suffix}", f"hsl:{suffix}"}
            )
            should_stop = not self._basic_hover_contexts
            enabled_kinds = self._enabled_hover_kinds_locked()
        self._basic_hover.set_enabled_kinds(enabled_kinds)
        if should_stop:
            self._basic_hover.stop()
            self._color_wheel_states.clear()

    def slider_hover_target(self):
        target = self._basic_hover.current_target()
        if isinstance(target, dict) and target.get("kind", "basic") in {"basic", "hsl"}:
            return target
        return None

    def slider_hover_status(self):
        status = self._basic_hover.status
        if status in {"ready", "ready_cached", "enabled_hover_targets_not_visible"}:
            return "selected_slider_not_hovered"
        return status

    def enable_color_wheel_hover(self, context=None):
        with self.mouse_lock:
            self._basic_hover_contexts.add(f"color_wheels:{context or 'default'}")
            enabled_kinds = self._enabled_hover_kinds_locked()
        self._basic_hover.set_enabled_kinds(enabled_kinds)
        return self._basic_hover.start()

    def disable_color_wheel_hover(self, context=None):
        self.adjustments.clear()
        with self.mouse_lock:
            self._basic_hover_contexts.discard(f"color_wheels:{context or 'default'}")
            should_stop = not self._basic_hover_contexts
            enabled_kinds = self._enabled_hover_kinds_locked()
            self._finish_color_wheel_gesture_locked("action_disabled")
            self._advance_color_wheel_feedback_revision_locked()
        self._basic_hover.set_enabled_kinds(enabled_kinds)
        if should_stop:
            self._basic_hover.stop()
            self._color_wheel_states.clear()

    def color_wheel_hover_target(self):
        return self._basic_hover.current_target("color_wheels")

    def color_wheel_hover_status(self):
        return self._basic_hover.status_for("color_wheels")

    def _enabled_hover_kinds_locked(self):
        return {
            token.partition(":")[0]
            for token in self._basic_hover_contexts
        }

    def _publish_color_wheel_feedback(self, target_key, state):
        hover = getattr(self, "_basic_hover", None)
        if hover is None:
            return False
        try:
            return bool(hover.update_color_wheel_feedback(target_key, state))
        except Exception as exc:
            print(f"color wheel overlay update failed: key={target_key} reason={exc}")
            return False

    def _pin_color_wheel_hover(self, target_key):
        hover = getattr(self, "_basic_hover", None)
        if hover is None:
            return False
        try:
            return bool(hover.pin_color_wheel_target(target_key))
        except Exception as exc:
            print(f"color wheel hover pin failed: key={target_key} reason={exc}")
            return False

    def _release_color_wheel_hover(self, target_key):
        hover = getattr(self, "_basic_hover", None)
        if hover is None:
            return False
        try:
            return bool(hover.release_color_wheel_target(target_key))
        except Exception as exc:
            print(f"color wheel hover release failed: key={target_key} reason={exc}")
            return False

    def _color_wheel_response_gain(self, target_key, mode):
        gains = getattr(self, "_color_wheel_response_gains", None)
        if gains is None:
            gains = {}
            self._color_wheel_response_gains = gains
        target_gains = gains.setdefault(str(target_key or ""), {})
        try:
            value = float(target_gains.get(mode, DEFAULT_RESPONSE_GAIN))
        except (TypeError, ValueError):
            value = DEFAULT_RESPONSE_GAIN
        return min(MAX_RESPONSE_GAIN, max(MIN_RESPONSE_GAIN, value))

    def _store_color_wheel_response_gain(self, target_key, mode, value):
        gains = getattr(self, "_color_wheel_response_gains", None)
        if gains is None:
            gains = {}
            self._color_wheel_response_gains = gains
        value = min(MAX_RESPONSE_GAIN, max(MIN_RESPONSE_GAIN, float(value)))
        gains.setdefault(str(target_key or ""), {})[mode] = value
        return value

    def screen_capture_permission(self):
        return self._basic_hover.screen_capture_available

    @staticmethod
    def _numbers(calibration):
        calibration = calibration or {}
        try:
            x = float(calibration.get("x"))
            y = float(calibration.get("y"))
            pixels = float(calibration.get("pixelsPerStep", 2.0))
            return x, y, pixels
        except (TypeError, ValueError):
            return None

    def adjust_parameter(self, calibration, ticks, fine=False):
        values = self._numbers(calibration)
        if values is None:
            if self._slider_diagnostic_enabled(calibration):
                self._write_slider_diagnostic({
                    "stage": "enqueue",
                    "ok": False,
                    "reason": "parameter_not_calibrated",
                    "requestIds": list(
                        (calibration or {}).get("_sliderDiagRequestIds") or []
                    ),
                })
            return AdjustmentResult(False, reason="parameter is not calibrated")
        if not self.mouse.has_permission():
            if self._slider_diagnostic_enabled(calibration):
                self._write_slider_diagnostic({
                    "stage": "enqueue",
                    "ok": False,
                    "reason": "accessibility_permission_missing",
                    "requestIds": list(
                        (calibration or {}).get("_sliderDiagRequestIds") or []
                    ),
                    "kind": (calibration or {}).get("kind"),
                    "key": (calibration or {}).get("targetKey"),
                })
            return AdjustmentResult(False, reason="macOS Accessibility permission is missing")
        self.adjustments.submit(calibration, ticks, fine)
        if self._slider_diagnostic_enabled(calibration):
            self._write_slider_diagnostic({
                "stage": "enqueue",
                "ok": True,
                "requestIds": list(
                    (calibration or {}).get("_sliderDiagRequestIds") or []
                ),
                "kind": (calibration or {}).get("kind"),
                "key": (calibration or {}).get("targetKey"),
                "ticks": ticks,
                "fine": bool(fine),
            })
        return AdjustmentResult(True, approximate=True)

    def adjust_color_wheel(self, target, ticks, mode="diameter", sensitivity=1.0):
        if not self.target_is_active():
            return AdjustmentResult(False, reason="Jianying Pro is not frontmost")
        if not isinstance(target, dict) or target.get("controlType") != "wheel":
            return AdjustmentResult(False, reason="color wheel is not recognized")
        require_fresh_handle = target.get("handleDetected") is not True
        geometry_source = str(target.get("geometrySource") or "")
        try:
            geometry_component_pixels = int(target.get("geometryComponentPixels") or 0)
        except (TypeError, ValueError):
            geometry_component_pixels = 0
        geometry_verified = bool(target.get("geometryVerified")) or bool(
            geometry_source
            and geometry_source != "layout_fallback"
            and geometry_component_pixels > 0
        )
        if require_fresh_handle and not geometry_verified:
            key = str(target.get("key") or "unknown")
            print(
                "color wheel drag: skipped "
                f"key={key} reason=wheel_geometry_not_verified"
            )
            return AdjustmentResult(False, reason="color wheel geometry is not verified")
        if not self.mouse.has_permission():
            return AdjustmentResult(False, reason="macOS Accessibility permission is missing")
        calibration = deepcopy(target)
        calibration.update({
            "dragMode": "colorWheel",
            "wheelMode": normalize_wheel_mode(mode),
            "sensitivity": sensitivity,
            "targetKey": target.get("key"),
            "x": target.get("handleX", target.get("centerX")),
            "y": target.get("handleY", target.get("centerY")),
            "pixelsPerStep": 1,
            # A verified ring may occasionally be recognized before its white
            # handle. Let the worker run the existing live ROI reacquisition,
            # but never fall back to a guessed centre if that fresh sample fails.
            "requireFreshHandle": require_fresh_handle,
        })
        self.adjustments.submit(calibration, ticks, False)
        return AdjustmentResult(True, approximate=True)

    @staticmethod
    def _slider_diagnostic_enabled(calibration):
        return str((calibration or {}).get("source") or "") in {
            "basic-hover",
            "hsl-hover",
        }

    @staticmethod
    def _slider_diagnostic_rect(rect):
        if not isinstance(rect, dict):
            return None
        try:
            return {
                name: round(float(rect[name]), 2)
                for name in ("x", "y", "w", "h")
            }
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _write_slider_diagnostic(payload):
        try:
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
        except Exception as exc:
            encoded = json.dumps({
                "stage": "logger_error",
                "reason": str(exc),
            }, separators=(",", ":"))
        print("slider diag: " + encoded)

    def _start_slider_probe_process(self):
        lock = getattr(self, "_slider_probe_lock", None)
        if lock is None:
            self._slider_probe_lock = RLock()
            lock = self._slider_probe_lock
        with lock:
            process = getattr(self, "_slider_probe_process", None)
            if process is not None and process.poll() is None:
                return process
            helper_path = str(getattr(self, "_hover_helper_path", "") or "")
            if not helper_path or not os.path.isfile(helper_path):
                self._slider_probe_process = None
                return None
            try:
                process = subprocess.Popen(
                    [helper_path, "ax-probe-loop"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                )
            except (OSError, subprocess.SubprocessError):
                process = None
            if process is not None and process.stdin is not None:
                try:
                    # Prime AppKit/AX asynchronously. The first native AX
                    # lookup can be much slower than every warm lookup; its
                    # tagged response is safely discarded by the request loop.
                    process.stdin.write(
                        '{"probeRequestId":"_warmup","x":0,"y":0}\n'
                    )
                    process.stdin.flush()
                except (BrokenPipeError, OSError):
                    try:
                        process.terminate()
                    except OSError:
                        pass
                    process = None
            self._slider_probe_process = process
            return process

    def _request_slider_accessibility_probe(self, x, y, timeout=0.04):
        lock = getattr(self, "_slider_probe_lock", None)
        if lock is None:
            self._slider_probe_lock = RLock()
            lock = self._slider_probe_lock
        with lock:
            process = self._start_slider_probe_process()
            if (
                process is None
                or process.stdin is None
                or process.stdout is None
            ):
                raise RuntimeError("AX probe helper is unavailable")
            probe_request_id = f"{time.monotonic_ns():x}"
            request = json.dumps({
                "probeRequestId": probe_request_id,
                "x": float(x),
                "y": float(y),
            }, separators=(",", ":"))
            try:
                process.stdin.write(request + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._slider_probe_process = None
                raise RuntimeError("AX probe helper pipe is closed") from exc

            deadline = time.monotonic() + max(0.001, float(timeout))
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("AX probe response timed out")
                readable, _, _ = select.select(
                    [process.stdout],
                    [],
                    [],
                    remaining,
                )
                if not readable:
                    raise TimeoutError("AX probe response timed out")
                line = process.stdout.readline()
                if not line:
                    self._slider_probe_process = None
                    raise RuntimeError("AX probe helper exited")
                try:
                    decoded = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if not isinstance(decoded, dict):
                    continue
                if decoded.get("event") == "ready":
                    continue
                if decoded.get("probeRequestId") != probe_request_id:
                    # A timed-out prior sample may arrive late. Discard it so
                    # it can never be mislabeled as this drag's focus state.
                    continue
                return decoded

    def _probe_slider_accessibility(
        self,
        calibration,
        phase,
        x,
        y,
    ):
        """Best-effort AX snapshot that must never affect the drag outcome."""
        started_at = time.monotonic()
        payload = {
            "stage": "ax_probe",
            "phase": str(phase),
            "requestIds": list(
                (calibration or {}).get("_sliderDiagRequestIds") or []
            ),
            "kind": (calibration or {}).get("kind"),
            "key": (calibration or {}).get("targetKey"),
            "point": {"x": round(float(x), 2), "y": round(float(y), 2)},
        }
        try:
            payload["probe"] = self._request_slider_accessibility_probe(x, y)
        except TimeoutError:
            payload["probe"] = {"ok": False, "reason": "ax_probe_timeout"}
        except Exception as exc:
            payload["probe"] = {
                "ok": False,
                "reason": "ax_probe_failed",
                "error": str(exc)[:240],
            }
        payload["elapsedMs"] = round(
            (time.monotonic() - started_at) * 1000.0,
            2,
        )
        self._write_slider_diagnostic(payload)
        return payload.get("probe")

    def _perform_adjustment(self, calibration, ticks, fine=False):
        slider_diagnostic = self._slider_diagnostic_enabled(calibration)
        frame = bool(calibration.get("_wheelFrame"))
        now = time.monotonic()
        active_at, active = getattr(self, "_wheel_active_check", (0.0, False))
        if not frame or now - active_at >= 0.050:
            active = self.target_is_active()
            self._wheel_active_check = (now, active)
        if not active:
            if frame:
                self.adjustments.clear()
            if slider_diagnostic:
                self._write_slider_diagnostic({
                    "stage": "skipped",
                    "reason": "target_inactive",
                    "requestIds": list(
                        (calibration or {}).get("_sliderDiagRequestIds") or []
                    ),
                    "kind": (calibration or {}).get("kind"),
                    "key": (calibration or {}).get("targetKey"),
                    "ticks": ticks,
                    "fine": bool(fine),
                })
            with self.mouse_lock:
                self._finish_color_wheel_gesture_locked("target_inactive")
            return
        if str((calibration or {}).get("dragMode")) == "colorWheel":
            target_key = str(calibration.get("targetKey") or "")
            mode = normalize_wheel_mode(calibration.get("wheelMode"))
            with self.mouse_lock:
                if frame and not self.adjustments.is_current(calibration):
                    return
                signature = self._color_wheel_signature(calibration)
                session = self._color_wheel_gesture
                cached_state = self._color_wheel_states.get(target_key)
                continuing_preview = bool(
                    session is None
                    and mode == "orbit"
                    and isinstance(cached_state, dict)
                    and cached_state.get("signature") == signature
                    and cached_state.get("orbitPreview") is True
                )
                continuing = bool(
                    continuing_preview
                    or (
                        session
                        and session.get("key") == target_key
                        and session.get("signature") == signature
                        and session.get("mode") == mode
                    )
                )
                if not continuing:
                    resumable_state = (
                        deepcopy(self._color_wheel_states.get(target_key))
                        if session is None
                        else None
                    )
                    finish_reason = (
                        "mode_changed"
                        if session
                        and session.get("key") == target_key
                        and session.get("signature") == signature
                        else "target_changed"
                    )
                    self._finish_color_wheel_gesture_locked(finish_reason)
                    if getattr(self, "_color_wheel_feedback_inflight", False):
                        synchronized = None
                        print(
                            "color wheel handle sync: "
                            f"key={target_key} result=skipped "
                            "reason=background_feedback_inflight"
                        )
                    else:
                        synchronized = self._synchronize_color_wheel_handle_locked(
                            calibration,
                            target_key,
                        )
                    if synchronized is None:
                        if calibration.get("requireFreshHandle"):
                            self._color_wheel_states.pop(target_key, None)
                            print(
                                "color wheel drag: skipped "
                                f"key={target_key} "
                                "reason=fresh_white_handle_not_detected"
                            )
                            return
                        calibration = self._fallback_color_wheel_calibration_locked(
                            calibration,
                            target_key,
                        )
                    else:
                        calibration = synchronized
                    resume = resume_diameter_state if mode == "diameter" else resume_orbit_state
                    resumed_state = resume(
                        calibration,
                        resumable_state,
                    )
                    if resumed_state is None:
                        self._color_wheel_states.pop(target_key, None)
                    else:
                        self._color_wheel_states[target_key] = resumed_state
                        print(
                            "color wheel diameter axis: resumed "
                            f"key={target_key} "
                            f"mode={mode} angle={math.degrees(resumed_state['angle']):.1f}deg "
                            f"radius={resumed_state['radius']:.1f}px"
                        )
                    # When a paused diameter is resumed at the centre, publish
                    # its remembered axis immediately. Publishing the raw
                    # centre handle here would briefly use the overlay's
                    # default -90 degree angle before the first drag segment.
                    self._publish_color_wheel_feedback(
                        target_key,
                        resumed_state or calibration,
                    )
                response_gain = self._color_wheel_response_gain(target_key, mode)
                plan = plan_wheel_motion(
                    calibration,
                    ticks,
                    mode,
                    calibration.get("sensitivity", 1.0),
                    self._color_wheel_states.get(target_key),
                    response_gain,
                )
                path = plan.get("path") or []
                on_screen = getattr(self.mouse, "point_on_screen", None)
                if frame and path and on_screen and not on_screen(*path[-1]):
                    session = self._color_wheel_gesture
                    previous = deepcopy(self._color_wheel_states.get(target_key))
                    original = session.get("original") if session else None
                    self._finish_color_wheel_gesture_locked("screen_edge", restore_pointer=False)
                    time.sleep(0.020)
                    fresh = self._synchronize_color_wheel_handle_locked(calibration, target_key)
                    if fresh is None:
                        self.adjustments.clear()
                        return
                    rebased = (resume_diameter_state if mode == "diameter" else resume_orbit_state)(fresh, previous)
                    if mode == "diameter" and previous and rebased is None:
                        # Preserve the trusted diameter after a clipped cursor,
                        # but land on the freshly observed actual white point.
                        rebased = dict(previous)
                        rebased.update(handleX=fresh["handleX"], handleY=fresh["handleY"],
                                       cursorX=fresh["handleX"], cursorY=fresh["handleY"])
                        dx = fresh["handleX"] - rebased["centerX"]
                        dy = fresh["handleY"] - rebased["centerY"]
                        rebased["signedRadius"] = dx * math.cos(rebased["axisAngle"]) + dy * math.sin(rebased["axisAngle"])
                    calibration = fresh
                    plan = plan_wheel_motion(fresh, ticks, mode, 1.0, rebased, response_gain)
                    plan["restoreOriginal"] = original
                    path = plan.get("path") or []
                    if path and not on_screen(*path[-1]):
                        self.adjustments.clear()
                        return
                if frame:
                    if not self.adjustments.is_current(calibration):
                        return
                    # The owner queue already budgets each frame. One endpoint
                    # avoids per-segment sleeps and lets reversal preempt the
                    # next frame rather than wait through a long mouse path.
                    plan["singleFrame"] = True
                    if path:
                        path = plan["path"] = [path[-1]]
                if path:
                    end_x, end_y = path[-1]
                    applied = self._continue_color_wheel_gesture_locked(
                        target_key,
                        plan,
                        path,
                        mode,
                        calibration,
                    )
                    if applied is False:
                        return
                    self._color_wheel_states[target_key] = plan["state"]
                    self._advance_color_wheel_feedback_revision_locked()
                    self._maybe_feedback_color_wheel_handle_locked(
                        calibration,
                        target_key,
                        mode,
                    )
                    if not frame or time.monotonic() - getattr(self, "_wheel_log_at", 0) >= .25:
                        self._wheel_log_at = time.monotonic()
                        print(
                            "color wheel drag segment: "
                            f"key={target_key} mode={mode} "
                            f"ticks={round(float(ticks), 2)} "
                            f"handle=({float(calibration.get('handleX')):.1f},"
                            f"{float(calibration.get('handleY')):.1f}) "
                            f"center=({float(calibration.get('centerX')):.1f},"
                            f"{float(calibration.get('centerY')):.1f}) "
                            f"start=({plan['startX']:.1f},{plan['startY']:.1f}) "
                            f"end=({end_x:.1f},{end_y:.1f}) points={len(path)} "
                            f"gain={plan['responseGain']:.3f} "
                            f"cursorDistance={plan['cursorDistance']:.1f} "
                            f"duration={plan.get('dragDurationMs', 0):.1f}ms held=true"
                        )
                    self._publish_color_wheel_feedback(
                        target_key,
                        plan["state"],
                    )
                elif plan.get("previewOnly"):
                    # A centred white handle represents zero strength. Orbit
                    # rotation should select direction without changing the
                    # Jianying value, so update only the outer colored dot.
                    self._color_wheel_states[target_key] = plan["state"]
                    self._advance_color_wheel_feedback_revision_locked()
                    self._publish_color_wheel_feedback(target_key, plan["state"])
                    if not frame or time.monotonic() - getattr(self, "_wheel_log_at", 0) >= .25:
                        self._wheel_log_at = time.monotonic()
                        print(
                            "color wheel orbit preview: "
                            f"key={target_key} ticks={round(float(ticks), 2)} "
                            f"angle={math.degrees(plan['state']['angle']):.1f}deg "
                            "handle=center mouseDrag=false"
                        )
                return {"boundary": not path and not plan.get("previewOnly")}
            return
        x, y, pixels = self._numbers(calibration)
        if str((calibration or {}).get("dragMode")) == "absoluteWheel":
            with self.mouse_lock:
                self._finish_color_wheel_gesture_locked("other_adjustment")
                self._activate_panel_locked(calibration)
                self.mouse.drag(
                    x,
                    y,
                    float(calibration.get("offsetX", 0)),
                    float(calibration.get("offsetY", 0)),
                )
            return
        scale = 0.25 if fine else 1.0
        axis = str((calibration or {}).get("axis", "horizontal"))
        distance = float(ticks) * pixels * scale
        delta_x = 0.0 if axis == "vertical" else distance
        delta_y = -distance if axis == "vertical" else 0.0
        end_x = x + delta_x
        end_y = y + delta_y
        hover_target = (calibration or {}).get("hoverTarget")
        keep_on_input = (
            isinstance(hover_target, dict)
            and hover_target.get("controlType") == "slider"
            and hover_target.get("kind") in {"basic", "hsl"}
        )
        if slider_diagnostic:
            hover_target = (calibration or {}).get("hoverTarget")
            hover_target = hover_target if isinstance(hover_target, dict) else {}
            hover_rect = self._slider_diagnostic_rect(
                hover_target.get("hoverRect")
            )
            overlay_rect = self._slider_diagnostic_rect(
                hover_target.get("overlayRect") or hover_target.get("hoverRect")
            )
            overlay_right_gap = None
            if overlay_rect is not None:
                overlay_right_gap = round(
                    x - overlay_rect["x"] - overlay_rect["w"],
                    2,
                )
            self._write_slider_diagnostic({
                "stage": "drag_plan",
                "requestIds": list(
                    (calibration or {}).get("_sliderDiagRequestIds") or []
                ),
                "kind": (calibration or {}).get("kind"),
                "key": (calibration or {}).get("targetKey"),
                "source": (calibration or {}).get("source"),
                "ticks": ticks,
                "fine": bool(fine),
                "axis": axis,
                "pixelsPerStep": pixels,
                "scale": scale,
                "start": {"x": round(x, 2), "y": round(y, 2)},
                "delta": {
                    "x": round(delta_x, 2),
                    "y": round(delta_y, 2),
                },
                "end": {"x": round(end_x, 2), "y": round(end_y, 2)},
                "hoverRect": hover_rect,
                "overlayRect": overlay_rect,
                "targetToOverlayRight": overlay_right_gap,
                "recognition": {
                    name: hover_target.get(name)
                    for name in (
                        "scanVersion",
                        "geometrySource",
                        "valueSource",
                        "overlaySource",
                    )
                    if hover_target.get(name) is not None
                },
            })
        with self.mouse_lock:
            self._finish_color_wheel_gesture_locked("other_adjustment")
            self._activate_panel_locked(calibration)
            if slider_diagnostic:
                self._probe_slider_accessibility(
                    calibration,
                    "before",
                    x,
                    y,
                )
            try:
                drag_trace = self.mouse.drag(
                    x, y, delta_x, delta_y,
                    restore_pointer=not keep_on_input,
                )
                if keep_on_input:
                    # Rest on the numeric field, never the old hover position.
                    # A large batch can end outside the row's hover hit area;
                    # returning to this field keeps the next detent on the
                    # same parameter after mouse-up.
                    time.sleep(0.01)
                    self.mouse.move(x, y)
                    if isinstance(drag_trace, dict):
                        drag_trace["restingPointerX"] = x
                        drag_trace["restingPointerY"] = y
            except Exception as exc:
                if slider_diagnostic:
                    self._write_slider_diagnostic({
                        "stage": "drag_result",
                        "requestIds": list(
                            (calibration or {}).get("_sliderDiagRequestIds") or []
                        ),
                        "kind": (calibration or {}).get("kind"),
                        "key": (calibration or {}).get("targetKey"),
                        "ok": False,
                        "error": str(exc)[:240],
                    })
                raise
            if slider_diagnostic:
                self._probe_slider_accessibility(
                    calibration,
                    "after",
                    x if keep_on_input else end_x,
                    y if keep_on_input else end_y,
                )
                self._write_slider_diagnostic({
                    "stage": "drag_result",
                    "requestIds": list(
                        (calibration or {}).get("_sliderDiagRequestIds") or []
                    ),
                    "kind": (calibration or {}).get("kind"),
                    "key": (calibration or {}).get("targetKey"),
                    "ok": True,
                    "trace": drag_trace,
                })

    @staticmethod
    def _color_wheel_signature(target):
        target = target or {}
        try:
            return (
                str(target.get("key") or target.get("targetKey") or ""),
                round(float(target.get("centerX")), 1),
                round(float(target.get("centerY")), 1),
                round(float(target.get("wheelRadius")), 1),
                int(float(target.get("scanVersion", 0))),
            )
        except (TypeError, ValueError):
            return None

    def _synchronize_color_wheel_handle_locked(self, calibration, target_key):
        calibration = deepcopy(calibration or {})
        try:
            center_x = float(calibration.get("centerX"))
            center_y = float(calibration.get("centerY"))
            radius = float(calibration.get("wheelRadius"))
        except (TypeError, ValueError):
            print(
                f"color wheel handle sync: key={target_key} "
                "result=skipped reason=invalid_geometry"
            )
            return None
        predicted_state = self._color_wheel_states.get(target_key) or {}
        predicted_x = float(predicted_state.get(
            "handleX", calibration.get("handleX", center_x)
        ))
        predicted_y = float(predicted_state.get(
            "handleY", calibration.get("handleY", center_y)
        ))
        started_at = time.monotonic()
        try:
            result = subprocess.run(
                [
                    self._hover_helper_path,
                    "locate-wheel-handle",
                    str(center_x),
                    str(center_y),
                    str(radius),
                ],
                capture_output=True,
                text=True,
                timeout=max(
                    0.05,
                    float(getattr(self, "color_wheel_handle_timeout_seconds", 0.4)),
                ),
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            print(
                f"color wheel handle sync: key={target_key} "
                f"result=failed reason={exc}"
            )
            return None
        payload = None
        for line in reversed((result.stdout or "").splitlines()):
            try:
                payload = json.loads(line)
                break
            except (TypeError, json.JSONDecodeError):
                continue
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            reason = (
                payload.get("reason")
                if isinstance(payload, dict)
                else "invalid_helper_response"
            )
            print(
                f"color wheel handle sync: key={target_key} "
                f"result=failed reason={reason} "
                f"duration={int((time.monotonic() - started_at) * 1000)}ms"
            )
            return None
        try:
            actual_x = float(payload.get("handleX"))
            actual_y = float(payload.get("handleY"))
        except (TypeError, ValueError):
            print(
                f"color wheel handle sync: key={target_key} "
                "result=failed reason=invalid_handle"
            )
            return None
        calibration.update({
            "x": actual_x,
            "y": actual_y,
            "handleX": actual_x,
            "handleY": actual_y,
            "handleDetected": True,
        })
        drift = ((actual_x - predicted_x) ** 2 + (actual_y - predicted_y) ** 2) ** 0.5
        print(
            f"color wheel handle sync: key={target_key} result=ready "
            f"predicted=({predicted_x:.1f},{predicted_y:.1f}) "
            f"actual=({actual_x:.1f},{actual_y:.1f}) drift={drift:.1f}px "
            f"duration={int((time.monotonic() - started_at) * 1000)}ms"
        )
        return calibration

    def _fallback_color_wheel_calibration_locked(self, calibration, target_key):
        """Keep an encoder event usable when a fresh white-handle sample times out."""
        fallback = deepcopy(calibration or {})
        state = self._color_wheel_states.get(target_key)
        if (
            isinstance(state, dict)
            and state.get("signature") == self._color_wheel_signature(fallback)
        ):
            source = state
            reason = "predicted_state"
        else:
            source = fallback
            reason = "scan_cache"
        try:
            handle_x = float(source.get(
                "handleX",
                fallback.get("handleX", fallback.get("centerX")),
            ))
            handle_y = float(source.get(
                "handleY",
                fallback.get("handleY", fallback.get("centerY")),
            ))
        except (AttributeError, TypeError, ValueError):
            return fallback
        fallback.update({
            "x": handle_x,
            "y": handle_y,
            "handleX": handle_x,
            "handleY": handle_y,
            "handleDetected": True,
        })
        print(
            "color wheel handle sync: "
            f"key={target_key} result=fallback source={reason} "
            f"handle=({handle_x:.1f},{handle_y:.1f})"
        )
        return fallback

    def _advance_color_wheel_feedback_revision_locked(self):
        revision = int(getattr(self, "_color_wheel_feedback_revision", 0)) + 1
        self._color_wheel_feedback_revision = revision
        return revision

    def _apply_color_wheel_feedback_locked(
        self,
        target_key,
        mode,
        state,
        synchronized,
        session,
    ):
        state = deepcopy(state or {})
        try:
            actual_x = float(synchronized.get("handleX"))
            actual_y = float(synchronized.get("handleY"))
            center_x = float(state.get("centerX"))
            center_y = float(state.get("centerY"))
            cursor_x = float(session.get("x"))
            cursor_y = float(session.get("y"))
        except (AttributeError, TypeError, ValueError):
            return state

        try:
            previous_handle_x = float(session.get("feedbackHandleX"))
            previous_handle_y = float(session.get("feedbackHandleY"))
            previous_cursor_x = float(session.get("feedbackCursorX"))
            previous_cursor_y = float(session.get("feedbackCursorY"))
        except (TypeError, ValueError):
            previous_handle_x = actual_x
            previous_handle_y = actual_y
            previous_cursor_x = cursor_x
            previous_cursor_y = cursor_y

        cursor_dx = cursor_x - previous_cursor_x
        cursor_dy = cursor_y - previous_cursor_y
        handle_dx = actual_x - previous_handle_x
        handle_dy = actual_y - previous_handle_y
        cursor_distance_sq = cursor_dx * cursor_dx + cursor_dy * cursor_dy
        old_gain = self._color_wheel_response_gain(target_key, mode)
        measured_gain = None
        if cursor_distance_sq >= 16.0:
            projected_gain = (
                handle_dx * cursor_dx + handle_dy * cursor_dy
            ) / cursor_distance_sq
            if projected_gain > 0.01:
                measured_gain = min(
                    MAX_RESPONSE_GAIN,
                    max(MIN_RESPONSE_GAIN, projected_gain),
                )
        if measured_gain is not None:
            new_gain = self._store_color_wheel_response_gain(
                target_key,
                mode,
                old_gain * 0.65 + measured_gain * 0.35,
            )
        else:
            new_gain = old_gain

        dx = actual_x - center_x
        dy = actual_y - center_y
        actual_radius = math.hypot(dx, dy)
        if mode == "diameter" and state.get("axisAngle") is not None:
            axis_angle = float(state["axisAngle"])
            signed_radius = dx * math.cos(axis_angle) + dy * math.sin(axis_angle)
            angle = axis_angle if signed_radius >= 0 else axis_angle + math.pi
            state.update({
                "axisAngle": axis_angle,
                "signedRadius": signed_radius,
                "radius": abs(signed_radius),
                "angle": angle,
            })
        else:
            angle = (
                math.atan2(dy, dx)
                if actual_radius >= 1.5
                else float(state.get("angle", -math.pi / 2))
            )
            state.update({
                "radius": actual_radius,
                "angle": angle,
            })
            if mode == "orbit":
                intended = float(state.get("orbitRadius", actual_radius))
                if abs(actual_radius - intended) > 3.0 and not synchronized.get("orbitDriftConfirmed"):
                    # Large corrections require fresh stationary evidence;
                    # never steer outward from one delayed screenshot.
                    state["orbitCorrectionAllowed"] = False
                    if synchronized.get("feedbackFinal"):
                        state["orbitRadius"] = actual_radius
                else:
                    state["orbitCorrectionAllowed"] = True
        state.update({
            "handleX": actual_x,
            "handleY": actual_y,
            "cursorX": cursor_x,
            "cursorY": cursor_y,
            "lastMode": mode,
            "responseGain": new_gain,
        })
        session.update({
            "feedbackHandleX": actual_x,
            "feedbackHandleY": actual_y,
            "feedbackCursorX": cursor_x,
            "feedbackCursorY": cursor_y,
            "lastFeedbackSegment": int(session.get("segments", 0)),
        })
        actual_distance = math.hypot(handle_dx, handle_dy)
        cursor_distance = math.sqrt(cursor_distance_sq)
        measured_text = "n/a" if measured_gain is None else f"{measured_gain:.3f}"
        print(
            "color wheel closed-loop feedback: "
            f"key={target_key} mode={mode} "
            f"cursor={cursor_distance:.1f}px actual={actual_distance:.1f}px "
            f"measuredGain={measured_text} gain={old_gain:.3f}->{new_gain:.3f} "
            f"handle=({actual_x:.1f},{actual_y:.1f})"
        )
        return state

    def _schedule_color_wheel_feedback_locked(
        self,
        calibration,
        target_key,
        mode,
        session=None,
        final=False,
    ):
        """Sample the real white handle without blocking encoder processing."""
        session = session or self._color_wheel_gesture
        state = self._color_wheel_states.get(target_key)
        if not session or not isinstance(state, dict):
            return False
        request = {
            "calibration": deepcopy(calibration or {}),
            "key": str(target_key or ""),
            "mode": normalize_wheel_mode(mode),
            "session": session,
            "segments": int(session.get("segments", 0)),
            "revision": int(getattr(self, "_color_wheel_feedback_revision", 0)),
            "final": bool(final),
            "state": deepcopy(state),
        }
        if getattr(self, "_color_wheel_feedback_inflight", False):
            # Only the newest sample matters. In particular, the idle sample
            # must supersede an older mid-gesture request.
            self._color_wheel_feedback_pending = request
            return False
        self._start_color_wheel_feedback_request_locked(request)
        return True

    def _start_color_wheel_feedback_request_locked(self, request):
        self._color_wheel_feedback_inflight = True
        try:
            worker = Thread(
                target=self._run_color_wheel_feedback_request,
                args=(request,),
                name="jianying-color-wheel-feedback",
                daemon=True,
            )
            worker.start()
        except Exception:
            self._color_wheel_feedback_inflight = False
            raise

    def _run_color_wheel_feedback_request(self, request):
        target_key = request["key"]
        try:
            synchronized = self._synchronize_color_wheel_handle_locked(
                request["calibration"],
                target_key,
            )
            if synchronized and request["final"] and request["mode"] == "orbit":
                expected = request.get("state") or {}
                cx, cy = expected.get("centerX", 0), expected.get("centerY", 0)
                intended = expected.get("orbitRadius", expected.get("radius", 0))
                actual = math.hypot(synchronized["handleX"] - cx, synchronized["handleY"] - cy)
                if (intended >= .90 * expected.get("wheelRadius", 1)
                        and max(4, .08 * expected.get("wheelRadius", 1)) <= intended - actual <= 12
                        and math.hypot(synchronized["handleX"] - expected.get("handleX", cx),
                                       synchronized["handleY"] - expected.get("handleY", cy)) <= 12):
                    samples = [synchronized]
                    for _ in range(2):
                        time.sleep(.020)
                        fresh = self._synchronize_color_wheel_handle_locked(request["calibration"], target_key)
                        if not fresh or math.hypot(fresh["handleX"] - synchronized["handleX"],
                                                   fresh["handleY"] - synchronized["handleY"]) > 2:
                            break
                        samples.append(fresh)
                    if len(samples) == 3:
                        synchronized = dict(samples[-1], orbitDriftConfirmed=True)
        except Exception as exc:
            synchronized = None
            print(
                "color wheel feedback: "
                f"key={target_key} result=failed error={exc}"
            )
        discard_reason = None
        with self.mouse_lock:
            revision = int(getattr(self, "_color_wheel_feedback_revision", 0))
            session = self._color_wheel_gesture
            request_session = request["session"]
            if request["revision"] != revision:
                discard_reason = "newer_motion"
            elif request["final"]:
                if session is not None:
                    discard_reason = "new_gesture"
            elif (
                session is not request_session
                or int(session.get("segments", 0)) != request["segments"]
            ):
                discard_reason = "newer_segment"
            state = self._color_wheel_states.get(target_key)
            if synchronized is None:
                discard_reason = discard_reason or "sample_failed"
            elif not isinstance(state, dict):
                discard_reason = discard_reason or "state_missing"
            if discard_reason is None:
                synchronized["feedbackFinal"] = request["final"]
                corrected = self._apply_color_wheel_feedback_locked(
                    target_key,
                    request["mode"],
                    state,
                    synchronized,
                    request_session,
                )
                self._color_wheel_states[target_key] = corrected
                self._publish_color_wheel_feedback(target_key, corrected)
            self._color_wheel_feedback_inflight = False
            pending = getattr(self, "_color_wheel_feedback_pending", None)
            self._color_wheel_feedback_pending = None
            if pending is not None:
                self._start_color_wheel_feedback_request_locked(pending)
        if discard_reason:
            print(
                "color wheel feedback: "
                f"key={target_key} result=discarded reason={discard_reason}"
            )

    def _maybe_feedback_color_wheel_handle_locked(self, calibration, target_key, mode):
        session = self._color_wheel_gesture
        if not session:
            return None
        now = time.monotonic()
        if session.get("singleFrame"):
            if now - session.get("feedbackAt", now) < .18:
                return None
            session["feedbackAt"] = now
        segments = int(session.get("segments", 0))
        last_feedback = int(session.get("lastFeedbackSegment", 0))
        interval = max(1, int(getattr(self, "color_wheel_feedback_segments", 3)))
        if segments - last_feedback < interval:
            return None
        session["lastFeedbackSegment"] = segments
        self._schedule_color_wheel_feedback_locked(
            calibration,
            target_key,
            mode,
            session=session,
            final=False,
        )
        return None

    def _continue_color_wheel_gesture_locked(
        self,
        target_key,
        plan,
        path,
        mode,
        calibration,
    ):
        if not plan.get("singleFrame"):
            self._cancel_color_wheel_release_locked()
        state = plan.get("state") or {}
        signature = state.get("signature")
        session = self._color_wheel_gesture
        compatible = bool(
            session
            and session.get("key") == target_key
            and session.get("signature") == signature
            and session.get("mode") == mode
            and abs(float(session.get("x")) - float(plan["startX"])) <= 1.5
            and abs(float(session.get("y")) - float(plan["startY"])) <= 1.5
        )
        if not compatible:
            self._finish_color_wheel_gesture_locked("target_changed")
            hover_pinned = self._pin_color_wheel_hover(target_key)
            try:
                original = self.mouse.begin_drag(
                    plan["startX"],
                    plan["startY"],
                    press_delay=0.035,
                )
            except Exception:
                if hover_pinned:
                    self._release_color_wheel_hover(target_key)
                raise
            self._color_wheel_gesture = {
                "key": target_key,
                "signature": signature,
                "mode": mode,
                "x": float(plan["startX"]),
                "y": float(plan["startY"]),
                "original": plan.get("restoreOriginal") or original,
                "singleFrame": bool(plan.get("singleFrame")),
                "feedbackAt": time.monotonic(),
                "segments": 0,
                "lastFeedbackSegment": 0,
                "feedbackHandleX": float(calibration.get("handleX", plan["startX"])),
                "feedbackHandleY": float(calibration.get("handleY", plan["startY"])),
                "feedbackCursorX": float(plan["startX"]),
                "feedbackCursorY": float(plan["startY"]),
                "calibration": deepcopy(calibration),
                "hoverPinned": hover_pinned,
            }
            print(
                "color wheel drag begin: "
                f"key={target_key} start=({plan['startX']:.1f},{plan['startY']:.1f})"
            )
        try:
            started_at = time.monotonic()
            angles = plan.get("orbitAngles") or []
            if plan.get("singleFrame"):
                if not self.adjustments.is_current(calibration):
                    self._finish_color_wheel_gesture_locked("input_cancelled")
                    return False
                end_x, end_y = path[-1]
                self.mouse.move(end_x, end_y, self.mouse.EVENT_LEFT_DRAGGED)
            elif mode == "orbit" and len(angles) == len(path):
                next_feedback_at = started_at + 1.0 / 60.0

                def publish_progress(index, count):
                    nonlocal next_feedback_at
                    now = time.monotonic()
                    if now < next_feedback_at and index != count:
                        return
                    angle = angles[index - 1]
                    feedback = dict(state)
                    feedback.update({
                        "angle": angle,
                        "handleX": state["centerX"] + math.cos(angle) * state["radius"],
                        "handleY": state["centerY"] + math.sin(angle) * state["radius"],
                        "cursorX": path[index - 1][0],
                        "cursorY": path[index - 1][1],
                    })
                    self._publish_color_wheel_feedback(target_key, feedback)
                    next_feedback_at = time.monotonic() + 1.0 / 60.0

                end_x, end_y = self.mouse.continue_drag(
                    path,
                    duration=plan["duration"],
                    on_progress=publish_progress,
                )
            else:
                end_x, end_y = self.mouse.continue_drag(path, duration=0.055)
            plan["dragDurationMs"] = (time.monotonic() - started_at) * 1000.0
        except Exception:
            self._finish_color_wheel_gesture_locked("drag_failed")
            raise
        session = self._color_wheel_gesture
        session["x"] = float(end_x)
        session["y"] = float(end_y)
        session["segments"] = int(session.get("segments", 0)) + 1
        session["lastOutputAt"] = time.monotonic()
        if not plan.get("singleFrame") or self._color_wheel_release_timer is None:
            self._schedule_color_wheel_release_locked()

    def _cancel_color_wheel_release_locked(self):
        timer = self._color_wheel_release_timer
        self._color_wheel_release_timer = None
        if timer is not None:
            timer.cancel()

    def _schedule_color_wheel_release_locked(self, delay=None):
        self._cancel_color_wheel_release_locked()
        self._color_wheel_gesture_generation += 1
        generation = self._color_wheel_gesture_generation
        timer = Timer(
            self.color_wheel_idle_release_seconds if delay is None else delay,
            self._release_color_wheel_after_idle,
            args=(generation,),
        )
        timer.daemon = True
        self._color_wheel_release_timer = timer
        timer.start()

    def _release_color_wheel_after_idle(self, generation):
        with self.mouse_lock:
            if generation != self._color_wheel_gesture_generation:
                return
            self._color_wheel_release_timer = None
            session = self._color_wheel_gesture
            if session and session.get("singleFrame"):
                remaining = self.color_wheel_idle_release_seconds - (time.monotonic() - session.get("lastOutputAt", 0))
                if remaining > 0:
                    self._schedule_color_wheel_release_locked(delay=remaining)
                    return
            self._finish_color_wheel_gesture_locked("idle")

    def _finish_color_wheel_gesture_locked(self, reason, restore_pointer=True):
        self._cancel_color_wheel_release_locked()
        session = self._color_wheel_gesture
        self._color_wheel_gesture = None
        if not session:
            return
        try:
            self.mouse.end_drag(
                session["x"],
                session["y"],
                session.get("original"),
                restore_pointer=restore_pointer,
            )
            print(
                "color wheel drag end: "
                f"key={session.get('key')} reason={reason} "
                f"end=({session['x']:.1f},{session['y']:.1f}) "
                f"segments={session.get('segments', 0)}"
            )
            if reason == "idle":
                target_key = str(session.get("key") or "")
                mode = normalize_wheel_mode(session.get("mode"))
                calibration = session.get("calibration") or {}
                self._schedule_color_wheel_feedback_locked(
                    calibration,
                    target_key,
                    mode,
                    session=session,
                    final=True,
                )
        except Exception as exc:
            print(f"color wheel drag end failed: reason={reason} error={exc}")
        finally:
            if session.get("hoverPinned"):
                self._release_color_wheel_hover(session.get("key"))

    def _activate_panel_locked(self, calibration):
        calibration = calibration or {}
        try:
            point = (float(calibration.get("preClickX")), float(calibration.get("preClickY")))
        except (TypeError, ValueError):
            return
        now = time.monotonic()
        last_point, last_time = self._last_panel_activation
        if last_point == point and now - last_time < 1.5:
            return
        self.mouse.click(point[0], point[1])
        self._last_panel_activation = (point, now)
        try:
            delay = float(calibration.get("preClickDelay", 0.12))
        except (TypeError, ValueError):
            delay = 0.12
        time.sleep(min(0.5, max(0.02, delay)))

    def reset_parameter(self, calibration):
        if not self.target_is_active():
            return AdjustmentResult(False, reason="Jianying Pro is not frontmost")
        values = self._numbers(calibration)
        if values is None:
            return AdjustmentResult(False, reason="parameter is not calibrated")
        if not self.mouse.has_permission():
            return AdjustmentResult(False, reason="macOS Accessibility permission is missing")
        try:
            self.adjustments.clear()
            with self.mouse_lock:
                self._finish_color_wheel_gesture_locked("reset_parameter")
                self._activate_panel_locked(calibration)
                self.mouse.double_click(values[0], values[1])
            return AdjustmentResult(True, approximate=True)
        except Exception as exc:
            return AdjustmentResult(False, reason=str(exc))

    def reset_color_wheel(self, target):
        if not self.target_is_active():
            return AdjustmentResult(False, reason="Jianying Pro is not frontmost")
        if not isinstance(target, dict):
            return AdjustmentResult(False, reason="color wheel is not recognized")
        if not self.mouse.has_permission():
            return AdjustmentResult(False, reason="macOS Accessibility permission is missing")
        try:
            reset_x = float(target.get("resetX"))
            reset_y = float(target.get("resetY"))
        except (TypeError, ValueError):
            return AdjustmentResult(False, reason="color wheel reset target is unavailable")
        try:
            self.adjustments.clear()
            with self.mouse_lock:
                self._finish_color_wheel_gesture_locked("reset_color_wheel")
                self._advance_color_wheel_feedback_revision_locked()
                if target.get("resetMode") == "click":
                    self.mouse.click(reset_x, reset_y)
                else:
                    self.mouse.double_click(reset_x, reset_y)
                key = str(target.get("key") or "")
                if target.get("controlType") == "wheel" and key:
                    state = centered_wheel_state(target, preserve_vertical_axis=True)
                    self._color_wheel_states[key] = state
                    self._publish_color_wheel_feedback(key, state)
            return AdjustmentResult(True, approximate=True)
        except Exception as exc:
            return AdjustmentResult(False, reason=str(exc))
