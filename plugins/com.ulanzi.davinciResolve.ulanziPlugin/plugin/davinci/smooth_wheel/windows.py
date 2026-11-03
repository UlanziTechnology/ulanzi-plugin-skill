"""Win32 bindings for the shared smooth-wheel session.

All coordinates are physical desktop pixels. A listen-only low-level hook
confirms tagged SendInput events; API return values alone are not confirmations.
Importing this module never installs a hook or emits input.
"""

from __future__ import annotations

import ctypes
from contextlib import contextmanager
from dataclasses import dataclass
import math
import ntpath
import os
from threading import Event, Thread, current_thread
import time

from .macos import CapturedBitmap, MacOSBindings, PermissionState


LONG = ctypes.c_int32
DWORD = ctypes.c_uint32
WORD = ctypes.c_uint16
HANDLE = ctypes.c_void_p
ULONG_PTR = ctypes.c_size_t
LRESULT = ctypes.c_ssize_t
HOOKPROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    LRESULT, ctypes.c_int, ULONG_PTR, ctypes.c_ssize_t
)


class POINT(ctypes.Structure):
    _fields_ = [("x", LONG), ("y", LONG)]


class RECT(ctypes.Structure):
    _fields_ = [("left", LONG), ("top", LONG), ("right", LONG), ("bottom", LONG)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", DWORD), ("flags", DWORD),
                ("hwndActive", HANDLE), ("hwndFocus", HANDLE), ("hwndCapture", HANDLE),
                ("hwndMenuOwner", HANDLE), ("hwndMoveSize", HANDLE), ("hwndCaret", HANDLE),
                ("rcCaret", RECT)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", DWORD)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", LONG), ("dy", LONG), ("mouseData", DWORD),
                ("dwFlags", DWORD), ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", WORD), ("wScan", WORD), ("dwFlags", DWORD),
                ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", DWORD), ("wParamL", WORD), ("wParamH", WORD)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", DWORD), ("data", INPUTUNION)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", POINT), ("mouseData", DWORD), ("flags", DWORD),
                ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", HANDLE), ("message", DWORD), ("wParam", ULONG_PTR),
                ("lParam", ctypes.c_ssize_t), ("time", DWORD), ("pt", POINT),
                ("lPrivate", DWORD)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", DWORD), ("biWidth", LONG), ("biHeight", LONG),
                ("biPlanes", WORD), ("biBitCount", WORD), ("biCompression", DWORD),
                ("biSizeImage", DWORD), ("biXPelsPerMeter", LONG),
                ("biYPelsPerMeter", LONG), ("biClrUsed", DWORD), ("biClrImportant", DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", DWORD * 1)]


@dataclass(frozen=True)
class WindowsAppIdentity:
    pid: int | None
    executable_path: str
    bundle_id: str = ""

    @property
    def is_davinci(self):
        return bool(self.pid and ntpath.basename(self.executable_path).lower() == "resolve.exe")


@dataclass(frozen=True)
class WindowsMouseSource:
    tag: int
    target_pid: int


def wait_for_windows_frame(timeout):
    """Use bundled Python's high-resolution sleep for the output cadence.

    Event.wait rounds ~8 ms waits to ~15.6 ms on the measured Windows host.
    Sleep releases the GIL and avoids that coarse wait without busy polling or
    a system-wide timer-resolution change. Cap each sleep at one 120 Hz frame;
    GestureRunner checks its stop event again before any subsequent output,
    while emergency button release remains independent of this waiter.
    """
    if timeout > 0:
        time.sleep(min(timeout, 1.0 / 120.0))


def absolute_coordinate(value, origin, extent):
    """Address the centre of a physical pixel in SendInput's 16-bit space."""
    if not all(math.isfinite(v) for v in (value, origin, extent)) or extent <= 0:
        raise ValueError("invalid virtual desktop geometry")
    pixel = int(round(value)) - int(origin)
    if not 0 <= pixel < extent:
        raise ValueError("mouse point is outside the virtual desktop")
    return min(65535, max(0, int((pixel + 0.5) * 65536 / extent)))


class WindowsMouseHook:
    """A private message-loop thread; callbacks always pass input through."""

    def __init__(self, bindings, callback):
        self._bindings = bindings
        self._callback = callback
        self._ready = Event()
        self._stop = Event()
        self._thread_id = None
        self._hook = None
        self._left_down = False
        self._last_position = None
        self.error = ""
        self._thread = Thread(target=self._run, name="wheel-win32-mouse-hook", daemon=True)

    @property
    def alive(self):
        return bool(self._hook and self._thread.is_alive() and not self._stop.is_set() and not self.error)

    def start(self):
        self._thread.start()
        if not self._ready.wait(2.0) or not self.alive:
            self.stop()
            raise RuntimeError(self.error or "Windows mouse hook did not start")
        return self

    def _dispatch(self, message, data):
        # Reuse the shared interlock's event vocabulary (originally CG types).
        types = {0x201: MacOSBindings.LEFT_DOWN, 0x202: MacOSBindings.LEFT_UP,
                 0x204: MacOSBindings.RIGHT_DOWN, 0x205: MacOSBindings.RIGHT_UP,
                 0x207: MacOSBindings.OTHER_DOWN, 0x208: MacOSBindings.OTHER_UP,
                 0x20B: MacOSBindings.OTHER_DOWN, 0x20C: MacOSBindings.OTHER_UP,
                 0x20A: MacOSBindings.SCROLL_WHEEL, 0x20E: MacOSBindings.SCROLL_WHEEL}
        if message == 0x201:
            self._left_down = True
        elif message == 0x202:
            self._left_down = False
        event_type = types.get(message)
        if message == 0x200:
            event_type = MacOSBindings.LEFT_DRAGGED if self._left_down else MacOSBindings.MOUSE_MOVED
        if event_type is None:
            return
        position = (int(data.pt.x), int(data.pt.y))
        previous = self._last_position
        self._last_position = position
        metadata = {"injected": bool(data.flags & 1), "nativeTime": int(data.time),
                    "nativeFlags": int(data.flags), "nativeMessage": int(message),
                    "deltaSource": "consecutive_hook_positions"}
        if previous is not None:
            metadata.update(deltaX=position[0] - previous[0], deltaY=position[1] - previous[1])
        self._callback(event_type, int(data.dwExtraInfo), position, time.monotonic(), metadata)

    def _run(self):
        u = self._bindings.user32
        k = self._bindings.kernel32
        self._thread_id = k.GetCurrentThreadId()
        # Create the queue before making the thread visible to stop().
        msg = MSG()
        u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)

        @HOOKPROC
        def hook_proc(code, message, pointer):
            try:
                if code >= 0 and not self._stop.is_set():
                    data = ctypes.cast(pointer, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                    self._dispatch(message, data)
            except Exception as exc:
                self.error = "mouse_hook_callback_failed: %s" % exc
            return u.CallNextHookEx(None, code, message, pointer)

        self._proc = hook_proc  # Keep the native callback alive until unhooked.
        try:
            with self._bindings.physical_coordinates():
                self._left_down = self._bindings.left_button_down()
                self._last_position = self._bindings.current_mouse_position()
                self._hook = u.SetWindowsHookExW(14, hook_proc, k.GetModuleHandleW(None), 0)
                if not self._hook:
                    raise ctypes.WinError(ctypes.get_last_error())
                self._ready.set()
                while not self._stop.is_set():
                    result = u.GetMessageW(ctypes.byref(msg), None, 0, 0)
                    if result == 0:
                        break
                    if result == -1:
                        raise ctypes.WinError(ctypes.get_last_error())
                    u.TranslateMessage(ctypes.byref(msg))
                    u.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self.error = str(exc)
        finally:
            if self._hook:
                u.UnhookWindowsHookEx(self._hook)
                self._hook = None
            self._ready.set()

    def stop(self):
        self._stop.set()
        if self._thread_id:
            self._bindings.user32.PostThreadMessageW(self._thread_id, 0x12, 0, 0)
        if self._thread.is_alive() and current_thread() is not self._thread:
            self._thread.join(timeout=1.0)


class WindowsBindings:
    """Small native boundary, replaceable by a fake for replay tests."""

    platform_name = "Windows"

    def __init__(self):
        self.available = False
        self.unavailable_reason = "Win32 APIs unavailable"
        if os.name != "nt":
            return
        try:
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
            self._bind_apis()
            self.available = True
            self.unavailable_reason = ""
        except Exception as exc:
            self.unavailable_reason = str(exc)

    def _bind_apis(self):
        u, k, g = self.user32, self.kernel32, self.gdi32
        signatures = [
            (u.GetCursorPos, [ctypes.POINTER(POINT)], ctypes.c_int),
            (u.SetCursorPos, [ctypes.c_int, ctypes.c_int], ctypes.c_int),
            (u.GetAsyncKeyState, [ctypes.c_int], ctypes.c_short),
            (u.GetDoubleClickTime, [], DWORD),
            (u.GetForegroundWindow, [], HANDLE),
            (u.GetWindowThreadProcessId, [HANDLE, ctypes.POINTER(DWORD)], DWORD),
            (u.GetGUIThreadInfo, [DWORD, ctypes.POINTER(GUITHREADINFO)], ctypes.c_int),
            (u.GetSystemMetrics, [ctypes.c_int], ctypes.c_int),
            (u.MonitorFromPoint, [POINT, DWORD], HANDLE),
            (u.GetMonitorInfoW, [HANDLE, ctypes.POINTER(MONITORINFO)], ctypes.c_int),
            (u.SendInput, [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int], ctypes.c_uint),
            (u.SetWindowsHookExW, [ctypes.c_int, HOOKPROC, HANDLE, DWORD], HANDLE),
            (u.UnhookWindowsHookEx, [HANDLE], ctypes.c_int),
            (u.CallNextHookEx, [HANDLE, ctypes.c_int, ULONG_PTR, ctypes.c_ssize_t], LRESULT),
            (u.PeekMessageW, [ctypes.POINTER(MSG), HANDLE, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint], ctypes.c_int),
            (u.GetMessageW, [ctypes.POINTER(MSG), HANDLE, ctypes.c_uint, ctypes.c_uint], ctypes.c_int),
            (u.TranslateMessage, [ctypes.POINTER(MSG)], ctypes.c_int),
            (u.DispatchMessageW, [ctypes.POINTER(MSG)], LRESULT),
            (u.PostThreadMessageW, [DWORD, ctypes.c_uint, ULONG_PTR, ctypes.c_ssize_t], ctypes.c_int),
            (k.GetCurrentThreadId, [], DWORD),
            (k.GetModuleHandleW, [ctypes.c_wchar_p], HANDLE),
            (k.OpenProcess, [DWORD, ctypes.c_int, DWORD], HANDLE),
            (k.CloseHandle, [HANDLE], ctypes.c_int),
            (k.QueryFullProcessImageNameW, [HANDLE, DWORD, ctypes.c_wchar_p, ctypes.POINTER(DWORD)], ctypes.c_int),
            (u.GetDC, [HANDLE], HANDLE), (u.ReleaseDC, [HANDLE, HANDLE], ctypes.c_int),
            (g.CreateCompatibleDC, [HANDLE], HANDLE),
            (g.CreateCompatibleBitmap, [HANDLE, ctypes.c_int, ctypes.c_int], HANDLE),
            (g.SelectObject, [HANDLE, HANDLE], HANDLE),
            (g.DeleteObject, [HANDLE], ctypes.c_int), (g.DeleteDC, [HANDLE], ctypes.c_int),
            (g.BitBlt, [HANDLE, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                        HANDLE, ctypes.c_int, ctypes.c_int, DWORD], ctypes.c_int),
            (g.GetDIBits, [HANDLE, HANDLE, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
                          ctypes.POINTER(BITMAPINFO), ctypes.c_uint], ctypes.c_int),
        ]
        for function, args, result in signatures:
            function.argtypes, function.restype = args, result
        self._set_dpi = getattr(u, "SetThreadDpiAwarenessContext", None)
        if self._set_dpi is not None:
            self._set_dpi.argtypes, self._set_dpi.restype = [HANDLE], HANDLE

    @contextmanager
    def physical_coordinates(self):
        previous = self._set_dpi(ctypes.c_void_p(-4)) if self._set_dpi else None
        try:
            yield
        finally:
            if previous:
                self._set_dpi(previous)

    def permissions(self):
        # Windows has no TCC prompts. Hook creation and each SendInput still
        # must succeed; elevated targets can reject input through UIPI.
        return PermissionState(self.available, self.available, self.available)

    def frontmost_app(self):
        pid = DWORD()
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd or not self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
            return WindowsAppIdentity(None, "")
        handle = self.kernel32.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return WindowsAppIdentity(pid.value, "")
        try:
            length = DWORD(32768)
            path = ctypes.create_unicode_buffer(length.value)
            if not self.kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length)):
                return WindowsAppIdentity(pid.value, "")
            return WindowsAppIdentity(pid.value, path.value)
        finally:
            self.kernel32.CloseHandle(handle)

    def current_mouse_position(self):
        point = POINT()
        with self.physical_coordinates():
            if not self.user32.GetCursorPos(ctypes.byref(point)):
                raise ctypes.WinError(ctypes.get_last_error())
        return point.x, point.y

    def warp_mouse_cursor(self, position):
        if not all(math.isfinite(v) for v in position):
            raise ValueError("non-finite mouse point")
        with self.physical_coordinates():
            if not self.user32.SetCursorPos(int(round(position[0])), int(round(position[1]))):
                raise ctypes.WinError(ctypes.get_last_error())

    def left_button_down(self):
        return bool(self.user32.GetAsyncKeyState(1) & 0x8000)

    def capture_diagnostics(self, target_pid=None):
        """Optional telemetry uses the same native reads as the transport gate."""
        return self.mouse_capture_state(target_pid)

    def mouse_capture_state(self, target_pid=None):
        """Read-only GUI capture sample; errors remain explicit to the caller.

        Query the foreground thread and, after focus changes, the last observed
        foreground window belonging to target_pid. No window enumeration or
        cross-thread messages are needed. A missing target is reported rather
        than silently querying thread 0 (which would mean the foreground).
        These sequential reads are not atomic and do not prove that Resolve has
        processed a DRAG. GetAsyncKeyState's high bit is the button state; a zero
        return may also mean inaccessible desktop/UIPI, and its low bit is not
        reliable evidence of a click.
        """
        started = time.monotonic()
        result = {"sampledAt": started, "foreground": None, "target": None,
                  "asyncLeftDown": None, "asyncLeftState": None, "errors": []}

        def failure(operation, exc=None):
            error = {"operation": operation}
            if exc is not None:
                error["error"] = str(exc)
            else:
                error["winError"] = int(ctypes.get_last_error())
            result["errors"].append(error)

        try:
            u = self.user32
            windows, threads = {}, {}

            def window_identity(hwnd):
                hwnd = int(hwnd or 0)
                if hwnd in windows:
                    return windows[hwnd]
                entry = {"hwnd": hwnd, "threadId": None, "pid": None}
                windows[hwnd] = entry
                if not hwnd:
                    return entry
                try:
                    pid = DWORD()
                    tid = int(u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)))
                    if tid:
                        entry.update(threadId=tid, pid=int(pid.value))
                    else:
                        failure("GetWindowThreadProcessId:%s" % hwnd)
                except Exception as exc:
                    failure("GetWindowThreadProcessId:%s" % hwnd, exc)
                return entry

            def gui_state(tid):
                if tid in threads:
                    return threads[tid]
                entry = {"ok": False, "threadId": tid}
                threads[tid] = entry
                try:
                    info = GUITHREADINFO()
                    info.cbSize = ctypes.sizeof(info)
                    if not u.GetGUIThreadInfo(tid, ctypes.byref(info)):
                        failure("GetGUIThreadInfo:%s" % tid)
                        return entry
                    entry.update(ok=True, flags=int(info.flags))
                    for name in ("hwndActive", "hwndFocus", "hwndCapture",
                                 "hwndMenuOwner", "hwndMoveSize", "hwndCaret"):
                        entry[name] = int(getattr(info, name) or 0)
                    capture = window_identity(entry["hwndCapture"])
                    entry.update(captureThreadId=capture["threadId"], capturePid=capture["pid"])
                except Exception as exc:
                    failure("GetGUIThreadInfo:%s" % tid, exc)
                return entry

            try:
                state = int(u.GetAsyncKeyState(1))
                result.update(asyncLeftState=state, asyncLeftDown=bool(state & 0x8000),
                              asyncLeftStateZeroAmbiguous=(state == 0))
            except Exception as exc:
                failure("GetAsyncKeyState", exc)

            try:
                foreground = dict(window_identity(u.GetForegroundWindow()))
                result["foreground"] = foreground
                if foreground["threadId"]:
                    foreground["gui"] = gui_state(foreground["threadId"])
                elif not foreground["hwnd"]:
                    failure("GetForegroundWindow", RuntimeError("no_foreground_window"))
            except Exception as exc:
                failure("GetForegroundWindow", exc)

            if target_pid is not None:
                target_pid = int(target_pid)
                result["targetPid"] = target_pid
                foreground = result["foreground"]
                cached = getattr(self, "_capture_diagnostic_target", None)
                if foreground and foreground["pid"] == target_pid:
                    self._capture_diagnostic_target = (target_pid, foreground["hwnd"])
                    result["target"] = dict(foreground, source="foreground")
                elif cached and cached[0] == target_pid:
                    target = dict(window_identity(cached[1]), source="cached_foreground")
                    result["target"] = target
                    if target["threadId"] and target["pid"] == target_pid:
                        target["gui"] = gui_state(target["threadId"])
                    else:
                        failure("target", RuntimeError("cached_target_window_unavailable_or_reused"))
                else:
                    failure("target", RuntimeError("target_window_not_observed"))
        except Exception as exc:
            failure("capture_diagnostics", exc)
        result["ok"] = not result["errors"]
        result["elapsedMs"] = (time.monotonic() - started) * 1000.0
        return result

    def double_click_interval(self):
        return self.user32.GetDoubleClickTime() / 1000.0

    def double_click_size(self):
        with self.physical_coordinates():
            return tuple(max(1, self.user32.GetSystemMetrics(i)) for i in (36, 37))

    def display_bounds_for_point(self, position):
        with self.physical_coordinates():
            monitor = self.user32.MonitorFromPoint(POINT(*map(lambda v: int(round(v)), position)), 0)
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(info)
            if not monitor or not self.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                raise RuntimeError("mouse point has no active monitor")
        r = info.rcMonitor
        return r.left, r.top, r.right - r.left, r.bottom - r.top

    def virtual_bounds(self):
        with self.physical_coordinates():
            return tuple(self.user32.GetSystemMetrics(i) for i in (76, 77, 78, 79))

    def start_event_tap(self, callback):
        return WindowsMouseHook(self, callback).start()

    def create_mouse_source(self, tag):
        app = self.frontmost_app()
        if not app.is_davinci:
            raise RuntimeError("DaVinci is no longer frontmost")
        return WindowsMouseSource(int(tag), app.pid)

    def release_mouse_source(self, source):
        pass  # SendInput has no native event-source handle.

    def post_left_mouse(self, source, kind, position, tag):
        if kind not in ("down", "drag", "up", "move"):
            raise ValueError("invalid mouse event kind")
        flags = {"down": 0x0002, "drag": 0, "up": 0x0004, "move": 0}[kind]
        dx = dy = 0
        # An emergency UP must never warp back after the user takes over.
        if kind != "up":
            pid = DWORD()
            hwnd = self.user32.GetForegroundWindow()
            if (not hwnd or not self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    or pid.value != source.target_pid):
                raise RuntimeError("DaVinci foreground process changed before mouse output")
            left, top, width, height = self.virtual_bounds()
            dx = absolute_coordinate(position[0], left, width)
            dy = absolute_coordinate(position[1], top, height)
            flags |= 0x0001 | 0x8000 | 0x4000 | 0x2000  # MOVE, ABSOLUTE, VIRTUALDESK, NOCOALESCE
        entry = INPUT()
        entry.type = 0
        entry.data.mi = MOUSEINPUT(dx, dy, 0, flags, 0, int(tag))
        if self.user32.SendInput(1, ctypes.byref(entry), ctypes.sizeof(INPUT)) != 1:
            raise RuntimeError("SendInput rejected %s (error=%s)" % (kind, ctypes.get_last_error()))

    def post_left_mouse_stationary_down(self, source, position, tag):
        """Press at an already positioned cursor without another MOVE.

        A host restoration can separate MOVE and DOWN from one compound input.
        Positioning and settling therefore happen before this call; validate
        the native cursor and foreground again immediately before pressing.
        """
        if not all(math.isfinite(v) for v in position):
            raise ValueError("non-finite stationary DOWN point")
        target = tuple(int(round(v)) for v in position)
        current = self.current_mouse_position()
        if (not all(math.isfinite(v) for v in current) or
                math.hypot(current[0] - target[0], current[1] - target[1]) > 1.5):
            raise RuntimeError("stationary DOWN cursor origin changed")
        pid = DWORD()
        hwnd = self.user32.GetForegroundWindow()
        if (not hwnd or not self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                or pid.value != source.target_pid):
            raise RuntimeError("DaVinci foreground process changed before mouse output")
        entry = INPUT()
        entry.type = 0
        entry.data.mi = MOUSEINPUT(0, 0, 0, 0x0002, 0, int(tag))
        if self.user32.SendInput(1, ctypes.byref(entry), ctypes.sizeof(INPUT)) != 1:
            raise RuntimeError("SendInput rejected stationary down (error=%s)" % ctypes.get_last_error())

    def screen_capture_supported(self):
        return self.available

    screen_capture_allowed = screen_capture_supported

    def capture_screen_region(self, x, y, width, height):
        values = (x, y, width, height)
        if not all(math.isfinite(v) for v in values) or width <= 0 or height <= 0:
            raise ValueError("invalid capture region")
        right, bottom = math.ceil(x + width), math.ceil(y + height)
        x, y = math.floor(x), math.floor(y)
        width, height = right - x, bottom - y
        if width > 2048 or height > 2048:
            raise ValueError("capture region exceeds wheel observation limit")
        with self.physical_coordinates():
            u, g = self.user32, self.gdi32
            screen = u.GetDC(None)
            memory = bitmap = previous = None
            try:
                if not screen:
                    raise RuntimeError("GetDC failed")
                memory = g.CreateCompatibleDC(screen)
                bitmap = g.CreateCompatibleBitmap(screen, width, height)
                if not memory or not bitmap:
                    raise RuntimeError("could not allocate wheel capture")
                previous = g.SelectObject(memory, bitmap)
                if not previous or previous == ctypes.c_void_p(-1).value:
                    raise RuntimeError("SelectObject failed")
                if not g.BitBlt(memory, 0, 0, width, height, screen, x, y, 0x40CC0020):
                    raise RuntimeError("BitBlt failed")
                # GetDIBits requires the bitmap to be deselected from its DC.
                g.SelectObject(memory, previous)
                previous = None
                info = BITMAPINFO()
                info.bmiHeader = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width,
                                                -height, 1, 32, 0, 0, 0, 0, 0, 0)
                data = (ctypes.c_ubyte * (width * height * 4))()
                if g.GetDIBits(memory, bitmap, 0, height, data, ctypes.byref(info), 0) != height:
                    raise RuntimeError("GetDIBits returned an incomplete wheel capture")
                return CapturedBitmap(bytes(data), width, height, width * 4,
                                      (x, y, width, height), 1.0, 1.0, (2, 1, 0))
            finally:
                if previous and previous != ctypes.c_void_p(-1).value:
                    g.SelectObject(memory, previous)
                if bitmap:
                    g.DeleteObject(bitmap)
                if memory:
                    g.DeleteDC(memory)
                if screen:
                    u.ReleaseDC(None, screen)
