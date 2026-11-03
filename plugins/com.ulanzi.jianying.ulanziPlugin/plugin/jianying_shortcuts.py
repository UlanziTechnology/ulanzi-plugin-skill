"""Read-only access to Jianying Pro's local shortcut profiles."""

from configparser import ConfigParser, Error as ConfigError
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import sys
from threading import RLock


PROFILE_ORDER = (
    "Final Cut Pro X",
    "Premiere Pro",
    "Custom1",
    "Custom2",
    "Custom3",
)

COMMAND_IDS = {
    "split": "cutoff",
    "undo": "undo",
    "redo": "redo",
    "copy": "copy",
    "paste": "paste",
    "cut": "cut",
    "delete": "del",
    "fullscreen": "toggleFullscreen",
    "play_pause": "togglePlay",
    "fast_forward": "largeNextFrame",
    "rewind": "largePreFrame",
    "previous_frame": "prevFrame",
    "next_frame": "nextFrame",
    "previous_edit": "prevCutPoint",
    "next_edit": "nextCutPoint",
    "track_height_down": "tracksHeightDown",
    "track_height_up": "tracksHeightUp",
    "zoom_out": "zoomOut",
    "zoom_in": "zoomIn",
    "zoom_fit": "quicklyAdjustZoomFit",
    "scroll_vertical": "scrollTrackV",
    "scroll_horizontal": "scrollTrackH",
    "previous_marker": "prevTimeMark",
    "next_marker": "nextTimeMark",
    # Jianying exposes audio recording and screen/camera video recording as
    # separate commands. The MVP "Record" action means timeline audio record.
    "record": "audioRecord",
    "export": "exportVideo",
}

COMMAND_ALIASES = {
    "timeline_start": "previous_frame",
    "timeline_end": "next_frame",
}

MAC_MODIFIERS = {
    "Ctrl": "⌘",
    "Control": "^",
    "Cmd": "⌘",
    "Command": "⌘",
    "Meta": "⌘",
    "Alt": "⌥",
    "Option": "⌥",
    "Shift": "⇧",
}

WINDOWS_MODIFIERS = {
    "Control": "Ctrl",
    "Cmd": "Ctrl",
    "Command": "Ctrl",
    "Meta": "Ctrl",
    "Option": "Alt",
}

MAC_KEYS = {
    "Backspace": "Delete",
    "Del": "Delete",
    "Plus": "=",
    "Minus": "-",
}

WINDOWS_KEYS = {
    "Del": "Delete",
    "Plus": "=",
    "Minus": "-",
}


@dataclass(frozen=True)
class DetectedBinding:
    command: str
    internal_command: str
    raw: str
    mac: str
    windows: str


@dataclass(frozen=True)
class ShortcutSnapshot:
    available: bool = False
    profile: str = ""
    config_version: str = ""
    bindings: dict = field(default_factory=dict)
    config_dir: str = ""
    error: str = ""


def _tokenize(sequence):
    """Split modifiers from the final key, including values such as Ctrl++."""
    remaining = str(sequence or "").strip()
    modifiers = []
    known = set(MAC_MODIFIERS) | set(WINDOWS_MODIFIERS) | {"Ctrl", "Alt", "Shift"}
    while "+" in remaining:
        candidate, tail = remaining.split("+", 1)
        if candidate not in known:
            break
        modifiers.append(candidate)
        remaining = tail
    return modifiers, remaining or "+"


def _candidate_score(sequence):
    value = str(sequence or "")
    if not value:
        return 1000
    score = 0
    if "MouseButton" in value or "Wheel" in value or value.endswith("_hold"):
        score += 100
    if value.endswith("++"):
        score += 10
    if any(ord(character) > 127 for character in value):
        score += 5
    return score


def _select_sequence(values):
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return ""
    candidates = [str(value).strip() for value in values if str(value).strip()]
    if not candidates:
        return ""
    return min(enumerate(candidates), key=lambda item: (_candidate_score(item[1]), item[0]))[1]


def _mac_hotkey(sequence):
    modifiers, key = _tokenize(sequence)
    rendered = [MAC_MODIFIERS.get(modifier, modifier) for modifier in modifiers]
    rendered.append(MAC_KEYS.get(key, key))
    return " ".join(rendered)


def _windows_hotkey(sequence):
    modifiers, key = _tokenize(sequence)
    rendered = [WINDOWS_MODIFIERS.get(modifier, modifier) for modifier in modifiers]
    rendered.append(WINDOWS_KEYS.get(key, key))
    return "+".join(rendered)


class JianyingShortcutProvider:
    """Load the active shortcut profile without changing Jianying files."""

    def __init__(self, config_dir=None):
        self._configured_dir = Path(config_dir).expanduser() if config_dir else None
        self._lock = RLock()
        self._fingerprint_value = None
        self._snapshot_value = ShortcutSnapshot()

    def _candidate_directories(self):
        if self._configured_dir:
            return [self._configured_dir]

        configured = os.environ.get("JY_SHORTCUT_CONFIG_DIR")
        if configured:
            return [Path(configured).expanduser()]

        candidates = []
        home = Path.home()
        if sys.platform == "darwin":
            candidates.extend((
                home / "Movies/JianyingPro/User Data/Config",
                home / "Library/Containers/com.lemon.lvpro/Data/Movies/JianyingPro/User Data/Config",
            ))
        elif sys.platform == "win32":
            local_app_data = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
            candidates.extend((
                local_app_data / "JianyingPro/User Data/Config",
                local_app_data / "JianyingPro/Config",
            ))

        unique = []
        seen = set()
        for candidate in candidates:
            value = str(candidate)
            if value not in seen:
                seen.add(value)
                unique.append(candidate)
        return unique

    def _find_config_dir(self):
        for directory in self._candidate_directories():
            if (directory / "Shortcut/combined.json").is_file():
                return directory
        return self._configured_dir

    @staticmethod
    def _fingerprint(directory):
        values = []
        for path in (directory / "keymapSettings", directory / "Shortcut/combined.json"):
            try:
                stat = path.stat()
                values.append((str(path), stat.st_mtime_ns, stat.st_size))
            except OSError:
                values.append((str(path), 0, 0))
        return tuple(values)

    @staticmethod
    def _read_settings(path):
        parser = ConfigParser()
        parser.read(path, encoding="utf-8")
        return {
            "current": parser.get("General", "currentKeymapIndex", fallback="0").strip(),
            "version": parser.get("General", "configVersion", fallback="").strip(),
        }

    @staticmethod
    def _active_profile(profiles, current):
        if current in profiles:
            return current
        ordered = [name for name in PROFILE_ORDER if name in profiles]
        ordered.extend(name for name in profiles if name not in ordered)
        try:
            index = int(current)
        except (TypeError, ValueError):
            index = 0
        if not ordered:
            return ""
        if index < 0 or index >= len(ordered):
            index = 0
        return ordered[index]

    @staticmethod
    def _bindings(sequence):
        bindings = {}
        for command, internal_command in COMMAND_IDS.items():
            selected = _select_sequence(sequence.get(internal_command))
            if not selected:
                continue
            bindings[command] = DetectedBinding(
                command=command,
                internal_command=internal_command,
                raw=selected,
                mac=_mac_hotkey(selected),
                windows=_windows_hotkey(selected),
            )
        return bindings

    def snapshot(self, force=False):
        with self._lock:
            directory = self._find_config_dir()
            if directory is None:
                self._snapshot_value = ShortcutSnapshot(error="shortcut config directory not found")
                return self._snapshot_value

            fingerprint = self._fingerprint(directory)
            if not force and fingerprint == self._fingerprint_value:
                return self._snapshot_value

            try:
                settings_path = directory / "keymapSettings"
                settings = self._read_settings(settings_path) if settings_path.is_file() else {"current": "0", "version": ""}
                profiles = json.loads((directory / "Shortcut/combined.json").read_text(encoding="utf-8"))
                if not isinstance(profiles, dict):
                    raise ValueError("shortcut profiles must be a JSON object")
                profile = self._active_profile(profiles, settings["current"])
                profile_data = profiles.get(profile) or {}
                if not isinstance(profile_data, dict):
                    raise ValueError("active shortcut profile must be a JSON object")
                sequence = profile_data.get("sequence") or {}
                if not isinstance(sequence, dict):
                    raise ValueError("active shortcut profile has no sequence map")
                snapshot = ShortcutSnapshot(
                    available=True,
                    profile=profile,
                    config_version=settings["version"],
                    bindings=self._bindings(sequence),
                    config_dir=str(directory),
                )
            except (OSError, ValueError, TypeError, ConfigError) as exc:
                snapshot = ShortcutSnapshot(config_dir=str(directory), error=str(exc))
                if self._snapshot_value.available:
                    return self._snapshot_value
            else:
                self._fingerprint_value = fingerprint
            self._snapshot_value = snapshot
            return snapshot

    def binding_for(self, command, snapshot=None):
        canonical = COMMAND_ALIASES.get(str(command or ""), str(command or ""))
        state = snapshot or self.snapshot()
        return state.bindings.get(canonical) if state.available else None
