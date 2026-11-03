"""Fallback wheel-handle builders used when the real dot is unavailable."""

import math
import time


def make_center_fallback_handle(area, wheel_geometry=None, source='center_fallback'):
    if wheel_geometry:
        center_x = wheel_geometry['wheel_center_x']
        center_y = wheel_geometry['wheel_center_y']
        visual_center_x = wheel_geometry.get('visual_center_x', center_x)
        visual_center_y = wheel_geometry.get('visual_center_y', center_y)
        wheel_radius = wheel_geometry['wheel_radius']
    elif area:
        center_x = area.get('center_x', area['x'] + area['w'] / 2)
        center_y = area.get('center_y', area['y'] + area['h'] / 2)
        visual_center_x = center_x
        visual_center_y = center_y
        wheel_radius = min(area['w'], area['h']) / 2
    else:
        return None

    return {
        'x': float(center_x),
        'y': float(center_y),
        'count': 0,
        'score': None,
        'source': source,
        'center_fallback': True,
        'wheel_center_x': float(center_x),
        'wheel_center_y': float(center_y),
        'visual_center_x': float(visual_center_x),
        'visual_center_y': float(visual_center_y),
        'wheel_radius': float(wheel_radius),
        'angle': -math.pi / 2,
        'radial_axis_angle': -math.pi / 2,
        'signed_radius': 0.0,
        'radius': 0.0,
        'updated_at': time.time(),
    }


__all__ = ['make_center_fallback_handle']
