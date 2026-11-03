"""Jianying Pro keyboard command catalog."""

from dataclasses import dataclass
from pathlib import Path
import sys
import time

from jianying_shortcuts import JianyingShortcutProvider


@dataclass(frozen=True)
class Shortcut:
    key: str
    label: str
    mac: str
    windows: str

    def for_current_os(self):
        return self.mac if sys.platform == "darwin" else self.windows


MAC_CONTROL = "^"
MAC_COMMAND = "⌘"
MAC_OPTION = "⌥"
MAC_SHIFT = "⇧"


def mac_hotkey(*keys):
    """Encode a Studio macOS hotkey: symbols separated by spaces."""
    return " ".join(str(key).strip() for key in keys if str(key).strip())


def windows_hotkey(*keys):
    """Encode a Studio Windows hotkey: key names separated by plus signs."""
    return "+".join(str(key).strip() for key in keys if str(key).strip())


SHORTCUTS = (
    Shortcut("split", "Split", mac_hotkey(MAC_COMMAND, "B"), windows_hotkey("Ctrl", "B")),
    Shortcut("undo", "Undo", mac_hotkey(MAC_COMMAND, "Z"), windows_hotkey("Ctrl", "Z")),
    Shortcut("redo", "Redo", mac_hotkey(MAC_COMMAND, MAC_SHIFT, "Z"), windows_hotkey("Ctrl", "Shift", "Z")),
    Shortcut("copy", "Copy", mac_hotkey(MAC_COMMAND, "C"), windows_hotkey("Ctrl", "C")),
    Shortcut("paste", "Paste", mac_hotkey(MAC_COMMAND, "V"), windows_hotkey("Ctrl", "V")),
    Shortcut("cut", "Cut", mac_hotkey(MAC_COMMAND, "X"), windows_hotkey("Ctrl", "X")),
    Shortcut("delete", "Delete", mac_hotkey("Delete"), windows_hotkey("Delete")),
    Shortcut("play_pause", "Play / Pause", mac_hotkey("Space"), windows_hotkey("Space")),
    Shortcut("fullscreen", "Fullscreen preview", mac_hotkey(MAC_COMMAND, MAC_SHIFT, "F"), windows_hotkey("Ctrl", "Shift", "F")),
    Shortcut("previous_frame", "Previous frame", mac_hotkey(MAC_COMMAND, "Left"), windows_hotkey("Ctrl", "Left")),
    Shortcut("next_frame", "Next frame", mac_hotkey(MAC_COMMAND, "Right"), windows_hotkey("Ctrl", "Right")),
    Shortcut("previous_edit", "Previous split point", mac_hotkey("Up"), windows_hotkey("Up")),
    Shortcut("next_edit", "Next split point", mac_hotkey("Down"), windows_hotkey("Down")),
    Shortcut("zoom_in", "Timeline zoom in", mac_hotkey(MAC_COMMAND, "="), windows_hotkey("Ctrl", "=")),
    Shortcut("zoom_out", "Timeline zoom out", mac_hotkey(MAC_COMMAND, "-"), windows_hotkey("Ctrl", "-")),
    Shortcut("fast_forward", "Fast forward", mac_hotkey("Right"), windows_hotkey("Right")),
    Shortcut("rewind", "Rewind", mac_hotkey("Left"), windows_hotkey("Left")),
    Shortcut("previous_marker", "Previous marker", mac_hotkey(MAC_OPTION, MAC_SHIFT, "M"), windows_hotkey("Alt", "Shift", "M")),
    Shortcut("next_marker", "Next marker", mac_hotkey(MAC_SHIFT, "M"), windows_hotkey("Shift", "M")),
    Shortcut("export", "Export", mac_hotkey(MAC_COMMAND, "E"), windows_hotkey("Ctrl", "E")),
    Shortcut("record", "Record", mac_hotkey(MAC_COMMAND, "R"), windows_hotkey("Ctrl", "R")),
    # Additional commands used by the timeline encoder rather than keypad choices.
    Shortcut("track_height_down", "Track height down", mac_hotkey(MAC_COMMAND, MAC_OPTION, "-"), windows_hotkey("Ctrl", "Alt", "-")),
    Shortcut("track_height_up", "Track height up", mac_hotkey(MAC_COMMAND, MAC_OPTION, "="), windows_hotkey("Ctrl", "Alt", "=")),
    Shortcut("zoom_fit", "Timeline fit", mac_hotkey(MAC_SHIFT, "Z"), windows_hotkey("Shift", "Z")),
    Shortcut("scroll_vertical", "Timeline vertical scroll", "Wheel", "Wheel"),
    Shortcut("scroll_horizontal", "Timeline horizontal scroll", mac_hotkey(MAC_OPTION, "Wheel"), windows_hotkey("Alt", "Wheel")),
)

SHORTCUT_BY_KEY = {item.key: item for item in SHORTCUTS}
SHORTCUT_BY_KEY.update({
    "timeline_start": SHORTCUT_BY_KEY["previous_frame"],
    "timeline_end": SHORTCUT_BY_KEY["next_frame"],
})

TIMELINE_CONTROL_MODES = (
    "frame_step",
    "track_height",
    "timeline_zoom",
    "vertical_scroll",
    "horizontal_scroll",
    "large_seek",
    "marker",
    "split_point",
)

TIMELINE_MODE_COMMANDS = {
    "frame_step": ("previous_frame", "next_frame"),
    "track_height": ("track_height_down", "track_height_up"),
    "timeline_zoom": ("zoom_out", "zoom_in"),
    "vertical_scroll": ("scroll_vertical", "scroll_vertical"),
    "horizontal_scroll": ("scroll_horizontal", "scroll_horizontal"),
    "large_seek": ("rewind", "fast_forward"),
    "marker": ("previous_marker", "next_marker"),
    "split_point": ("previous_edit", "next_edit"),
}

TIMELINE_FALLBACK_RAW = {
    "previous_frame": "Ctrl+Left",
    "next_frame": "Ctrl+Right",
    "track_height_down": "Ctrl+Alt+-",
    "track_height_up": "Ctrl+Alt+=",
    "zoom_out": "Ctrl+-",
    "zoom_in": "Ctrl+=",
    "scroll_vertical": "Wheel",
    "scroll_horizontal": "Alt+Wheel",
    "rewind": "Left",
    "fast_forward": "Right",
    "previous_marker": "Alt+Shift+M",
    "next_marker": "Shift+M",
    "previous_edit": "Up",
    "next_edit": "Down",
}

_SHORTCUT_PROVIDER = JianyingShortcutProvider()

GLOBAL_SHORTCUT_CATALOG_KEY = "jianyingShortcutCatalog"
GLOBAL_SHORTCUT_CATALOG_SCHEMA = 1


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SHORTCUT_ICON_DIRECTORY = PLUGIN_ROOT / "resources" / "icons" / "shortcuts"


def shortcut_icon_path(key):
    """Return an absolute SVG path accepted by the Studio path-icon API."""
    shortcut = resolve_shortcut(key)
    path = SHORTCUT_ICON_DIRECTORY / f"{shortcut.key}.svg"
    if not path.is_file():
        path = SHORTCUT_ICON_DIRECTORY / "split.svg"
    return str(path)


def resolve_shortcut(key):
    fallback = SHORTCUT_BY_KEY.get(key, SHORTCUT_BY_KEY["split"])
    snapshot = _SHORTCUT_PROVIDER.snapshot()
    binding = _SHORTCUT_PROVIDER.binding_for(fallback.key, snapshot)
    if binding is None and not snapshot.available:
        return fallback
    if binding is None:
        return Shortcut(fallback.key, fallback.label, "", "")
    return Shortcut(fallback.key, fallback.label, binding.mac, binding.windows)


def _platform_hotkey(binding, fallback, platform):
    is_mac = str(platform or sys.platform).lower() in {"darwin", "mac", "macos"}
    if binding is not None:
        return binding.mac if is_mac else binding.windows
    return fallback.mac if is_mac else fallback.windows


def _scroll_input(raw, direction, platform=None):
    """Render Jianying's Wheel binding in the current platform's token form."""
    parts = [part.strip() for part in str(raw or "").split("+")]
    if not parts or parts[-1].lower() != "wheel":
        return ""
    is_mac = str(platform or sys.platform).lower() in {"darwin", "mac", "macos"}
    modifier_aliases = (
        {
            "alt": MAC_OPTION,
            "option": MAC_OPTION,
            "shift": MAC_SHIFT,
            "ctrl": MAC_COMMAND,
            "control": MAC_CONTROL,
            "cmd": MAC_COMMAND,
            "command": MAC_COMMAND,
            "meta": MAC_COMMAND,
        }
        if is_mac
        else {
            "alt": "Alt",
            "option": "Alt",
            "shift": "Shift",
            "ctrl": "Ctrl",
            "control": "Ctrl",
            "cmd": "Ctrl",
            "command": "Ctrl",
            "meta": "Ctrl",
        }
    )
    modifiers = [
        modifier_aliases.get(part.lower(), part)
        for part in parts[:-1]
        if part
    ]
    scroll = "SCROLL UP" if direction < 0 else "SCROLL DOWN"
    formatter = mac_hotkey if is_mac else windows_hotkey
    return formatter(*(modifiers + [scroll]))


def resolve_timeline_input(mode, direction, platform=None):
    """Resolve one dial direction through Jianying's active shortcut profile.

    The returned mapping has ``kind`` set to ``hotkey``, ``scroll`` or
    ``unassigned``. Wheel values use native platform notation: for example,
    macOS emits ``⌥ SCROLL DOWN``. Windows horizontal scrolling uses explicit
    ``HWHEEL LEFT/RIGHT`` directions, independent of shortcut assignments;
    these are internal native-input tokens, never host hotkey requests.
    Other modes continue to follow the active shortcut profile.
    """
    mode = str(mode or "")
    if mode not in TIMELINE_MODE_COMMANDS:
        raise ValueError(f"unknown timeline control mode: {mode}")
    try:
        direction = -1 if float(direction) < 0 else 1 if float(direction) > 0 else 0
    except (TypeError, ValueError):
        direction = 0
    if not direction:
        raise ValueError("timeline control direction must be non-zero")

    command = TIMELINE_MODE_COMMANDS[mode][0 if direction < 0 else 1]
    fallback = SHORTCUT_BY_KEY[command]
    snapshot = _SHORTCUT_PROVIDER.snapshot()
    binding = _SHORTCUT_PROVIDER.binding_for(command, snapshot)

    if mode == "horizontal_scroll" and str(platform or sys.platform).lower() in {
        "win32", "windows",
    }:
        return {
            "mode": mode,
            "direction": direction,
            "kind": "scroll",
            "value": "HWHEEL LEFT" if direction < 0 else "HWHEEL RIGHT",
            "command": command,
            "raw": binding.raw if binding is not None else "",
            "assigned": True,
            "detected": binding is not None,
            "profile": snapshot.profile,
        }

    if binding is None and snapshot.available:
        return {
            "mode": mode,
            "direction": direction,
            "kind": "unassigned",
            "value": "",
            "command": command,
            "raw": "",
            "assigned": False,
            "detected": False,
            "profile": snapshot.profile,
        }

    raw = binding.raw if binding is not None else TIMELINE_FALLBACK_RAW[command]
    scroll_value = _scroll_input(raw, direction, platform)
    kind = "scroll" if scroll_value else "hotkey"
    value = scroll_value or _platform_hotkey(binding, fallback, platform)
    return {
        "mode": mode,
        "direction": direction,
        "kind": kind,
        "value": value,
        "command": command,
        "raw": raw,
        "assigned": bool(value),
        "detected": binding is not None,
        "profile": snapshot.profile,
    }


def _display_hotkey(value, mac=False):
    replacements = {
        "Left": "←",
        "Right": "→",
        "Up": "↑",
        "Down": "↓",
        "Delete": "⌫" if mac else "Delete",
        "Backspace": "⌫" if mac else "Backspace",
    }
    separator = " " if mac else "+"
    parts = str(value or "").split(separator)
    rendered = [replacements.get(part, part) for part in parts]
    return "".join(rendered) if mac else "+".join(rendered)


def shortcut_catalog_info(force=False):
    """Return active-profile shortcuts for the Property Inspector."""
    snapshot = _SHORTCUT_PROVIDER.snapshot(force=force)
    values = {}
    for fallback in SHORTCUTS:
        binding = _SHORTCUT_PROVIDER.binding_for(fallback.key, snapshot)
        if binding is not None:
            shortcut = Shortcut(fallback.key, fallback.label, binding.mac, binding.windows)
        elif snapshot.available:
            shortcut = Shortcut(fallback.key, fallback.label, "", "")
        else:
            shortcut = fallback
        values[fallback.key] = {
            "mac": _display_hotkey(shortcut.mac, mac=True),
            "windows": _display_hotkey(shortcut.windows),
            "detected": binding is not None,
            "assigned": binding is not None if snapshot.available else True,
        }
    return {
        "autoDetected": snapshot.available,
        "profile": snapshot.profile,
        "configVersion": snapshot.config_version,
        "error": snapshot.error,
        "shortcuts": values,
    }


def shortcut_global_settings(force=False, now=None):
    """Build the plugin-wide, read-only shortcut display snapshot."""
    catalog = shortcut_catalog_info(force=force)
    catalog.update(
        {
            "schemaVersion": GLOBAL_SHORTCUT_CATALOG_SCHEMA,
            "platform": sys.platform,
            "updatedAt": int((time.time() if now is None else now) * 1000),
        }
    )
    return {GLOBAL_SHORTCUT_CATALOG_KEY: catalog}


def publish_shortcut_catalog(api, force=False, now=None, context=None):
    """Persist and broadcast the shared shortcut snapshot through Ulanzi Studio."""
    settings = shortcut_global_settings(force=force, now=now)
    api.set_global_settings(settings, context)
    return settings[GLOBAL_SHORTCUT_CATALOG_KEY]
