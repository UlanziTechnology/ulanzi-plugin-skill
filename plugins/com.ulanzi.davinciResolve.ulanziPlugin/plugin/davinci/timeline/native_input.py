"""Cross-platform native keyboard and high-resolution wheel injection."""

import ctypes
import platform
import threading
import time


IS_MAC = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"

_MAC_AVAILABLE = False
_NSWorkspace = None
_NSRunningApplication = None
if IS_MAC:
    try:
        from AppKit import (
            NSRunningApplication as _NSRunningApplication,
            NSWorkspace as _NSWorkspace,
        )
        from Quartz import (
            CGEventCreate,
            CGEventCreateKeyboardEvent,
            CGEventCreateMouseEvent,
            CGEventCreateScrollWheelEvent,
            CGEventGetLocation,
            CGEventPost,
            CGEventSetFlags,
            CGPreflightPostEventAccess,
            CGSessionCopyCurrentDictionary,
            kCGEventFlagMaskAlternate,
            kCGEventFlagMaskCommand,
            kCGEventFlagMaskControl,
            kCGEventFlagMaskShift,
            kCGEventMouseMoved,
            kCGHIDEventTap,
            kCGMouseButtonLeft,
            kCGScrollEventUnitPixel,
        )
        _MAC_AVAILABLE = True
    except ImportError:
        _MAC_AVAILABLE = False


MAC_KEY_CODES = {
    "left": 123,
    "right": 124,
    "down": 125,
    "up": 126,
    "minus": 27,
    "equal": 24,
    "command": 55,
    "shift": 56,
    "option": 58,
    "control": 59,
}
MAC_MODIFIER_FLAGS = {}
if _MAC_AVAILABLE:
    MAC_MODIFIER_FLAGS = {
        "shift": kCGEventFlagMaskShift,
        "command": kCGEventFlagMaskCommand,
        "option": kCGEventFlagMaskAlternate,
        "control": kCGEventFlagMaskControl,
    }

WINDOWS_KEY_CODES = {
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "minus": 0xBD,
    "equal": 0xBB,
    "shift": 0x10,
    "control": 0x11,
    "option": 0x12,
    "command": 0x11,
}
WINDOWS_EXTENDED_KEY_CODES = {
    WINDOWS_KEY_CODES["left"],
    WINDOWS_KEY_CODES["up"],
    WINDOWS_KEY_CODES["right"],
    WINDOWS_KEY_CODES["down"],
}

VIEW_SCROLL_MODIFIERS = {
    "track_height": ("shift",),
    "timeline_zoom": ("option",),
    "vertical_scroll": (),
    "horizontal_scroll": ("command",),
}

# Positive dial ticks mean expand, zoom in, scroll down/right.
VIEW_SCROLL_SIGNS = {
    "track_height": 1,
    "timeline_zoom": 1,
    "vertical_scroll": -1,
    "horizontal_scroll": -1,
}

MAC_PIXELS_PER_TICK = {
    "track_height": 18.0,
    "timeline_zoom": 16.0,
    "vertical_scroll": 32.0,
    "horizontal_scroll": 34.0,
}

WINDOWS_WHEEL_DELTA_PER_TICK = {
    "track_height": 60.0,
    "timeline_zoom": 60.0,
    "vertical_scroll": 60.0,
    "horizontal_scroll": 60.0,
}


class NativeTimelineInput:
    """Inject input without moving the pointer away from the timeline."""

    def __init__(self, key_repeat_interval_seconds=0.005):
        self._lock = threading.RLock()
        self._scroll_residue = {}
        self._last_mac_scroll_flags = None
        self.last_error = ""
        self._windows = None
        self.key_repeat_interval_seconds = max(0.0, float(key_repeat_interval_seconds))

    @property
    def available(self):
        return bool(_MAC_AVAILABLE or IS_WINDOWS)

    def is_resolve_running(self):
        """Return whether a DaVinci Resolve process/window is currently present."""
        if IS_MAC and _MAC_AVAILABLE and _NSWorkspace:
            try:
                if _NSRunningApplication:
                    direct_matches = _NSRunningApplication.runningApplicationsWithBundleIdentifier_(
                        "com.blackmagic-design.DaVinciResolve"
                    )
                    if direct_matches:
                        return True
                workspace = _NSWorkspace.sharedWorkspace()
                for app in workspace.runningApplications():
                    bundle_id = str(app.bundleIdentifier() or "").lower()
                    name = str(app.localizedName() or "").lower()
                    if (
                        "blackmagic-design.davinciresolve" in bundle_id
                        or "davinci resolve" in name
                    ):
                        return True
                return False
            except Exception as exc:
                self.last_error = f"running app check failed: {exc}"
                return False

        if IS_WINDOWS:
            try:
                from ctypes import wintypes

                user32 = self._windows_api()["user32"]
                found = [False]
                callback_type = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)

                @callback_type(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
                def visit_window(hwnd, _lparam):
                    if not user32.IsWindowVisible(hwnd):
                        return True
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length <= 0:
                        return True
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buffer, len(buffer))
                    if "davinci resolve" in buffer.value.lower():
                        found[0] = True
                        return False
                    return True

                user32.EnumWindows(visit_window, 0)
                return found[0]
            except Exception as exc:
                self.last_error = f"running window check failed: {exc}"
                return False

        return False

    def is_resolve_frontmost(self):
        if IS_MAC and _MAC_AVAILABLE and _NSWorkspace:
            try:
                session = CGSessionCopyCurrentDictionary() or {}
                if session.get("CGSSessionScreenIsLocked"):
                    self.last_error = "macOS screen is locked"
                    return False
                app = _NSWorkspace.sharedWorkspace().frontmostApplication()
                bundle_id = str(app.bundleIdentifier() or "").lower()
                name = str(app.localizedName() or "").lower()
                return "blackmagic-design.davinciresolve" in bundle_id or "davinci resolve" in name
            except Exception as exc:
                self.last_error = f"frontmost app check failed: {exc}"
                return False

        if IS_WINDOWS:
            try:
                windows = self._windows_api()
                hwnd = windows["user32"].GetForegroundWindow()
                if not hwnd:
                    return False
                length = windows["user32"].GetWindowTextLengthW(hwnd)
                buffer = ctypes.create_unicode_buffer(max(1, length + 1))
                windows["user32"].GetWindowTextW(hwnd, buffer, len(buffer))
                return "davinci resolve" in buffer.value.lower()
            except Exception as exc:
                self.last_error = f"foreground window check failed: {exc}"
                return False

        return False

    def scroll(self, mode, ticks, sensitivity=1.0):
        if not ticks or mode not in VIEW_SCROLL_MODIFIERS:
            return False
        with self._lock:
            if IS_MAC and _MAC_AVAILABLE:
                return self._mac_scroll(mode, ticks, sensitivity)
            if IS_WINDOWS:
                return self._windows_scroll(mode, ticks, sensitivity)
            self.last_error = "native input is unavailable on this platform"
            return False

    def _mac_can_post_events(self):
        if not IS_MAC or not _MAC_AVAILABLE:
            return False
        try:
            if not CGPreflightPostEventAccess():
                self.last_error = (
                    "macOS input permission is missing; allow Ulanzi Studio "
                    "in Privacy & Security > Accessibility"
                )
                return False
            return True
        except Exception as exc:
            self.last_error = f"macOS input permission check failed: {exc}"
            return False

    def move_frames(self, delta_frames):
        return self._repeat_direction_key(delta_frames, modifiers=())

    def move_seconds(self, delta_seconds):
        return self._repeat_direction_key(delta_seconds, modifiers=("shift",))

    def zoom_with_shortcut(self, ticks):
        if not ticks:
            return False
        modifiers = ("command",) if IS_MAC else ("control",)
        key = "equal" if ticks > 0 else "minus"
        return self._repeat_key(key, abs(int(ticks)), modifiers)

    def track_height_with_shortcut(self, ticks):
        if not ticks:
            return False
        # This is commonly configured by Resolve users; native Shift+wheel remains primary.
        modifiers = ("control", "option")
        key = "up" if ticks > 0 else "down"
        return self._repeat_key(key, abs(int(ticks)), modifiers)

    def release_all_modifiers(self):
        if not IS_WINDOWS:
            return
        try:
            for modifier in ("shift", "control", "option"):
                self._windows_key_event(WINDOWS_KEY_CODES[modifier], key_up=True)
        except Exception:
            pass

    def _repeat_direction_key(self, signed_count, modifiers):
        count = int(signed_count)
        if not count:
            return False
        return self._repeat_key("right" if count > 0 else "left", abs(count), modifiers)

    def _repeat_key(self, key, count, modifiers=()):
        count = min(256, max(0, int(count)))
        if not count:
            return False
        with self._lock:
            for index in range(count):
                if not self._key_press(key, modifiers):
                    return False
                if index + 1 < count and self.key_repeat_interval_seconds:
                    # Resolve drops synthetic key pairs that arrive in the same
                    # run-loop slice. A short consumer-side interval preserves
                    # exact frame/second counts without building an OS backlog.
                    time.sleep(self.key_repeat_interval_seconds)
        return True

    def _key_press(self, key, modifiers=()):
        if IS_MAC and _MAC_AVAILABLE:
            if not self._mac_can_post_events():
                return False
            try:
                return self._mac_key_press(key, modifiers)
            except Exception as exc:
                self.last_error = f"macOS keyboard input failed: {exc}"
                return False

        if IS_WINDOWS:
            pressed = []
            try:
                for modifier in modifiers:
                    vk = WINDOWS_KEY_CODES[modifier]
                    self._windows_key_event(vk, key_up=False)
                    pressed.append(vk)
                vk = WINDOWS_KEY_CODES[key]
                self._windows_key_event(vk, key_up=False)
                self._windows_key_event(vk, key_up=True)
                return True
            except Exception as exc:
                self.last_error = f"Windows keyboard input failed: {exc}"
                return False
            finally:
                for vk in reversed(pressed):
                    try:
                        self._windows_key_event(vk, key_up=True)
                    except Exception:
                        pass

        self.last_error = "keyboard input is unavailable on this platform"
        return False

    def _mac_post_key_event(self, key, is_down, flags):
        event = CGEventCreateKeyboardEvent(None, MAC_KEY_CODES[key], bool(is_down))
        # Zero must be written explicitly. Otherwise a plain frame-step event
        # can inherit Shift from the previous second-step shortcut in Resolve.
        CGEventSetFlags(event, int(flags))
        CGEventPost(kCGHIDEventTap, event)

    def _mac_key_press(self, key, modifiers=()):
        """Post one key press with real modifier down/up boundaries."""
        active_flags = 0
        pressed_modifiers = []
        key_is_down = False
        try:
            for modifier in modifiers:
                active_flags |= MAC_MODIFIER_FLAGS.get(modifier, 0)
                self._mac_post_key_event(modifier, True, active_flags)
                pressed_modifiers.append(modifier)

            self._mac_post_key_event(key, True, active_flags)
            key_is_down = True
            self._mac_post_key_event(key, False, active_flags)
            key_is_down = False
            return True
        finally:
            # Never leave a synthetic key or modifier held when Quartz posting
            # fails halfway through the sequence.
            if key_is_down:
                try:
                    self._mac_post_key_event(key, False, active_flags)
                except Exception:
                    pass
            for modifier in reversed(pressed_modifiers):
                active_flags &= ~MAC_MODIFIER_FLAGS.get(modifier, 0)
                try:
                    self._mac_post_key_event(modifier, False, active_flags)
                except Exception:
                    pass

    def _take_scroll_delta(self, mode, raw_delta):
        value = float(raw_delta) + self._scroll_residue.get(mode, 0.0)
        delta = int(value)
        self._scroll_residue[mode] = value - delta
        return delta

    def _mac_scroll(self, mode, ticks, sensitivity):
        if not self._mac_can_post_events():
            return False
        raw_delta = (
            int(ticks)
            * MAC_PIXELS_PER_TICK[mode]
            * float(sensitivity)
            * VIEW_SCROLL_SIGNS[mode]
        )
        delta = self._take_scroll_delta(mode, raw_delta)
        if not delta:
            return True
        try:
            flags = 0
            for modifier in VIEW_SCROLL_MODIFIERS[mode]:
                flags |= MAC_MODIFIER_FLAGS.get(modifier, 0)

            # Resolve caches the modifier state associated with the pointer.
            # A tagged Option-scroll followed by an unmodified scroll can
            # therefore continue zooming until the user physically moves the
            # mouse. Refresh the pointer state at its current location whenever
            # the synthetic wheel gesture changes modifiers. This adds one
            # event per mode transition, not per dial tick.
            if flags != self._last_mac_scroll_flags:
                self._mac_refresh_pointer_flags(flags)

            event = CGEventCreateScrollWheelEvent(
                None,
                kCGScrollEventUnitPixel,
                1,
                delta,
            )
            # Set zero explicitly as well. Leaving a newly-created event's
            # flags implicit is what allows Resolve's previous modifier state
            # to leak into vertical scrolling.
            CGEventSetFlags(event, flags)
            CGEventPost(kCGHIDEventTap, event)
            self._last_mac_scroll_flags = flags
            return True
        except Exception as exc:
            self.last_error = f"macOS wheel input failed: {exc}"
            return False

    def _mac_refresh_pointer_flags(self, flags):
        """Refresh Resolve's pointer modifier cache without moving the cursor."""
        reference = CGEventCreate(None)
        location = CGEventGetLocation(reference)
        event = CGEventCreateMouseEvent(
            None,
            kCGEventMouseMoved,
            location,
            kCGMouseButtonLeft,
        )
        CGEventSetFlags(event, int(flags))
        CGEventPost(kCGHIDEventTap, event)

    def _windows_scroll(self, mode, ticks, sensitivity):
        raw_delta = (
            int(ticks)
            * WINDOWS_WHEEL_DELTA_PER_TICK[mode]
            * float(sensitivity)
            * VIEW_SCROLL_SIGNS[mode]
        )
        delta = self._take_scroll_delta(mode, raw_delta)
        if not delta:
            return True

        modifiers = VIEW_SCROLL_MODIFIERS[mode]
        # Resolve maps Command-wheel on macOS to Control-wheel on Windows.
        modifiers = tuple("control" if item == "command" else item for item in modifiers)
        pressed = []
        try:
            for modifier in modifiers:
                vk = WINDOWS_KEY_CODES[modifier]
                self._windows_key_event(vk, key_up=False)
                pressed.append(vk)
            self._windows_mouse_wheel(delta)
            return True
        except Exception as exc:
            self.last_error = f"Windows wheel input failed: {exc}"
            return False
        finally:
            for vk in reversed(pressed):
                try:
                    self._windows_key_event(vk, key_up=True)
                except Exception:
                    pass

    def _windows_api(self):
        if self._windows is not None:
            return self._windows
        if not IS_WINDOWS or not hasattr(ctypes, "windll"):
            raise RuntimeError("Win32 input is unavailable")

        from ctypes import wintypes

        ulong_ptr = wintypes.WPARAM

        class MouseInput(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class KeyboardInput(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class HardwareInput(ctypes.Structure):
            _fields_ = [
                ("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            ]

        class InputUnion(ctypes.Union):
            _fields_ = [("mi", MouseInput), ("ki", KeyboardInput), ("hi", HardwareInput)]

        class Input(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("union", InputUnion)]

        user32 = ctypes.windll.user32
        user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int)
        user32.SendInput.restype = wintypes.UINT
        self._windows = {
            "user32": user32,
            "Input": Input,
            "InputUnion": InputUnion,
            "KeyboardInput": KeyboardInput,
            "MouseInput": MouseInput,
        }
        return self._windows

    def _windows_key_event(self, virtual_key, key_up=False):
        api = self._windows_api()
        # Navigation arrows are extended keys in Win32. Without this flag they
        # can be interpreted as numeric-keypad input depending on NumLock.
        flags = 0x0001 if int(virtual_key) in WINDOWS_EXTENDED_KEY_CODES else 0
        if key_up:
            flags |= 0x0002
        keyboard = api["KeyboardInput"](
            wVk=int(virtual_key),
            wScan=0,
            dwFlags=flags,
            time=0,
            dwExtraInfo=0,
        )
        event = api["Input"](type=1, union=api["InputUnion"](ki=keyboard))
        if api["user32"].SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) != 1:
            raise OSError("SendInput keyboard event failed")

    def _windows_mouse_wheel(self, delta):
        api = self._windows_api()
        mouse = api["MouseInput"](
            dx=0,
            dy=0,
            mouseData=int(delta) & 0xFFFFFFFF,
            dwFlags=0x0800,
            time=0,
            dwExtraInfo=0,
        )
        event = api["Input"](type=0, union=api["InputUnion"](mi=mouse))
        if api["user32"].SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) != 1:
            raise OSError("SendInput wheel event failed")


__all__ = [
    "NativeTimelineInput",
    "VIEW_SCROLL_MODIFIERS",
    "VIEW_SCROLL_SIGNS",
]
