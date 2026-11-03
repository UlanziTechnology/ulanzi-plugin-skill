"""Edge-hold finalization for wheel diameter gestures."""

from .wheel_diameter_final_logic import wheel_diameter_edge_hold_plan
from .wheel_diameter_logs import wheel_diameter_edge_hold_log_message


def wheel_diameter_apply_edge_hold(
    area_name,
    center_x,
    center_y,
    axis_angle,
    moved,
    target_signed_radius,
    final_signed_radius,
    final_x,
    final_y,
    max_radius,
    debug_slow_fn=None,
):
    edge_hold = wheel_diameter_edge_hold_plan(
        moved,
        target_signed_radius,
        final_signed_radius,
        max_radius,
        center_x,
        center_y,
        axis_angle,
    )
    if edge_hold['held']:
        previous_final_signed_radius = edge_hold['previous_final_signed_radius']
        final_signed_radius = edge_hold['final_signed_radius']
        final_x = edge_hold['final_x']
        final_y = edge_hold['final_y']
        if debug_slow_fn:
            debug_slow_fn(wheel_diameter_edge_hold_log_message(
                area_name,
                previous_final_signed_radius,
                target_signed_radius,
                max_radius,
            ))

    return {
        'final_signed_radius': final_signed_radius,
        'final_x': final_x,
        'final_y': final_y,
        'held': edge_hold['held'],
    }


__all__ = ['wheel_diameter_apply_edge_hold']
