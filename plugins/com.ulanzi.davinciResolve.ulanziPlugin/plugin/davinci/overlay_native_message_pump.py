"""Win32 overlay message-pump helper."""


def pump_win32_messages(
    limit=50,
    *,
    is_windows,
    win32_available,
    user32,
    ctypes_module,
    msg_cls,
    pm_remove,
):
    if not (is_windows and win32_available and user32 and msg_cls):
        return

    msg = msg_cls()
    count = 0
    while count < limit and user32.PeekMessageW(ctypes_module.byref(msg), None, 0, 0, pm_remove):
        user32.TranslateMessage(ctypes_module.byref(msg))
        user32.DispatchMessageW(ctypes_module.byref(msg))
        count += 1


__all__ = ['pump_win32_messages']
