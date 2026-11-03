"""Runtime helpers for TourBox diagnostic probe execution."""

import json
import os
import time

from ..platform_tourbox_input import TourBoxMouseInput


PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
TOURBOX_PROBE_CONFIG_PATH = os.path.join(PLUGIN_ROOT, 'tourbox_probe_config.json')
DIAGNOSTICS_DIR = os.path.join(PLUGIN_ROOT, 'diagnostics')


class TourBoxProbeEventRecorder:
    """Collects requested/cursor positions for TourBox diagnostic reports."""

    def __init__(self, get_cursor_position_fn):
        self._get_cursor_position_fn = get_cursor_position_fn
        self.events = []

    def record(self, name, x=None, y=None, ok=True):
        cursor_x, cursor_y = self._get_cursor_position_fn()
        self.events.append({
            't': round(time.perf_counter(), 6),
            'name': name,
            'requested': None if x is None else [round(float(x), 3), round(float(y), 3)],
            'cursor': [cursor_x, cursor_y],
            'ok': bool(ok),
        })


class TourBoxProbeConfigAccessor:
    """Tiny wrapper so probe runners do not define local config getters."""

    def __init__(self, config):
        self._config = config if isinstance(config, dict) else {}

    def get(self, name, default):
        return self._config.get(name, default)


def tourbox_probe_config_getter():
    return TourBoxProbeConfigAccessor(load_tourbox_probe_config()).get


def load_tourbox_probe_config():
    if not os.path.exists(TOURBOX_PROBE_CONFIG_PATH):
        return {'enabled': False}
    try:
        with open(TOURBOX_PROBE_CONFIG_PATH, 'r', encoding='utf-8-sig') as fh:
            config = json.load(fh)
    except Exception as exc:
        print(f"tourbox probe config read failed: {exc}")
        return {'enabled': False}
    if not isinstance(config, dict):
        return {'enabled': False}
    return config


def create_tourbox_probe_run_dir(prefix):
    run_dir = os.path.join(DIAGNOSTICS_DIR, f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


def tourbox_probe_run_context(prefix, *, config_get, get_cursor_position_fn):
    original_cursor = get_cursor_position_fn()
    final_cursor_policy = str(config_get('cursor_after_drag', 'after_handle')).lower()
    event_recorder = TourBoxProbeEventRecorder(get_cursor_position_fn)
    return {
        'original_cursor': original_cursor,
        'final_cursor_policy': final_cursor_policy,
        'final_cursor_target': None,
        'run_dir': create_tourbox_probe_run_dir(prefix),
        'event_recorder': event_recorder,
        'events': event_recorder.events,
        'record': event_recorder.record,
    }


__all__ = [
    'DIAGNOSTICS_DIR',
    'PLUGIN_ROOT',
    'TOURBOX_PROBE_CONFIG_PATH',
    'TourBoxMouseInput',
    'TourBoxProbeConfigAccessor',
    'TourBoxProbeEventRecorder',
    'create_tourbox_probe_run_dir',
    'load_tourbox_probe_config',
    'tourbox_probe_config_getter',
    'tourbox_probe_run_context',
]
