"""Timeline mode definitions and action settings normalization."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TimelineMode:
    id: str
    title_en: str
    title_zh: str
    short_en: str
    short_zh: str


MODE_DEFINITIONS = (
    TimelineMode("frame_step", "Previous / next frame", "上一帧 / 下一帧", "Frame", "逐帧"),
    TimelineMode("track_height", "Track height", "轨道高度", "Track", "轨高"),
    TimelineMode("timeline_zoom", "Timeline zoom", "时间线缩放", "Zoom", "缩放"),
    TimelineMode("vertical_scroll", "Timeline vertical scroll", "时间线上下滚动", "V Scroll", "上下"),
    TimelineMode("horizontal_scroll", "Timeline horizontal scroll", "时间线左右滚动", "H Scroll", "左右"),
    TimelineMode("playhead_seconds", "Playhead large step", "时间轴前后移动", "Seconds", "秒移"),
)
MODE_IDS = tuple(mode.id for mode in MODE_DEFINITIONS)
MODE_BY_ID = {mode.id: mode for mode in MODE_DEFINITIONS}

MODE_FEEDBACK_ICONS = {
    "frame_step": "resources/timeline-mode-frame-step.svg",
    "track_height": "resources/timeline-mode-track-height.svg",
    "timeline_zoom": "resources/timeline-mode-zoom.svg",
    "vertical_scroll": "resources/timeline-mode-vertical-scroll.svg",
    "horizontal_scroll": "resources/timeline-mode-horizontal-scroll.svg",
    "playhead_seconds": "resources/timeline-mode-playhead-seconds.svg",
}

MODE_LOCALIZATIONS = {
    "zh_hk": {
        "frame_step": ("上一幀 / 下一幀", "逐幀"),
        "track_height": ("軌道高度", "軌高"),
        "timeline_zoom": ("時間線縮放", "縮放"),
        "vertical_scroll": ("時間線上下捲動", "上下"),
        "horizontal_scroll": ("時間線左右捲動", "左右"),
        "playhead_seconds": ("播放頭大步移動", "秒移"),
    },
    "ja_jp": {
        "frame_step": ("前 / 次のフレーム", "フレーム"),
        "track_height": ("トラックの高さ", "トラック"),
        "timeline_zoom": ("タイムラインズーム", "ズーム"),
        "vertical_scroll": ("タイムライン縦スクロール", "縦"),
        "horizontal_scroll": ("タイムライン横スクロール", "横"),
        "playhead_seconds": ("再生ヘッドの大移動", "秒移動"),
    },
    "de_de": {
        "frame_step": ("Vorheriger / nächster Frame", "Frame"),
        "track_height": ("Spurhöhe", "Spur"),
        "timeline_zoom": ("Timeline-Zoom", "Zoom"),
        "vertical_scroll": ("Timeline vertikal scrollen", "Vert."),
        "horizontal_scroll": ("Timeline horizontal scrollen", "Horiz."),
        "playhead_seconds": ("Abspielkopf-Großschritt", "Sek."),
    },
    "es_es": {
        "frame_step": ("Fotograma anterior / siguiente", "Fotog."),
        "track_height": ("Altura de pista", "Pista"),
        "timeline_zoom": ("Zoom de línea de tiempo", "Zoom"),
        "vertical_scroll": ("Desplazamiento vertical", "Vert."),
        "horizontal_scroll": ("Desplazamiento horizontal", "Horiz."),
        "playhead_seconds": ("Salto grande del cabezal", "Seg."),
    },
    "ko_kr": {
        "frame_step": ("이전 / 다음 프레임", "프레임"),
        "track_height": ("트랙 높이", "트랙"),
        "timeline_zoom": ("타임라인 확대/축소", "확대"),
        "vertical_scroll": ("타임라인 세로 스크롤", "세로"),
        "horizontal_scroll": ("타임라인 가로 스크롤", "가로"),
        "playhead_seconds": ("재생 헤드 크게 이동", "초 이동"),
    },
    "pt_pt": {
        "frame_step": ("Fotograma anterior / seguinte", "Fotog."),
        "track_height": ("Altura da faixa", "Faixa"),
        "timeline_zoom": ("Zoom da linha temporal", "Zoom"),
        "vertical_scroll": ("Deslocamento vertical", "Vert."),
        "horizontal_scroll": ("Deslocamento horizontal", "Horiz."),
        "playhead_seconds": ("Avanço amplo do cursor", "Seg."),
    },
}

VALID_BACKENDS = ("auto", "scripting", "tcp", "keyboard")
SECONDS_PER_TICK_OPTIONS = (1, 5, 10, 30)
SCROLL_SENSITIVITY_OPTIONS = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0)

DEFAULT_TIMELINE_SETTINGS = {
    "mode": "frame_step",
    "backend": "auto",
    "seconds_per_tick": 1,
    "scroll_sensitivity": 1.0,
    "require_resolve_focus": True,
    "invert_direction": False,
    "settings_version": 1,
}


def _as_bool(value, fallback):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
    if value in (0, 1):
        return bool(value)
    return fallback


def normalize_timeline_settings(settings, current=None):
    normalized = DEFAULT_TIMELINE_SETTINGS.copy()
    if current:
        normalized.update(current)
    incoming = settings or {}

    mode = incoming.get("mode", normalized["mode"])
    normalized["mode"] = mode if mode in MODE_IDS else DEFAULT_TIMELINE_SETTINGS["mode"]

    backend = incoming.get("backend", normalized["backend"])
    normalized["backend"] = backend if backend in VALID_BACKENDS else "auto"

    try:
        seconds = int(incoming.get("seconds_per_tick", normalized["seconds_per_tick"]))
    except (TypeError, ValueError):
        seconds = DEFAULT_TIMELINE_SETTINGS["seconds_per_tick"]
    normalized["seconds_per_tick"] = min(
        SECONDS_PER_TICK_OPTIONS,
        key=lambda option: abs(option - seconds),
    )

    try:
        sensitivity = float(incoming.get("scroll_sensitivity", normalized["scroll_sensitivity"]))
    except (TypeError, ValueError):
        sensitivity = DEFAULT_TIMELINE_SETTINGS["scroll_sensitivity"]
    normalized["scroll_sensitivity"] = min(
        SCROLL_SENSITIVITY_OPTIONS,
        key=lambda option: abs(option - sensitivity),
    )

    normalized["require_resolve_focus"] = _as_bool(
        incoming.get("require_resolve_focus", normalized["require_resolve_focus"]),
        normalized["require_resolve_focus"],
    )
    normalized["invert_direction"] = _as_bool(
        incoming.get("invert_direction", normalized["invert_direction"]),
        normalized["invert_direction"],
    )
    normalized["settings_version"] = DEFAULT_TIMELINE_SETTINGS["settings_version"]
    return normalized


def localized_mode(mode_id, language="en", short=False):
    mode = MODE_BY_ID.get(mode_id, MODE_DEFINITIONS[0])
    language_key = str(language or "").strip().lower().replace("-", "_")
    if language_key in MODE_LOCALIZATIONS:
        full_title, short_title = MODE_LOCALIZATIONS[language_key][mode.id]
        return short_title if short else full_title
    is_zh = language_key.startswith("zh")
    if short:
        return mode.short_zh if is_zh else mode.short_en
    return mode.title_zh if is_zh else mode.title_en


def feedback_icon(mode_id):
    """Return the plugin-relative feedback icon for a timeline mode."""
    return MODE_FEEDBACK_ICONS.get(mode_id, MODE_FEEDBACK_ICONS[MODE_IDS[0]])


__all__ = [
    "TimelineMode",
    "MODE_DEFINITIONS",
    "MODE_IDS",
    "MODE_BY_ID",
    "MODE_LOCALIZATIONS",
    "MODE_FEEDBACK_ICONS",
    "VALID_BACKENDS",
    "SECONDS_PER_TICK_OPTIONS",
    "SCROLL_SENSITIVITY_OPTIONS",
    "DEFAULT_TIMELINE_SETTINGS",
    "normalize_timeline_settings",
    "localized_mode",
    "feedback_icon",
]
