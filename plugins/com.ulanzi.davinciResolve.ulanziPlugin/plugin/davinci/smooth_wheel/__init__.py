"""Platform-neutral continuous color-wheel gesture core.

This package promotes the behavior validated in ``tourbox-wheel-lab`` 0.1.20
into the formal-plugin candidate.  It deliberately owns only geometry,
lossless scheduling, pointer-lifecycle events, and cadence gain.  DaVinci
recognition and native mouse injection remain adapter responsibilities.
"""

from .engine import (
    EngineSnapshot,
    GestureConfig,
    GestureEngine,
    GestureMode,
    GestureRunner,
    StepResult,
)
from .geometry import MotionResult, Vec2, WheelModel
from .motion import CadenceGain
from .sinks import (
    GestureSink,
    MotionFrame,
    MotionAwareGestureSink,
    MotionObservationSink,
    PointerEvent,
    PointerEventKind,
    RecordingSink,
    TransportStep,
    TransportAwareGestureSink,
)

SOURCE_LAB_VERSION = "0.1.20"

__all__ = [
    "CadenceGain",
    "EngineSnapshot",
    "GestureConfig",
    "GestureEngine",
    "GestureMode",
    "GestureRunner",
    "GestureSink",
    "MotionFrame",
    "MotionAwareGestureSink",
    "MotionObservationSink",
    "MotionResult",
    "PointerEvent",
    "PointerEventKind",
    "RecordingSink",
    "SOURCE_LAB_VERSION",
    "StepResult",
    "TransportStep",
    "TransportAwareGestureSink",
    "Vec2",
    "WheelModel",
]
