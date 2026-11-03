"""Mouse-path execution helpers for wheel diameter gestures."""

from .config import WHEEL_DIAMETER_OUTER_CONTROL_JUMP_SETTLE_SECONDS
from .wheel_diameter_logs import wheel_diameter_adjust_log_message
from .wheel_state_diameter_payloads import wheel_diameter_drag_repress_payload


def wheel_diameter_execute_mouse_path(
    area_name,
    drag,
    drag_source,
    signed_radius,
    target_signed_radius,
    max_radius,
    axis_angle,
    target_control_angle,
    center_crossing,
    target_x,
    target_y,
    target_outer_x,
    target_outer_y,
    start_reference_x,
    start_reference_y,
    mouse_plan,
    cursor_start_x,
    cursor_start_y,
    logical_start_x,
    logical_start_y,
    mouse_drag_begin_fn,
    mouse_drag_move_absolute_path_fn,
    mouse_drag_end_fn,
    get_cursor_position_fn,
    release_wheel_drag_fn,
    clear_wheel_drag_state_fn,
):
    input_dx = mouse_plan['input_dx']
    input_dy = mouse_plan['input_dy']
    mouse_input_dx = mouse_plan['mouse_input_dx']
    mouse_input_dy = mouse_plan['mouse_input_dy']
    drag_duration = mouse_plan['drag_duration']
    drag_mode = mouse_plan['drag_mode']
    move_path = mouse_plan['move_path']
    outer_control_crossing = mouse_plan['outer_control_crossing']
    center_repress_crossing = mouse_plan.get('center_repress_crossing')
    center_bypass_crossing = mouse_plan.get('center_bypass_crossing')

    moved = False
    cursor_end_x = cursor_start_x
    cursor_end_y = cursor_start_y
    try:
        if center_bypass_crossing:
            bypass_press_x = mouse_plan.get('center_bypass_press_x', cursor_start_x)
            bypass_press_y = mouse_plan.get('center_bypass_press_y', cursor_start_y)
            print(
                f"diameter center-cross bypass reanchor {area_name}: "
                f"press=({bypass_press_x:.0f},{bypass_press_y:.0f}) "
                f"target=({target_x:.0f},{target_y:.0f})"
            )
            if drag.get('button_down', True):
                mouse_drag_end_fn(
                    cursor_start_x,
                    cursor_start_y,
                    pre_delay=0.0,
                    post_delay=0.018,
                )
                drag['button_down'] = False
            if not mouse_drag_begin_fn(bypass_press_x, bypass_press_y):
                clear_wheel_drag_state_fn()
                return {'ok': False}
            drag.update(wheel_diameter_drag_repress_payload(
                bypass_press_x,
                bypass_press_y,
                bypass_press_x,
                bypass_press_y,
            ))
            cursor_start_x = bypass_press_x
            cursor_start_y = bypass_press_y
        elif center_repress_crossing:
            repress_press_x = mouse_plan.get('center_repress_press_x', target_x)
            repress_press_y = mouse_plan.get('center_repress_press_y', target_y)
            print(
                f"diameter center-cross repress {area_name}: "
                f"press=({repress_press_x:.0f},{repress_press_y:.0f}) "
                f"target=({target_x:.0f},{target_y:.0f})"
            )
            if drag.get('button_down', True):
                mouse_drag_end_fn(
                    cursor_start_x,
                    cursor_start_y,
                    pre_delay=0.0,
                    post_delay=0.018,
                )
                drag['button_down'] = False
            if not mouse_drag_begin_fn(repress_press_x, repress_press_y):
                clear_wheel_drag_state_fn()
                return {'ok': False}
            drag.update(wheel_diameter_drag_repress_payload(
                repress_press_x,
                repress_press_y,
                target_x,
                target_y,
            ))
            cursor_start_x = repress_press_x
            cursor_start_y = repress_press_y
        elif mouse_plan.get('cursor_reanchor') and not outer_control_crossing:
            raw_cursor_start_x = mouse_plan.get('raw_cursor_start_x', cursor_start_x)
            raw_cursor_start_y = mouse_plan.get('raw_cursor_start_y', cursor_start_y)
            print(
                f"diameter cursor reanchor {area_name}: "
                f"reason={mouse_plan.get('cursor_reanchor_reason')} "
                f"raw=({raw_cursor_start_x:.0f},{raw_cursor_start_y:.0f}) "
                f"anchor=({cursor_start_x:.0f},{cursor_start_y:.0f}) "
                f"axis_drift={mouse_plan.get('cursor_axis_drift', 0.0):.1f} "
                f"distance={mouse_plan.get('cursor_anchor_distance', 0.0):.1f}"
            )
            if drag.get('button_down', True):
                mouse_drag_end_fn(
                    raw_cursor_start_x,
                    raw_cursor_start_y,
                    pre_delay=0.0,
                    post_delay=0.015,
                )
                drag['button_down'] = False
            if not mouse_drag_begin_fn(cursor_start_x, cursor_start_y):
                clear_wheel_drag_state_fn()
                return {'ok': False}
            drag.update(wheel_diameter_drag_repress_payload(
                cursor_start_x,
                cursor_start_y,
                cursor_start_x,
                cursor_start_y,
            ))
            drag['logical_start_x'] = logical_start_x
            drag['logical_start_y'] = logical_start_y
        elif mouse_plan.get('cursor_reanchor_suppressed') and not outer_control_crossing:
            raw_cursor_start_x = mouse_plan.get('raw_cursor_start_x', cursor_start_x)
            raw_cursor_start_y = mouse_plan.get('raw_cursor_start_y', cursor_start_y)
            anchor_x = mouse_plan.get('cursor_anchor_x', cursor_start_x)
            anchor_y = mouse_plan.get('cursor_anchor_y', cursor_start_y)
            print(
                f"diameter cursor reanchor skipped {area_name}: "
                f"reason={mouse_plan.get('cursor_reanchor_suppressed')} "
                f"raw=({raw_cursor_start_x:.0f},{raw_cursor_start_y:.0f}) "
                f"anchor=({anchor_x:.0f},{anchor_y:.0f}) "
                f"anchor_radius={mouse_plan.get('cursor_anchor_radius', 0.0):.1f} "
                f"axis_drift={mouse_plan.get('cursor_axis_drift', 0.0):.1f} "
                f"distance={mouse_plan.get('cursor_anchor_distance', 0.0):.1f}"
            )
        if outer_control_crossing:
            mouse_drag_end_fn(
                cursor_start_x,
                cursor_start_y,
                pre_delay=0.0,
                post_delay=WHEEL_DIAMETER_OUTER_CONTROL_JUMP_SETTLE_SECONDS,
            )
            drag['button_down'] = False
            if not mouse_drag_begin_fn(target_x, target_y):
                clear_wheel_drag_state_fn()
                return {'ok': False}
            drag.update(wheel_diameter_drag_repress_payload(
                target_x,
                target_y,
                target_x,
                target_y,
            ))
            cursor_start_x = target_x
            cursor_start_y = target_y
        print(wheel_diameter_adjust_log_message(
            area_name,
            drag_source,
            drag_mode,
            signed_radius,
            target_signed_radius,
            max_radius,
            axis_angle,
            target_control_angle,
            center_crossing,
            input_dx,
            input_dy,
            mouse_input_dx,
            mouse_input_dy,
            target_outer_x,
            target_outer_y,
            logical_start_x,
            logical_start_y,
            drag.get('safe_press_used'),
            drag.get('axis_lock_source'),
            cursor_start_x,
            cursor_start_y,
            drag.get('press_x', start_reference_x),
            drag.get('press_y', start_reference_y),
        ))
        moved = mouse_drag_move_absolute_path_fn(
            move_path,
            duration=drag_duration,
        )
        cursor_end_x, cursor_end_y = get_cursor_position_fn()
        drag['x'] = cursor_end_x
        drag['y'] = cursor_end_y
        drag['button_down'] = True
    except Exception:
        release_wheel_drag_fn()
        raise

    return {
        'ok': True,
        'moved': moved,
        'cursor_start_x': cursor_start_x,
        'cursor_start_y': cursor_start_y,
        'cursor_end_x': cursor_end_x,
        'cursor_end_y': cursor_end_y,
    }


__all__ = ['wheel_diameter_execute_mouse_path']
