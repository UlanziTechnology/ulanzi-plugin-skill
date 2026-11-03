"""DaVinci application/window state helpers for label discovery."""


DAVINCI_RESOLVE_BUNDLE_ID = "com.blackmagic-design.DaVinciResolve"


def find_macos_resolve_application(*, running_application_cls=None, workspace_cls=None):
    """Find the live Resolve process without relying only on NSWorkspace's cache."""
    if running_application_cls is not None:
        try:
            matches = running_application_cls.runningApplicationsWithBundleIdentifier_(
                DAVINCI_RESOLVE_BUNDLE_ID
            ) or []
        except Exception:
            matches = []
        for app in matches:
            try:
                if app.isTerminated():
                    continue
            except Exception:
                pass
            return app

    if workspace_cls is None:
        return None

    try:
        applications = workspace_cls.sharedWorkspace().runningApplications()
    except Exception:
        return None

    for app in applications:
        try:
            bundle_id = str(app.bundleIdentifier() or '').lower()
            name = str(app.localizedName() or '').lower()
        except Exception:
            continue
        if (
            bundle_id == DAVINCI_RESOLVE_BUNDLE_ID.lower()
            or 'blackmagic-design.davinciresolve' in bundle_id
            or 'davinci resolve' in name
        ):
            try:
                if app.isTerminated():
                    continue
            except Exception:
                pass
            return app
    return None


def find_davinci_app(
    finder,
    *,
    is_windows,
    win32_available,
    windows_uia_available,
    user32_obj,
    is_mac,
    davinci_available,
    desktop_cls,
    workspace_cls,
    running_application_cls,
    find_windows_by_title_fn,
    score_window_info_fn,
    get_window_process_id_fn,
):
    if is_windows:
        if not windows_uia_available or desktop_cls is None:
            return False

        print("[init] searching DaVinci window (Win32)...", flush=True)
        candidates = find_windows_by_title_fn({'davinci', 'resolve', 'blackmagic'})
        scored_candidates = []
        for info in candidates:
            score = score_window_info_fn(info)
            if score:
                scored_candidates.append((score, info))

        for _score, info in sorted(scored_candidates, key=lambda item: item[0], reverse=True):
            try:
                _x, _y, width, height = info['frame']
                if width <= 0 or height <= 0:
                    continue
            except Exception:
                continue

            try:
                hwnd = int(info['hwnd'])
                desktop = desktop_cls(backend='uia')
                window = desktop.window(handle=hwnd)
            except Exception as exc:
                print(f"[init] UIA attach DaVinci window failed: {exc}", flush=True)
                continue

            if is_cached_hwnd_alive(
                finder,
                hwnd=hwnd,
                is_windows=is_windows,
                win32_available=win32_available,
                user32_obj=user32_obj,
            ):
                finder.target_app = window
                finder.uia_window = window
                finder.target_hwnd = hwnd
                finder.target_pid = get_window_process_id_fn(hwnd)
                print(f"[init] found DaVinci window: {info['title']}", flush=True)
                return True

        print("[init] Win32 did not find DaVinci; waiting for the next retry.", flush=True)
        return False

    if (
        not is_mac
        or not davinci_available
        or (workspace_cls is None and running_application_cls is None)
    ):
        return False

    app = find_macos_resolve_application(
        running_application_cls=running_application_cls,
        workspace_cls=workspace_cls,
    )
    if app is None:
        return False
    finder.target_app = app
    return True


def clear_windows_target_cache(finder):
    finder.target_hwnd = 0
    finder.target_pid = 0


def is_cached_hwnd_alive(
    finder,
    hwnd=None,
    *,
    is_windows,
    win32_available,
    user32_obj=None,
):
    if not is_windows or not win32_available or user32_obj is None:
        return False

    hwnd = int(hwnd or finder.target_hwnd or 0)
    if not hwnd:
        return False

    try:
        return bool(user32_obj.IsWindow(hwnd)) and bool(user32_obj.IsWindowVisible(hwnd))
    except Exception:
        return False


def is_app_running(
    finder,
    *,
    is_windows,
    win32_available,
    user32_obj,
    is_mac,
    davinci_available,
    workspace_cls,
    running_application_cls,
    get_window_process_id_fn,
):
    if is_windows:
        if is_cached_hwnd_alive(
            finder,
            is_windows=is_windows,
            win32_available=win32_available,
            user32_obj=user32_obj,
        ):
            if not finder.target_pid:
                finder.target_pid = get_window_process_id_fn(finder.target_hwnd)
            return True
        clear_windows_target_cache(finder)
        return False

    if not is_mac or not davinci_available:
        return False

    app = find_macos_resolve_application(
        running_application_cls=running_application_cls,
        workspace_cls=workspace_cls,
    )
    if app is not None:
        finder.target_app = app
        return True

    if not finder.target_app or workspace_cls is None:
        return False

    try:
        if finder.target_app.isTerminated():
            return False
        target_pid = finder.target_app.processIdentifier()
    except Exception:
        return False

    workspace = workspace_cls.sharedWorkspace()
    for app in workspace.runningApplications():
        try:
            if app.processIdentifier() == target_pid:
                return True
        except Exception:
            continue
    return False


def is_frontmost(
    finder,
    *,
    is_windows,
    win32_available,
    user32_obj,
    is_mac,
    davinci_available,
    workspace_cls,
    running_application_cls,
    get_window_process_id_fn,
):
    if is_windows:
        if not is_app_running(
            finder,
            is_windows=is_windows,
            win32_available=win32_available,
            user32_obj=user32_obj,
            is_mac=is_mac,
            davinci_available=davinci_available,
            workspace_cls=workspace_cls,
            running_application_cls=running_application_cls,
            get_window_process_id_fn=get_window_process_id_fn,
        ):
            return False
        try:
            foreground_hwnd = user32_obj.GetForegroundWindow()
            if not foreground_hwnd:
                return False
            foreground_pid = get_window_process_id_fn(foreground_hwnd)
            return (
                foreground_hwnd == finder.target_hwnd
                or (bool(finder.target_pid) and foreground_pid == finder.target_pid)
            )
        except Exception:
            return False

    if not is_app_running(
        finder,
        is_windows=is_windows,
        win32_available=win32_available,
        user32_obj=user32_obj,
        is_mac=is_mac,
        davinci_available=davinci_available,
        workspace_cls=workspace_cls,
        running_application_cls=running_application_cls,
        get_window_process_id_fn=get_window_process_id_fn,
    ):
        return False

    try:
        workspace = workspace_cls.sharedWorkspace()
        front_app = workspace.frontmostApplication()
        if front_app is None:
            return False
        return front_app.processIdentifier() == finder.target_app.processIdentifier()
    except Exception:
        return False


def initialize_ax(
    finder,
    *,
    is_windows,
    ax_create_application_fn,
):
    if not finder.find_davinci_app():
        return False, "DaVinci Resolve not found"

    if is_windows:
        finder.refresh_main_window()
        if not finder.main_win:
            return False, "Unable to get DaVinci Resolve main window"
        return True, None

    pid = finder.target_app.processIdentifier()
    finder.ax_app = ax_create_application_fn(pid)

    finder.refresh_main_window()
    if not finder.main_win:
        return False, "Unable to get main window"

    return True, None


def refresh_main_window(
    finder,
    *,
    is_windows,
    ax_create_application_fn,
    get_attr_fn,
):
    if not finder.is_app_running():
        finder.ax_app = None
        finder.main_win = None
        finder.uia_window = None
        finder.labels = []
        return None

    if is_windows:
        finder.uia_window = finder.target_app
        finder.main_win = finder.uia_window
        return finder.main_win

    if not finder.ax_app:
        finder.ax_app = ax_create_application_fn(finder.target_app.processIdentifier())

    finder.main_win = get_attr_fn(finder.ax_app, 'AXMainWindow')
    if not finder.main_win:
        windows = get_attr_fn(finder.ax_app, 'AXWindows')
        finder.main_win = windows[0] if windows else None
    return finder.main_win


__all__ = [
    'DAVINCI_RESOLVE_BUNDLE_ID',
    'clear_windows_target_cache',
    'find_davinci_app',
    'find_macos_resolve_application',
    'initialize_ax',
    'is_app_running',
    'is_cached_hwnd_alive',
    'is_frontmost',
    'refresh_main_window',
]
