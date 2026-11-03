"""Target, mouse feedback, retry, and finish orchestration."""

from .feedback import execute_diameter_target
from .finalize import finish_diameter_session
from .target import build_diameter_target


def _target_stage(
    area,
    ticks,
    preparation,
    active_context,
    runtime,
    sensitivity,
):
    return build_diameter_target(
        area,
        ticks,
        preparation,
        active_context,
        runtime,
        sensitivity,
    )


def _execute_stage(area, preparation, active_context, target_context, runtime):
    return execute_diameter_target(
        area,
        preparation,
        active_context,
        target_context,
        runtime,
    )


def _finish_stage(
    area,
    preparation,
    active_context,
    target_context,
    feedback_context,
    runtime,
):
    return finish_diameter_session(
        area,
        preparation,
        active_context,
        target_context,
        feedback_context,
        runtime,
    )


def run_active_diameter_session(
    area,
    ticks,
    preparation,
    active_context,
    runtime,
    sensitivity,
):
    target_context = _target_stage(
        area,
        ticks,
        preparation,
        active_context,
        runtime,
        sensitivity,
    )
    if target_context['done']:
        return True

    feedback_context = _execute_stage(
        area,
        preparation,
        active_context,
        target_context,
        runtime,
    )
    if not feedback_context['ok']:
        return False
    return _finish_stage(
        area,
        preparation,
        active_context,
        target_context,
        feedback_context,
        runtime,
    )


__all__ = ['run_active_diameter_session']
