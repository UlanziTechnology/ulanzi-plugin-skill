"""Ulanzi encoder Action for DaVinci Resolve timeline control."""

import threading
import time

from .modes import (
    MODE_IDS,
    feedback_icon,
    localized_mode,
    normalize_timeline_settings,
)
from .resolve_backends import TimelineCommandRouter
from .scheduler import TimelineEventScheduler


class DaVinciTimelineAction:
    """Six-mode timeline controller with press-and-turn mode selection."""

    # Ulanzi Studio can omit dialup after a press-and-turn gesture on some
    # firmware/host combinations. The app uses these bounds to commit a
    # rotated preview, or cancel an idle plain press, without leaving the
    # action permanently trapped in selection mode.
    dial_auto_release_seconds = 0.50
    dial_auto_cancel_seconds = 1.50

    def __init__(self, context, api, router=None, initial_settings=None):
        self.context = context
        self.ud_api = api
        self.settings = normalize_timeline_settings(
            initial_settings if isinstance(initial_settings, dict) else None
        )
        self.mode = self.settings["mode"]
        self.active = False
        self._router = router or TimelineCommandRouter(hotkey_fn=self.ud_api.hotkey)
        self._selection_active = False
        self._selection_rotated = False
        self._preview_mode_index = MODE_IDS.index(self.mode)
        self._last_failure_log_at = 0.0
        self._destroyed = False
        self._base_state_initialized = False
        self._last_feedback_signature = None
        self._scheduler = TimelineEventScheduler(
            self._execute_batch,
            result_fn=self._on_batch_result,
            batch_limit_fn=self._batch_limit,
        )
        self._ensure_base_state_icon()
        self._update_device_feedback(preview=False)
        threading.Thread(
            target=self._warm_up,
            name="davinci-timeline-backend-probe",
            daemon=True,
        ).start()

    def _warm_up(self):
        try:
            self._router.warm_up()
        except Exception as exc:
            self._router.last_error = f"Backend probe failed: {exc}"

    def update_settings(self, settings, action_type="init"):
        previous_settings = self.settings
        # Property Inspector settings are authoritative. They must also recover
        # an instance stranded in selection mode by a missing dialup event.
        self._selection_active = False
        self._selection_rotated = False
        self.settings = normalize_timeline_settings(settings, current=self.settings)
        self.mode = self.settings["mode"]
        self._preview_mode_index = MODE_IDS.index(self.mode)
        # Every setting can change the meaning or direction of queued ticks.
        # Never let input captured under the previous configuration execute
        # with the newly selected backend, sensitivity, step size, or direction.
        if previous_settings != self.settings:
            self._scheduler.flush()
        self._update_device_feedback(preview=False)
        return True

    def set_active(self, active):
        self.active = bool(active)
        if self.active:
            self._ensure_base_state_icon()
            self._update_device_feedback(preview=False)

    def on_dial_press(self):
        self._scheduler.flush()
        self._selection_active = True
        self._selection_rotated = False
        self._preview_mode_index = MODE_IDS.index(self.mode)
        return True

    def on_dial_rotate_hold(self, ticks):
        ticks = int(ticks)
        if not ticks:
            return False
        if not self._selection_active:
            self.on_dial_press()
        self._selection_rotated = True
        self._preview_mode_index = (self._preview_mode_index + ticks) % len(MODE_IDS)
        self._update_device_feedback(preview=True)
        return True

    def on_dial_release(self, rotated=False):
        should_commit = self._selection_active and (self._selection_rotated or bool(rotated))
        if should_commit:
            self.mode = MODE_IDS[self._preview_mode_index]
            self.settings["mode"] = self.mode
            try:
                self.ud_api.set_settings(self.settings.copy(), self.context)
            except Exception:
                pass
        self._selection_active = False
        self._selection_rotated = False
        self._scheduler.flush()
        self._update_device_feedback(preview=False)
        return should_commit

    def on_dial_rotate(self, ticks):
        if self._selection_active:
            return self.on_dial_rotate_hold(ticks)
        return self._scheduler.submit(self.mode, ticks)

    def _batch_limit(self, mode):
        if mode == "frame_step":
            return 3
        if mode != "playhead_seconds":
            return 8
        # Keep each native-input burst below roughly one output frame worth
        # of key pairs. Excess fast input is then handled by stale-tail discard.
        seconds = max(1, int(self.settings.get("seconds_per_tick", 1)))
        return max(1, 3 // seconds)

    def _execute_batch(self, mode, ticks):
        if self._destroyed:
            return False
        return self._router.execute(mode, ticks, self.settings)

    def _on_batch_result(self, ok, mode, ticks):
        if ok:
            return
        now = time.monotonic()
        if now - self._last_failure_log_at < 1.0:
            return
        self._last_failure_log_at = now
        message = self._router.last_error or f"Timeline command failed: {mode} {ticks}"
        print(f"timeline control: {message}")

    def _language(self):
        return getattr(self.ud_api, "language", "en") or "en"

    def _display_mode(self):
        if self._selection_active and self._selection_rotated:
            return MODE_IDS[self._preview_mode_index]
        return self.mode

    def _ensure_base_state_icon(self):
        if self._base_state_initialized:
            return True
        try:
            self.ud_api.set_state_icon(self.context, 0)
            self._base_state_initialized = True
            return True
        except Exception:
            return False

    def _update_device_feedback(self, preview=False):
        mode_id = self._display_mode()
        full_title = localized_mode(mode_id, self._language(), short=False)
        feedback_title = full_title
        if preview:
            feedback_title = f"‹ {localized_mode(mode_id, self._language(), short=True)} ›"
        icon_path = feedback_icon(mode_id)
        indicator_value = self._preview_mode_index + 1
        feedback_signature = (feedback_title, icon_path, indicator_value)
        if feedback_signature == self._last_feedback_signature:
            return False
        try:
            self.ud_api.set_feedback(
                self.context,
                {
                    "title": {
                        "text": feedback_title,
                    },
                    "icon": {
                        "value": icon_path,
                        "enabled": True,
                    },
                    "indicator": {
                        "value": indicator_value,
                        "enabled": True,
                    },
                },
            )
            self._last_feedback_signature = feedback_signature
            return True
        except Exception:
            return False

    def get_status_payload(self):
        if self._router.is_resolve_running():
            return {
                "type": "davinci_status",
                "level": "success",
                "statusKey": "DaVinci Resolve detected.",
            }
        return {
            "type": "davinci_status",
            "level": "warn",
            "statusKey": (
                "DaVinci Resolve not detected. Open DaVinci Resolve, "
                "then this plugin will reconnect automatically."
            ),
        }

    def on_connection_lost(self):
        self._selection_active = False
        self._selection_rotated = False
        self._base_state_initialized = False
        self._last_feedback_signature = None
        self._scheduler.flush()
        self._router.suspend()

    def destroy(self):
        self._destroyed = True
        self._selection_active = False
        self._selection_rotated = False
        self._scheduler.stop()
        self._router.close()


__all__ = ["DaVinciTimelineAction"]
