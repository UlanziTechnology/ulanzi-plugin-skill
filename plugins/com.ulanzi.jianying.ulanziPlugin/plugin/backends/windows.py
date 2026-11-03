"""Windows automation backend prepared for Jianying Pro package testing."""

import ctypes
from ctypes import wintypes
from copy import deepcopy
from contextlib import ExitStack
import json
import os
from queue import Empty, Queue
import subprocess
from threading import RLock, Thread, Timer
import time

from basic_hover import BasicHoverService
from color_wheel import (
    DEFAULT_RESPONSE_GAIN,
    centered_wheel_state,
    normalize_wheel_mode,
)
from .base import AdjustmentResult, AutomationBackend, CoalescingAdjustmentQueue
from .windows_wheel_queue import WindowsWheelAdjustmentQueue


class WheelServerClient:
    """Serialized NDJSON client for the Windows continuous-wheel helper."""

    _END = object()
    _WHEEL_DIAGNOSTIC_EVENTS = frozenset({
        "wheel-press", "wheel-release", "wheel-repress-wait",
        "wheel-boundary-plan", "wheel-boundary-move", "wheel-boundary-progress",
        "wheel-async-feedback", "wheel-axis-rebased", "wheel-motion-failure", "wheel-cursor-trace",
        "wheel-fixed-input-stop",
    })
    _SLIDER_TAKEOVER_FAILURES = frozenset({
        "external_mouse_move", "external_mouse_left_down", "external_mouse_left_up",
    })

    def __init__(self, helper_path, emergency_release=None, event_listener=None):
        self.helper_path = helper_path
        self.emergency_release = emergency_release
        self.event_listener = event_listener
        self._lock = RLock()
        self._state_lock = RLock()
        self._write_lock = RLock()
        self._wheel_input_generation = 0
        self._fixed_input_snapshot = None
        self._process = None
        self._output = None
        self._reader = None
        self._request_id = 0
        self._server_generation = 0
        self._process_generation = 0
        self._session_active = False
        self._session_token = 0
        self._session_generation = 0
        self._last_released_token = 0
        self._last_completed_token = 0
        self._slider_cancel_generation = 0
        self._slider_cancel_reason = ""

    @staticmethod
    def _creationflags():
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def _consume_wheel_diagnostic(self, event, generation):
        if (
            not isinstance(event, dict)
            or not isinstance(event.get("event"), str)
            or event["event"] not in self._WHEEL_DIAGNOSTIC_EVENTS
        ):
            return False
        if self._is_current_generation(generation):
            try:
                print(
                    "windows wheel diag: "
                    + json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                )
            except (OSError, UnicodeError, ValueError):
                # Observability must not turn a press diagnostic into a failed
                # request or stop the output reader while input is held.
                pass
        return True

    def _start_locked(self):
        if self._process is not None and self._process.poll() is None:
            return True
        self._stop_locked(force=True)
        if not os.path.isfile(self.helper_path):
            return False
        try:
            process = subprocess.Popen(
                [self.helper_path, "wheel-server"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=self._creationflags(),
            )
        except OSError:
            return False
        output = Queue()
        self._server_generation += 1
        generation = self._server_generation
        self._process = process
        self._process_generation = generation
        self._output = output

        def read_stdout():
            try:
                for line in iter(process.stdout.readline, ""):
                    try:
                        decoded = json.loads(str(line or "").strip())
                    except (TypeError, json.JSONDecodeError):
                        decoded = None
                    if self._consume_wheel_diagnostic(decoded, generation):
                        continue
                    if (
                        isinstance(decoded, dict)
                        and decoded.get("event") == "slider-session-trace"
                    ):
                        if self._is_current_generation(generation):
                            print(
                                "windows slider session: "
                                + json.dumps(decoded, ensure_ascii=False, separators=(",", ":"))
                            )
                        continue
                    if (
                        isinstance(decoded, dict)
                        and decoded.get("event") in {
                            "wheel-session-ended",
                            "slider-session-ended",
                        }
                        and self._is_current_generation(generation)
                    ):
                        decoded = dict(decoded)
                        self.mark_idle_released(
                            decoded.get("sessionToken"),
                            generation=generation,
                            slider_reason=(
                                str(decoded.get("reason") or "idle")
                                if decoded.get("event") == "slider-session-ended"
                                else None
                            ),
                        )
                        if callable(self.event_listener):
                            try:
                                self.event_listener(decoded)
                            except Exception as exc:
                                print(
                                    "windows wheel session event ignored: "
                                    f"reason={exc}"
                                )
                        continue
                    output.put(line)
            finally:
                # A stopped helper's reader may finish after a replacement
                # helper has already started. Only release input owned by this
                # reader's process generation; otherwise an old EOF could
                # mouse-up a brand-new drag.
                self._emergency_release_if_needed(generation)
                output.put(self._END)

        reader = Thread(
            target=read_stdout,
            name="jianying-wheel-server-output",
            daemon=True,
        )
        self._reader = reader
        reader.start()
        print(f"windows wheel server: started pid={process.pid}")
        app_data = os.environ.get("APPDATA")
        if app_data:
            trace_path = os.path.join(
                app_data, "Ulanzi", "UlanziDeck", "logs",
                "com.ulanzi.ulanzistudio.jianying", f"wheel-cursor-trace-{process.pid}.jsonl",
            )
            print(f"windows wheel cursor trace: file={trace_path} durationMs=400 intervalMs=8")
        return True

    def invalidate_wheel_input(self, generation):
        # This channel never waits for the in-flight request. Native reads it
        # independently while a press guard or frame is being executed.
        with self._write_lock:
            self._wheel_input_generation = generation
            process = self._process
            if process is not None and process.poll() is None:
                try:
                    process.stdin.write(json.dumps({
                        "command": "wheel-generation", "generation": generation,
                    }) + "\n")
                    process.stdin.flush()
                except (OSError, ValueError):
                    pass  # The owning request performs emergency teardown.

    def _write_fixed_input_locked(self, process):
        snapshot = self._fixed_input_snapshot
        if snapshot is None:
            return
        generation, last_input = snapshot
        process.stdin.write(json.dumps({
            "command": "wheel-fixed-input", "generation": generation,
            "active": last_input is not None,
            "inputTimestampMs": last_input * 1000.0 if last_input is not None else 0.0,
            "inputAgeMs": max(0.0, (time.monotonic() - last_input) * 1000.0)
            if last_input is not None else 0.0,
        }) + "\n")

    def update_fixed_input(self, generation, last_input):
        # Bypass the request/response lock so an in-flight reanchor sees actual
        # knob arrivals. Queue dispatch and helper restarts never renew the age.
        with self._write_lock:
            snapshot = self._fixed_input_snapshot
            if snapshot is not None and generation < snapshot[0]:
                return
            if (snapshot is not None and generation == snapshot[0]
                    and last_input is not None and snapshot[1] is not None
                    and last_input < snapshot[1]):
                return
            self._fixed_input_snapshot = (generation, last_input)
            process = self._process
            if process is not None and process.poll() is None:
                try:
                    self._write_fixed_input_locked(process)
                    process.stdin.flush()
                except (OSError, ValueError):
                    pass  # The owning request handles a failed helper.

    def request(self, payload, event_handler=None, timeout=3.0, command="wheel", request_guard=None):
        with self._lock:
            if request_guard is not None and not request_guard():
                return {"performed": False, "reason": "wheel_input_cancelled"}
            if not self._start_locked():
                return {"performed": False, "reason": "native_helper_unavailable"}
            if request_guard is not None and not request_guard():
                return {"performed": False, "reason": "wheel_input_cancelled"}
            with self._state_lock:
                slider_generation = self._slider_cancel_generation
                if (
                    command == "adjust"
                    and (payload or {}).get("_sliderCancelGeneration", slider_generation)
                    != slider_generation
                ):
                    return self._slider_cancelled_response()
            self._request_id += 1
            request_id = self._request_id
            request = deepcopy(payload or {})
            request["command"] = str(command or "wheel")
            request["requestId"] = request_id
            # Native may press the mouse before its first final response. Mark
            # this request as potentially holding input before writing it so a
            # timeout, EOF or crash always has an emergency mouse-up path.
            generation = self._process_generation
            with self._state_lock:
                # Recheck after acquiring the request lock: a queued task may
                # have been taken from the deque before manual takeover.
                if command == "adjust" and slider_generation != self._slider_cancel_generation:
                    return self._slider_cancelled_response()
                if request.get("wheelFrame") and request.get("wheelGeneration") != self._wheel_input_generation:
                    return {"performed": False, "reason": "wheel_input_cancelled"}
            try:
                # Acquire state before write, matching idle callbacks, but let
                # the reader process releases during pipe writes. ExitStack
                # keeps write ownership after the brief state claim, including
                # on guard returns or exceptions. Fixed guards are lock-free.
                with ExitStack() as send_locks:
                    with self._state_lock:
                        send_locks.enter_context(self._write_lock)
                        if request_guard is not None and not request_guard():
                            return {"performed": False, "reason": "wheel_input_cancelled"}
                        if request.get("wheelFixed") and self._fixed_input_snapshot is not None:
                            fixed_generation, last_input = self._fixed_input_snapshot
                            if (fixed_generation != request.get("fixedWheelGeneration")
                                    or last_input is None):
                                return {"performed": False, "reason": "wheel_input_cancelled"}
                        self._set_session_state(True, request_id, generation)
                    if request.get("wheelFixed"):
                        self._write_fixed_input_locked(self._process)
                    if request.get("wheelFrame"):
                        self._process.stdin.write(json.dumps({
                            "command": "wheel-generation",
                            "generation": self._wheel_input_generation,
                        }) + "\n")
                    self._process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                    self._process.stdin.flush()
            except (OSError, ValueError) as exc:
                self._stop_locked(force=True)
                return {
                    "performed": False,
                    "reason": f"windows_wheel_server_failed:{exc}",
                }
            deadline = time.monotonic() + max(0.1, float(timeout))
            detail = []
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._stop_locked(force=True)
                    return {"performed": False, "reason": "windows_wheel_server_timeout"}
                try:
                    line = self._output.get(timeout=remaining)
                except Empty:
                    self._stop_locked(force=True)
                    return {"performed": False, "reason": "windows_wheel_server_timeout"}
                if line is self._END:
                    self._stop_locked(force=True)
                    return {
                        "performed": False,
                        "reason": "windows_wheel_server_stopped",
                        "detail": " ".join(detail)[-180:],
                    }
                stripped = str(line or "").strip()
                if not stripped:
                    continue
                try:
                    decoded = json.loads(stripped)
                except (TypeError, json.JSONDecodeError):
                    detail.append(stripped)
                    continue
                if not isinstance(decoded, dict):
                    continue
                # The reader normally consumes these events. Keep a guard at
                # the response boundary as well: diagnostics carry requestId,
                # but never acknowledge a command or change session state.
                if self._consume_wheel_diagnostic(decoded, generation):
                    continue
                if decoded.get("event") == "wheel-preview":
                    if decoded.get("requestId") == request_id and callable(event_handler):
                        try:
                            event_handler(decoded)
                        except Exception as exc:
                            print(f"windows wheel server event ignored: reason={exc}")
                    continue
                if decoded.get("requestId") != request_id:
                    continue
                with self._state_lock:
                    if command == "adjust":
                        if (
                            decoded.get("failureDetail") in self._SLIDER_TAKEOVER_FAILURES
                            and slider_generation == self._slider_cancel_generation
                        ):
                            self._slider_cancel_generation += 1
                            self._slider_cancel_reason = "safety:" + decoded["failureDetail"]
                        if slider_generation != self._slider_cancel_generation:
                            # Keep actual appliedTicks, but stop the remaining
                            # Python chunks even if a success response was
                            # already buffered when the release event arrived.
                            decoded = dict(decoded)
                            decoded["sessionActive"] = False
                            decoded["sliderBatchCancelled"] = True
                            if decoded.get("performed"):
                                decoded.update(self._slider_cancelled_response())
                    active = bool(decoded.get("sessionActive"))
                    state_accepted = self._set_session_state(
                        active,
                        request_id if active else 0,
                        generation,
                    )
                if active and not state_accepted:
                    # The native idle event can overtake a delayed final
                    # response.  Do not resurrect a drag token that has already
                    # ended and been reacquired on the reader thread.
                    decoded = dict(decoded)
                    decoded["sessionActive"] = False
                    decoded["sessionEndedBeforeResponse"] = True
                return decoded

    def cancel(self):
        with self._lock:
            process = self._process
            generation = self._process_generation
            if process is None or process.poll() is not None:
                # A crashed process may have pressed the button before its
                # response. Preserve the potential-down evidence until the
                # unified emergency teardown has released it.
                self._stop_locked(force=True)
                return
            self._request_id += 1
            request_id = self._request_id
            try:
                with self._write_lock:
                    self._process.stdin.write(json.dumps({
                        "command": "cancel", "requestId": request_id,
                    }) + "\n")
                    self._process.stdin.flush()
                deadline = time.monotonic() + 0.8
                while time.monotonic() < deadline:
                    try:
                        line = self._output.get(timeout=deadline - time.monotonic())
                    except Empty:
                        break
                    if line is self._END:
                        break
                    try:
                        decoded = json.loads(str(line or "").strip())
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if self._consume_wheel_diagnostic(decoded, generation):
                        continue
                    if isinstance(decoded, dict) and decoded.get("requestId") == request_id:
                        self._set_session_state(False, generation=generation)
                        return
            except (OSError, ValueError):
                pass
            self._stop_locked(force=True)

    def session_token(self):
        with self._state_lock:
            return self._session_token if self._session_active else 0

    def slider_cancellation_generation(self):
        with self._state_lock:
            return self._slider_cancel_generation

    def _slider_cancelled_response(self):
        return {
            "performed": False, "sessionActive": False,
            "sessionEndedBeforeResponse": True,
            "reason": "slider_scrub_cancelled",
            "failureDetail": self._slider_cancel_reason.removeprefix("safety:"),
        }

    def mark_idle_released(self, token, generation=None, slider_reason=None):
        with self._state_lock:
            if generation is not None and not self._is_current_generation(generation):
                return False
            if not token or token != self._session_token:
                return False
            self._session_active = False
            self._session_token = 0
            self._session_generation = 0
            self._last_released_token = int(token)
            self._last_completed_token = max(
                self._last_completed_token,
                int(token),
            )
            if slider_reason and slider_reason != "idle":
                self._slider_cancel_generation += 1
                self._slider_cancel_reason = slider_reason
            return True

    def consume_idle_release(self, token, on_consume=None):
        with self._state_lock:
            try:
                token = int(token)
            except (TypeError, ValueError):
                return False
            if not token or token != self._last_released_token:
                return False
            if on_consume is not None and self._session_active:
                return False
            self._last_released_token = 0
            # Consume and clear atomically with respect to a new request's
            # _set_session_state. Never acquire the request/response _lock here.
            if on_consume is not None:
                on_consume()
            return True

    def pin_release_ready(self, token):
        """Return true only after native idle-end or emergency teardown."""
        with self._state_lock:
            if self._session_active:
                return False
            try:
                token = int(token)
            except (TypeError, ValueError):
                token = 0
            return self._last_released_token in (0, token)

    def stop(self):
        with self._lock:
            process = self._process
            if process is not None and process.poll() is None:
                self._request_id += 1
                try:
                    with self._write_lock:
                        process.stdin.write(json.dumps({
                            "command": "shutdown", "requestId": self._request_id,
                        }) + "\n")
                        process.stdin.flush()
                    process.wait(timeout=1.0)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    pass
            self._stop_locked(force=True)

    def _stop_locked(self, force=False):
        process = self._process
        generation = self._process_generation
        self._process = None
        self._process_generation = 0
        self._output = None
        self._reader = None
        if process is not None:
            if process.poll() is None and force:
                try:
                    process.kill()
                except OSError:
                    pass
            for stream in (process.stdin, process.stdout):
                try:
                    if stream is not None and not stream.closed:
                        stream.close()
                except OSError:
                    pass
        self._emergency_release_if_needed(generation or None)

    def _set_session_state(self, active, token=0, generation=None):
        with self._state_lock:
            if active:
                try:
                    token = int(token) if token else 0
                except (TypeError, ValueError):
                    token = 0
                if token and token <= self._last_completed_token:
                    return False
                self._session_active = True
                self._session_token = token
                self._session_generation = int(
                    generation or self._process_generation or 0
                )
                self._last_released_token = 0
                return True
            if (
                generation is not None
                and self._session_active
                and self._session_generation != int(generation)
            ):
                return
            self._session_active = False
            self._session_token = 0
            self._session_generation = 0
            return True

    def _is_current_generation(self, generation):
        with self._state_lock:
            return bool(
                generation
                and self._process_generation == int(generation)
            )

    def _emergency_release_if_needed(self, generation=None):
        with self._state_lock:
            if (
                generation is not None
                and self._session_active
                and self._session_generation != int(generation)
            ):
                return False
            active = self._session_active
            completed_token = self._session_token if active else 0
            self._session_active = False
            self._session_token = 0
            self._session_generation = 0
            if completed_token:
                self._last_completed_token = max(
                    self._last_completed_token,
                    int(completed_token),
                )
        if active and callable(self.emergency_release):
            try:
                self.emergency_release()
            except Exception as exc:
                print(f"windows wheel emergency release failed: reason={exc}")
        return active


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("value", INPUTUNION),
    ]


class WindowsHotkeySender:
    """Post one complete Windows key chord without the host hotkey parser."""

    INPUT_KEYBOARD = 1
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002

    MODIFIERS = {
        "ctrl": 0x11,
        "control": 0x11,
        "shift": 0x10,
        "alt": 0x12,
        "option": 0x12,
        "win": 0x5B,
        "windows": 0x5B,
        "meta": 0x5B,
    }
    NAMED_KEYS = {
        "backspace": (0x08, False),
        "tab": (0x09, False),
        "enter": (0x0D, False),
        "return": (0x0D, False),
        "escape": (0x1B, False),
        "esc": (0x1B, False),
        "space": (0x20, False),
        "pageup": (0x21, True),
        "pgup": (0x21, True),
        "pagedown": (0x22, True),
        "pgdn": (0x22, True),
        "end": (0x23, True),
        "home": (0x24, True),
        "left": (0x25, True),
        "up": (0x26, True),
        "right": (0x27, True),
        "down": (0x28, True),
        "insert": (0x2D, True),
        "delete": (0x2E, True),
        "del": (0x2E, True),
        "-": (0xBD, False),
        "minus": (0xBD, False),
        "=": (0xBB, False),
        "plus": (0xBB, False),
        ",": (0xBC, False),
        ".": (0xBE, False),
        "/": (0xBF, False),
        ";": (0xBA, False),
        "'": (0xDE, False),
        "[": (0xDB, False),
        "]": (0xDD, False),
        "\\": (0xDC, False),
        "`": (0xC0, False),
    }

    def __init__(self, user32):
        self.user32 = user32
        try:
            self.user32.SendInput.argtypes = [
                wintypes.UINT,
                ctypes.POINTER(INPUT),
                ctypes.c_int,
            ]
            self.user32.SendInput.restype = wintypes.UINT
        except AttributeError:
            # Focused tests use a small Python stand-in for user32.
            pass

    @classmethod
    def _split(cls, hotkey):
        remaining = str(hotkey or "").strip()
        modifiers = []
        while "+" in remaining:
            candidate, tail = remaining.split("+", 1)
            normalized = candidate.strip().lower()
            if normalized not in cls.MODIFIERS:
                break
            modifiers.append(cls.MODIFIERS[normalized])
            remaining = tail
        key = remaining.strip() or "+"
        return modifiers, key

    @classmethod
    def parse(cls, hotkey):
        modifiers, key = cls._split(hotkey)
        normalized = key.lower()
        resolved = cls.NAMED_KEYS.get(normalized)
        if resolved is None and len(key) == 1 and key.isascii() and key.isalnum():
            resolved = (ord(key.upper()), False)
        if resolved is None and normalized.startswith("f"):
            try:
                function_number = int(normalized[1:])
            except ValueError:
                function_number = 0
            if 1 <= function_number <= 24:
                resolved = (0x6F + function_number, False)
        if resolved is None:
            raise ValueError(f"unsupported Windows hotkey key: {key}")
        # Do not press the same modifier twice if a profile contains aliases.
        return tuple(dict.fromkeys(modifiers)), resolved[0], resolved[1]

    @classmethod
    def _keyboard_input(cls, virtual_key, key_up=False, extended=False):
        flags = 0
        if extended:
            flags |= cls.KEYEVENTF_EXTENDEDKEY
        if key_up:
            flags |= cls.KEYEVENTF_KEYUP
        return INPUT(
            type=cls.INPUT_KEYBOARD,
            ki=KEYBDINPUT(
                wVk=virtual_key,
                wScan=0,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            ),
        )

    def send(self, hotkey):
        modifiers, key, extended = self.parse(hotkey)
        events = [self._keyboard_input(modifier) for modifier in modifiers]
        events.extend(
            (
                self._keyboard_input(key, extended=extended),
                self._keyboard_input(key, key_up=True, extended=extended),
            )
        )
        events.extend(
            self._keyboard_input(modifier, key_up=True)
            for modifier in reversed(modifiers)
        )
        input_array = (INPUT * len(events))(*events)
        ctypes.set_last_error(0)
        sent = int(self.user32.SendInput(len(events), input_array, ctypes.sizeof(INPUT)))
        if sent == len(events):
            return True

        # A partial SendInput must never leave Alt/Shift/Ctrl held down.
        releases = [self._keyboard_input(key, key_up=True, extended=extended)]
        releases.extend(
            self._keyboard_input(modifier, key_up=True)
            for modifier in reversed(modifiers)
        )
        release_array = (INPUT * len(releases))(*releases)
        self.user32.SendInput(
            len(releases),
            release_array,
            ctypes.sizeof(INPUT),
        )
        return False


class WindowsHorizontalScrollSender:
    """Send one horizontal-only wheel detent without keys or pointer motion."""

    INPUT_MOUSE = 0
    MOUSEEVENTF_HWHEEL = 0x1000
    WHEEL_DELTA = 120
    PLUGIN_EVENT_TAG = 0x554C4E5A

    def __init__(self, user32):
        self.user32 = user32
        try:
            self.user32.SendInput.argtypes = [
                wintypes.UINT,
                ctypes.POINTER(INPUT),
                ctypes.c_int,
            ]
            self.user32.SendInput.restype = wintypes.UINT
        except AttributeError:
            pass  # Pure tests supply a recording user32 stand-in.

    def send(self, token):
        if token == "HWHEEL LEFT":
            delta = -self.WHEEL_DELTA
        elif token == "HWHEEL RIGHT":
            delta = self.WHEEL_DELTA
        else:
            raise ValueError(f"unsupported Windows horizontal scroll token: {token}")
        # HWHEEL positive means right (unlike the old vertical-wheel UP token).
        # No MOVE/WHEEL/button flags and no keyboard events: there is nothing
        # held across detents, and no cleanup input or fallback can double-send.
        event = INPUT(
            type=self.INPUT_MOUSE,
            mi=MOUSEINPUT(
                dx=0,
                dy=0,
                mouseData=delta & 0xFFFFFFFF,
                dwFlags=self.MOUSEEVENTF_HWHEEL,
                time=0,
                dwExtraInfo=self.PLUGIN_EVENT_TAG,
            ),
        )
        input_array = (INPUT * 1)(event)
        ctypes.set_last_error(0)
        sent = int(self.user32.SendInput(1, input_array, ctypes.sizeof(INPUT)))
        return sent == 1


class WindowsMouse:
    LEFT_DOWN = 0x0002
    LEFT_UP = 0x0004
    VK_LBUTTON = 0x01

    def __init__(self):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self.user32.GetCursorPos.restype = wintypes.BOOL
        self.user32.SetCursorPos.argtypes = [wintypes.INT, wintypes.INT]
        self.user32.SetCursorPos.restype = wintypes.BOOL
        self.user32.GetAsyncKeyState.argtypes = [wintypes.INT]
        self.user32.GetAsyncKeyState.restype = ctypes.c_short
        self.user32.mouse_event.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_size_t,
        ]
        self.user32.mouse_event.restype = None

    def position(self):
        point = wintypes.POINT()
        if not self.user32.GetCursorPos(ctypes.byref(point)):
            raise ctypes.WinError(ctypes.get_last_error())
        return point

    def move(self, x, y):
        if not self.user32.SetCursorPos(round(x), round(y)):
            raise ctypes.WinError(ctypes.get_last_error())

    def left_button_down(self):
        return bool(self.user32.GetAsyncKeyState(self.VK_LBUTTON) & 0x8000)

    def release_left(self):
        self._button(self.LEFT_UP)

    def _button(self, flags):
        self.user32.mouse_event(flags, 0, 0, 0, 0)

    def drag(self, x, y, dx, dy, duration=0.08, restore_pointer=True):
        original = self.position()
        self.move(x, y)
        time.sleep(0.015)
        self._button(self.LEFT_DOWN)
        steps = max(2, min(12, int(abs(dx) + abs(dy)) // 2 + 1))
        for index in range(1, steps + 1):
            ratio = index / steps
            self.move(x + dx * ratio, y + dy * ratio)
            time.sleep(max(0.002, duration / steps))
        self._button(self.LEFT_UP)
        if restore_pointer:
            self.move(original.x, original.y)

    def double_click(self, x, y, restore_pointer=True):
        original = self.position()
        self.move(x, y)
        for _ in range(2):
            self._button(self.LEFT_DOWN)
            self._button(self.LEFT_UP)
            time.sleep(0.08)
        if restore_pointer:
            self.move(original.x, original.y)

    def click(self, x, y, restore_pointer=True):
        original = self.position()
        self.move(x, y)
        self._button(self.LEFT_DOWN)
        self._button(self.LEFT_UP)
        if restore_pointer:
            self.move(original.x, original.y)


class WindowsJianyingBackend(AutomationBackend):
    supports_wheel_motion_profile = True
    target_bundle_id = "JianyingPro.exe"
    supports_basic_hover = True
    supports_hsl_hover = True
    supports_color_wheel_hover = True
    target_executables = {
        "jianyingpro.exe",
        "jianyingpro_douyin.exe",
        "videofusion.exe",
    }

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    def __init__(self, api):
        super().__init__(api)
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._timeline_hotkeys = WindowsHotkeySender(self.user32)
        self._timeline_horizontal_scroll = WindowsHorizontalScrollSender(self.user32)
        self.user32.GetForegroundWindow.argtypes = []
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        self.kernel32.CreateToolhelp32Snapshot.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self.kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self.kernel32.Process32FirstW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESSENTRY32W),
        ]
        self.kernel32.Process32FirstW.restype = wintypes.BOOL
        self.kernel32.Process32NextW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESSENTRY32W),
        ]
        self.kernel32.Process32NextW.restype = wintypes.BOOL
        self.mouse = WindowsMouse()
        self.mouse_lock = RLock()
        self._last_panel_activation = (None, 0.0)
        try:
            self.user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            self.user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
            self.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass
        plugin_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        self._hover_helper_path = os.path.join(
            plugin_root, "native", "jianying_windows_helper.exe"
        )
        self._basic_hover_contexts = set()
        self._basic_hover = BasicHoverService(
            self._hover_helper_path,
            self.pointer_position,
            self.target_is_active,
            self.mouse.left_button_down,
            self._handle_hover_invalidation,
            refresh_on_frontmost_return=True,
        )
        self._color_wheel_states = {}
        self._color_wheel_state_lock = RLock()
        self._wheel_server = WheelServerClient(
            self._hover_helper_path,
            self.mouse.release_left,
            self._handle_wheel_server_event,
        )
        self._wheel_pin_timer = None
        self._wheel_pin_key = ""
        self._wheel_pin_generation = 0
        self.adjustments = WindowsWheelAdjustmentQueue(
            self._perform_adjustment, self._wheel_server.invalidate_wheel_input,
            self._wheel_server.update_fixed_input)

    def execute_timeline_scroll(self, token, mode=None):
        """Use the native horizontal axis only for timeline horizontal mode."""
        if mode != "horizontal_scroll":
            return super().execute_timeline_scroll(token, mode=mode)
        self._last_timeline_scroll_transport = "win32.SendInput.HWHEEL"
        self._last_shortcut_api_result = None
        if not self.target_is_active():
            self._last_timeline_scroll_result = "target-not-frontmost"
            return False
        try:
            performed = self._timeline_horizontal_scroll.send(token)
        except (AttributeError, OSError, ValueError) as exc:
            self._last_timeline_scroll_result = (
                f"exception:{type(exc).__name__}:{str(exc)[:80]}"
            )
            print(
                "windows timeline horizontal scroll failed: "
                f"token={token!r} result={self._last_timeline_scroll_result}"
            )
            return False
        self._last_timeline_scroll_result = (
            True if performed else f"sendinput-failed:{ctypes.get_last_error()}"
        )
        print(
            "windows timeline horizontal scroll: "
            f"token={token!r} axis=horizontal "
            f"delta={-120 if token == 'HWHEEL LEFT' else 120} "
            f"result={self._last_timeline_scroll_result}"
        )
        return performed

    def execute_timeline_shortcut(self, hotkey, mode=None):
        """Use one native chord for deterministic timeline detents."""
        mode = str(mode or "timeline")
        self._last_timeline_shortcut_transport = "win32.SendInput"
        self._last_shortcut_api_result = None
        if not hotkey:
            self._last_timeline_shortcut_result = "empty-hotkey"
            return False
        if not self.target_is_active():
            self._last_timeline_shortcut_result = "target-not-frontmost"
            return False
        try:
            performed = self._timeline_hotkeys.send(hotkey)
        except (AttributeError, OSError, ValueError) as exc:
            self._last_timeline_shortcut_result = (
                f"exception:{type(exc).__name__}:{str(exc)[:80]}"
            )
            print(
                "windows timeline hotkey failed: "
                f"mode={mode} token={hotkey!r} "
                f"result={self._last_timeline_shortcut_result}"
            )
            return False
        if performed:
            self._last_timeline_shortcut_result = True
        else:
            error_code = ctypes.get_last_error()
            self._last_timeline_shortcut_result = f"sendinput-failed:{error_code}"
        print(
            "windows timeline hotkey: "
            f"mode={mode} token={hotkey!r} "
            f"result={self._last_timeline_shortcut_result}"
        )
        return performed

    def execute_marker_shortcut(self, hotkey):
        """Compatibility entry point retained for focused marker callers."""
        performed = self.execute_timeline_shortcut(hotkey, mode="marker")
        self._last_marker_shortcut_transport = self._last_timeline_shortcut_transport
        self._last_marker_shortcut_result = self._last_timeline_shortcut_result
        return performed

    @staticmethod
    def _wheel_feedback_order(state):
        if not isinstance(state, dict):
            return None
        try:
            request_id = int(state.get("_requestId"))
        except (TypeError, ValueError):
            return None
        if request_id <= 0:
            return None
        try:
            phase = int(state.get("_phase"))
        except (TypeError, ValueError):
            source = str(state.get("source") or "")
            phase = 2 if (
                state.get("verified") is True
                or source in {
                    "continuous-session-reacquired",
                    "screen-reacquired",
                    "orbit-preview",
                }
            ) else 1
        return request_id, max(1, phase)

    @classmethod
    def _stamp_wheel_feedback(cls, state, request_id, phase=None):
        state = deepcopy(state)
        try:
            request_id = int(request_id)
        except (TypeError, ValueError):
            request_id = 0
        if request_id > 0:
            state["_requestId"] = request_id
            if phase is None:
                order = cls._wheel_feedback_order(state)
                phase = order[1] if order is not None else 1
            state["_phase"] = max(1, int(phase))
        return state

    def _wheel_state_guard(self):
        lock = getattr(self, "_color_wheel_state_lock", None)
        if lock is None:
            # Some focused unit tests construct the backend with __new__.
            # Production initialization always creates this lock eagerly.
            lock = RLock()
            self._color_wheel_state_lock = lock
        return lock

    def _read_color_wheel_state(self, target_key):
        with self._wheel_state_guard():
            return deepcopy(self._color_wheel_states.get(str(target_key or "")))

    def _commit_color_wheel_state(self, target_key, state):
        target_key = str(target_key or "")
        if not target_key or not isinstance(state, dict):
            return False
        with self._wheel_state_guard():
            current = self._color_wheel_states.get(target_key)
            current_order = self._wheel_feedback_order(current)
            incoming_order = self._wheel_feedback_order(state)
            if (
                current_order is not None
                and incoming_order is not None
                and incoming_order < current_order
            ):
                print(
                    "windows color wheel state: ignored stale feedback "
                    f"key={target_key} incoming={incoming_order} "
                    f"current={current_order}"
                )
                return False
            self._color_wheel_states[target_key] = deepcopy(state)
            return True

    def _clear_color_wheel_states(self):
        with self._wheel_state_guard():
            self._color_wheel_states.clear()

    def _handle_hover_invalidation(self, reason):
        """Synchronously retire geometry that can now point at another row."""
        self._clear_adjustment_queue()
        self._cancel_wheel_server_session()
        self._cancel_wheel_pin_release(release=True)
        if reason in {
            "input_click_pending", "input_click", "input_scroll",
            "layout_change_pending", "target_not_frontmost", "service_stopped",
        }:
            # Manual input or a changed inspector invalidates the remembered
            # diameter axis as well as the hovered handle. Clear after cancel:
            # an ending native request may publish one last old observation.
            # Do not hold the state lock while waiting for native cancellation.
            # Ordinary feedback/idle preserves the axis through the centre.
            self._clear_color_wheel_states()
        print(f"windows adjustment invalidated: reason={reason}")

    def _handle_wheel_server_event(self, event):
        if event.get("event") == "slider-session-ended":
            # A held slider now has a longer idle grace period. If the user
            # takes over during it, queued turns must not re-press the old row.
            reason = str(event.get("reason") or "idle")
            server = getattr(self, "_wheel_server", None)
            if (
                reason != "idle"
                and server is not None
                and server.consume_idle_release(
                    event.get("sessionToken"), self._clear_adjustment_queue
                )
            ):
                print(f"windows slider session stopped: reason={reason}")
            return
        if event.get("event") != "wheel-session-ended":
            return
        generation = event.get("wheelGeneration")
        if generation is not None and generation != getattr(self.adjustments, "_generation", None):
            return
        target_key = str(event.get("key") or "")
        server = getattr(self, "_wheel_server", None)
        released = bool(
            server is not None
            and server.consume_idle_release(event.get("sessionToken"))
        )
        if not released:
            print(
                "windows color wheel session feedback: ignored stale token "
                f"key={target_key} token={event.get('sessionToken')}"
            )
            return
        self._release_wheel_pin_from_server_event(target_key)
        if not self.target_is_active():
            return
        feedback = event.get("feedback")
        if not isinstance(feedback, dict) or not target_key:
            return
        feedback = self._stamp_wheel_feedback(
            feedback,
            event.get("sessionToken"),
            phase=2,
        )
        signature = self._color_wheel_signature(feedback)
        if signature is None:
            return
        feedback["signature"] = signature
        published = bool(
            self._basic_hover.update_color_wheel_feedback(target_key, feedback)
        )
        if published:
            published = self._commit_color_wheel_state(target_key, feedback)
        print(
            "windows color wheel session feedback: "
            f"key={target_key} published={published} "
            f"source={feedback.get('source')} "
            f"angle={feedback.get('angle')} radius={feedback.get('radius')} "
            f"reacquireMs={event.get('reacquireMs')}"
        )
    def _release_wheel_pin_from_server_event(self, target_key):
        target_key = str(target_key or "")
        lock = getattr(self, "mouse_lock", None)
        if lock is None or not target_key:
            return
        with lock:
            if getattr(self, "_wheel_pin_key", "") != target_key:
                return
            timer = getattr(self, "_wheel_pin_timer", None)
            self._wheel_pin_generation = int(
                getattr(self, "_wheel_pin_generation", 0)
            ) + 1
            self._wheel_pin_timer = None
            self._wheel_pin_key = ""
            if timer is not None:
                timer.cancel()
        self._basic_hover.release_color_wheel_target(target_key)

    def frontmost_executable(self):
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return ""
        process_id = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        handle = self.kernel32.OpenProcess(
            self.PROCESS_QUERY_LIMITED_INFORMATION, False, process_id.value
        )
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not self.kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            ):
                return ""
            return os.path.basename(buffer.value)
        finally:
            self.kernel32.CloseHandle(handle)

    def target_is_active(self):
        return self.frontmost_executable().lower() in self.target_executables

    def target_is_running(self):
        snapshot = self.kernel32.CreateToolhelp32Snapshot(
            self.TH32CS_SNAPPROCESS, 0
        )
        if snapshot == self.INVALID_HANDLE_VALUE:
            return False
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            has_entry = self.kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while has_entry:
                if str(entry.szExeFile).lower() in self.target_executables:
                    return True
                has_entry = self.kernel32.Process32NextW(
                    snapshot, ctypes.byref(entry)
                )
            return False
        finally:
            self.kernel32.CloseHandle(snapshot)

    def pointer_position(self):
        point = self.mouse.position()
        return {"x": int(point.x), "y": int(point.y)}

    def _enabled_hover_kinds_locked(self):
        return {token.partition(":")[0] for token in self._basic_hover_contexts}

    def _enable_hover(self, kind, context):
        with self.mouse_lock:
            self._basic_hover_contexts.add(f"{kind}:{context or 'default'}")
            enabled_kinds = self._enabled_hover_kinds_locked()
        print(
            "windows hover kinds: "
            f"enabled={sorted(enabled_kinds)} reason=enable "
            f"kind={kind} context={context or 'default'}"
        )
        self._basic_hover.set_enabled_kinds(enabled_kinds)
        return self._basic_hover.start()

    def _disable_hover(self, kind, context):
        with self.mouse_lock:
            self._basic_hover_contexts.discard(f"{kind}:{context or 'default'}")
            should_stop = not self._basic_hover_contexts
            enabled_kinds = self._enabled_hover_kinds_locked()
            color_wheels_disabled = bool(
                kind == "color_wheels" and "color_wheels" not in enabled_kinds
            )
            if color_wheels_disabled:
                self._clear_color_wheel_states()
        print(
            "windows hover kinds: "
            f"enabled={sorted(enabled_kinds)} reason=disable "
            f"kind={kind} context={context or 'default'}"
        )
        self._basic_hover.set_enabled_kinds(enabled_kinds)
        if color_wheels_disabled:
            self._clear_adjustment_queue()
            self._cancel_wheel_server_session(stop=True)
            self._cancel_wheel_pin_release(release=True)
        elif kind not in enabled_kinds:
            # A pending Basic/HSL scrub may otherwise execute against the same
            # coordinates after its action is removed or the page is switched.
            self._clear_adjustment_queue()
            self._cancel_wheel_server_session()
        if should_stop:
            self._basic_hover.stop()

    def _schedule_wheel_pin_release(self, target_key, delay=0.34):
        target_key = str(target_key or "")
        lock = getattr(self, "mouse_lock", None)
        if lock is None:
            self._basic_hover.release_color_wheel_target(target_key)
            return
        with lock:
            previous = getattr(self, "_wheel_pin_timer", None)
            if previous is not None:
                previous.cancel()
            self._wheel_pin_generation = int(
                getattr(self, "_wheel_pin_generation", 0)
            ) + 1
            pin_generation = self._wheel_pin_generation
            self._wheel_pin_key = target_key
            server = getattr(self, "_wheel_server", None)
            session_token = server.session_token() if server is not None else 0

            def release_if_current():
                with lock:
                    if (
                        self._wheel_pin_generation != pin_generation
                        or self._wheel_pin_key != target_key
                    ):
                        return
                # Do not infer mouse-up from elapsed wall time. Native marks
                # the matching token released only after its actual idle
                # EndContinuousDrag event; on scheduling delay, poll without
                # disarming the pin or its emergency-release evidence.
                if server is not None and not server.pin_release_ready(session_token):
                    with lock:
                        if (
                            self._wheel_pin_generation != pin_generation
                            or self._wheel_pin_key != target_key
                        ):
                            return
                        retry = Timer(0.08, release_if_current)
                        retry.daemon = True
                        self._wheel_pin_timer = retry
                        retry.start()
                    return
                with lock:
                    if (
                        self._wheel_pin_generation != pin_generation
                        or self._wheel_pin_key != target_key
                    ):
                        return
                    self._wheel_pin_timer = None
                    self._wheel_pin_key = ""
                self._basic_hover.release_color_wheel_target(target_key)

            timer = Timer(max(0.05, float(delay)), release_if_current)
            timer.daemon = True
            self._wheel_pin_timer = timer
            timer.start()

    def _cancel_wheel_pin_release(self, release=False):
        lock = getattr(self, "mouse_lock", None)
        if lock is None:
            return
        with lock:
            timer = getattr(self, "_wheel_pin_timer", None)
            target_key = getattr(self, "_wheel_pin_key", "")
            self._wheel_pin_generation = int(
                getattr(self, "_wheel_pin_generation", 0)
            ) + 1
            self._wheel_pin_timer = None
            self._wheel_pin_key = ""
            if timer is not None:
                timer.cancel()
        if release and target_key:
            self._basic_hover.release_color_wheel_target(target_key)

    def enable_basic_hover(self, context=None):
        return self._enable_hover("basic", context)

    def disable_basic_hover(self, context=None):
        self._disable_hover("basic", context)

    def basic_hover_target(self):
        return self._basic_hover.current_target("basic")

    def basic_hover_status(self):
        return self._basic_hover.status_for("basic")

    def enable_hsl_hover(self, context=None):
        return self._enable_hover("hsl", context)

    def disable_hsl_hover(self, context=None):
        self._disable_hover("hsl", context)

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
        print(
            "windows hover kinds: "
            f"enabled={sorted(enabled_kinds)} reason=enable "
            f"kind=selected_slider context={suffix}"
        )
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
            slider_kinds_disabled = not ({"basic", "hsl"} & enabled_kinds)
        print(
            "windows hover kinds: "
            f"enabled={sorted(enabled_kinds)} reason=disable "
            f"kind=selected_slider context={suffix}"
        )
        self._basic_hover.set_enabled_kinds(enabled_kinds)
        if slider_kinds_disabled:
            self._clear_adjustment_queue()
            self._cancel_wheel_server_session()
        if should_stop:
            self._basic_hover.stop()

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
        return self._enable_hover("color_wheels", context)

    def disable_color_wheel_hover(self, context=None):
        self._disable_hover("color_wheels", context)

    def color_wheel_hover_target(self):
        return self._basic_hover.current_target("color_wheels")

    def color_wheel_hover_status(self):
        return self._basic_hover.status_for("color_wheels")

    def screen_capture_permission(self):
        return self._basic_hover.screen_capture_available

    def _run_helper(self, command, payload=None, timeout=8, event_handler=None, request_guard=None):
        if not os.path.isfile(self._hover_helper_path):
            return {"performed": False, "reason": "native_helper_unavailable"}
        if command == "wheel":
            guard_options = {"request_guard": request_guard} if request_guard is not None else {}
            return self._wheel_server.request(
                payload,
                event_handler=event_handler,
                # A zero-step press may need the full OS double-click guard
                # (up to 5.05 s), plus recognition and a 30-detent request.
                # This is only a finite response deadline, not an input delay.
                timeout=8.0,
                **guard_options,
            )
        if command == "adjust":
            return self._wheel_server.request(
                payload,
                event_handler=event_handler,
                timeout=min(float(timeout), 3.0),
                command="adjust",
            )
        if event_handler is not None:
            return self._run_helper_streaming(
                command,
                payload,
                timeout=timeout,
                event_handler=event_handler,
            )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                [self._hover_helper_path, command],
                input=json.dumps(payload or {}, ensure_ascii=False) if payload is not None else None,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                creationflags=creationflags,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"performed": False, "reason": f"windows_helper_failed:{exc}"}
        response = None
        for line in reversed((result.stdout or "").splitlines()):
            try:
                response = json.loads(line)
                break
            except (TypeError, json.JSONDecodeError):
                continue
        if not isinstance(response, dict):
            detail = (result.stderr or "").strip().replace("\n", " ")[:180]
            return {
                "performed": False,
                "reason": "invalid_windows_helper_response",
                "detail": detail,
            }
        return response

    def _run_helper_streaming(self, command, payload, timeout, event_handler):
        """Read safe native preview events before the final helper response."""
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = None
        output = Queue()
        end_of_stream = object()

        def read_stdout(stream):
            try:
                for line in iter(stream.readline, ""):
                    output.put(line)
            finally:
                output.put(end_of_stream)

        try:
            process = subprocess.Popen(
                [self._hover_helper_path, command],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
            reader = Thread(
                target=read_stdout,
                args=(process.stdout,),
                name="jianying-windows-helper-output",
                daemon=True,
            )
            reader.start()
            if process.stdin is not None:
                process.stdin.write(json.dumps(payload or {}, ensure_ascii=False))
                process.stdin.close()

            deadline = time.monotonic() + max(0.1, float(timeout))
            response = None
            detail_lines = []
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    process.wait(timeout=1)
                    return {"performed": False, "reason": "windows_helper_timeout"}
                try:
                    line = output.get(timeout=remaining)
                except Empty:
                    process.kill()
                    process.wait(timeout=1)
                    return {"performed": False, "reason": "windows_helper_timeout"}
                if line is end_of_stream:
                    break
                stripped = str(line or "").strip()
                if not stripped:
                    continue
                try:
                    decoded = json.loads(stripped)
                except (TypeError, json.JSONDecodeError):
                    detail_lines.append(stripped)
                    continue
                if not isinstance(decoded, dict):
                    continue
                if decoded.get("event") == "wheel-preview":
                    try:
                        event_handler(decoded)
                    except Exception as exc:
                        print(f"windows helper event ignored: reason={exc}")
                    continue
                response = decoded

            remaining = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
                return {"performed": False, "reason": "windows_helper_timeout"}
            if not isinstance(response, dict):
                return {
                    "performed": False,
                    "reason": "invalid_windows_helper_response",
                    "detail": " ".join(detail_lines)[-180:],
                }
            return response
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            if process is not None and process.poll() is None:
                process.kill()
            return {"performed": False, "reason": f"windows_helper_failed:{exc}"}
        finally:
            if process is not None:
                for stream in (process.stdout, process.stdin):
                    try:
                        if stream is not None and not stream.closed:
                            stream.close()
                    except OSError:
                        pass

    @staticmethod
    def _numbers(calibration):
        calibration = calibration or {}
        try:
            return (
                float(calibration.get("x")),
                float(calibration.get("y")),
                float(calibration.get("pixelsPerStep", 2.0)),
            )
        except (TypeError, ValueError):
            return None

    def adjust_parameter(self, calibration, ticks, fine=False):
        if not self.target_is_active():
            self._clear_adjustment_queue()
            self._cancel_wheel_server_session()
            self._cancel_wheel_pin_release(release=True)
            return AdjustmentResult(False, reason="Jianying Pro is not frontmost")
        values = self._numbers(calibration)
        if values is None:
            return AdjustmentResult(False, reason="parameter is not calibrated")
        hover_target = (calibration or {}).get("hoverTarget")
        if isinstance(hover_target, dict) and not self._valid_slider_hover_target(
            hover_target
        ):
            return AdjustmentResult(
                False, reason="hovered slider geometry is not safely recognized"
            )
        if isinstance(hover_target, dict):
            calibration = deepcopy(calibration)
            # Native emits each detent within a same-direction batch. Keep
            # reversals ordered instead of subtracting them before execution.
            calibration["_preserveTickOrder"] = True
            calibration["_sliderCancelGeneration"] = self._slider_cancellation_generation()
        self.adjustments.submit(
            calibration,
            ticks,
            fine,
            replace_pending_hover=isinstance(
                (calibration or {}).get("hoverTarget"), dict
            ),
        )
        return AdjustmentResult(True, approximate=True)

    @staticmethod
    def _valid_slider_hover_target(target):
        if (
            not isinstance(target, dict)
            or target.get("controlType") != "slider"
            or target.get("handleDetected") is not True
            or target.get("numericVerified") is not True
            or str(target.get("kind") or "") not in {"basic", "hsl", "color_wheels"}
            or not str(target.get("key") or "")
            or not str(target.get("windowHwnd") or "")
        ):
            return False
        try:
            float(target.get("processId"))
            dpi = float(target.get("dpi"))
            handle_x = float(target.get("handleX"))
            handle_y = float(target.get("handleY"))
            scrub_x = float(target.get("x"))
            scrub_y = float(target.get("y"))
        except (TypeError, ValueError):
            return False
        if dpi <= 0:
            return False

        def valid_rect(name, point=None):
            rect = target.get(name)
            if not isinstance(rect, dict):
                return False
            try:
                left = float(rect["x"])
                top = float(rect["y"])
                width = float(rect["w"])
                height = float(rect["h"])
            except (KeyError, TypeError, ValueError):
                return False
            if width <= 0 or height <= 0:
                return False
            if point is None:
                return True
            return (
                left <= point[0] <= left + width
                and top <= point[1] <= top + height
            )

        return (
            valid_rect("windowRect")
            and valid_rect("trackRect", (handle_x, handle_y))
            and valid_rect("valueRect", (scrub_x, scrub_y))
        )

    def _wheel_log_due(self, stage):
        now = time.monotonic()
        times = getattr(self, "_wheel_log_times", None)
        if times is None:
            times = self._wheel_log_times = {}
        if now - times.get(stage, -1.0) < .25:
            return False
        times[stage] = now
        return True

    def _perform_adjustment(
        self,
        calibration,
        ticks,
        fine=False,
        _wheel_pin_held=False,
    ):
        frame = bool(calibration.get("_wheelFrame"))
        fixed = bool(calibration.get("_fixedWheel"))
        queued_wheel = frame or fixed
        if queued_wheel and not self.adjustments.is_current(calibration):
            return {"performed": False, "reason": "wheel_input_cancelled"}
        if not self.target_is_active():
            self._clear_adjustment_queue()
            self._cancel_wheel_server_session()
            self._cancel_wheel_pin_release(release=True)
            return {"performed": False, "reason": "jianying_not_frontmost"}
        hover_target = (calibration or {}).get("hoverTarget")
        if isinstance(hover_target, dict):
            command = "wheel" if calibration.get("dragMode") == "windowsColorWheel" else "adjust"
            if command == "adjust":
                calibration = dict(calibration)
                calibration.setdefault(
                    "_sliderCancelGeneration", self._slider_cancellation_generation()
                )
                if calibration["_sliderCancelGeneration"] != self._slider_cancellation_generation():
                    return {
                        "performed": False, "sessionActive": False,
                        "reason": "slider_scrub_cancelled", "appliedTicks": 0,
                    }
                self._cancel_wheel_pin_release(release=True)
                chunks = self._wheel_tick_chunks(ticks)
                if not chunks:
                    return {"performed": False, "reason": "no_ticks"}
                if len(chunks) > 1:
                    print(
                        "windows slider chunks: "
                        f"kind={hover_target.get('kind')} key={hover_target.get('key')} "
                        f"requestedTicks={ticks} chunks={chunks}"
                    )
                    response = None
                    applied_ticks = 0
                    for chunk in chunks:
                        if not self.target_is_active():
                            self._clear_adjustment_queue()
                            self._cancel_wheel_server_session()
                            break
                        response = self._perform_adjustment(calibration, chunk, fine)
                        if isinstance(response, dict):
                            applied_ticks += response.get(
                                "appliedTicks", chunk if response.get("performed") else 0
                            )
                        if self._slider_response_requires_stop(response):
                            break
                    if isinstance(response, dict):
                        response = dict(response)
                        response["requestedTicks"] = ticks
                        response["appliedTicks"] = applied_ticks
                    return response
            if command == "wheel" and not frame:
                chunks = self._wheel_tick_chunks(ticks)
                if len(chunks) > 1:
                    print(
                        "windows color wheel chunks: "
                        f"key={hover_target.get('key')} totalTicks={ticks} "
                        f"chunks={chunks}"
                    )
                    target_key = str(hover_target.get("key") or "")
                    pin_method = getattr(
                        self._basic_hover,
                        "pin_color_wheel_target",
                        None,
                    )
                    release_method = getattr(
                        self._basic_hover,
                        "release_color_wheel_target",
                        None,
                    )
                    pinned = bool(
                        callable(pin_method) and pin_method(target_key)
                    )
                    if pinned:
                        self._cancel_wheel_pin_release(release=False)
                    chunk_response = None
                    try:
                        for chunk in chunks:
                            if not self.target_is_active():
                                self._clear_adjustment_queue()
                                break
                            chunk_response = self._perform_adjustment(
                                calibration,
                                chunk,
                                fine,
                                _wheel_pin_held=pinned,
                            )
                            if self._wheel_response_requires_stop(chunk_response):
                                break
                    finally:
                        if pinned and callable(release_method):
                            if (
                                isinstance(chunk_response, dict)
                                and chunk_response.get("sessionActive")
                                and not self._wheel_response_requires_stop(chunk_response)
                            ):
                                self._schedule_wheel_pin_release(target_key)
                            else:
                                release_method(target_key)
                    return chunk_response
            wheel_mode = normalize_wheel_mode(calibration.get("wheelMode"))
            payload = {
                "target": deepcopy(hover_target),
                "ticks": ticks,
                "fine": bool(fine),
                "mode": wheel_mode,
                "sensitivity": calibration.get("sensitivity", 1.0),
            }
            if frame:
                payload.update(wheelFrame=True, wheelGeneration=calibration["_wheelGeneration"])
            elif fixed:
                payload.update(wheelFixed=True, fixedWheelGeneration=calibration["_fixedWheelGeneration"],
                               fixedFirstBatch=bool(calibration.get("_fixedWheelFirstBatch")))
                if "_fixedWheelInputMs" in calibration:
                    payload["fixedBatchInputMs"] = calibration["_fixedWheelInputMs"]
            if command == "adjust":
                payload["_sliderCancelGeneration"] = calibration["_sliderCancelGeneration"]
            wheel_signature = None
            if command == "wheel":
                wheel_signature = self._color_wheel_signature(hover_target)
                previous = self._read_color_wheel_state(
                    str(hover_target.get("key") or "")
                )
                payload["responseGain"] = DEFAULT_RESPONSE_GAIN
                if (
                    isinstance(previous, dict)
                    and previous.get("signature") == wheel_signature
                ):
                    # The visible handle/angle belongs to the wheel and is
                    # shared by every Color Wheels action instance.  A
                    # diameter axis, however, is valid only while continuing
                    # a diameter gesture.  Reusing it after an orbit gesture
                    # makes another button jump back to the pre-orbit point.
                    for key in ("angle", "responseGain"):
                        if previous.get(key) is not None:
                            payload[
                                "previewAngle" if key == "angle" else key
                            ] = previous[key]
                    if wheel_mode == "orbit" and previous.get("lastMode") == "orbit":
                        for key in ("orbitRadius", "orbitCorrectionAllowed", "handleX", "handleY"):
                            if key in previous:
                                payload[key] = previous[key]
                    if (
                        wheel_mode == "diameter"
                        and str(previous.get("lastMode") or "").strip().lower()
                        == "diameter"
                    ):
                        for key in ("axisAngle", "signedRadius"):
                            if previous.get(key) is not None:
                                payload[key] = previous[key]
            target_key = str(hover_target.get("key") or "")
            pin_method = getattr(
                self._basic_hover,
                "pin_color_wheel_target",
                None,
            )
            release_method = getattr(
                self._basic_hover,
                "release_color_wheel_target",
                None,
            )
            pinned_here = bool(
                command == "wheel"
                and not _wheel_pin_held
                and callable(pin_method)
                and pin_method(target_key)
            )
            if pinned_here:
                self._cancel_wheel_pin_release(release=False)
            preview_allowed = bool(_wheel_pin_held or pinned_here)
            preview_published = False
            final_published = False
            response = None

            def handle_helper_event(event):
                nonlocal preview_published
                if command != "wheel" or not preview_allowed:
                    return
                if queued_wheel and not self.adjustments.is_current(calibration):
                    return
                feedback = event.get("feedback")
                event_key = str(event.get("key") or target_key)
                if (
                    not isinstance(feedback, dict)
                    or event_key != target_key
                    or not self.target_is_active()
                ):
                    return
                preview = self._stamp_wheel_feedback(
                    feedback,
                    event.get("requestId"),
                    phase=1,
                )
                preview["signature"] = wheel_signature
                preview_published = bool(
                    self._basic_hover.update_color_wheel_feedback(
                        target_key,
                        preview,
                    )
                )
                if preview_published:
                    preview_published = self._commit_color_wheel_state(
                        target_key,
                        preview,
                    )
                if not frame or self._wheel_log_due("preview"):
                    print(
                        "windows color wheel preview: "
                        f"key={target_key} published={preview_published} "
                        f"requestId={event.get('requestId')} "
                        f"motionTicks={event.get('motionTicks')} "
                        f"source={preview.get('source')} "
                        f"angle={preview.get('angle')} "
                        f"radius={preview.get('radius')} "
                        f"validationMs={event.get('validationMs')} "
                        f"nativeElapsedMs={event.get('nativeElapsedMs')}"
                    )

            try:
                started = time.monotonic()
                helper_options = {}
                if fixed:
                    # Recheck after waiting for the transport lock, but never
                    # discard an isolated first detent while preparing it. Native
                    # also checks live input before continuing a stale batch.
                    helper_options["request_guard"] = lambda: self.adjustments.is_current(calibration)
                response = self._run_helper(
                    command,
                    payload,
                    event_handler=handle_helper_event if command == "wheel" else None,
                    **helper_options,
                )
                if queued_wheel and not self.adjustments.is_current(calibration):
                    return {"performed": False, "reason": "wheel_input_cancelled"}
                if frame and not response.get("performed"):
                    try:
                        print(
                            "windows wheel frame failure: "
                            + json.dumps({
                                "key": target_key, "mode": wheel_mode,
                                "ticks": ticks,
                                "wheelGeneration": calibration.get("_wheelGeneration"),
                                "response": response,
                            }, ensure_ascii=False, default=str)
                        )
                    except (OSError, UnicodeError, ValueError):
                        pass
                    # A boundary or lost capture consumes no further distance.
                    # An old frame must never clear a newly reversed gesture.
                    self.adjustments.discard_if_current(calibration)
                    self._cancel_wheel_server_session()
                    return response
                elapsed_ms = int(round((time.monotonic() - started) * 1000))
                if not frame or self._wheel_log_due("adjustment"):
                    print(
                        "windows adjustment: "
                        f"command={command} kind={hover_target.get('kind')} "
                        f"key={hover_target.get('key')} ticks={ticks} "
                        f"performed={bool(response.get('performed'))} "
                        f"reason={response.get('reason', '')} mode={response.get('mode', '')} "
                        f"steps={response.get('steps')} "
                        f"appliedTicks={response.get('appliedTicks')} "
                        f"stepwise={response.get('stepwise')} "
                        f"maxMotionTicks={response.get('maxMotionTicks')} "
                        f"pressWaitMs={response.get('pressWaitMs')} "
                        f"sessionReused={response.get('sessionReused')} "
                        f"physicalDistance={response.get('physicalDistance')} "
                        f"dpiScale={response.get('dpiScale')} "
                        f"validation={response.get('validation', '')} "
                        f"verified={response.get('verified')} "
                        f"gain={response.get('responseGain')} "
                        f"startRadius={response.get('startRadius')} "
                        f"handleLimit={response.get('handleLimit')} "
                        f"expectedDelta={response.get('expectedHandleDelta')} "
                        f"cursorDelta={response.get('cursorDelta')} "
                        f"observedDelta={response.get('observedHandleDelta')} "
                        f"validationMs={response.get('validationMs')} "
                        f"dragMs={response.get('dragMs')} "
                        f"reacquireMs={response.get('reacquireMs')} "
                        f"failureDetail={response.get('failureDetail', '')} "
                        f"nativeTotalMs={response.get('nativeTotalMs')} "
                        f"elapsedMs={elapsed_ms}"
                    )
                if (
                    self._slider_response_requires_stop(response)
                    if command == "adjust"
                    else self._wheel_response_requires_stop(response)
                ):
                    if fixed:
                        if not self.adjustments.discard_if_current(calibration):
                            return response
                    else:
                        self._clear_adjustment_queue()
                    self._cancel_wheel_server_session()
                    if command == "wheel":
                        self._cancel_wheel_pin_release(release=True)
                    print(
                        "windows adjustment queue cleared: "
                        f"command={command} key={target_key} "
                        f"reason={response.get('reason', '')}"
                    )
                if command == "wheel":
                    feedback = response.get("feedback")
                    if isinstance(feedback, dict) and self.target_is_active():
                        feedback_source = str(feedback.get("source") or "")
                        observed = feedback_source in {
                            "screen-reacquired",
                            "orbit-preview",
                        }
                        predicted = feedback_source == "continuous-drag-predicted"
                        feedback = self._stamp_wheel_feedback(
                            feedback,
                            response.get("requestId"),
                            phase=2 if observed else 1,
                        )
                        feedback["signature"] = wheel_signature
                        if observed:
                            final_published = bool(
                                self._basic_hover.update_color_wheel_feedback(
                                    target_key, feedback
                                )
                            )
                        elif predicted and preview_published:
                            final_published = True
                        if final_published:
                            final_published = self._commit_color_wheel_state(
                                target_key,
                                feedback,
                            )
                        if not frame or self._wheel_log_due("feedback"):
                            print(
                                "windows color wheel feedback: "
                                f"key={target_key} published={final_published} "
                                f"source={feedback_source} observed={observed} "
                                f"angle={feedback.get('angle')} "
                                f"radius={feedback.get('radius')}"
                            )
            finally:
                if pinned_here and callable(release_method):
                    if (
                        isinstance(response, dict)
                        and response.get("sessionActive")
                        and not self._wheel_response_requires_stop(response)
                    ):
                        self._schedule_wheel_pin_release(target_key)
                    else:
                        release_method(target_key)
            return response
        x, y, pixels = self._numbers(calibration)
        if str((calibration or {}).get("dragMode")) == "absoluteWheel":
            with self.mouse_lock:
                self._activate_panel_locked(calibration)
                self.mouse.drag(
                    x,
                    y,
                    float(calibration.get("offsetX", 0)),
                    float(calibration.get("offsetY", 0)),
                )
            return
        distance = float(ticks) * pixels * (0.25 if fine else 1.0)
        with self.mouse_lock:
            self._activate_panel_locked(calibration)
            if str((calibration or {}).get("axis", "horizontal")) == "vertical":
                self.mouse.drag(x, y, 0, -distance)
            else:
                self.mouse.drag(x, y, distance, 0)

    @staticmethod
    def _wheel_tick_chunks(ticks, maximum=30):
        """Transport cap for legacy callers and sliders.

        Live Windows fixed wheel input is already limited to two-detent batches
        by WindowsWheelAdjustmentQueue, so no long local chunk loop escapes its
        stop/reversal policy. Native still applies each detent separately.
        """
        try:
            remaining = abs(int(round(float(ticks))))
            direction = -1 if float(ticks) < 0 else 1
        except (TypeError, ValueError):
            return []
        maximum = max(1, int(maximum))
        chunks = []
        while remaining:
            size = min(maximum, remaining)
            chunks.append(direction * size)
            remaining -= size
        return chunks

    @staticmethod
    def _slider_response_requires_stop(response):
        return (
            isinstance(response, dict)
            and (
                response.get("failureDetail") in WheelServerClient._SLIDER_TAKEOVER_FAILURES
                or any(
                    str(response.get(field) or "").strip().lower().startswith("slider_takeover_")
                    for field in ("reason", "failureDetail")
                )
            )
        ) or WindowsJianyingBackend._wheel_response_requires_stop(response)

    def _slider_cancellation_generation(self):
        server = getattr(self, "_wheel_server", None)
        return server.slider_cancellation_generation() if server is not None else 0

    @staticmethod
    def _wheel_response_requires_stop(response):
        if not isinstance(response, dict) or response.get("performed"):
            return False
        reason = str(response.get("reason") or "").strip().lower()
        if not reason:
            return False
        return any(
            marker in reason
            for marker in (
                "foreground",
                "not_frontmost",
                "not_recognized",
                "not recognized",
                "hovered_target",
                "window_mismatch",
                "point_not_owned",
                "wheel_server",
                "interaction_server",
                "native_helper",
                "uia_range",
                "numeric_scrubber",
                "slider_scrub",
                "slider_press_",
            )
        )

    def _clear_adjustment_queue(self):
        queue = getattr(self, "adjustments", None)
        if queue is not None:
            queue.clear()

    def _cancel_wheel_server_session(self, stop=False):
        server = getattr(self, "_wheel_server", None)
        if server is None:
            return
        if stop:
            server.stop()
        else:
            server.cancel()

    def adjust_color_wheel(self, target, ticks, mode="diameter", sensitivity=1.0,
                           motion_profile="fixed", motion_context=None):
        if not self.target_is_active():
            self._clear_adjustment_queue()
            self._cancel_wheel_server_session()
            self._cancel_wheel_pin_release(release=True)
            return AdjustmentResult(False, reason="Jianying Pro is not frontmost")
        if not isinstance(target, dict) or target.get("controlType") != "wheel":
            return AdjustmentResult(False, reason="color wheel is not recognized")
        if target.get("handleDetected") is not True:
            key = str(target.get("key") or "unknown")
            print(
                f"windows color wheel drag: skipped key={key} "
                "reason=white_handle_not_detected"
            )
            return AdjustmentResult(
                False, reason="color wheel white handle is not recognized"
            )
        calibration = deepcopy(target)
        calibration.update({
            "dragMode": "windowsColorWheel",
            "wheelMode": normalize_wheel_mode(mode),
            "wheelMotion": "accelerated" if motion_profile == "accelerated" else "fixed",
            "motionContext": motion_context,
            # The smart Windows actions intentionally hide sensitivity: one
            # physical encoder detent must always be exactly one logical
            # Jianying step, including profiles saved by older plugin builds.
            # Keep macOS behaviour untouched in its own backend.
            "sensitivity": 1.0,
            "targetKey": target.get("key"),
            "hoverTarget": deepcopy(target),
            # Queue identity follows the wheel, not its moving white handle.
            # Native still reads the actual drag origin from hoverTarget.
            "x": target.get("centerX"),
            "y": target.get("centerY"),
            "pixelsPerStep": 1,
            "_preserveTickOrder": True,
        })
        self.adjustments.submit(
            calibration, ticks, False, replace_pending_hover=True
        )
        return AdjustmentResult(True, approximate=True)

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
        hover_target = (calibration or {}).get("hoverTarget")
        if isinstance(hover_target, dict):
            self._clear_adjustment_queue()
            self._cancel_wheel_server_session()
            self._cancel_wheel_pin_release(release=True)
            response = self._run_helper("reset", {"target": hover_target})
            print(
                "windows reset: "
                f"kind={hover_target.get('kind')} key={hover_target.get('key')} "
                f"performed={bool(response.get('performed'))} "
                f"reason={response.get('reason') or ''} "
                f"mode={response.get('mode') or ''} "
                f"source={response.get('resetSource') or hover_target.get('resetSource') or ''} "
                f"point=({response.get('clickX', '')},{response.get('clickY', '')}) "
                f"validation={response.get('targetValidation') or ''}"
            )
            return AdjustmentResult(
                bool(response.get("performed")),
                reason=str(response.get("reason") or ""),
            )
        values = self._numbers(calibration)
        if values is None:
            return AdjustmentResult(False, reason="parameter is not calibrated")
        try:
            self._clear_adjustment_queue()
            self._cancel_wheel_server_session()
            self._cancel_wheel_pin_release(release=True)
            with self.mouse_lock:
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
        self._clear_adjustment_queue()
        self._cancel_wheel_server_session()
        self._cancel_wheel_pin_release(release=True)
        response = self._run_helper("reset", {"target": target})
        if (
            response.get("performed")
            and target.get("controlType") == "wheel"
            and self.target_is_active()
        ):
            key = str(target.get("key") or "")
            if key:
                state = centered_wheel_state(target, preserve_vertical_axis=True)
                self._commit_color_wheel_state(key, state)
                self._basic_hover.update_color_wheel_feedback(key, state)
        return AdjustmentResult(
            bool(response.get("performed")),
            reason=str(response.get("reason") or ""),
        )

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
