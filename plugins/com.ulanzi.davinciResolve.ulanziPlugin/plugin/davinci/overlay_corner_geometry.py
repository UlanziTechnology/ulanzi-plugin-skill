"""Shared corner-marker geometry for overlay painters."""


def overlay_corner_geometry(width, height, corner_length, corner_width, corner_inset):
    min_dim = max(1, min(int(width), int(height)))
    base_inset = max(2, int(corner_width))
    default_inset = base_inset + int(corner_inset)

    if min_dim < 36:
        inset = max(base_inset + 1, min(5, int(round(min_dim * 0.14))))
        corner_len = min(int(corner_length), max(4, int(round(min_dim * 0.18))))
    elif min_dim < default_inset * 2 + 8:
        inset = max(base_inset + 1, min(6, int(round(min_dim * 0.15))))
        corner_len = min(int(corner_length), max(5, int(round(min_dim * 0.20))))
    else:
        inset = default_inset
        corner_len = min(int(corner_length), max(8, min_dim // 4))

    max_len = max(1, min_dim - inset * 2)
    corner_len = max(1, min(corner_len, max_len))
    return inset, inset + corner_len


__all__ = ['overlay_corner_geometry']
