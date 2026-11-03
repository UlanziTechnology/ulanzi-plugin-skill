"""SMPTE timecode arithmetic, including 29.97/59.94 drop-frame."""

import math
import re


_TIMECODE_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})([:;])(\d{2})$")


def nominal_fps(frame_rate):
    value = float(frame_rate or 0)
    if value <= 0:
        raise ValueError("frame rate must be positive")
    return int(math.floor(value + 0.5))


def parse_timecode(value):
    match = _TIMECODE_RE.match(str(value or "").strip())
    if not match:
        raise ValueError(f"invalid timecode: {value!r}")
    hour, minute, second, separator, frame = match.groups()
    return int(hour), int(minute), int(second), int(frame), separator == ";"


def _drop_frames_for_rate(frame_rate):
    nominal = nominal_fps(frame_rate)
    if nominal not in (30, 60):
        raise ValueError("drop-frame is valid only for nominal 30/60 fps")
    return 2 if nominal == 30 else 4


def timecode_to_frames(value, frame_rate):
    hour, minute, second, frame, drop_frame = parse_timecode(value)
    nominal = nominal_fps(frame_rate)
    if frame >= nominal or minute >= 60 or second >= 60:
        raise ValueError(f"timecode is outside {nominal} fps range: {value!r}")

    result = ((hour * 3600 + minute * 60 + second) * nominal) + frame
    if drop_frame:
        dropped = _drop_frames_for_rate(frame_rate)
        total_minutes = hour * 60 + minute
        result -= dropped * (total_minutes - total_minutes // 10)
    return result


def frames_to_timecode(frame_number, frame_rate, drop_frame=False):
    nominal = nominal_fps(frame_rate)
    frame_number = max(0, int(frame_number))

    if drop_frame:
        dropped = _drop_frames_for_rate(frame_rate)
        frames_per_10_minutes = nominal * 60 * 10 - dropped * 9
        frames_per_minute = nominal * 60 - dropped
        frames_per_24_hours = (nominal * 3600 - dropped * 54) * 24
        frame_number %= frames_per_24_hours
        ten_minute_blocks, remainder = divmod(frame_number, frames_per_10_minutes)
        adjustment = dropped * 9 * ten_minute_blocks
        if remainder >= dropped:
            adjustment += dropped * ((remainder - dropped) // frames_per_minute)
        timecode_frames = frame_number + adjustment
        separator = ";"
    else:
        timecode_frames = frame_number % (nominal * 3600 * 24)
        separator = ":"

    hour, remainder = divmod(timecode_frames, nominal * 3600)
    minute, remainder = divmod(remainder, nominal * 60)
    second, frame = divmod(remainder, nominal)
    return f"{hour:02d}:{minute:02d}:{second:02d}{separator}{frame:02d}"


def add_frames(value, delta_frames, frame_rate):
    _, _, _, _, drop_frame = parse_timecode(value)
    current = timecode_to_frames(value, frame_rate)
    return frames_to_timecode(current + int(delta_frames), frame_rate, drop_frame=drop_frame)


__all__ = [
    "nominal_fps",
    "parse_timecode",
    "timecode_to_frames",
    "frames_to_timecode",
    "add_frames",
]
