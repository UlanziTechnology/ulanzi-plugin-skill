"""DaVinci window/title matching helpers used by UI discovery."""

import os

from .config import WHEEL_LABEL_ALIASES


BROWSER_PROCESS_NAMES = {
    'chrome.exe',
    'msedge.exe',
    'firefox.exe',
    'brave.exe',
    'larkshell.exe',
    'lark.exe',
}

RESOLVE_PROCESS_NAMES = {'resolve.exe', 'davinciresolve.exe'}


def score_davinci_title(title):
    lowered = (title or '').lower()
    if not lowered:
        return 0

    if 'ulanzi' in lowered or 'pyattachdavinci' in lowered or 'pyattatchdavinci' in lowered:
        return 0
    if 'google chrome' in lowered or 'microsoft edge' in lowered or 'firefox' in lowered:
        return 0

    if 'davinci resolve' in lowered:
        return 100
    if 'resolve studio' in lowered:
        return 90
    if 'blackmagic' in lowered and 'resolve' in lowered:
        return 80
    return 0


def is_davinci_title(title):
    return score_davinci_title(title) > 0


def score_davinci_process(title, process_path):
    title_score = score_davinci_title(title)
    if not title_score:
        return 0

    process_name = os.path.basename(process_path or '').lower()
    if process_name in BROWSER_PROCESS_NAMES:
        return 0
    if process_name in RESOLVE_PROCESS_NAMES:
        return title_score + 1000
    return title_score


def score_davinci_window(
    window,
    title,
    *,
    is_windows,
    win32_available,
    get_window_process_path_fn,
):
    title_score = score_davinci_title(title)
    if not title_score:
        return 0

    if is_windows and win32_available:
        try:
            process_path = get_window_process_path_fn(int(window.handle))
        except Exception:
            process_path = ''
        return score_davinci_process(title, process_path)

    return title_score


def score_davinci_window_info(window_info, get_window_process_path_fn):
    process_path = get_window_process_path_fn(int(window_info.get('hwnd', 0)))
    return score_davinci_process(window_info.get('title', ''), process_path)


def canonical_wheel_name(text):
    for canonical, aliases in WHEEL_LABEL_ALIASES.items():
        if text in aliases:
            return canonical
    return text


def get_window_handle(window):
    try:
        return int(window.handle)
    except Exception:
        return 0


def is_window_visible(window, user32):
    try:
        hwnd = get_window_handle(window)
        if hwnd:
            return bool(user32.IsWindowVisible(hwnd))
    except Exception:
        pass

    try:
        if hasattr(window, 'is_visible') and not window.is_visible():
            return False
    except Exception:
        pass

    try:
        hwnd = get_window_handle(window)
        return bool(user32.IsWindowVisible(hwnd))
    except Exception:
        pass

    try:
        rect = window.rectangle()
        return rect.width() > 0 and rect.height() > 0
    except Exception:
        return False
