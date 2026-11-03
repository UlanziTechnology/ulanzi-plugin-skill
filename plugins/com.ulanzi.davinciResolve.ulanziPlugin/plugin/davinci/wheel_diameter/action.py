"""Public entrypoint for wheel diameter push/pull gestures."""

from .flow import run_active_diameter_session
from .runtime import WheelDiameterRuntime
from .session import begin_or_reuse_diameter_drag, prepare_diameter_session


def handle_wheel_diameter_rotate(
    area,
    ticks,
    runtime: WheelDiameterRuntime,
    sensitivity,
):
    if ticks == 0:
        return False

    preparation = prepare_diameter_session(area, runtime)
    active_context = begin_or_reuse_diameter_drag(
        area,
        ticks,
        preparation,
        runtime,
        sensitivity,
    )
    if not active_context['ok']:
        return False
    if active_context['done']:
        return True
    return run_active_diameter_session(
        area,
        ticks,
        preparation,
        active_context,
        runtime,
        sensitivity,
    )


__all__ = ['handle_wheel_diameter_rotate']
