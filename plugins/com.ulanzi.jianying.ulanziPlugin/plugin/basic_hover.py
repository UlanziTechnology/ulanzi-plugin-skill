"""macOS hover recognition for Jianying sliders and color wheels."""

from copy import deepcopy
import json
import math
import os
from queue import Empty, Queue
import subprocess
import sys
from threading import Event, RLock, Thread
import time


BASIC_HOVER_KEYS = (
    "temperature",
    "tint",
    "saturation",
    "vibrance",
    "exposure",
    "brightness",
    "contrast",
    "highlights",
    "shadows",
    "whites",
    "blacks",
    "sharpen",
    "clarity",
    "fade",
    "vignette",
    "grain",
)
HSL_HOVER_KEYS = ("hue", "saturation", "luminance")
COLOR_WHEEL_HOVER_KEYS = (
    "intensity",
    "shadows",
    "midtones",
    "highlights",
    "global",
)
HOVER_KINDS = frozenset({"basic", "hsl", "color_wheels"})
# The adjustment inspector has two additional tabs without hover actions. Keep
# them as scan hints as well: a known Curve/Mask selection must prevent the
# recognizer from mistaking that panel for Basic, even when those kinds never
# produce Python hover targets.
ADJUSTMENT_TAB_KINDS = frozenset({
    "basic",
    "hsl",
    "curve",
    "color_wheels",
    "mask",
})
HOVER_KIND_NOT_VISIBLE = {
    "basic": "basic_parameters_not_visible",
    "hsl": "hsl_parameters_not_visible",
    "color_wheels": "color_wheels_not_visible",
}
ALL_HOVER_KEYS = frozenset(
    BASIC_HOVER_KEYS + HSL_HOVER_KEYS + COLOR_WHEEL_HOVER_KEYS
)
TRANSIENT_SCAN_REASONS = frozenset({
    "basic_parameters_not_visible",
    "hsl_parameters_not_visible",
    "color_wheels_not_visible",
    # The Windows native recognizer uses the generic kind + suffix form.
    # Keep the macOS reason above and retry either spelling without ever
    # exposing stale targets while an input-triggered refresh is pending.
    "color_wheels_parameters_not_visible",
    "active_tab_ambiguous",
    "vision_recognition_failed",
})
WHEEL_OVERLAY_CORNER_MARGIN = 7.0
WHEEL_OVERLAY_DOT_RADIUS = 8.0
# Keep a one-pixel anti-aliased seam: visually attached, without covering the ring.
WHEEL_OVERLAY_DOT_EDGE_GAP = 1.0
WHEEL_OVERLAY_EDGE_PADDING = 2.0


class BasicHoverService:
    """Cache Vision targets and expose only the row under the pointer."""

    scan_poll_interval_seconds = 0.05
    scan_retry_seconds = 0.25
    click_refresh_delay_seconds = 0.16
    # Match the proven DaVinci manual-wheel flow: wait briefly after mouse-up,
    # then reacquire the real white handle before rebuilding the visual dot.
    manual_release_refresh_delay_seconds = 0.08
    scroll_refresh_delay_seconds = 0.45
    max_refresh_attempts = 3
    scan_timeout_seconds = 6.0
    vision_warmup_timeout_seconds = 30.0
    hover_interval_seconds = 0.05
    active_interval_seconds = 0.5

    def __init__(
        self,
        helper_path,
        position_provider,
        target_active_provider,
        primary_button_down_provider=None,
        invalidation_callback=None,
        refresh_on_frontmost_return=False,
    ):
        self.helper_path = helper_path
        self.position_provider = position_provider
        self.target_active_provider = target_active_provider
        self.primary_button_down_provider = primary_button_down_provider
        self.invalidation_callback = invalidation_callback
        self.refresh_on_frontmost_return = bool(refresh_on_frontmost_return)
        self._lock = RLock()
        self._stop = Event()
        self._started = False
        self._targets = []
        self._basic_overlay_columns_cache = None
        self._basic_viewport_cache = None
        self._active_tab_hint = None
        self._active_tab_hint_source = None
        self._targets_scan_version = 0
        self._targets_updated_at = 0.0
        self._current = None
        self._active = False
        self._status = "not_started"
        self._screen_capture_available = None
        # Direct service users retain the historical all-kinds behavior.
        # The macOS backend narrows this set to the action kinds currently
        # present on the Deck before starting the service.
        self._enabled_kinds = HOVER_KINDS
        self._overlay_process = None
        self._persistent_scan_enabled = bool(
            os.name == "nt"
            and str(self.helper_path or "").lower().endswith(".exe")
        )
        # Overlay commands can originate from the hover loop, the native wheel
        # preview callback and the idle reacquire callback.  Serialize both the
        # payload decision and the write so an older frame can never land after
        # a newer one.
        self._overlay_lock = RLock()
        self._overlay_io_lock = RLock()
        self._scan_server_lock = RLock()
        self._scan_server_process = None
        self._scan_server_responses = None
        self._scan_server_request_id = 0
        self._overlay_signature = None
        self._color_wheel_feedback = {}
        self._color_wheel_angle_history = {}
        self._pinned_color_wheel_target = None
        self._refresh_requested = True
        self._refresh_reason = "initial"
        self._refresh_not_before = 0.0
        self._next_scan_at = 0.0
        self._refresh_attempts = 0
        self._refresh_generation = 0
        self._scan_in_progress = False
        self._vision_warmup_complete = False
        self._layout_change_pending = False
        self._pointer_input_pending = False

    def start(self):
        with self._lock:
            if self._started:
                return True
            if not os.path.isfile(self.helper_path) or not os.access(self.helper_path, os.X_OK):
                self._set_status("native_helper_unavailable")
                return False
            self._started = True
            stop_event = Event()
            self._stop = stop_event
            self._refresh_requested = True
            self._refresh_reason = "initial"
            self._refresh_not_before = 0.0
            self._next_scan_at = 0.0
            self._refresh_attempts = 0
            self._refresh_generation = 0
            self._basic_overlay_columns_cache = None
            self._clear_basic_viewport_locked("start")
            self._active_tab_hint = None
            self._active_tab_hint_source = None
            self._scan_in_progress = False
            self._vision_warmup_complete = False
            self._layout_change_pending = False
            self._pointer_input_pending = False
        try:
            active = bool(self.target_active_provider())
        except Exception:
            active = False
        with self._lock:
            self._active = active
        self._start_overlay()
        if self._persistent_scan_enabled:
            try:
                self._ensure_scan_server()
            except OSError as exc:
                # The scan loop retries lazily. Overlay/hover state remains
                # usable and no macOS code path reaches this branch.
                print(f"basic hover scan server: start_failed reason={exc}")
        Thread(
            target=self._scan_loop,
            args=(stop_event,),
            name="jianying-basic-vision",
            daemon=True,
        ).start()
        Thread(
            target=self._hover_loop,
            args=(stop_event,),
            name="jianying-basic-hover",
            daemon=True,
        ).start()
        return True

    def stop(self):
        with self._lock:
            if not self._started:
                return
            self._started = False
            self._stop.set()
            self._targets = []
            self._basic_overlay_columns_cache = None
            self._clear_basic_viewport_locked("stop")
            self._active_tab_hint = None
            self._active_tab_hint_source = None
            self._current = None
            self._color_wheel_feedback.clear()
            self._color_wheel_angle_history.clear()
            self._pinned_color_wheel_target = None
            self._refresh_requested = False
            self._scan_in_progress = False
            self._layout_change_pending = False
            self._pointer_input_pending = False
        self._notify_invalidation("service_stopped")
        self._hide_overlay()
        self._stop_scan_server()
        process = self._overlay_process
        self._overlay_process = None
        if process is not None:
            try:
                process.stdin.close()
            except (AttributeError, OSError):
                pass
            try:
                process.terminate()
            except OSError:
                pass

    @property
    def status(self):
        with self._lock:
            return self._status

    @property
    def screen_capture_available(self):
        with self._lock:
            return self._screen_capture_available

    @staticmethod
    def _target_kind(target):
        return str((target or {}).get("kind") or "basic")

    @staticmethod
    def _normalized_tab_hint(value):
        """Return the native adjustment-tab identifier, or None if unknown."""
        normalized = str(value or "").strip().lower().replace("-", "_")
        normalized = "_".join(normalized.split())
        normalized = {
            "colorwheel": "color_wheels",
            "color_wheel": "color_wheels",
            "adjust_mask": "mask",
        }.get(normalized, normalized)
        return normalized if normalized in ADJUSTMENT_TAB_KINDS else None

    def _clear_tab_hint_locked(self, reason):
        previous = self._active_tab_hint
        previous_source = self._active_tab_hint_source
        self._active_tab_hint = None
        self._active_tab_hint_source = None
        if previous is not None:
            print(
                "basic hover tab hint: action=clear "
                f"reason={str(reason or 'unknown')} previous={previous} "
                f"source={previous_source or 'unknown'}"
            )
        return previous is not None

    def _cache_tab_hint_locked(self, hint, source):
        hint = self._normalized_tab_hint(hint)
        if hint is None or hint == self._active_tab_hint:
            return False
        self._active_tab_hint = hint
        self._active_tab_hint_source = str(source or "unknown")
        print(
            "basic hover tab hint: action=cache "
            f"kind={hint} source={self._active_tab_hint_source}"
        )
        return True

    def _update_tab_hint_from_input(self, payload):
        """Consume optional native tab metadata without requiring new helpers."""
        if not isinstance(payload, dict):
            return False
        scope = str(payload.get("scope") or "").strip().lower()
        navigation = str(payload.get("navigation") or "").strip().lower()
        is_tab_navigation = bool(
            payload.get("tabNavigation") is True
            or payload.get("tabHit") is True
            or scope in {
                "adjustment_tab",
                "adjustment_tabs",
                "tab_navigation",
                "top_navigation",
            }
            or navigation in {"adjustment_tab", "adjustment_tabs"}
        )
        # Old overlay payloads have neither tabKind nor a navigation marker.
        # Leaving the hint untouched keeps that protocol backward compatible.
        if "tabKind" not in payload and not is_tab_navigation:
            return False

        hint = self._normalized_tab_hint(payload.get("tabKind"))
        with self._lock:
            if hint is None:
                return self._clear_tab_hint_locked("unknown_tab_navigation")
            return self._cache_tab_hint_locked(hint, "overlay_event")

    def _notify_invalidation(self, reason):
        callback = self.invalidation_callback
        if not callable(callback):
            return
        try:
            callback(str(reason or "hover_invalidated"))
        except Exception as exc:
            print(
                "basic hover invalidation callback ignored: "
                f"reason={reason} error={exc}"
            )

    def set_enabled_kinds(self, kinds):
        """Limit recognition and overlay output to instantiated action kinds."""
        enabled = frozenset(
            str(kind)
            for kind in (kinds or ())
            if str(kind) in HOVER_KINDS
        )
        with self._lock:
            if enabled == self._enabled_kinds:
                return False
            self._enabled_kinds = enabled
            self._targets = [
                target
                for target in self._targets
                if self._target_kind(target) in enabled
            ]
            current_allowed = bool(
                self._current
                and self._target_kind(self._current) in enabled
            )
            if not current_allowed:
                self._current = None
            if "color_wheels" not in enabled:
                self._pinned_color_wheel_target = None
                self._color_wheel_feedback.clear()
                self._color_wheel_angle_history.clear()
            if "basic" not in enabled:
                self._clear_basic_overlay_columns_locked(
                    "basic_kind_disabled"
                )
                self._clear_basic_viewport_locked("basic_kind_disabled")
            started = self._started
        self._hide_overlay()
        if started and enabled:
            self._request_refresh("enabled_kinds_changed", delay=0)
        return True

    def status_for(self, kind):
        kind = str(kind or "")
        with self._lock:
            status = self._status
            enabled = kind in self._enabled_kinds
            has_targets = any(
                self._target_kind(target) == kind
                for target in self._targets
            )
        if kind in HOVER_KIND_NOT_VISIBLE and (
            not enabled
            or (
                not has_targets
                and status in {
                    "ready",
                    "ready_cached",
                    "enabled_hover_targets_not_visible",
                } | TRANSIENT_SCAN_REASONS
            )
        ):
            return HOVER_KIND_NOT_VISIBLE[kind]
        return status

    def _filter_enabled_targets(self, targets):
        with self._lock:
            enabled = self._enabled_kinds
        return [
            target
            for target in (targets or [])
            if self._target_kind(target) in enabled
            and self._valid_wheel_geometry(target)
        ]

    def _scoped_scan_result(self, targets, reason):
        raw_targets = list(targets or [])
        filtered = self._filter_enabled_targets(raw_targets)
        reason = str(reason or "unknown")
        if raw_targets and not filtered and reason in {"ready", "ready_cached"}:
            with self._lock:
                enabled = self._enabled_kinds
            if len(enabled) == 1:
                reason = HOVER_KIND_NOT_VISIBLE[next(iter(enabled))]
            else:
                reason = "enabled_hover_targets_not_visible"
        return filtered, reason

    def current_target(self, kind=None):
        with self._lock:
            if kind and kind not in self._enabled_kinds:
                return None
            if not self._active or self._refresh_requested or not self._current:
                return None
            target = deepcopy(self._current)
            scan_version = self._targets_scan_version
            scan_age_ms = max(
                0,
                int(round((time.monotonic() - self._targets_updated_at) * 1000)),
            )
            enabled = self._enabled_kinds
        if self._target_kind(target) not in enabled:
            return None
        if not self._valid_wheel_geometry(target):
            return None
        if kind and target.get("kind", "basic") != kind:
            return None
        # This marker exists only on the ephemeral copy returned to an action.
        # Native input may use it for a cheap safety path because the hover
        # service has just rechecked active state, invalidation and pointer row.
        target["_validatedHover"] = True
        target["_scanAgeMs"] = scan_age_ms
        if target.get("kind") == "color_wheels":
            target["scanVersion"] = scan_version
        return target

    def pin_color_wheel_target(self, target_key):
        """Keep the active wheel selected while plugin-generated dragging moves the pointer."""
        target_key = str(target_key or "")
        with self._lock:
            if "color_wheels" not in self._enabled_kinds:
                return False
            current = deepcopy(self._current)
            if (
                not self._active
                or self._refresh_requested
                or not current
                or current.get("kind") != "color_wheels"
                or current.get("controlType") != "wheel"
                or str(current.get("key") or "") != target_key
                or not self._valid_wheel_geometry(current)
            ):
                return False
            self._pinned_color_wheel_target = deepcopy(current)
        self._show_overlay(current, quiet=True)
        print(f"basic hover target: pinned key={target_key}")
        return True

    def release_color_wheel_target(self, target_key=None):
        """Resume pointer-based hover detection after the drag pointer is restored."""
        expected_key = str(target_key or "")
        with self._lock:
            pinned = self._pinned_color_wheel_target
            if not pinned:
                return False
            pinned_key = str(pinned.get("key") or "")
            if expected_key and pinned_key != expected_key:
                return False
            self._pinned_color_wheel_target = None
        print(f"basic hover target: released key={pinned_key}")
        return True

    def _set_status(self, value):
        value = str(value or "unknown")
        with self._lock:
            if value == self._status:
                return
            self._status = value
        print(f"basic hover status: {value}")

    @staticmethod
    def _creationflags():
        return (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if os.name == "nt" else 0
        )

    def _start_scan_server_locked(self):
        process = subprocess.Popen(
            [self.helper_path, "scan-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=self._creationflags(),
        )
        responses = Queue()
        self._scan_server_process = process
        self._scan_server_responses = responses
        Thread(
            target=self._read_scan_server_output,
            args=(process, responses),
            name="jianying-basic-scan-server-log",
            daemon=True,
        ).start()
        print(f"basic hover scan server: started pid={process.pid}")
        return process, responses

    def _ensure_scan_server(self):
        if not self._persistent_scan_enabled:
            raise OSError("persistent_scan_server_not_enabled")
        with self._scan_server_lock:
            process = self._scan_server_process
            responses = self._scan_server_responses
            if (
                process is not None
                and process.poll() is None
                and process.stdin is not None
                and responses is not None
            ):
                return process, responses
            return self._start_scan_server_locked()

    @staticmethod
    def _read_scan_server_output(process, responses):
        stream = process.stdout
        if stream is None:
            responses.put(None)
            return
        try:
            for line in stream:
                responses.put(line)
        except (OSError, ValueError):
            pass
        finally:
            responses.put(None)

    def _discard_scan_server(self, expected_process=None, restart=False):
        process = None
        with self._scan_server_lock:
            current = self._scan_server_process
            if expected_process is not None and current is not expected_process:
                return
            process = current
            self._scan_server_process = None
            self._scan_server_responses = None
        if process is not None:
            try:
                if process.stdin is not None:
                    process.stdin.close()
            except (OSError, ValueError):
                pass
            if process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass
            try:
                process.wait(timeout=0.5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
        if restart and self._persistent_scan_enabled:
            try:
                self._ensure_scan_server()
            except OSError as exc:
                print(f"basic hover scan server: restart_failed reason={exc}")

    def _stop_scan_server(self):
        self._discard_scan_server()

    def _scan_via_server(self, timeout=6.0, tab_hint=None):
        tab_hint = self._normalized_tab_hint(tab_hint)
        last_error = None
        for attempt in range(2):
            process, responses = self._ensure_scan_server()
            with self._scan_server_lock:
                if self._scan_server_process is not process:
                    last_error = OSError("scan_server_replaced")
                    continue
                self._scan_server_request_id += 1
                request_id = self._scan_server_request_id
                try:
                    request = {
                        "command": "scan",
                        "requestId": request_id,
                    }
                    if tab_hint is not None:
                        request["tabHint"] = tab_hint
                    process.stdin.write(json.dumps(request) + "\n")
                    process.stdin.flush()
                except (AttributeError, BrokenPipeError, OSError, ValueError) as exc:
                    last_error = OSError(f"scan_server_write_failed:{exc}")
                    self._discard_scan_server(process)
                    continue

            deadline = time.monotonic() + max(0.1, float(timeout))
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise Empty()
                    line = responses.get(timeout=remaining)
                    if line is None:
                        raise OSError("scan_server_exited")
                    try:
                        payload = json.loads(str(line).strip())
                    except (TypeError, json.JSONDecodeError):
                        print(f"basic hover scan server: output={str(line).strip()[:180]}")
                        continue
                    if not isinstance(payload, dict):
                        continue
                    if payload.get("requestId") != request_id:
                        print(
                            "basic hover scan server: ignored_response "
                            f"request={payload.get('requestId')} expected={request_id}"
                        )
                        continue
                    return payload
            except Empty:
                self._discard_scan_server(process, restart=True)
                raise subprocess.TimeoutExpired(
                    [self.helper_path, "scan-server"], timeout
                )
            except OSError as exc:
                last_error = exc
                self._discard_scan_server(process)
                if attempt == 0:
                    continue
        raise last_error or OSError("scan_server_unavailable")

    def _start_overlay(self):
        try:
            process = subprocess.Popen(
                [self.helper_path, "overlay"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=self._creationflags(),
            )
        except OSError as exc:
            self._overlay_process = None
            self._set_status(f"overlay_start_failed:{exc}")
            return
        self._overlay_process = process
        print(f"basic hover overlay: started pid={process.pid}")
        Thread(
            target=self._read_overlay_output,
            args=(process,),
            name="jianying-basic-overlay-log",
            daemon=True,
        ).start()

    def _read_overlay_output(self, process):
        stream = process.stdout
        if stream is None:
            return
        try:
            for line in stream:
                self._handle_overlay_line(line)
        except (OSError, ValueError) as exc:
            print(f"basic hover overlay: output_failed reason={exc}")
        finally:
            return_code = process.poll()
            with self._lock:
                unexpected = self._started and self._overlay_process is process
            if unexpected:
                print(f"basic hover overlay: exited code={return_code}")

    def _handle_overlay_line(self, line):
        line = str(line or "").strip()
        if not line:
            return
        try:
            payload = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            print(f"basic hover overlay: output={line[:180]}")
            return
        event = str(payload.get("event") or "unknown")
        if event == "shown":
            rect = payload.get("rect") or {}
            try:
                detail = " ".join(
                    f"{key}={round(float(rect[key]), 1)}"
                    for key in ("x", "y", "w", "h")
                )
            except (KeyError, TypeError, ValueError):
                detail = "rect=invalid"
            render_mode = str(payload.get("renderMode") or "unknown")
            visible = bool(payload.get("visible"))
            hwnd = str(payload.get("hwnd") or "")
            native_state = ""
            if "topmost" in payload or "extendedStyle" in payload:
                native_state = (
                    f" topmost={bool(payload.get('topmost'))}"
                    f" exStyle={str(payload.get('extendedStyle') or 'unknown')}"
                )
            print(f"basic hover overlay: shown {detail}")
            print(
                "basic hover overlay state: "
                f"mode={render_mode} visible={visible} hwnd={hwnd}{native_state}"
            )
        elif event == "hidden":
            print("basic hover overlay: hidden")
        elif event == "error":
            reason = str(payload.get("reason") or "unknown")
            with self._overlay_lock:
                self._overlay_signature = None
            print(f"basic hover overlay: error reason={reason}")
        elif event == "input":
            kind = str(payload.get("kind") or "unknown")
            if kind not in {"click", "release", "scroll"}:
                print(f"basic hover input: ignored kind={kind}")
                return
            # The native helper only emits input while Jianying is frontmost,
            # and only for the right-side inspector. Continuous trackpad events
            # extend the quiet period instead of starting one scan per event.
            with self._lock:
                self._active = True
                layout_change_pending = self._layout_change_pending
                if kind == "click":
                    self._clear_basic_viewport_locked("input_click")
                if layout_change_pending and kind == "click":
                    # A tab click can arrive while native resize/scroll
                    # coalescing is waiting for its stable edge. Preserve the
                    # explicit tab identity for that eventual scan even though
                    # the input itself remains deferred.
                    pending_tab_hint = self._normalized_tab_hint(
                        payload.get("tabKind")
                    )
                    if pending_tab_hint is not None:
                        self._cache_tab_hint_locked(
                            pending_tab_hint,
                            "overlay_event_layout_pending",
                        )
            if layout_change_pending:
                self._hide_overlay()
                print(f"basic hover input: deferred kind={kind} reason=layout_change_pending")
                return
            wait_for_release = False
            if kind == "click" and self._persistent_scan_enabled:
                # The native protocol also reports right/middle clicks. Only a
                # real left-button hold can become a wheel drag that needs the
                # mouse-up transaction. New helpers provide the authoritative
                # button name; the async key state is only for old helpers that
                # emitted the historical button-less `click` payload.
                button = payload.get("button")
                if button is not None:
                    wait_for_release = str(button).strip().lower() == "left"
                else:
                    provider = self.primary_button_down_provider
                    if provider is None:
                        wait_for_release = True
                    else:
                        try:
                            wait_for_release = bool(provider())
                        except Exception:
                            wait_for_release = True
            if wait_for_release:
                # The Windows low-level hook reports the initial button-down.
                # Invalidate the old handle immediately, but never capture the
                # wheel while the user is still dragging it. A matching native
                # `release` edge schedules the one authoritative rescan.
                started = self._begin_pointer_input()
                # Invalidate the in-flight scan generation before publishing
                # the tab hint. Otherwise an older scan can land between the
                # two operations and overwrite the user's newer tab click.
                self._update_tab_hint_from_input(payload)
                self._hide_overlay()
                if started:
                    self._notify_invalidation("input_click_pending")
                    print("basic hover cache: invalidated reason=input_click_pending")
                return
            if kind == "release":
                requested = self._finish_pointer_input()
                self._hide_overlay()
                if requested:
                    print("basic hover cache: refresh requested reason=input_release")
                else:
                    print("basic hover input: ignored kind=release reason=no_pending_click")
                return
            if kind == "click":
                with self._lock:
                    self._clear_basic_overlay_columns_locked("input_click")
                    self._clear_basic_viewport_locked("input_click")
            delay = (
                self.scroll_refresh_delay_seconds
                if kind == "scroll"
                else self.click_refresh_delay_seconds
            )
            requested = self._request_refresh(
                f"input_{kind}",
                delay=delay,
            )
            if kind == "click":
                # New macOS helpers attach a canonical tabKind only when the
                # click lands on the five AX adjustment tabs. Missing metadata
                # from an older helper is deliberately a no-op. The refresh
                # generation is advanced first so stale scan results cannot
                # win this transaction.
                self._update_tab_hint_from_input(payload)
            self._hide_overlay()
            if requested:
                self._notify_invalidation(f"input_{kind}")
                print(f"basic hover cache: refresh requested reason=input_{kind}")
        elif event == "layout_change":
            phase = str(payload.get("phase") or "unknown")
            with self._lock:
                self._active = True
            if phase == "pending":
                started = self._begin_layout_change()
                self._hide_overlay()
                if started:
                    self._notify_invalidation("layout_change_pending")
                    print("basic hover cache: invalidated reason=layout_change_pending")
            elif phase == "stable":
                with self._lock:
                    was_pending = self._layout_change_pending
                    self._layout_change_pending = False
                if not was_pending:
                    print("basic hover layout: ignored phase=stable reason=no_pending_change")
                    return
                requested = self._request_refresh("layout_change", delay=0)
                self._hide_overlay()
                if requested:
                    print("basic hover cache: refresh requested reason=layout_change")
            else:
                print(f"basic hover layout: ignored phase={phase}")
        elif event == "monitor":
            status = str(payload.get("status") or "unknown")
            if status == "ready":
                # The native form must begin hidden. Send a defensive hide
                # after its UI handle and message loop are ready as well, and
                # invalidate any optimistic signature so a legitimate hover
                # can immediately show itself again on the next loop.
                with self._overlay_lock:
                    self._overlay_signature = None
                    if self._send_overlay({"command": "hide"}):
                        print("basic hover overlay: initial hide sent")
            print(f"basic hover input monitor: {status}")
        else:
            print(f"basic hover overlay: event={event}")

    def _begin_layout_change(self):
        """Invalidate stale geometry without scanning until the layout settles."""
        now = time.monotonic()
        with self._lock:
            if self._layout_change_pending:
                return False
            self._layout_change_pending = True
            self._refresh_generation += 1
            self._refresh_requested = False
            self._refresh_reason = "layout_change_pending"
            self._refresh_not_before = now
            self._next_scan_at = now
            self._refresh_attempts = 0
            self._targets = []
            self._clear_basic_overlay_columns_locked("layout_change_pending")
            self._clear_basic_viewport_locked("layout_change_pending")
            self._clear_tab_hint_locked("layout_change_pending")
            self._current = None
            self._pinned_color_wheel_target = None
            self._color_wheel_feedback.clear()
            self._pointer_input_pending = False
        return True

    def _begin_frontmost_refresh(self):
        """Drop background-era geometry before scanning the active Jianying tab."""
        now = time.monotonic()
        with self._lock:
            self._refresh_generation += 1
            self._refresh_requested = True
            self._refresh_reason = "frontmost"
            self._refresh_not_before = now
            self._next_scan_at = now
            self._refresh_attempts = 0
            # A click that both activates Jianying and switches an inspector
            # tab occurs before Jianying becomes foreground, so the native
            # foreground-gated hook intentionally cannot report it. Never
            # reuse Basic/HSL/Color Wheels coordinates across that boundary.
            self._targets = []
            self._targets_updated_at = 0.0
            self._clear_basic_overlay_columns_locked("frontmost")
            self._clear_basic_viewport_locked("frontmost")
            self._clear_tab_hint_locked("frontmost")
            self._current = None
            self._pinned_color_wheel_target = None
            self._color_wheel_feedback.clear()
            self._color_wheel_angle_history.clear()
            self._pointer_input_pending = False
        return True

    def _begin_pointer_input(self):
        """Invalidate visual feedback at Windows mouse-down without scanning mid-drag."""
        now = time.monotonic()
        with self._lock:
            started = not self._pointer_input_pending
            self._pointer_input_pending = True
            self._refresh_generation += 1
            self._refresh_requested = True
            self._refresh_reason = "input_click_pending"
            self._refresh_not_before = now
            self._next_scan_at = now
            self._refresh_attempts = 0
            self._clear_basic_overlay_columns_locked("input_click_pending")
            self._clear_basic_viewport_locked("input_click_pending")
            self._current = None
            self._pinned_color_wheel_target = None
            self._color_wheel_feedback.clear()
            # A fresh screen handle is authoritative after manual input. Do
            # not let near-center angle smoothing reuse the pre-drag angle.
            self._color_wheel_angle_history.clear()
        return started

    def _finish_pointer_input(self):
        """Schedule one settled scan after a native Windows mouse-up edge."""
        now = time.monotonic()
        with self._lock:
            if not self._pointer_input_pending:
                return False
            self._pointer_input_pending = False
            self._refresh_generation += 1
            self._refresh_requested = True
            self._refresh_reason = "input_release"
            self._refresh_not_before = (
                now + self.manual_release_refresh_delay_seconds
            )
            self._next_scan_at = now
            self._refresh_attempts = 0
            self._current = None
            self._pinned_color_wheel_target = None
            self._color_wheel_feedback.clear()
            self._color_wheel_angle_history.clear()
        return True

    def _cancel_pointer_input_for_inactive_target(self):
        """Release a lost mouse transaction and force a scan on next activation."""
        now = time.monotonic()
        with self._lock:
            if not self._pointer_input_pending:
                return False
            self._pointer_input_pending = False
            self._refresh_generation += 1
            self._refresh_requested = True
            self._refresh_reason = "pointer_input_interrupted"
            self._refresh_not_before = now
            self._next_scan_at = now
            self._refresh_attempts = 0
            self._current = None
            self._pinned_color_wheel_target = None
            self._color_wheel_feedback.clear()
            self._color_wheel_angle_history.clear()
        return True

    def _request_refresh(self, reason, delay=0.0):
        now = time.monotonic()
        try:
            delay = max(0.0, float(delay))
        except (TypeError, ValueError):
            delay = 0.0
        reason = str(reason or "requested")
        with self._lock:
            changed = not self._refresh_requested or self._refresh_reason != reason
            self._refresh_generation += 1
            self._refresh_requested = True
            self._refresh_reason = reason
            self._refresh_attempts = 0
            self._current = None
            self._pinned_color_wheel_target = None
            self._color_wheel_feedback.clear()
            if delay <= 0:
                self._refresh_not_before = now
                self._next_scan_at = min(self._next_scan_at, now)
            else:
                self._refresh_not_before = max(
                    self._refresh_not_before,
                    now + delay,
                )
        return changed

    def _scan_due(self, now=None):
        now = time.monotonic() if now is None else float(now)
        with self._lock:
            return bool(
                self._active
                and self._refresh_requested
                and not self._layout_change_pending
                and not self._pointer_input_pending
                and not self._scan_in_progress
                and now >= self._refresh_not_before
                and now >= self._next_scan_at
            )

    def _send_overlay(self, payload):
        with self._overlay_io_lock:
            process = self._overlay_process
            if process is None or process.poll() is not None or process.stdin is None:
                print("basic hover overlay: command_failed reason=process_unavailable")
                return False
            try:
                process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                process.stdin.flush()
                return True
            except (BrokenPipeError, OSError) as exc:
                print(f"basic hover overlay: command_failed reason={exc}")
                return False

    def _hide_overlay(self):
        with self._overlay_lock:
            if self._overlay_signature is None:
                return
            self._overlay_signature = None
            self._send_overlay({"command": "hide"})

    @staticmethod
    def _wheel_geometry_signature(target):
        try:
            return (
                str(target.get("key") or target.get("targetKey") or ""),
                round(float(target.get("centerX")), 1),
                round(float(target.get("centerY")), 1),
                round(float(target.get("wheelRadius")), 1),
                int(float(target.get("scanVersion", 0))),
            )
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _wheel_feedback_order(state):
        """Return a logical request/phase order for asynchronous wheel state."""
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

    @staticmethod
    def _wheel_angle(source, fallback=-math.pi / 2):
        source = source or {}
        try:
            if source.get("angle") is not None:
                return float(source["angle"])
            center_x = float(source.get("centerX"))
            center_y = float(source.get("centerY"))
            handle_x = float(source.get("handleX"))
            handle_y = float(source.get("handleY"))
        except (AttributeError, TypeError, ValueError):
            return float(fallback)
        dx = handle_x - center_x
        dy = handle_y - center_y
        return math.atan2(dy, dx) if math.hypot(dx, dy) >= 1.5 else float(fallback)

    def _stable_wheel_angle(self, target, feedback=None):
        """Suppress large angle errors when a tiny handle vector is noisy."""
        angle = self._wheel_angle(feedback or target)
        try:
            key = str(target.get("key") or "")
            center_x = float(target.get("centerX"))
            center_y = float(target.get("centerY"))
            wheel_radius = max(12.0, float(target.get("wheelRadius")))
            handle_x = float(target.get("handleX"))
            handle_y = float(target.get("handleY"))
        except (AttributeError, TypeError, ValueError):
            return angle
        if not key:
            return angle

        with self._lock:
            previous = deepcopy(self._color_wheel_angle_history.get(key))
        if feedback is not None:
            with self._lock:
                self._color_wheel_angle_history[key] = {
                    "centerX": center_x,
                    "centerY": center_y,
                    "wheelRadius": wheel_radius,
                    "angle": angle,
                }
            return angle

        handle_radius = math.hypot(handle_x - center_x, handle_y - center_y)
        dead_radius = max(2.5, wheel_radius * 0.05)
        reliable_radius = max(5.0, wheel_radius * 0.10)
        previous_compatible = bool(
            previous
            and abs(float(previous.get("centerX")) - center_x)
                <= max(4.0, wheel_radius * 0.08)
            and abs(float(previous.get("centerY")) - center_y)
                <= max(4.0, wheel_radius * 0.08)
            and abs(float(previous.get("wheelRadius")) - wheel_radius) <= 4.0
        )
        if not previous_compatible:
            if handle_radius >= reliable_radius:
                with self._lock:
                    self._color_wheel_angle_history[key] = {
                        "centerX": center_x,
                        "centerY": center_y,
                        "wheelRadius": wheel_radius,
                        "angle": angle,
                    }
            return angle

        previous_angle = float(previous["angle"])
        if handle_radius <= dead_radius:
            return previous_angle
        if handle_radius >= reliable_radius:
            with self._lock:
                self._color_wheel_angle_history[key] = {
                    "centerX": center_x,
                    "centerY": center_y,
                    "wheelRadius": wheel_radius,
                    "angle": angle,
                }
            return angle
        blend = (handle_radius - dead_radius) / (reliable_radius - dead_radius)
        delta = math.atan2(
            math.sin(angle - previous_angle),
            math.cos(angle - previous_angle),
        )
        return previous_angle + delta * blend

    @staticmethod
    def _wheel_dot_color(target, angle):
        palette = (target or {}).get("huePalette")
        if not isinstance(palette, list) or len(palette) < 3:
            return None

        def rgb(value):
            value = str(value or "").strip().lstrip("#")
            if len(value) != 6:
                return None
            try:
                return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))
            except ValueError:
                return None

        try:
            position = (float(angle) % (math.pi * 2)) / (math.pi * 2) * len(palette)
        except (TypeError, ValueError):
            return None
        lower_index = int(math.floor(position)) % len(palette)
        upper_index = (lower_index + 1) % len(palette)
        lower = rgb(palette[lower_index])
        upper = rgb(palette[upper_index])
        if lower is None or upper is None:
            return None
        blend = position - math.floor(position)
        channels = tuple(
            max(0, min(255, round(start + (end - start) * blend)))
            for start, end in zip(lower, upper)
        )
        return "#{:02x}{:02x}{:02x}".format(*channels)

    def _wheel_overlay_payload(self, target):
        try:
            center_x = float(target.get("centerX"))
            center_y = float(target.get("centerY"))
            wheel_radius = max(
                12.0,
                float(target.get("wheelVisualRadius", target.get("wheelRadius"))),
            )
            dpi_scale = max(1.0, float(target.get("dpi", 96.0)) / 96.0)
        except (AttributeError, TypeError, ValueError):
            return None

        target_signature = self._wheel_geometry_signature(target)
        with self._lock:
            feedback = deepcopy(self._color_wheel_feedback.get(target_signature))
        angle = self._stable_wheel_angle(target, feedback)
        dot_radius = WHEEL_OVERLAY_DOT_RADIUS * dpi_scale
        dot_edge_gap = WHEEL_OVERLAY_DOT_EDGE_GAP * dpi_scale
        edge_padding = WHEEL_OVERLAY_EDGE_PADDING * dpi_scale
        corner_margin = WHEEL_OVERLAY_CORNER_MARGIN * dpi_scale
        dot_distance = (
            wheel_radius
            + dot_radius
            + dot_edge_gap
        )
        extent = (
            dot_distance
            + dot_radius
            + edge_padding
        )
        payload = {
            "command": "show",
            "style": "wheel",
            "x": center_x - extent,
            "y": center_y - extent,
            "w": extent * 2,
            "h": extent * 2,
            "wheelCenterX": center_x,
            "wheelCenterY": center_y,
            "wheelRadius": wheel_radius,
            "cornerMargin": corner_margin,
            "dotAngle": angle,
            "dotDistance": dot_distance,
            "dotRadius": dot_radius,
            "dotVisible": bool(feedback or target.get("handleDetected") is True),
        }
        dot_color = self._wheel_dot_color(target, angle)
        if dot_color is not None:
            payload["dotColor"] = dot_color
        return payload

    def update_color_wheel_feedback(self, target_key, state):
        """Move the outer dot from gesture state without running recognition."""
        if not isinstance(state, dict):
            return False
        feedback = deepcopy(state)
        feedback["key"] = str(target_key or feedback.get("key") or "")
        signature = feedback.get("signature")
        if isinstance(signature, list):
            signature = tuple(signature)
        if signature is None:
            signature = self._wheel_geometry_signature(feedback)
        feedback["signature"] = signature
        with self._lock:
            current = deepcopy(self._current)
            matching_target = next((
                target
                for target in self._targets
                if target.get("kind") == "color_wheels"
                and target.get("controlType") == "wheel"
                and str(target.get("key") or "") == feedback["key"]
                and self._wheel_geometry_signature(target) == signature
            ), None)
            if matching_target is None:
                return False
            existing = self._color_wheel_feedback.get(signature)
            existing_order = self._wheel_feedback_order(existing)
            incoming_order = self._wheel_feedback_order(feedback)
            if (
                existing_order is not None
                and incoming_order is not None
                and incoming_order < existing_order
            ):
                print(
                    "basic hover wheel feedback: ignored stale state "
                    f"key={feedback['key']} incoming={incoming_order} "
                    f"current={existing_order}"
                )
                return False
            self._color_wheel_feedback[signature] = feedback
            current_matches = bool(
                current
                and current.get("kind") == "color_wheels"
                and current.get("controlType") == "wheel"
                and str(current.get("key") or "") == feedback["key"]
                and self._wheel_geometry_signature(current) == signature
            )
        if current_matches:
            self._show_overlay(current, quiet=True)
        return True

    def clear_color_wheel_feedback(self, target_key, signature=None):
        """Discard a temporary wheel preview when native validation fails."""
        target_key = str(target_key or "")
        if isinstance(signature, list):
            signature = tuple(signature)
        removed = False
        with self._lock:
            current = deepcopy(self._current)
            for feedback_signature, feedback in list(
                self._color_wheel_feedback.items()
            ):
                if (
                    str((feedback or {}).get("key") or "") == target_key
                    and (
                        signature is None
                        or feedback_signature == signature
                    )
                ):
                    del self._color_wheel_feedback[feedback_signature]
                    removed = True
            current_matches = bool(
                removed
                and current
                and current.get("kind") == "color_wheels"
                and current.get("controlType") == "wheel"
                and str(current.get("key") or "") == target_key
                and (
                    signature is None
                    or self._wheel_geometry_signature(current) == signature
                )
            )
        if current_matches:
            self._show_overlay(current, quiet=True)
        return removed

    def _show_overlay(self, target, quiet=False):
        with self._overlay_lock:
            with self._lock:
                enabled = self._target_kind(target) in self._enabled_kinds
                is_wheel = (
                    target.get("kind") == "color_wheels"
                    and target.get("controlType") == "wheel"
                )
                if is_wheel:
                    # Feedback and pinned targets also reach this final
                    # display path. Never revive their frame during a rescan.
                    enabled = (
                        enabled
                        and self._active
                        and not self._refresh_requested
                        and self._valid_wheel_geometry(target)
                    )
            if not enabled:
                self._hide_overlay()
                return
            if is_wheel:
                payload = self._wheel_overlay_payload(target)
                if payload is None:
                    self._hide_overlay()
                    return
                signature = tuple(
                    round(float(payload[key]), 4)
                    for key in (
                        "x", "y", "w", "h", "wheelCenterX", "wheelCenterY",
                        "wheelRadius", "dotAngle", "dotDistance", "dotRadius",
                    )
                ) + (
                    "wheel",
                    bool(payload["dotVisible"]),
                    str(payload.get("dotColor") or ""),
                )
                if signature == self._overlay_signature:
                    return
                if quiet:
                    payload["quiet"] = True
                sent = self._send_overlay(payload)
                self._overlay_signature = signature if sent else None
                return

            rect = target.get("overlayRect") or target.get("hoverRect") or {}
            try:
                signature = tuple(
                    round(float(rect[key]), 1) for key in ("x", "y", "w", "h")
                )
            except (KeyError, TypeError, ValueError):
                self._hide_overlay()
                return
            if signature == self._overlay_signature:
                return
            sent = self._send_overlay({
                "command": "show",
                "x": signature[0],
                "y": signature[1],
                "w": signature[2],
                "h": signature[3],
            })
            self._overlay_signature = signature if sent else None

    @staticmethod
    def _valid_wheel_geometry(target):
        if not isinstance(target, dict):
            return False
        if (
            target.get("kind") != "color_wheels"
            or target.get("controlType") != "wheel"
        ):
            return True
        source = str(target.get("geometrySource") or "")
        if (
            "layout_fallback" in source
            or target.get("geometryVerified") is False
            or target.get("wheelFullyVisible") is False
        ):
            return False
        try:
            component_pixels = int(target.get("geometryComponentPixels") or 0)
            coordinates = [float(target[key]) for key in ("centerX", "centerY")]
            radius = float(target["wheelRadius"])
            visual_radius = float(target.get("wheelVisualRadius", radius))
        except (KeyError, TypeError, ValueError, OverflowError):
            return False
        # Older macOS helpers and Windows provide pixel provenance without a
        # full-visibility flag. Explicit rejection always wins over that proof.
        verified = target.get("geometryVerified") is True or bool(
            source and component_pixels > 0
        )
        return (
            verified
            and all(math.isfinite(value) and abs(value) < 100000 for value in coordinates)
            and math.isfinite(radius)
            and math.isfinite(visual_radius)
            and 0 < radius < 100000
            and 0 < visual_radius < 100000
        )

    @staticmethod
    def _valid_target(target):
        if not isinstance(target, dict) or target.get("key") not in ALL_HOVER_KEYS:
            return False
        if not BasicHoverService._valid_wheel_geometry(target):
            return False
        hover_rect = target.get("hoverRect")
        overlay_rect = target.get("overlayRect") or hover_rect
        if not isinstance(hover_rect, dict) or not isinstance(overlay_rect, dict):
            return False
        try:
            numbers = [float(target[name]) for name in ("x", "y")]
            if target.get("resetAvailable") is not False:
                numbers.extend(float(target[name]) for name in ("resetX", "resetY"))
            numbers.extend(float(hover_rect[name]) for name in ("x", "y", "w", "h"))
            numbers.extend(float(overlay_rect[name]) for name in ("x", "y", "w", "h"))
        except (KeyError, TypeError, ValueError):
            return False
        return (
            all(abs(number) < 100000 for number in numbers)
            and float(hover_rect["w"]) > 0
            and float(hover_rect["h"]) > 0
            and float(overlay_rect["w"]) > 0
            and float(overlay_rect["h"]) > 0
        )

    @staticmethod
    def _basic_columns_layout_key(scan_context):
        if not isinstance(scan_context, dict):
            return None
        layout = scan_context.get("layout")
        window = scan_context.get("window")
        if not isinstance(layout, dict) or not isinstance(window, dict):
            return None
        inspector = layout.get("inspectorBounds")
        if not isinstance(inspector, dict):
            return None

        def rect_signature(rect):
            try:
                return tuple(
                    round(float(rect[name]), 1)
                    for name in ("x", "y", "w", "h")
                )
            except (KeyError, TypeError, ValueError):
                return None

        window_signature = rect_signature(window)
        inspector_signature = rect_signature(inspector)
        if window_signature is None or inspector_signature is None:
            return None
        return (
            "basic",
            str(scan_context.get("recognition") or "unknown"),
            str(layout.get("source") or "unknown"),
            window_signature,
            inspector_signature,
        )

    @staticmethod
    def _observed_basic_overlay_columns(targets, scan_context):
        kinds = {
            str((target or {}).get("kind") or "basic")
            for target in (targets or [])
        }
        if kinds != {"basic"}:
            return None, "not_basic_only"
        if str((scan_context or {}).get("recognition") or "") != "accessibility":
            return None, "not_accessibility"
        layout = (scan_context or {}).get("layout") or {}
        inspector = layout.get("inspectorBounds") or {}
        window = (scan_context or {}).get("window") or {}
        try:
            inspector_left = float(inspector["x"])
            inspector_width = float(inspector["w"])
            inspector_right = inspector_left + inspector_width
            window_right = float(window["x"]) + float(window["w"])
        except (KeyError, TypeError, ValueError):
            return None, "layout_unavailable"

        columns = []
        for target in targets:
            rect = target.get("overlayRect") or {}
            try:
                columns.append((float(rect["x"]), float(rect["w"])))
            except (KeyError, TypeError, ValueError):
                return None, "overlay_unavailable"
        if len(columns) < 2:
            return None, "insufficient_rows"
        lefts = sorted(value[0] for value in columns)
        widths = sorted(value[1] for value in columns)
        if lefts[-1] - lefts[0] > 2 or widths[-1] - widths[0] > 2:
            return None, "columns_not_shared"
        middle = len(columns) // 2
        left = lefts[middle]
        width = widths[middle]
        right = left + width
        canonical_right = window_right - 138.0
        minimum_width = max(96.0, inspector_width * 0.35)
        # The label column does not grow with a wide inspector, so a fixed
        # percentage cap rejects valid 846pt/1242pt layouts.  Reserve a small
        # responsive leading gutter instead, then cap the canonical span at a
        # conservative absolute width.  The endpoint check below remains the
        # primary guard against the historical 558pt long frame.
        minimum_left_inset = min(
            20.0,
            max(12.0, inspector_width * 0.02),
        )
        maximum_width = min(
            1120.0,
            max(
                0.0,
                canonical_right
                - (inspector_left + minimum_left_inset)
                + 12.0,
            ),
        )
        if (
            width < minimum_width
            or width > maximum_width
            or left < inspector_left + minimum_left_inset
            or right > inspector_right + 1
        ):
            return None, "columns_out_of_bounds"

        # Accessibility normalization intentionally anchors the value-side
        # corner near the window's canonical 138pt inset. The two bad scans in
        # the supplied video ended 421pt short and 27pt long, respectively.
        if abs(right - canonical_right) > 12.0:
            return None, "right_endpoint_untrusted"
        return {
            "x": left,
            "w": width,
            "source": str(
                (scan_context or {}).get("parameterOverlaySource")
                or "unknown"
            ),
        }, "trusted"

    @staticmethod
    def _basic_targets_inside_inspector(targets, scan_context):
        if str((scan_context or {}).get("recognition") or "") != "accessibility":
            return list(targets or []), 0
        layout = (scan_context or {}).get("layout") or {}
        inspector = layout.get("inspectorBounds") or {}
        try:
            inspector_top = float(inspector["y"])
            inspector_bottom = inspector_top + float(inspector["h"])
        except (KeyError, TypeError, ValueError):
            return list(targets or []), 0

        visible = []
        rejected = 0
        for target in targets or []:
            if str((target or {}).get("kind") or "basic") != "basic":
                visible.append(target)
                continue
            rects = (
                target.get("hoverRect") or {},
                target.get("overlayRect") or {},
            )
            try:
                fully_visible = all(
                    float(rect["y"]) >= inspector_top - 1.0
                    and float(rect["y"]) + float(rect["h"])
                        <= inspector_bottom + 1.0
                    for rect in rects
                )
            except (KeyError, TypeError, ValueError):
                fully_visible = False
            if fully_visible:
                visible.append(target)
            else:
                rejected += 1
        return visible, rejected

    @staticmethod
    def _normalized_viewport_rect(rect):
        if not isinstance(rect, dict):
            return None
        try:
            normalized = {
                name: float(rect[name])
                for name in ("x", "y", "w", "h")
            }
        except (KeyError, TypeError, ValueError):
            return None
        if (
            not all(math.isfinite(value) for value in normalized.values())
            or any(abs(value) >= 100000 for value in normalized.values())
            or normalized["w"] <= 0
            or normalized["h"] <= 0
        ):
            return None
        return normalized

    @classmethod
    def _basic_viewport_layout(cls, scan_context):
        if not isinstance(scan_context, dict):
            return None
        layout = scan_context.get("layout")
        if not isinstance(layout, dict):
            return None
        window = cls._normalized_viewport_rect(scan_context.get("window"))
        inspector = cls._normalized_viewport_rect(
            layout.get("inspectorBounds")
        )
        if window is None or inspector is None:
            return None

        window_right = window["x"] + window["w"]
        window_bottom = window["y"] + window["h"]
        inspector_right = inspector["x"] + inspector["w"]
        inspector_bottom = inspector["y"] + inspector["h"]
        if (
            inspector["w"] < 180
            or inspector["h"] < 120
            or inspector["x"] < window["x"] - 2
            or inspector["y"] < window["y"] - 2
            or inspector_right > window_right + 2
            or inspector_bottom > window_bottom + 2
            or abs(inspector_right - window_right) > 24
        ):
            return None
        key = (
            tuple(round(window[name], 1) for name in ("x", "y", "w", "h")),
            tuple(round(inspector[name], 1) for name in ("x", "y", "w", "h")),
        )
        return key, window, inspector

    @classmethod
    def _validated_basic_viewport_hint(cls, targets, scan_context):
        if str((scan_context or {}).get("recognition") or "") != "accessibility":
            return None
        basic_targets = list(targets or [])
        if len(basic_targets) < 2 or {
            cls._target_kind(target) for target in basic_targets
        } != {"basic"}:
            return None
        layout_info = cls._basic_viewport_layout(scan_context)
        if layout_info is None:
            return None
        layout_key, window, inspector = layout_info
        layout = scan_context.get("layout") or {}
        diagnostics = scan_context.get("diagnostics") or {}
        if not isinstance(diagnostics, dict):
            diagnostics = {}

        candidates = []
        for source, fallback in (
            (
                "diagnostics.basicAccessibilityFallback",
                diagnostics.get("basicAccessibilityFallback"),
            ),
            (
                "layout.basicAccessibilityFallback",
                layout.get("basicAccessibilityFallback"),
            ),
        ):
            if (
                isinstance(fallback, dict)
                and fallback.get("eligible") is True
                and str(fallback.get("reason") or "") == "ready"
            ):
                candidates.append((source, fallback))

        viewport = diagnostics.get("accessibilityViewport")
        if isinstance(viewport, dict):
            strict = {
                "contentTop": viewport.get("y"),
                "contentBottom": diagnostics.get(
                    "accessibilityContentBottom"
                ),
                "footerTop": diagnostics.get("accessibilityFooterTop"),
                "navigationBottom": diagnostics.get(
                    "accessibilityNavigationBottom"
                ),
            }
            if strict["contentBottom"] is None:
                try:
                    strict["contentBottom"] = (
                        float(viewport["y"]) + float(viewport["h"])
                    )
                except (KeyError, TypeError, ValueError):
                    pass
            if strict["navigationBottom"] is None:
                tab_frames = diagnostics.get("accessibilityTabFrames")
                if not isinstance(tab_frames, dict):
                    tab = diagnostics.get("tab") or {}
                    accessibility = (
                        tab.get("accessibility")
                        if isinstance(tab, dict) else None
                    )
                    tab_frames = (
                        accessibility.get("frames")
                        if isinstance(accessibility, dict) else None
                    )
                frame_bottoms = []
                for frame in (
                    tab_frames.values()
                    if isinstance(tab_frames, dict) else ()
                ):
                    normalized = cls._normalized_viewport_rect(frame)
                    if normalized is not None:
                        frame_bottoms.append(
                            normalized["y"] + normalized["h"]
                        )
                if frame_bottoms:
                    strict["navigationBottom"] = max(frame_bottoms)
            candidates.append(("diagnostics.accessibilityViewport", strict))

        inspector_bottom = inspector["y"] + inspector["h"]
        for source, candidate in candidates:
            try:
                content_top = float(candidate["contentTop"])
                content_bottom = float(candidate["contentBottom"])
                footer_top = float(candidate["footerTop"])
                navigation_bottom = float(candidate["navigationBottom"])
            except (KeyError, TypeError, ValueError):
                continue
            boundaries = (
                content_top,
                content_bottom,
                footer_top,
                navigation_bottom,
            )
            if (
                not all(math.isfinite(value) for value in boundaries)
                or any(abs(value) >= 100000 for value in boundaries)
                or navigation_bottom < inspector["y"] - 1
                or navigation_bottom > content_top
                or content_top < inspector["y"] - 1
                or content_bottom - content_top < 80
                or content_bottom > footer_top
                or footer_top - content_bottom > 64
                or footer_top > inspector_bottom + 1
                or content_top - navigation_bottom
                    > max(160, inspector["h"] * 0.25)
            ):
                continue

            rows_valid = True
            for target in basic_targets:
                for rect_name in ("hoverRect", "overlayRect"):
                    rect = cls._normalized_viewport_rect(
                        target.get(rect_name)
                    )
                    if (
                        rect is None
                        or rect["y"] < content_top - 1
                        or rect["y"] + rect["h"] > content_bottom + 1
                    ):
                        rows_valid = False
                        break
                if not rows_valid:
                    break
            if not rows_valid:
                continue

            return {
                "key": layout_key,
                "source": source,
                "hint": {
                    "window": window,
                    "inspector": inspector,
                    "contentTop": content_top,
                    "contentBottom": content_bottom,
                    "footerTop": footer_top,
                    "navigationBottom": navigation_bottom,
                },
            }
        return None

    def _seed_basic_viewport_locked(self, targets, scan_context):
        observed = self._validated_basic_viewport_hint(
            targets,
            scan_context,
        )
        if observed is None:
            return False
        previous = self._basic_viewport_cache
        self._basic_viewport_cache = observed
        if previous == observed:
            return False
        hint = observed["hint"]
        print(
            "basic hover viewport: action=seed "
            f"content=({hint['contentTop']:.1f},{hint['contentBottom']:.1f}) "
            f"footer={hint['footerTop']:.1f} "
            f"navigation={hint['navigationBottom']:.1f} "
            f"source={observed['source']}"
        )
        return True

    def _clear_basic_viewport_locked(self, reason):
        cached = self._basic_viewport_cache
        self._basic_viewport_cache = None
        if cached is not None:
            hint = cached.get("hint") or {}
            print(
                "basic hover viewport: action=clear "
                f"reason={str(reason or 'unknown')} "
                f"content=({float(hint.get('contentTop', 0)):.1f},"
                f"{float(hint.get('contentBottom', 0)):.1f})"
            )
        return cached is not None

    def _clear_basic_viewport_for_layout_locked(self, scan_context):
        cached = self._basic_viewport_cache
        if cached is None:
            return False
        layout_info = self._basic_viewport_layout(scan_context)
        if layout_info is None:
            return False
        if cached.get("key") == layout_info[0]:
            return False
        return self._clear_basic_viewport_locked("layout_mismatch")

    def _clear_basic_overlay_columns_locked(self, reason):
        cached = self._basic_overlay_columns_cache
        self._basic_overlay_columns_cache = None
        if cached is not None:
            print(
                "basic hover columns: action=clear "
                f"reason={str(reason or 'unknown')} "
                f"cached=({cached['x']:.1f},{cached['w']:.1f})"
            )
        return cached is not None

    def _stabilize_basic_overlay_columns_locked(
        self,
        targets,
        scan_context,
    ):
        targets = deepcopy(targets or [])
        raw_kinds = set((scan_context or {}).get("rawKinds") or [])
        if raw_kinds and raw_kinds != {"basic"}:
            self._clear_basic_overlay_columns_locked("recognized_kind_changed")
            return targets

        targets, viewport_rejected = self._basic_targets_inside_inspector(
            targets,
            scan_context,
        )
        if viewport_rejected:
            print(
                "basic hover viewport: action=reject "
                f"rows={viewport_rejected}"
            )
        if not targets:
            return []

        cache_key = self._basic_columns_layout_key(scan_context)
        cached = self._basic_overlay_columns_cache
        if (
            cached is not None
            and cache_key is not None
            and cached.get("key") == cache_key
            and {
                str((target or {}).get("kind") or "basic")
                for target in targets
            } == {"basic"}
        ):
            for target in targets:
                rect = dict(target.get("overlayRect") or {})
                rect["x"] = cached["x"]
                rect["w"] = cached["w"]
                target["overlayRect"] = rect
                target["overlayColumnSource"] = "cached_horizontal_columns"
            print(
                "basic hover columns: action=reuse "
                f"x={cached['x']:.1f} w={cached['w']:.1f} "
                f"refresh={str((scan_context or {}).get('refreshReason') or 'unknown')}"
            )
            return targets

        observed, rejection = self._observed_basic_overlay_columns(
            targets,
            scan_context,
        )
        if cache_key is None or observed is None:
            if targets and {
                str((target or {}).get("kind") or "basic")
                for target in targets
            } == {"basic"}:
                print(
                    "basic hover columns: action=reject "
                    f"reason={rejection}"
                )
            if (
                str((scan_context or {}).get("recognition") or "")
                    == "accessibility"
                and rejection in {
                    "columns_not_shared",
                    "columns_out_of_bounds",
                    "overlay_unavailable",
                    "right_endpoint_untrusted",
                }
            ):
                # A first scan has no known-good columns to reuse. Suppress
                # visibly corrupt AX geometry and let the normal transient
                # retry path reacquire it instead of flashing a 110/558pt box.
                return []
            return targets

        observed["key"] = cache_key
        self._basic_overlay_columns_cache = observed
        for target in targets:
            target["overlayColumnSource"] = "cached_horizontal_columns_seed"
        print(
            "basic hover columns: action=seed "
            f"x={observed['x']:.1f} w={observed['w']:.1f} "
            f"source={observed['source']}"
        )
        return targets

    def _scan_once(self, scan_session=None):
        started_at = time.monotonic()
        with self._lock:
            if scan_session is None:
                scan_session = self._stop
            if scan_session is not self._stop or scan_session.is_set():
                return
            if self._scan_in_progress or not self._refresh_requested:
                return
            self._scan_in_progress = True
            refresh_reason = self._refresh_reason
            refresh_generation = self._refresh_generation
            tab_hint = self._active_tab_hint
            mac_one_shot = sys.platform == "darwin" and not self._persistent_scan_enabled
            warmup_scan = mac_one_shot and not self._vision_warmup_complete
            scan_timeout = (
                self.vision_warmup_timeout_seconds
                if warmup_scan else self.scan_timeout_seconds
            )
            basic_viewport_hint = None
            if (
                sys.platform == "darwin"
                and not self._persistent_scan_enabled
                and refresh_reason == "input_scroll"
                and tab_hint == "basic"
                and self._basic_viewport_cache is not None
            ):
                basic_viewport_hint = deepcopy(
                    self._basic_viewport_cache.get("hint")
                )
        payload = None
        detail = ""
        transport = "scan-server" if self._persistent_scan_enabled else "one-shot"
        try:
            if self._persistent_scan_enabled:
                payload = self._scan_via_server(
                    timeout=self.scan_timeout_seconds, tab_hint=tab_hint
                )
            else:
                # The optional argument is ignored by older Swift helpers, so
                # their payload format and one-shot lifecycle remain valid.
                command = [self.helper_path, "scan"]
                if tab_hint is not None:
                    command.extend(["--tab-hint", tab_hint])
                if basic_viewport_hint is not None:
                    serialized_viewport_hint = json.dumps(
                        basic_viewport_hint,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    command.extend([
                        "--basic-viewport-hint",
                        serialized_viewport_hint,
                    ])
                    print(
                        "basic hover viewport: action=reuse "
                        f"content=("
                        f"{basic_viewport_hint['contentTop']:.1f},"
                        f"{basic_viewport_hint['contentBottom']:.1f}) "
                        "refresh=input_scroll"
                    )
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=scan_timeout,
                    check=False,
                    creationflags=self._creationflags(),
                )
                detail = (result.stderr or "").strip().replace("\n", " ")[:180]
                for line in reversed((result.stdout or "").splitlines()):
                    try:
                        payload = json.loads(line)
                        break
                    except (TypeError, json.JSONDecodeError):
                        continue
        except (OSError, subprocess.SubprocessError) as exc:
            reason = f"vision_helper_failed:{exc}"
            # A new model/shape may need another ANE compilation even after
            # earlier OCR succeeded. Only the normal short timeout schedules
            # a recovery scan; a failed long wait must terminate the attempt.
            retry_vision_warmup = (
                mac_one_shot
                and not warmup_scan
                and isinstance(exc, subprocess.TimeoutExpired)
            )
            applied = self._set_scan_result(
                [], reason, False, generation=refresh_generation,
                scan_session=scan_session,
                retry_vision_warmup=retry_vision_warmup,
            )
            print(
                f"basic hover scan: reason={reason} targets=0 "
                f"duration={int((time.monotonic() - started_at) * 1000)}ms "
                f"source={refresh_reason} transport={transport} "
                f"timeout={scan_timeout:g}s warmup={str(warmup_scan).lower()} "
                f"tab_hint={tab_hint or 'none'}"
                f"{'' if applied else ' discarded=stale'}"
            )
            return

        if not isinstance(payload, dict):
            reason = f"invalid_vision_response:{detail}"
            applied = self._set_scan_result(
                [], reason, False, generation=refresh_generation,
                scan_session=scan_session,
            )
            print(
                f"basic hover scan: reason={reason} targets=0 "
                f"duration={int((time.monotonic() - started_at) * 1000)}ms "
                f"source={refresh_reason} transport={transport} "
                f"timeout={scan_timeout:g}s warmup={str(warmup_scan).lower()} "
                f"tab_hint={tab_hint or 'none'}"
                f"{'' if applied else ' discarded=stale'}"
            )
            return

        raw_targets = [
            target
            for target in payload.get("targets") or []
            if self._valid_target(target)
        ]
        raw_kind_hints = [
            self._normalized_tab_hint(self._target_kind(target))
            for target in raw_targets
        ]
        result_tab_hint = None
        if (
            payload.get("ok") is True
            and raw_kind_hints
            and all(raw_kind_hints)
            and len(set(raw_kind_hints)) == 1
        ):
            result_tab_hint = raw_kind_hints[0]
        reason = str(
            payload.get("reason")
            or ("ready" if raw_targets else "basic_parameters_not_visible")
        )
        targets, reason = self._scoped_scan_result(raw_targets, reason)
        recognition = str(payload.get("recognition") or "unknown")
        capture_available = reason != "screen_capture_unavailable"
        diagnostics = payload.get("diagnostics")
        layout = payload.get("layout")
        self._log_scan_diagnostics(
            diagnostics,
            layout=layout,
        )
        self._log_color_wheel_geometry(targets)
        scan_context = {
            "recognition": recognition,
            "layout": layout,
            "window": payload.get("window"),
            "diagnostics": diagnostics,
            "parameterOverlaySource": (
                diagnostics.get("parameterOverlaySource")
                if isinstance(diagnostics, dict) else None
            ),
            "rawKinds": sorted({
                self._target_kind(target)
                for target in raw_targets
            }),
            "refreshReason": refresh_reason,
            "tabHint": tab_hint,
        }
        applied = self._set_scan_result(
            targets,
            reason,
            capture_available,
            generation=refresh_generation,
            scan_context=scan_context,
            result_tab_hint=result_tab_hint,
            scan_session=scan_session,
            # AX-only success bypasses Vision and cannot warm its model. A
            # completed OCR scan still warms it when newer input makes the
            # returned coordinates stale, or when no controls were found.
            vision_warmup_completed=(
                mac_one_shot and recognition.startswith("accurate")
            ),
        )
        print(
            f"basic hover scan: reason={reason} targets={len(targets)} "
            f"duration={int((time.monotonic() - started_at) * 1000)}ms "
            f"source={refresh_reason} recognition={recognition} transport={transport} "
            f"timeout={scan_timeout:g}s warmup={str(warmup_scan).lower()} "
            f"tab_hint={tab_hint or 'none'}"
            f"{'' if applied else ' discarded=stale'}"
        )

    @staticmethod
    def _log_scan_diagnostics(diagnostics, layout=None):
        if not isinstance(diagnostics, dict):
            return
        accepted = [str(value) for value in diagnostics.get("accepted") or []]
        rejected = (
            diagnostics.get("rejected")
            or diagnostics.get("colorWheelRejected")
            or []
        )
        texts = [str(value) for value in diagnostics.get("inspectorTexts") or []]
        timings = diagnostics.get("timingsMs") or {}
        tab = diagnostics.get("tab") or {}
        uia_cache = str(diagnostics.get("uiaProbeCache") or "unknown")
        layout = layout if isinstance(layout, dict) else {}
        compact_rejected = []
        for item in rejected[:32]:
            if not isinstance(item, dict):
                continue
            compact_rejected.append({
                key: item.get(key)
                for key in ("key", "text", "reason", "nearby")
                if item.get(key) not in (None, "", [])
            })
        print(
            "basic hover recognition: "
            f"accepted={json.dumps(accepted, ensure_ascii=False)} "
            f"rejected={json.dumps(compact_rejected, ensure_ascii=False)} "
            f"tab={json.dumps(tab, ensure_ascii=False)} "
            f"timings={json.dumps(timings, ensure_ascii=False)} "
            f"uia_cache={uia_cache} "
            f"layout={json.dumps(layout, ensure_ascii=False)} "
            f"inspector_texts={json.dumps(texts[:80], ensure_ascii=False)}"
        )

    @staticmethod
    def _log_color_wheel_geometry(targets):
        wheels = []
        for target in targets:
            if target.get("kind") != "color_wheels" or target.get("controlType") != "wheel":
                continue
            try:
                wheels.append({
                    "key": str(target.get("key") or ""),
                    "center": [
                        round(float(target.get("centerX")), 1),
                        round(float(target.get("centerY")), 1),
                    ],
                    "radius": round(float(target.get("wheelRadius")), 1),
                    "handle": [
                        round(float(target.get("handleX")), 1),
                        round(float(target.get("handleY")), 1),
                    ],
                    "detected": target.get("handleDetected") is True,
                    "source": str(target.get("geometrySource") or "unknown"),
                    "stabilized": target.get("centerStabilized") is True,
                    "rawCenter": [
                        round(float(target.get("rawCenterX", target.get("centerX"))), 1),
                        round(float(target.get("rawCenterY", target.get("centerY"))), 1),
                    ],
                })
            except (TypeError, ValueError):
                continue
        if wheels:
            print(
                "basic hover color wheels: "
                f"{json.dumps(wheels, ensure_ascii=False)}"
            )

    def _set_scan_result(
        self,
        targets,
        reason,
        capture_available,
        generation=None,
        scan_context=None,
        result_tab_hint=None,
        scan_session=None,
        vision_warmup_completed=False,
        retry_vision_warmup=False,
    ):
        targets, reason = self._scoped_scan_result(targets, reason)
        now = time.monotonic()
        using_cached_targets = False
        with self._lock:
            # start() resets the refresh generation, so generation alone is
            # insufficient across stop/start. Never let an old daemon scan
            # release a new session's scan slot or publish state into it.
            if scan_session is not None and (
                scan_session is not self._stop or scan_session.is_set()
            ):
                return False
            self._scan_in_progress = False
            if vision_warmup_completed:
                self._vision_warmup_complete = True
            elif retry_vision_warmup:
                self._vision_warmup_complete = False
            if (
                generation is not None
                and generation != self._refresh_generation
            ):
                return False
            self._cache_tab_hint_locked(result_tab_hint, "scan_result")
            self._screen_capture_available = bool(capture_available)
            self._clear_basic_viewport_for_layout_locked(scan_context)
            raw_kinds = set((scan_context or {}).get("rawKinds") or [])
            if raw_kinds and raw_kinds != {"basic"}:
                self._clear_basic_viewport_locked(
                    "recognized_kind_changed"
                )
            if not targets and raw_kinds and raw_kinds != {"basic"}:
                self._clear_basic_overlay_columns_locked(
                    "recognized_kind_changed"
                )
            if targets:
                targets = self._stabilize_basic_overlay_columns_locked(
                    targets,
                    scan_context,
                )
                if not targets:
                    reason = "basic_parameters_not_visible"
                else:
                    self._seed_basic_viewport_locked(
                        targets,
                        scan_context,
                    )
            if targets:
                version = int(self._refresh_generation)
                versioned_targets = targets
                for target in versioned_targets:
                    if target.get("kind") == "color_wheels":
                        # Keep the internal hover/pinned target on the same
                        # geometry version returned to action handlers. Without
                        # this, live angle feedback is rejected as stale even
                        # though it belongs to the current wheel scan.
                        target["scanVersion"] = version
                self._targets = versioned_targets
                self._color_wheel_feedback.clear()
                self._targets_scan_version = version
                self._targets_updated_at = now
                self._refresh_requested = False
                self._refresh_attempts = 0
                self._next_scan_at = now
            elif retry_vision_warmup:
                self._targets = []
                self._current = None
                self._refresh_requested = True
                self._refresh_reason = "vision_warmup_retry"
                self._refresh_not_before = now
                self._next_scan_at = now + self.scan_retry_seconds
                self._refresh_attempts = 0
            elif (
                reason in TRANSIENT_SCAN_REASONS
                and self._targets
            ):
                using_cached_targets = True
                if self._refresh_requested:
                    self._refresh_attempts += 1
                    if self._refresh_attempts < self.max_refresh_attempts:
                        self._next_scan_at = now + self.scan_retry_seconds
                    else:
                        if self._refresh_reason.startswith("input_"):
                            # A real Jianying interaction invalidated the old
                            # geometry. Never resume it after repeated OCR
                            # misses because that could drag the wrong control.
                            self._targets = []
                            self._current = None
                            using_cached_targets = False
                        self._refresh_requested = False
                        self._refresh_attempts = 0
            elif reason in TRANSIENT_SCAN_REASONS:
                self._targets = []
                self._current = None
                self._refresh_attempts += 1
                if self._refresh_attempts < self.max_refresh_attempts:
                    self._next_scan_at = now + self.scan_retry_seconds
                else:
                    self._refresh_requested = False
                    self._refresh_attempts = 0
            else:
                self._targets = []
                self._current = None
                self._refresh_requested = False
                self._refresh_attempts = 0
            self._set_status("ready_cached" if using_cached_targets else reason)
        return True

    def _scan_loop(self, stop_event):
        while not stop_event.is_set():
            if self._scan_due():
                self._scan_once(scan_session=stop_event)
            stop_event.wait(self.scan_poll_interval_seconds)

    @staticmethod
    def _contains(target, x, y):
        rect = target.get("hoverRect") or {}
        try:
            left = float(rect["x"])
            top = float(rect["y"])
            width = float(rect["w"])
            height = float(rect["h"])
        except (KeyError, TypeError, ValueError):
            return False
        return left <= x <= left + width and top <= y <= top + height

    def _hover_loop(self, stop_event):
        next_active_check = 0.0
        while not stop_event.is_set():
            now = time.monotonic()
            if now >= next_active_check:
                try:
                    active = bool(self.target_active_provider())
                except Exception:
                    active = False
                with self._lock:
                    was_active = self._active
                    self._active = active
                    if not active:
                        self._current = None
                        if was_active:
                            self._clear_basic_viewport_locked(
                                "target_not_frontmost"
                            )
                            self._clear_tab_hint_locked("target_not_frontmost")
                    pointer_input_pending = self._pointer_input_pending
                if not active and pointer_input_pending:
                    interrupted = self._cancel_pointer_input_for_inactive_target()
                    if interrupted:
                        self._hide_overlay()
                        print(
                            "basic hover cache: refresh deferred "
                            "reason=pointer_input_interrupted"
                        )
                if not active and was_active:
                    self._notify_invalidation("target_not_frontmost")
                if active and not was_active:
                    if self.refresh_on_frontmost_return:
                        self._begin_frontmost_refresh()
                        self._hide_overlay()
                        print("basic hover cache: invalidated reason=frontmost_return")
                    else:
                        # Preserve the stable macOS cache policy. The Windows
                        # backend opts into the stricter foreground transaction
                        # because an activating click can also switch tabs
                        # before its low-level hook is allowed to observe it.
                        with self._lock:
                            has_cached_targets = bool(self._targets)
                        if not has_cached_targets:
                            self._request_refresh("frontmost", delay=0)
                elif not active:
                    self._set_status("jianying_not_frontmost")
                next_active_check = now + self.active_interval_seconds

            hovered = None
            with self._lock:
                active = self._active
                cache_valid = not self._refresh_requested
                targets = deepcopy(self._targets) if cache_valid else []
                pinned = deepcopy(self._pinned_color_wheel_target)
            if active and cache_valid and pinned and self._valid_wheel_geometry(pinned):
                # Encoder-driven color-wheel gestures temporarily move the
                # system pointer outside the wheel. Keep the original target
                # and overlay stable until mouseUp restores the pointer.
                hovered = pinned
            elif active and cache_valid and targets:
                try:
                    position = self.position_provider()
                    mouse_x = float(position["x"])
                    mouse_y = float(position["y"])
                except (KeyError, TypeError, ValueError, RuntimeError):
                    mouse_x = mouse_y = float("inf")
                hovered = next(
                    (target for target in targets if self._contains(target, mouse_x, mouse_y)),
                    None,
                )

            with self._lock:
                old_key = (
                    self._target_kind(self._current),
                    self._current.get("key"),
                ) if self._current else None
                new_key = (
                    self._target_kind(hovered),
                    hovered.get("key"),
                ) if hovered else None
                self._current = deepcopy(hovered)
            if hovered:
                self._show_overlay(hovered)
                if new_key != old_key:
                    print(
                        "basic hover target: "
                        f"kind={new_key[0]} key={new_key[1]} "
                        f"value={hovered.get('value', '-')}"
                    )
            else:
                self._hide_overlay()
            stop_event.wait(self.hover_interval_seconds)


__all__ = [
    "ALL_HOVER_KEYS",
    "BASIC_HOVER_KEYS",
    "HSL_HOVER_KEYS",
    "COLOR_WHEEL_HOVER_KEYS",
    "HOVER_KINDS",
    "BasicHoverService",
]
