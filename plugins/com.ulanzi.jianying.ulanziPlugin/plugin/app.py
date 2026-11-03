#!/usr/bin/env python3
"""Ulanzi Studio Python entrypoint for Jianying Pro."""

import os
import site
import sys
from threading import RLock, Timer
import time
import traceback


PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.abspath(os.path.join(PLUGIN_DIR, ".."))
VENDORED_SITE = os.path.join(PLUGIN_ROOT, "site-packages")
SDK_DIR = os.path.join(PLUGIN_DIR, "libs")

for path in (PLUGIN_DIR, SDK_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)
if os.path.isdir(VENDORED_SITE):
    if os.name == "nt":
        site.addsitedir(VENDORED_SITE)
        if VENDORED_SITE in sys.path:
            sys.path.remove(VENDORED_SITE)
        sys.path.insert(0, VENDORED_SITE)
    elif VENDORED_SITE not in sys.path:
        sys.path.insert(0, VENDORED_SITE)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


class TeeLog:
    """Keep Studio-launched Python diagnostics available to developers."""

    def __init__(self, console, path):
        self.console = console
        if os.path.exists(path) and os.path.getsize(path) > 2 * 1024 * 1024:
            os.replace(path, f"{path}.1")
        self.file = open(path, "a", encoding="utf-8", buffering=1)
        self.lock = RLock()

    def write(self, value):
        with self.lock:
            try:
                self.console.write(value)
            except Exception:
                pass
            self.file.write(value)
        return len(value)

    def flush(self):
        with self.lock:
            try:
                self.console.flush()
            except Exception:
                pass
            self.file.flush()

    def __getattr__(self, name):
        return getattr(self.console, name)


if sys.platform == "darwin":
    LOG_DIR = os.path.expanduser("~/Library/Logs/Ulanzi")
elif sys.platform == "win32":
    LOG_DIR = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Ulanzi", "Logs"
    )
else:
    LOG_DIR = ""

if LOG_DIR:
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        log_path = os.path.join(LOG_DIR, "JianyingPlugin.log")
        sys.stdout = TeeLog(sys.stdout, log_path)
        sys.stderr = TeeLog(sys.stderr, log_path)
    except OSError:
        pass

from ulanzi_api import UlanziApi

from action_ids import PLUGIN_UUID
from action_router import ActionRouter
from backends.factory import create_backend
from shortcut_catalog import publish_shortcut_catalog


api = UlanziApi()
backend = create_backend(api)
router = ActionRouter(api, backend)
_recent_runs = {}
_instance_lock = None


def acquire_single_instance():
    global _instance_lock
    if sys.platform != "darwin":
        return True
    try:
        import fcntl

        lock_path = "/tmp/com.ulanzi.ulanzistudio.jianying.lock"
        _instance_lock = open(lock_path, "a+", encoding="utf-8")
        fcntl.flock(_instance_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (OSError, ImportError):
        return False


def guarded(label, callback, message):
    try:
        return callback(message or {})
    except Exception as exc:
        print(f"{label} failed: {exc}")
        traceback.print_exc()
        return None


def event_ticks(message):
    message = message or {}
    param = message.get("param") or {}
    rotate_event = str(
        message.get("rotateEvent") or param.get("rotateEvent") or ""
    ).lower()
    ticks = message.get("ticks", param.get("ticks"))
    if ticks not in (None, ""):
        try:
            ticks = int(ticks)
            if "left" in rotate_event:
                return -abs(ticks)
            if "right" in rotate_event:
                return abs(ticks)
            return ticks
        except (TypeError, ValueError):
            pass
    return -1 if "left" in rotate_event else 1 if "right" in rotate_event else 0


def is_fine_rotation(message):
    param = (message or {}).get("param") or {}
    value = str(
        (message or {}).get("rotateEvent") or param.get("rotateEvent") or ""
    ).lower()
    return "hold" in value


def log_timeline_host_event(instance, event, message, ticks=None, fine=None):
    """Forward only compact dial fields to timeline diagnostic logging."""
    logger = getattr(instance, "log_host_dial_event", None)
    if not callable(logger):
        return False
    message = message or {}
    param = message.get("param") or {}
    raw_ticks = message.get("ticks", param.get("ticks"))
    rotate_event = message.get(
        "rotateEvent", param.get("rotateEvent", "")
    )
    try:
        logger(
            event,
            ticks=ticks,
            raw_ticks=raw_ticks,
            rotate_event=rotate_event,
            fine=fine,
        )
    except Exception as exc:
        print(
            "timeline diag: stage=host-event-log "
            f"event={event} result=exception error={type(exc).__name__}:{str(exc)[:100]}"
        )
    return True


@api.on_connected
def on_connected(connection):
    api.localize_ui()
    print(
        f"connected to Ulanzi Studio at {api.address}:{api.port} "
        f"({api.language})"
    )
    catalog = publish_shortcut_catalog(api, force=True)
    print(
        "published Jianying shortcut catalog: "
        f"{catalog.get('profile') or 'built-in fallback'}"
    )


@api.on_close
def on_close(connection):
    print(f"Ulanzi Studio connection closed: {connection}")


@api.on_error
def on_error(error):
    if isinstance(error, dict):
        error = error.get("error")
    print(f"Ulanzi Studio connection error: {error}")


@api.on_add
def on_add(message):
    return guarded("add", router.add, message)


def run_action(message, source="run"):
    context = (message or {}).get("context")
    now = time.monotonic()
    if now - _recent_runs.get(context, 0) < 0.12:
        if os.name == "nt":
            print(
                "windows press event: "
                f"context={context} source={source} state=deduplicated "
                "reason=app-run-window elapsedMs="
                f"{max(0.0, now - _recent_runs.get(context, 0)) * 1000.0:.0f}"
            )
        return False
    _recent_runs[context] = now
    instance = router.ensure(message)
    if instance is not None and hasattr(instance, "execute_press_event"):
        return instance.execute_press_event(source)
    return instance.execute() if instance is not None else False


@api.on_run
def on_run(message):
    return guarded("run", lambda value: run_action(value, "run"), message)


@api.on_key_down
def on_key_down(message):
    return guarded("keydown", lambda value: run_action(value, "keydown"), message)


@api.on_set_active
def on_set_active(message):
    return guarded("setActive", router.set_active, message)


@api.on_clear
def on_clear(message):
    return guarded("clear", router.clear, message)


@api.on_did_receive_settings
def on_did_receive_settings(message):
    return guarded("settings", router.apply_settings, message)


@api.on_param_from_app
def on_param_from_app(message):
    return guarded("legacy app settings", router.apply_settings, message)


@api.on_param_from_plugin
def on_param_from_plugin(message):
    return guarded("legacy plugin settings", router.apply_settings, message)


@api.on_dial_down
def on_dial_down(message):
    instance = router.ensure(message)
    if instance is not None and hasattr(instance, "on_dial_down"):
        log_timeline_host_event(instance, "dialdown", message)
        return guarded("dialdown", lambda _: instance.on_dial_down(), message)
    return False


@api.on_dial_up
def on_dial_up(message):
    instance = router.ensure(message)
    if instance is not None and hasattr(instance, "on_dial_up"):
        log_timeline_host_event(instance, "dialup", message)
        return guarded("dialup", lambda _: instance.on_dial_up(), message)
    return False


@api.on_dial_rotate
def on_dial_rotate(message):
    instance = router.ensure(message)
    if instance is not None and hasattr(instance, "on_rotate"):
        ticks = event_ticks(message)
        fine = is_fine_rotation(message)
        timeline_logged = log_timeline_host_event(
            instance,
            "dialrotate",
            message,
            ticks=ticks,
            fine=fine,
        )
        if os.name == "nt" and not timeline_logged:
            param = (message or {}).get("param") or {}
            print(
                "windows dial event: "
                f"context={(message or {}).get('context', '')} "
                f"action={(message or {}).get('action', '')} "
                f"ticks={ticks} rawTicks={(message or {}).get('ticks', param.get('ticks'))} "
                f"rotateEvent={(message or {}).get('rotateEvent', param.get('rotateEvent', ''))} "
                f"fine={fine} monotonicMs={time.monotonic() * 1000:.1f}"
            )
        return guarded(
            "dialrotate",
            lambda _: instance.on_rotate(ticks, fine),
            message,
        )
    return False


@api.on_send_to_plugin
def on_send_to_plugin(message):
    payload = (message or {}).get("payload") or {}
    context = (message or {}).get("context")
    if payload.get("type") == "requestJianyingStatus":
        if context:
            api.send_to_property_inspector(
                {
                    "type": "jianyingStatus",
                    "running": backend.target_is_running(),
                },
                context,
            )
        return

    if payload.get("type") == "requestShortcutCatalog":
        catalog = publish_shortcut_catalog(
            api,
            force=bool(payload.get("force")),
            context=context,
        )
        print(
            "refreshed Jianying shortcut catalog: "
            f"{catalog.get('profile') or 'built-in shortcuts'}; "
            f"context={context or '-'}"
        )
        return

    if not context:
        return
    if payload.get("type") == "requestStatus":
        instance = router.get(context)
        api.send_to_property_inspector(
            {
                "type": "status",
                "targetBundleId": backend.target_bundle_id,
                "targetVersion": backend.target_version(),
                "targetActive": backend.target_is_active(),
                "automationPermission": backend.automation_permission(),
                "screenCapturePermission": backend.screen_capture_permission(),
                "basicHoverStatus": backend.basic_hover_status(),
                "hslHoverStatus": backend.hsl_hover_status(),
                "colorWheelHoverStatus": backend.color_wheel_hover_status(),
                "automationReason": getattr(instance, "last_automation_reason", ""),
            },
            context,
        )
        return

    if payload.get("type") == "capturePointer":
        try:
            delay = min(10.0, max(1.0, float(payload.get("delay", 3))))
        except (TypeError, ValueError):
            delay = 3.0

        def capture_pointer():
            try:
                position = backend.pointer_position()
                response = {
                    "type": "pointerPosition",
                    "position": position,
                    "captureTarget": payload.get("captureTarget", "parameter"),
                    "automationPermission": backend.automation_permission(),
                }
                if position is None:
                    response["error"] = "pointer capture is unavailable on this platform"
            except Exception as exc:
                response = {
                    "type": "pointerPosition",
                    "position": None,
                    "captureTarget": payload.get("captureTarget", "parameter"),
                    "error": str(exc),
                }
            api.send_to_property_inspector(response, context)

        api.send_to_property_inspector(
            {"type": "pointerCaptureStarted", "delay": delay}, context
        )
        timer = Timer(delay, capture_pointer)
        timer.daemon = True
        timer.start()


def main():
    print("=" * 58)
    print("Jianying Pro 11 - Ulanzi Studio Python plugin")
    print(f"Plugin UUID: {PLUGIN_UUID}")
    print(f"Target bundle: {backend.target_bundle_id or 'platform default'}")
    if backend.target_version():
        print(f"Target version: {backend.target_version()}")
    print("=" * 58)

    if not acquire_single_instance():
        print("another Jianying plugin process is already running")
        return 0
    api.connect(PLUGIN_UUID, daemon=True)
    print(f"connecting to {api.address}:{api.port}; language={api.language}")
    try:
        while True:
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("stopped")
    finally:
        api.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
