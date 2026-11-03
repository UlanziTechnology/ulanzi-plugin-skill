"""Latency-aware Resolve routing across host hotkeys and Resolve transports."""

import os
import socket
import struct
import sys
import threading
import time

from .native_input import IS_WINDOWS, NativeTimelineInput
from .timecode import add_frames, nominal_fps, timecode_to_frames


VIEW_MODES = {
    "track_height",
    "timeline_zoom",
    "vertical_scroll",
    "horizontal_scroll",
}
PLAYHEAD_MODES = {"frame_step", "playhead_seconds"}

# Windows timeline gestures must be delegated to Ulanzi Deck. Each tuple is
# ordered as (negative/left dial tick, positive/right dial tick).
WINDOWS_HOTKEYS = {
    "frame_step": ("Left", "Right"),
    "track_height": ("Shift+SCROLL DOWN", "Shift+SCROLL UP"),
    "timeline_zoom": ("Alt+SCROLL DOWN", "Alt+SCROLL UP"),
    "vertical_scroll": ("SCROLL UP", "SCROLL DOWN"),
    "horizontal_scroll": ("Ctrl+SCROLL UP", "Ctrl+SCROLL DOWN"),
    "playhead_seconds": ("Shift+Left", "Shift+Right"),
}


class ResolveScriptingTransport:
    name = "scripting"

    def __init__(self, retry_seconds=3.0):
        self.retry_seconds = float(retry_seconds)
        self._lock = threading.RLock()
        self._resolve = None
        self._last_probe_at = 0.0
        self._last_probe_ok = False
        self.last_error = ""
        self.last_latency_ms = None

    def _module_paths(self):
        paths = []
        env_path = os.getenv("RESOLVE_SCRIPT_API")
        if env_path:
            paths.append(os.path.join(env_path, "Modules"))
            paths.append(env_path)
        if sys.platform == "darwin":
            paths.append(
                "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"
            )
        elif os.name == "nt":
            program_data = os.getenv("PROGRAMDATA", r"C:\ProgramData")
            paths.append(
                os.path.join(
                    program_data,
                    "Blackmagic Design",
                    "DaVinci Resolve",
                    "Support",
                    "Developer",
                    "Scripting",
                    "Modules",
                )
            )
        else:
            paths.append("/opt/resolve/Developer/Scripting/Modules")
        return paths

    def _connect(self):
        for path in self._module_paths():
            if path and os.path.isdir(path) and path not in sys.path:
                sys.path.insert(0, path)
        try:
            import DaVinciResolveScript as dvr_script

            return dvr_script.scriptapp("Resolve")
        except Exception as exc:
            self.last_error = f"Scripting API unavailable: {exc}"
            return None

    def close(self):
        # Do not wait on a potentially hung Resolve IPC call during plugin
        # teardown. Assigning these references is atomic in CPython.
        self._resolve = None
        self._last_probe_ok = False

    def probe(self, force=False):
        with self._lock:
            now = time.monotonic()
            if self._resolve is not None:
                try:
                    if self._resolve.GetVersionString():
                        self._last_probe_ok = True
                        return True
                except Exception:
                    self._resolve = None
                    self._last_probe_ok = False

            if not force and now - self._last_probe_at < self.retry_seconds:
                return self._last_probe_ok

            self._last_probe_at = now
            started = time.perf_counter()
            self._resolve = self._connect()
            self.last_latency_ms = (time.perf_counter() - started) * 1000.0
            self._last_probe_ok = self._resolve is not None
            if self._last_probe_ok:
                self.last_error = ""
            return self._last_probe_ok

    def _current_timeline(self):
        if not self.probe():
            return None
        try:
            project_manager = self._resolve.GetProjectManager()
            project = project_manager.GetCurrentProject() if project_manager else None
            timeline = project.GetCurrentTimeline() if project else None
            if not timeline:
                self.last_error = "No current Resolve timeline"
            return timeline
        except Exception as exc:
            self.last_error = f"Cannot access current timeline: {exc}"
            self._resolve = None
            self._last_probe_ok = False
            return None

    def move_frames(self, delta_frames):
        delta_frames = int(delta_frames)
        if not delta_frames:
            return True
        with self._lock:
            timeline = self._current_timeline()
            if timeline is None:
                return False
            return self._move_frames_on_timeline(timeline, delta_frames)

    def _move_frames_on_timeline(self, timeline, delta_frames, frame_rate=None):
        started = time.perf_counter()
        try:
            current = timeline.GetCurrentTimecode()
            frame_rate = float(frame_rate or timeline.GetSetting("timelineFrameRate"))
            current_frames = timecode_to_frames(current, frame_rate)
            target_frames = current_frames + int(delta_frames)

            try:
                start_timecode = timeline.GetStartTimecode()
                start_timecode_frames = timecode_to_frames(start_timecode, frame_rate)
                start_frame = int(timeline.GetStartFrame())
                end_frame = int(timeline.GetEndFrame())
                target_frames = min(
                    start_timecode_frames + max(0, end_frame - start_frame - 1),
                    max(start_timecode_frames, target_frames),
                )
            except Exception:
                target_frames = max(0, target_frames)

            target = add_frames(current, target_frames - current_frames, frame_rate)
            result = timeline.SetCurrentTimecode(target)
            self.last_latency_ms = (time.perf_counter() - started) * 1000.0
            if not result:
                self.last_error = f"Resolve rejected timecode {target}"
                return False
            self.last_error = ""
            return True
        except Exception as exc:
            self.last_latency_ms = (time.perf_counter() - started) * 1000.0
            self.last_error = f"Scripting timeline move failed: {exc}"
            return False

    def move_seconds(self, delta_seconds):
        with self._lock:
            timeline = self._current_timeline()
            if timeline is None:
                return False
            try:
                frame_rate = float(timeline.GetSetting("timelineFrameRate"))
                frames = int(delta_seconds) * nominal_fps(frame_rate)
            except Exception as exc:
                self.last_error = f"Cannot read timeline frame rate: {exc}"
                return False
            return self._move_frames_on_timeline(timeline, frames, frame_rate)

    def describe(self):
        if self._last_probe_ok:
            latency = "" if self.last_latency_ms is None else f" ({self.last_latency_ms:.1f} ms)"
            return f"Scripting API{latency}"
        return self.last_error or "Scripting API not connected"


class ResolveTcpTransport:
    """Blackmagic TCP transport-control protocol v1.2 client."""

    name = "tcp"

    def __init__(self, host="127.0.0.1", port=9060, timeout=0.08, retry_seconds=3.0):
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.retry_seconds = float(retry_seconds)
        self._socket = None
        self._lock = threading.RLock()
        self._last_probe_at = 0.0
        self._last_probe_ok = False
        self._auto_retry_after = 0.0
        self.last_error = ""
        self.last_latency_ms = None

    def close(self):
        sock, self._socket = self._socket, None
        self._last_probe_ok = False
        self._auto_retry_after = 0.0
        if sock:
            try:
                sock.close()
            except Exception:
                pass

    @property
    def is_ready(self):
        """Whether the low-latency transport was already connected."""
        with self._lock:
            return (
                self._socket is not None
                and self._last_probe_ok
                and time.monotonic() >= self._auto_retry_after
            )

    @staticmethod
    def _command_bytes(command, payload=b""):
        encoded = command.encode("ascii")
        return struct.pack("<i", len(encoded)) + encoded + payload

    def _recv_exact(self, size):
        chunks = []
        remaining = int(size)
        while remaining > 0:
            chunk = self._socket.recv(remaining)
            if not chunk:
                raise ConnectionError("Resolve closed the TCP connection")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _request(self, command, payload=b"", response_size=0):
        try:
            self._socket.sendall(self._command_bytes(command, payload))
            status = self._recv_exact(1)[0]
            if status != 0:
                self.last_error = f"TCP command {command} returned status 0x{status:02X}"
                return None
            return self._recv_exact(response_size) if response_size else b""
        except Exception as exc:
            self.last_error = f"TCP command {command} failed: {exc}"
            self.close()
            return None

    def probe(self, force=False):
        with self._lock:
            now = time.monotonic()
            if self._socket is not None:
                return True
            if not force and now - self._last_probe_at < self.retry_seconds:
                return self._last_probe_ok
            self._last_probe_at = now
            started = time.perf_counter()
            try:
                self._socket = socket.create_connection((self.host, self.port), self.timeout)
                self._socket.settimeout(self.timeout)
                response = self._request("connect")
                self._last_probe_ok = response is not None
                if not self._last_probe_ok:
                    self.close()
            except Exception as exc:
                self.last_error = f"TCP 9060 unavailable: {exc}"
                self.close()
                self._last_probe_ok = False
            self.last_latency_ms = (time.perf_counter() - started) * 1000.0
            if self._last_probe_ok:
                self.last_error = ""
            return self._last_probe_ok

    def _timecode_and_rate(self):
        if not self.probe():
            return None
        timecode = self._request("gettc", response_size=4)
        if timecode is None:
            return None
        frame_rate_bytes = self._request("getframerate", response_size=4)
        if frame_rate_bytes is None:
            return None
        hour, minute, second, frame = struct.unpack("4B", timecode)
        frame_rate = struct.unpack("<f", frame_rate_bytes)[0]
        return (hour, minute, second, frame), frame_rate

    def move_frames(self, delta_frames):
        delta_frames = int(delta_frames)
        if not delta_frames:
            return True
        with self._lock:
            started = time.perf_counter()
            current = self._timecode_and_rate()
            if current is None:
                return False
            parts, frame_rate = current
            return self._move_from_snapshot(parts, frame_rate, delta_frames, started)

    def _move_from_snapshot(self, parts, frame_rate, delta_frames, started=None):
        if started is None:
            started = time.perf_counter()
        try:
            # Protocol v1.2 does not expose the drop-frame separator. Avoid an
            # ambiguous direct jump and let the router use exact arrow fallback.
            if abs(frame_rate - round(frame_rate)) > 0.01:
                self.last_error = "TCP timecode is ambiguous for fractional frame rates"
                self._auto_retry_after = time.monotonic() + self.retry_seconds
                return False
            nominal = nominal_fps(frame_rate)
            hour, minute, second, frame = parts
            current_frames = ((hour * 3600 + minute * 60 + second) * nominal) + frame
            target = max(0, current_frames + delta_frames)
            target_hour, remainder = divmod(target, nominal * 3600)
            target_minute, remainder = divmod(remainder, nominal * 60)
            target_second, target_frame = divmod(remainder, nominal)
            payload = struct.pack(
                "4B",
                target_hour % 24,
                target_minute,
                target_second,
                target_frame,
            )
            result = self._request("goto", payload=payload)
            self.last_latency_ms = (time.perf_counter() - started) * 1000.0
            if result is not None:
                self._auto_retry_after = 0.0
            return result is not None
        except Exception as exc:
            self.last_latency_ms = (time.perf_counter() - started) * 1000.0
            self.last_error = f"TCP timeline move failed: {exc}"
            return False

    def move_seconds(self, delta_seconds):
        with self._lock:
            started = time.perf_counter()
            current = self._timecode_and_rate()
            if current is None:
                return False
            parts, frame_rate = current
            if abs(frame_rate - round(frame_rate)) > 0.01:
                self.last_error = "TCP timecode is ambiguous for fractional frame rates"
                self._auto_retry_after = time.monotonic() + self.retry_seconds
                return False
            frames = int(delta_seconds) * nominal_fps(frame_rate)
            return self._move_from_snapshot(parts, frame_rate, frames, started)

    def describe(self):
        if self._last_probe_ok:
            latency = "" if self.last_latency_ms is None else f" ({self.last_latency_ms:.1f} ms)"
            return f"TCP 9060{latency}"
        return self.last_error or "TCP 9060 not connected"


class TimelineCommandRouter:
    """Select the fastest safe backend for each timeline mode."""

    def __init__(self, native_input=None, scripting=None, tcp=None, hotkey_fn=None):
        self.native = native_input or NativeTimelineInput()
        self.scripting = scripting or ResolveScriptingTransport()
        self.tcp = tcp or ResolveTcpTransport()
        self._hotkey_fn = hotkey_fn
        self.last_backend = "none"
        self.last_error = ""
        self._closed = False
        self._probe_lock = threading.Lock()
        self._tcp_probe_thread = None

    def warm_up(self):
        if self._closed:
            return False
        if IS_WINDOWS:
            if self._hotkey_fn is None:
                self.last_backend = "none"
                self.last_error = "Ulanzi host hotkey API is unavailable"
                return False
            self.last_backend = "ulanzi-hotkey"
            self.last_error = ""
            return True
        # TCP is the only documented programmatic transport with latency low
        # enough for interactive dial use. Discover it first; Scripting remains
        # available as an explicit backend and as a final automatic fallback.
        tcp_ok = self.tcp.probe()
        if self._closed:
            self.tcp.close()
            close_scripting = getattr(self.scripting, "close", None)
            if close_scripting:
                close_scripting()
            return False
        if tcp_ok:
            self.last_backend = "tcp"
            self.last_error = ""
            return True

        if self.native.available:
            self.last_backend = "keyboard"
            self.last_error = ""
            # Warm the scripting bridge in this already-background call so an
            # explicit Scripting selection does not pay cold-connect latency.
            self.scripting.probe()
            if self._closed:
                self.tcp.close()
                close_scripting = getattr(self.scripting, "close", None)
                if close_scripting:
                    close_scripting()
                return False
            return True

        scripting_ok = self.scripting.probe()
        if self._closed:
            self.tcp.close()
            close_scripting = getattr(self.scripting, "close", None)
            if close_scripting:
                close_scripting()
            return False
        if scripting_ok:
            self.last_backend = "scripting"
            return True
        self.last_backend = "none"
        self.last_error = self.scripting.last_error or self.tcp.last_error
        return False

    def is_resolve_running(self):
        return self.native.is_resolve_running()

    def execute(self, mode, ticks, settings):
        ticks = int(ticks)
        if not ticks:
            return True
        if settings.get("invert_direction"):
            ticks = -ticks

        if settings.get("require_resolve_focus", True) and not self.native.is_resolve_frontmost():
            self.last_backend = "blocked"
            self.last_error = "DaVinci Resolve is not the frontmost application"
            return False

        if IS_WINDOWS:
            return self._execute_windows_hotkey(mode, ticks, settings)

        if mode in VIEW_MODES:
            return self._execute_view(mode, ticks, settings)
        if mode in PLAYHEAD_MODES:
            return self._execute_playhead(mode, ticks, settings)
        self.last_error = f"Unknown timeline mode: {mode}"
        return False

    def _execute_windows_hotkey(self, mode, ticks, settings):
        shortcuts = WINDOWS_HOTKEYS.get(mode)
        if shortcuts is None:
            self.last_backend = "none"
            self.last_error = f"Unknown timeline mode: {mode}"
            return False
        if self._hotkey_fn is None:
            self.last_backend = "none"
            self.last_error = "Ulanzi host hotkey API is unavailable"
            return False

        signed_count = ticks
        if mode == "playhead_seconds":
            signed_count *= int(settings.get("seconds_per_tick", 1))
        repeat_count = min(256, abs(int(signed_count)))
        shortcut = shortcuts[1] if signed_count > 0 else shortcuts[0]

        try:
            # The scheduler may coalesce several detents into one batch. Send
            # one complete host-side hotkey for every effective step, without
            # pressing or releasing modifiers inside the plugin process.
            for _ in range(repeat_count):
                self._hotkey_fn(shortcut)
            self.last_backend = "ulanzi-hotkey"
            self.last_error = ""
            return True
        except Exception as exc:
            self.last_backend = "none"
            self.last_error = f"Ulanzi timeline hotkey failed: {exc}"
            return False

    def _ensure_tcp_probe_async(self):
        probe = getattr(self.tcp, "probe", None)
        if self._closed or not probe:
            return
        with self._probe_lock:
            if self._tcp_probe_thread and self._tcp_probe_thread.is_alive():
                return
            self._tcp_probe_thread = threading.Thread(
                target=self._tcp_probe_worker,
                name="davinci-timeline-tcp-probe",
                daemon=True,
            )
            self._tcp_probe_thread.start()

    def _tcp_probe_worker(self):
        try:
            self.tcp.probe()
        except Exception:
            pass
        if self._closed:
            self.tcp.close()

    def _execute_view(self, mode, ticks, settings):
        if self.native.scroll(mode, ticks, settings.get("scroll_sensitivity", 1.0)):
            self.last_backend = "native-wheel"
            self.last_error = ""
            return True

        fallback = False
        if mode == "timeline_zoom":
            fallback = self.native.zoom_with_shortcut(ticks)
        elif mode == "track_height":
            fallback = self.native.track_height_with_shortcut(ticks)
        if fallback:
            self.last_backend = "keyboard"
            self.last_error = ""
            return True

        self.last_backend = "none"
        self.last_error = self.native.last_error or f"No input fallback for {mode}"
        return False

    def _execute_playhead(self, mode, ticks, settings):
        seconds = ticks * int(settings.get("seconds_per_tick", 1))
        backend_setting = settings.get("backend", "auto")
        errors = []
        tcp_attempted = False

        if backend_setting == "auto" and not getattr(self.tcp, "is_ready", False):
            # Discovery never delays the physical detent currently being
            # handled. A successful background reconnect is used next time.
            self._ensure_tcp_probe_async()

        if backend_setting == "auto" and getattr(self.tcp, "is_ready", False):
            # Prefer the already-connected low-latency programming interface.
            # Do not synchronously open it here: the 80 ms connection timeout
            # would make the first physical detent feel sticky. warm_up() owns
            # discovery, while explicit TCP mode may connect on demand.
            tcp_attempted = True
            moved = (
                self.tcp.move_frames(ticks)
                if mode == "frame_step"
                else self.tcp.move_seconds(seconds)
            )
            if moved:
                self.last_backend = self.tcp.name
                self.last_error = ""
                return True
            errors.append(self.tcp.last_error)

        if backend_setting in ("auto", "keyboard"):
            # Live Resolve 20.3 measurements show native events are consumed in
            # about 20 ms after warm-up, while SetCurrentTimecode can block for
            # 65-500 ms. The input adapter adds the small spacing Resolve needs
            # to avoid dropping repeated synthetic key pairs.
            if self._keyboard_playhead(mode, ticks, seconds):
                return True
            if backend_setting == "keyboard":
                return False

        transports = []
        if backend_setting == "scripting":
            transports = [self.scripting]
        elif backend_setting == "tcp":
            transports = [self.tcp]
        else:
            # Scripting exposes the drop-frame separator and is exact for every rate.
            transports = []
            if not tcp_attempted:
                transports.append(self.tcp)
            transports.append(self.scripting)

        for transport in transports:
            if not transport.probe():
                errors.append(transport.last_error)
                continue
            moved = (
                transport.move_frames(ticks)
                if mode == "frame_step"
                else transport.move_seconds(seconds)
            )
            if moved:
                self.last_backend = transport.name
                self.last_error = ""
                return True
            errors.append(transport.last_error)

        if backend_setting == "auto":
            errors.append(self.native.last_error)

        self.last_backend = "none"
        self.last_error = next((error for error in errors if error), "No playhead backend available")
        return False

    def _keyboard_playhead(self, mode, ticks, seconds):
        moved = self.native.move_frames(ticks) if mode == "frame_step" else self.native.move_seconds(seconds)
        if moved:
            self.last_backend = "keyboard"
            self.last_error = ""
            return True
        self.last_backend = "none"
        self.last_error = self.native.last_error
        return False

    def status_payload(self, mode_title):
        if self.last_backend == "scripting":
            detail = self.scripting.describe()
        elif self.last_backend == "tcp":
            detail = self.tcp.describe()
        elif self.last_backend == "native-wheel":
            detail = "Native high-resolution wheel"
        elif self.last_backend == "ulanzi-hotkey":
            detail = "Ulanzi host hotkey"
        elif self.last_backend == "keyboard":
            detail = "Keyboard fallback"
        else:
            detail = self.last_error or "Backend will be selected on first rotation"
        level = "success" if self.last_backend not in ("none", "blocked") else "warn"
        return {
            "type": "timeline_status",
            "level": level,
            "mode": mode_title,
            "backend": self.last_backend,
            "detail": detail,
        }

    def close(self):
        self._closed = True
        if not IS_WINDOWS:
            self.native.release_all_modifiers()
        self.tcp.close()
        close_scripting = getattr(self.scripting, "close", None)
        if close_scripting:
            close_scripting()

    def suspend(self):
        if not IS_WINDOWS:
            self.native.release_all_modifiers()
        self.tcp.close()


__all__ = [
    "ResolveScriptingTransport",
    "ResolveTcpTransport",
    "TimelineCommandRouter",
    "VIEW_MODES",
    "PLAYHEAD_MODES",
    "WINDOWS_HOTKEYS",
]
