#!/usr/bin/env python3
"""
DaVinci Color Wheels Action for Ulanzi Plugin

实现功能：
1. 检测 Label 位置，计算 Label 下方的正方形区域
2. 鼠标进入该区域时显示 Overlay，移出后隐藏
3. 在区域内检测 3x3 调节点，移动到调节点进行控制
"""

import sys
import os
import time
import threading
import platform
import warnings
import ctypes
from functools import partial

from davinci import platform_windows_native as win32_native

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)

warnings.filterwarnings('ignore', category=SyntaxWarning)

# 添加依赖路径
_qt_scanner_path = os.path.join(os.path.dirname(__file__), '..', '..', 'qt_component_scanner')
if os.path.exists(_qt_scanner_path):
    sys.path.insert(0, _qt_scanner_path)

PLATFORM_NAME = platform.system()
IS_MAC = PLATFORM_NAME == 'Darwin'
IS_WINDOWS = PLATFORM_NAME == 'Windows'
MAC_DEPENDENCY_HINT = (
    "开源示例不附带 PyQt5/Qt，请按插件 README.md 在匹配的 Python 环境中安装依赖，"
    "并在 macOS 系统设置中授予辅助功能和屏幕录制权限。"
)

DAVINCI_AVAILABLE = False
DAVINCI_DEPENDENCY_MESSAGE = "当前平台暂不支持 DaVinci 轮盘控制"
WINDOWS_UIA_AVAILABLE = False
WINDOWS_UIA_MESSAGE = None
WIN32_AVAILABLE = IS_WINDOWS and win32_native.AVAILABLE
TKINTER_AVAILABLE = False
WIN32_OVERLAY_AVAILABLE = False
UI_BACKEND = "none"
_main_thread_callbacks = {}
_main_thread_callback_sequence = 0
_main_thread_callbacks_lock = threading.Lock()

if IS_MAC:
    try:
        from AppKit import NSRunningApplication, NSWorkspace, NSEvent, NSScreen
        from ApplicationServices import (
            AXUIElementCreateApplication,
            AXUIElementCopyAttributeValue,
            AXUIElementPerformAction,
            AXUIElementSetMessagingTimeout,
            AXIsProcessTrusted,
            kAXPressAction,
        )
        from Quartz import (
            CGEventCreate,
            CGEventCreateMouseEvent,
            CGEventGetLocation,
            CGEventPost,
            CGSessionCopyCurrentDictionary,
            kCGHIDEventTap,
            kCGEventMouseMoved,
            kCGEventLeftMouseDown,
            kCGEventLeftMouseUp,
            kCGEventLeftMouseDragged,
        )
        DAVINCI_AVAILABLE = True
        DAVINCI_DEPENDENCY_MESSAGE = None
    except ImportError as e:
        DAVINCI_DEPENDENCY_MESSAGE = f"macOS DaVinci 依赖不可用：{e}；{MAC_DEPENDENCY_HINT}"
elif IS_WINDOWS:
    if WIN32_AVAILABLE:
        try:
            from pywinauto import Desktop
            WINDOWS_UIA_AVAILABLE = True
            DAVINCI_AVAILABLE = True
            DAVINCI_DEPENDENCY_MESSAGE = None
        except ImportError:
            WINDOWS_UIA_MESSAGE = "Windows UIA 依赖缺失：请运行 `python3 -m pip install pywinauto`"
            DAVINCI_DEPENDENCY_MESSAGE = WINDOWS_UIA_MESSAGE
    else:
        DAVINCI_DEPENDENCY_MESSAGE = "Windows Win32 API 不可用"

# 导入 PyQt5。Windows 可使用 tkinter overlay，因此 PyQt5 只在 macOS 上是必需依赖。
try:
    from PyQt5.QtWidgets import QApplication, QWidget
    from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QRectF, QByteArray
    from PyQt5.QtGui import QPainter, QColor, QPen, QImage
    from PyQt5.QtSvg import QSvgRenderer
    PYQT_AVAILABLE = True
    UI_BACKEND = "PyQt5"
except ImportError as e:
    PYQT_AVAILABLE = False
    if IS_MAC:
        print(f"Warning: PyQt5 not available: {e}")
        if DAVINCI_DEPENDENCY_MESSAGE is None:
            DAVINCI_DEPENDENCY_MESSAGE = f"macOS overlay 依赖不可用：{e}；{MAC_DEPENDENCY_HINT}"
    if IS_WINDOWS:
        try:
            import tkinter as tk
            TKINTER_AVAILABLE = True
            UI_BACKEND = "tkinter"
        except ImportError:
            if WIN32_AVAILABLE:
                WIN32_OVERLAY_AVAILABLE = True
                UI_BACKEND = "win32"
            else:
                UI_BACKEND = "none"

    class _UnavailableSignal:
        def __init__(self):
            self._callbacks = []

        def connect(self, callback):
            self._callbacks.append(callback)

        def emit(self, *args, **kwargs):
            global _main_thread_callback_sequence
            queued_at = time.perf_counter()
            with _main_thread_callbacks_lock:
                for callback in list(self._callbacks):
                    if args and isinstance(args[0], bool):
                        _main_thread_callback_sequence += 1
                        key = (callback, _main_thread_callback_sequence)
                    else:
                        key = callback
                    _main_thread_callbacks[key] = (callback, args, kwargs, queued_at)

    def pyqtSignal(*_args, **_kwargs):
        return _UnavailableSignal()

    class _UnavailableQtObject:
        def __init__(self, *_args, **_kwargs):
            pass

        def __getattr__(self, _name):
            def _noop(*_args, **_kwargs):
                return None
            return _noop

    class _UnavailableApplication(_UnavailableQtObject):
        @staticmethod
        def instance():
            return None

    class _UnavailableThread(_UnavailableQtObject):
        def __init__(self, *_args, **_kwargs):
            super().__init__()
            self._thread = None

        def start(self):
            self._thread = threading.Thread(target=self.run, daemon=True)
            self._thread.start()

        def wait(self):
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=1)

    class _UnavailableTimer(_UnavailableQtObject):
        def __init__(self, *_args, **_kwargs):
            self.timeout = _UnavailableSignal()

        def start(self, *_args, **_kwargs):
            return None

        def stop(self):
            return None

    QApplication = _UnavailableApplication
    QWidget = _UnavailableQtObject
    QThread = _UnavailableThread
    QTimer = _UnavailableTimer
    QPainter = _UnavailableQtObject
    QColor = _UnavailableQtObject
    QPen = _UnavailableQtObject
    QImage = _UnavailableQtObject
    QByteArray = _UnavailableQtObject
    QSvgRenderer = _UnavailableQtObject
    QRectF = _UnavailableQtObject
    Qt = _UnavailableQtObject()

OVERLAY_AVAILABLE = PYQT_AVAILABLE or TKINTER_AVAILABLE or WIN32_OVERLAY_AVAILABLE

from davinci.config import (
    AX_TEXT_ATTRIBUTES,
    DAVINCI_STATE_CHECK_INTERVAL_MS,
    DEBUG_CALLBACK_LATENCY_MS,
    DEBUG_CALLBACK_PROCESS_MS,
    DEBUG_LOOP_GAP_MS,
    DEBUG_SLOW_LOG_ENABLED,
    DEBUG_STATE_CHECK_MS,
    DEBUG_TK_UPDATE_MS,
    HOVER_POLL_INTERVAL_MS,
    OVERLAY_CORNER_ACTIVE_COLOR,
    OVERLAY_CORNER_COLOR,
    OVERLAY_CORNER_INSET,
    OVERLAY_CORNER_LENGTH,
    OVERLAY_CORNER_WIDTH,
    OVERLAY_FORCE_WIN32_NATIVE_DEFAULT,
    OVERLAY_NATIVE_USE_PER_PIXEL_ALPHA,
    OVERLAY_WHEEL_DOT_RADIUS,
    OVERLAY_WHEEL_DOT_SVG_TEMPLATE,
    TOURBOX_PROBE_EXTRA_INFO,
    create_wheel_manager_config,
)
from davinci.action_runtime import create_davinci_wheel_action_class
from davinci.label_finder import create_label_finder_class
from davinci.manager import (
    DaVinciManagerRuntime,
    create_davinci_wheel_manager_class,
)
from davinci.monitor_thread import create_monitor_thread_class
from davinci.overlay_colors import _argb_from_hex, _colorref_from_hex
from davinci.overlay_event_loop import process_overlay_events_cycle
from davinci.overlay_native_bindings import OverlayNativeBindings
from davinci.overlay_native_message_pump import pump_win32_messages
from davinci.overlay_native_alpha_paint import (
    draw_native_alpha_corners,
    draw_native_alpha_wheel_state,
    redraw_native_alpha_dot,
    redraw_native_alpha_overlay,
)
from davinci.overlay_native_paint import (
    draw_native_filled_ellipse,
    paint_native_overlay,
    redraw_native_overlay_window,
)
from davinci.overlay_native_runtime import OverlayNativeRuntime
from davinci.overlay_qt_paint import paint_qt_overlay
from davinci.overlay_tk_root import TkRootProvider
from davinci.overlay_tk_paint import redraw_tk_overlay
from davinci.overlay_windowing import (
    apply_tk_click_through,
    create_native_overlay_window,
    create_tk_overlay,
    initialize_overlay_backend,
    setup_qt_overlay_window,
)
from davinci.overlay_window_visibility import (
    delete_native_overlay,
    delete_tk_overlay,
    hide_native_overlay,
    hide_native_dot_window,
    hide_tk_overlay,
    refresh_overlay_surface,
    show_native_overlay,
    show_tk_overlay,
    update_overlay_geometry,
)
from davinci.platform_mouse_button_state import (
    PluginMouseButtonState,
    is_left_mouse_button_down as platform_is_left_mouse_button_down,
)
from davinci.platform_mouse_actions import PlatformMouseActions
from davinci.platform_mouse_input import PlatformMouseInput
from davinci.platform_screen_capture import PlatformScreenCapture
from davinci.platform_tourbox_input import TourBoxMouseInput
from davinci.platform_window_info import Win32WindowInfoAdapter
from davinci.smooth_wheel.backend import create_manager_smooth_wheel_backend
from davinci.wheel_detection_adapter import WheelDetectionAdapter
from davinci.manager.state import wheel_release_state_callbacks
from davinci.wheel_area_overlay import create_wheel_area_overlay_class
from davinci.wheel_visual_paint import wheel_state_for_paint


# ============== 配置 ==============

OVERLAY_FORCE_WIN32_NATIVE = OVERLAY_FORCE_WIN32_NATIVE_DEFAULT and IS_WINDOWS and WIN32_AVAILABLE
if OVERLAY_FORCE_WIN32_NATIVE:
    WIN32_OVERLAY_AVAILABLE = True
    UI_BACKEND = "win32-native"
def debug_slow(message):
    if DEBUG_SLOW_LOG_ENABLED:
        print(f"[wheel-debug {time.strftime('%H:%M:%S')}] {message}")

_plugin_mouse_button_state = PluginMouseButtonState(time.time)


def create_mac_ax_application(pid):
    element = AXUIElementCreateApplication(pid)
    AXUIElementSetMessagingTimeout(element, 2.0)
    return element


def is_mac_screen_locked():
    try:
        session = CGSessionCopyCurrentDictionary() or {}
        return bool(session.get('CGSSessionScreenIsLocked'))
    except Exception:
        return False


def is_left_mouse_button_down():
    return platform_is_left_mouse_button_down(
        is_windows=IS_WINDOWS,
        win32_available=WIN32_AVAILABLE,
        user32=win32_native.user32,
        vk_lbutton=win32_native.VK_LBUTTON,
        is_mac=IS_MAC,
        davinci_available=DAVINCI_AVAILABLE,
        nsevent=NSEvent if IS_MAC and DAVINCI_AVAILABLE else None,
    )

_tk_root_provider = TkRootProvider()
_native_overlay_class_name = f'UlanziDavinciOverlay_{os.getpid()}'
_native_overlay_runtime = (
    OverlayNativeRuntime(
        is_windows=IS_WINDOWS,
        win32_available=WIN32_AVAILABLE,
        user32=win32_native.user32,
        kernel32=win32_native.kernel32,
        ctypes_module=ctypes,
        wndproc_cls=win32_native.WNDPROC,
        wndclass_cls=win32_native.WNDCLASS,
        paintstruct_cls=win32_native.PAINTSTRUCT,
        gdiplus=win32_native.gdiplus,
        gdiplus_startup_input_cls=win32_native.GdiplusStartupInput,
        class_name=_native_overlay_class_name,
        wm_nchittest=win32_native.WM_NCHITTEST,
        httransparent=win32_native.HTTRANSPARENT,
        wm_erasebkgnd=win32_native.WM_ERASEBKGND,
        wm_paint=win32_native.WM_PAINT,
        cs_hredraw=win32_native.CS_HREDRAW,
        cs_vredraw=win32_native.CS_VREDRAW,
    )
    if WIN32_AVAILABLE
    else None
)


_overlay_native_bindings = OverlayNativeBindings(
    ensure_gdiplus_fn=_native_overlay_runtime.ensure_gdiplus,
    gdiplus=win32_native.gdiplus,
    gdi32=win32_native.gdi32,
    user32=win32_native.user32,
    kernel32=win32_native.kernel32,
    ctypes_module=ctypes,
    bitmap_info_cls=win32_native.BITMAPINFO,
    bitmap_info_header_cls=win32_native.BITMAPINFOHEADER,
    point_cls=win32_native.POINT,
    size_cls=win32_native.SIZE,
    blend_function_cls=win32_native.BLENDFUNCTION,
    bi_rgb=win32_native.BI_RGB,
    dib_rgb_colors=win32_native.DIB_RGB_COLORS,
    smoothing_mode=win32_native.GDIP_SMOOTHING_MODE_ANTIALIAS,
    pixel_offset_mode=win32_native.GDIP_PIXEL_OFFSET_MODE_HALF,
    ac_src_over=win32_native.AC_SRC_OVER,
    ac_src_alpha=win32_native.AC_SRC_ALPHA,
    ulw_alpha=win32_native.ULW_ALPHA,
    argb_from_hex_fn=_argb_from_hex,
    dot_radius=OVERLAY_WHEEL_DOT_RADIUS,
    sw_hide=win32_native.SW_HIDE,
    sw_shownoactivate=win32_native.SW_SHOWNOACTIVATE,
    hwnd_topmost=win32_native.HWND_TOPMOST,
    swp_nomove=win32_native.SWP_NOMOVE,
    swp_nosize=win32_native.SWP_NOSIZE,
    swp_noactivate=win32_native.SWP_NOACTIVATE,
    swp_showwindow=win32_native.SWP_SHOWWINDOW,
    instances=_native_overlay_runtime.instances,
    ensure_class_fn=_native_overlay_runtime.ensure_class,
    native_use_per_pixel_alpha=OVERLAY_NATIVE_USE_PER_PIXEL_ALPHA,
    class_name=_native_overlay_class_name,
    ws_ex_layered=win32_native.WS_EX_LAYERED,
    ws_ex_transparent=win32_native.WS_EX_TRANSPARENT,
    ws_ex_topmost=win32_native.WS_EX_TOPMOST,
    ws_ex_toolwindow=win32_native.WS_EX_TOOLWINDOW,
    ws_ex_noactivate=win32_native.WS_EX_NOACTIVATE,
    ws_popup=win32_native.WS_POPUP,
    lwa_colorkey=win32_native.LWA_COLORKEY,
) if WIN32_AVAILABLE else None


_pump_win32_messages = partial(
    pump_win32_messages,
    is_windows=IS_WINDOWS,
    win32_available=WIN32_AVAILABLE,
    user32=win32_native.user32,
    ctypes_module=ctypes,
    msg_cls=win32_native.MSG,
    pm_remove=win32_native.PM_REMOVE,
)


_platform_mouse_input = PlatformMouseInput(
    is_windows=IS_WINDOWS,
    is_mac=IS_MAC,
    davinci_available=DAVINCI_AVAILABLE,
    win32_available=WIN32_AVAILABLE,
    user32=win32_native.user32,
    ctypes_module=ctypes,
    point_cls=win32_native.POINT,
    nsevent=globals().get('NSEvent'),
    nsscreen=globals().get('NSScreen'),
    cg_event_create=globals().get('CGEventCreate'),
    cg_event_get_location=globals().get('CGEventGetLocation'),
    cg_event_create_mouse_event=globals().get('CGEventCreateMouseEvent'),
    cg_event_post=globals().get('CGEventPost'),
    k_cg_hid_event_tap=globals().get('kCGHIDEventTap'),
    k_mouse_moved=globals().get('kCGEventMouseMoved'),
    k_left_down=globals().get('kCGEventLeftMouseDown'),
    k_left_up=globals().get('kCGEventLeftMouseUp'),
    k_left_dragged=globals().get('kCGEventLeftMouseDragged'),
    tourbox_mouse_input_cls=TourBoxMouseInput,
    input_cls=win32_native.INPUT,
    mouseinput_cls=win32_native.MOUSEINPUT,
    input_mouse=win32_native.INPUT_MOUSE,
    move_flag=win32_native.MOUSEEVENTF_MOVE,
    left_down_flag=win32_native.MOUSEEVENTF_LEFTDOWN,
    left_up_flag=win32_native.MOUSEEVENTF_LEFTUP,
    absolute_flag=win32_native.MOUSEEVENTF_ABSOLUTE,
    virtual_desktop_flag=win32_native.MOUSEEVENTF_VIRTUALDESK,
    mark_button_down_fn=_plugin_mouse_button_state.mark_down,
    mark_button_up_fn=_plugin_mouse_button_state.mark_up,
    default_extra_info=TOURBOX_PROBE_EXTRA_INFO,
)

_win32_window_info = Win32WindowInfoAdapter(
    is_available=WIN32_AVAILABLE,
    user32=win32_native.user32,
    kernel32=win32_native.kernel32,
    ctypes_module=ctypes,
    wintypes_module=win32_native.wintypes,
    rect_cls=win32_native.RECT,
    enum_windows_proc_cls=win32_native.EnumWindowsProc,
    process_query_limited_information=(
        win32_native.PROCESS_QUERY_LIMITED_INFORMATION
    ),
)

_platform_screen_capture = PlatformScreenCapture(
    is_windows=IS_WINDOWS,
    win32_available=WIN32_AVAILABLE,
    pyqt_available=PYQT_AVAILABLE,
    user32=win32_native.user32,
    gdi32=win32_native.gdi32,
    ctypes_module=ctypes,
    bitmap_info_cls=win32_native.BITMAPINFO,
    bitmap_info_header_cls=win32_native.BITMAPINFOHEADER,
    q_application_cls=QApplication,
    q_image_cls=QImage,
    sys_argv=sys.argv,
    srccopy=win32_native.SRCCOPY,
    captureblt=win32_native.CAPTUREBLT,
    bi_rgb=win32_native.BI_RGB,
    dib_rgb_colors=win32_native.DIB_RGB_COLORS,
)

_platform_mouse_actions = PlatformMouseActions(_platform_mouse_input)
mouse_drag_begin = _platform_mouse_actions.mouse_drag_begin
mouse_drag_move = _platform_mouse_actions.mouse_drag_move
mouse_drag_move_absolute = _platform_mouse_actions.mouse_drag_move_absolute
mouse_drag_move_by = _platform_mouse_actions.mouse_drag_move_by
mouse_drag_end = _platform_mouse_actions.mouse_drag_end
mouse_click = _platform_mouse_actions.mouse_click
mouse_drag_move_path = _platform_mouse_actions.mouse_drag_move_path
mouse_drag_move_absolute_path = _platform_mouse_actions.mouse_drag_move_absolute_path
mouse_drag_move_by_path = _platform_mouse_actions.mouse_drag_move_by_path


_wheel_detection_adapter = WheelDetectionAdapter(_platform_screen_capture.capture_region, debug_slow)

WheelAreaOverlay = create_wheel_area_overlay_class(
    widget_cls=QWidget,
    sys_platform=sys.platform,
    force_win32_native=OVERLAY_FORCE_WIN32_NATIVE,
    is_windows=IS_WINDOWS,
    win32_available=WIN32_AVAILABLE,
    tkinter_available=TKINTER_AVAILABLE,
    win32_overlay_available=WIN32_OVERLAY_AVAILABLE,
    pyqt_available=PYQT_AVAILABLE,
    tk_root_provider=_tk_root_provider,
    tk_module=globals().get('tk'),
    tk_error_cls=getattr(globals().get('tk'), 'TclError', Exception),
    native_bindings=_overlay_native_bindings,
    native_runtime=_native_overlay_runtime,
    user32=win32_native.user32,
    gdi32=win32_native.gdi32,
    gdiplus=win32_native.gdiplus,
    ctypes_module=ctypes,
    rect_cls=win32_native.RECT,
    qt_cls=Qt,
    c_void_p_cls=ctypes.c_void_p,
    q_painter_cls=QPainter,
    q_color_cls=QColor,
    q_pen_cls=QPen,
    q_svg_renderer_cls=QSvgRenderer,
    q_byte_array_cls=QByteArray,
    q_rectf_cls=QRectF,
    overlay_native_use_per_pixel_alpha=OVERLAY_NATIVE_USE_PER_PIXEL_ALPHA,
    wheel_dot_radius=OVERLAY_WHEEL_DOT_RADIUS,
    wheel_dot_svg_template=OVERLAY_WHEEL_DOT_SVG_TEMPLATE,
    corner_length=OVERLAY_CORNER_LENGTH,
    corner_width=OVERLAY_CORNER_WIDTH,
    corner_inset=OVERLAY_CORNER_INSET,
    corner_active_color=OVERLAY_CORNER_ACTIVE_COLOR,
    corner_color=OVERLAY_CORNER_COLOR,
    hwnd_topmost=win32_native.HWND_TOPMOST,
    sw_hide=win32_native.SW_HIDE,
    swp_noactivate=win32_native.SWP_NOACTIVATE,
    swp_showwindow=win32_native.SWP_SHOWWINDOW,
    get_window_long_fn=win32_native.get_window_long,
    set_window_long_fn=win32_native.set_window_long,
    gwl_exstyle=win32_native.GWL_EXSTYLE,
    ws_ex_layered=win32_native.WS_EX_LAYERED,
    ws_ex_transparent=win32_native.WS_EX_TRANSPARENT,
    ws_ex_topmost=win32_native.WS_EX_TOPMOST,
    ws_ex_toolwindow=win32_native.WS_EX_TOOLWINDOW,
    ws_ex_noactivate=win32_native.WS_EX_NOACTIVATE,
    lwa_colorkey=win32_native.LWA_COLORKEY,
    swp_nomove=win32_native.SWP_NOMOVE,
    swp_nosize=win32_native.SWP_NOSIZE,
    ps_solid=win32_native.PS_SOLID,
    gdip_unit_pixel=win32_native.GDIP_UNIT_PIXEL,
)

LabelFinder = create_label_finder_class(
    is_windows=IS_WINDOWS,
    win32_available=WIN32_AVAILABLE,
    windows_uia_available=WINDOWS_UIA_AVAILABLE,
    user32_obj=win32_native.user32,
    is_mac=IS_MAC,
    davinci_available=DAVINCI_AVAILABLE,
    desktop_cls=(Desktop if WINDOWS_UIA_AVAILABLE else None),
    workspace_cls=(NSWorkspace if IS_MAC and DAVINCI_AVAILABLE else None),
    running_application_cls=(
        NSRunningApplication if IS_MAC and DAVINCI_AVAILABLE else None
    ),
    ax_create_application_fn=(
        create_mac_ax_application if IS_MAC and DAVINCI_AVAILABLE else None
    ),
    ax_perform_action_fn=(
        AXUIElementPerformAction if IS_MAC and DAVINCI_AVAILABLE else None
    ),
    ax_copy_attribute_value_fn=(
        AXUIElementCopyAttributeValue if IS_MAC and DAVINCI_AVAILABLE else None
    ),
    press_action=(kAXPressAction if IS_MAC and DAVINCI_AVAILABLE else None),
    ax_text_attributes=AX_TEXT_ATTRIBUTES,
    win32_window_info=_win32_window_info,
    platform_mouse_input=_platform_mouse_input,
    wheel_detection_adapter=_wheel_detection_adapter,
    debug_slow_fn=debug_slow,
    sleep_fn=time.sleep,
)

MonitorThread = create_monitor_thread_class(
    qthread_cls=QThread,
    signal_factory=pyqtSignal,
    hover_poll_interval_ms=HOVER_POLL_INTERVAL_MS,
    davinci_state_check_interval_ms=DAVINCI_STATE_CHECK_INTERVAL_MS,
    get_cursor_position_fn=_platform_mouse_input.get_cursor_position,
    is_left_mouse_button_down_fn=is_left_mouse_button_down,
    plugin_mouse_button_active_fn=_plugin_mouse_button_state.active,
    debug_slow_fn=debug_slow,
    debug_loop_gap_ms=DEBUG_LOOP_GAP_MS,
    debug_state_check_ms=DEBUG_STATE_CHECK_MS,
)


def process_overlay_events():
    return process_overlay_events_cycle(
        _main_thread_callbacks,
        _main_thread_callbacks_lock,
        _tk_root_provider.root,
        time_module=time,
        tkinter_available=TKINTER_AVAILABLE,
        tk_error_cls=tk.TclError if TKINTER_AVAILABLE else Exception,
        win32_overlay_available=WIN32_OVERLAY_AVAILABLE,
        pump_win32_messages_fn=_pump_win32_messages,
        debug_slow_fn=debug_slow,
        debug_callback_latency_ms=DEBUG_CALLBACK_LATENCY_MS,
        debug_callback_process_ms=DEBUG_CALLBACK_PROCESS_MS,
        debug_tk_update_ms=DEBUG_TK_UPDATE_MS,
    )


def detect_wheel_circle_in_area(area):
    return _wheel_detection_adapter.detect_wheel_circle_in_area(area)


def detect_handle_in_area(
    area_x,
    area_y,
    area_w,
    area_h=None,
    wheel_geometry=None,
    expected_handle=None,
    expected_axis=None,
):
    """
    在指定区域内检测 3x3 调节点

    Returns:
        dict: {'x': screen_x, 'y': screen_y} 或 None
    """
    return _wheel_detection_adapter.detect_handle_in_area(
        area_x,
        area_y,
        area_w,
        area_h=area_h,
        wheel_geometry=wheel_geometry,
        expected_handle=expected_handle,
        expected_axis=expected_axis,
    )


# ============== DaVinci Wheel Action ==============

_manager_runtime = DaVinciManagerRuntime(
    config=create_wheel_manager_config(IS_WINDOWS),
    davinci_available=DAVINCI_AVAILABLE,
    davinci_dependency_message=DAVINCI_DEPENDENCY_MESSAGE,
    overlay_available=OVERLAY_AVAILABLE,
    is_mac=IS_MAC,
    is_windows=IS_WINDOWS,
    win32_available=WIN32_AVAILABLE,
    win32_overlay_available=WIN32_OVERLAY_AVAILABLE,
    overlay_force_win32_native=OVERLAY_FORCE_WIN32_NATIVE,
    pyqt_available=PYQT_AVAILABLE,
    qapplication_cls=QApplication,
    qtimer_cls=QTimer,
    argv=sys.argv,
    label_finder_factory=LabelFinder,
    monitor_thread_factory=MonitorThread,
    overlay_factory=WheelAreaOverlay,
    platform_mouse_input=_platform_mouse_input,
    platform_mouse_actions=_platform_mouse_actions,
    wheel_detection_adapter=_wheel_detection_adapter,
    plugin_mouse_button_state=_plugin_mouse_button_state,
    pump_win32_messages=_pump_win32_messages,
    process_overlay_events=process_overlay_events,
    is_left_mouse_button_down=is_left_mouse_button_down,
    is_mac_screen_locked=(is_mac_screen_locked if IS_MAC else None),
    ax_is_process_trusted=(
        AXIsProcessTrusted if IS_MAC and DAVINCI_AVAILABLE else None
    ),
    debug_slow=debug_slow,
    smooth_wheel_backend_factory=(
        partial(
            create_manager_smooth_wheel_backend,
            platform_name=PLATFORM_NAME,
            plugin_mouse_button_state=_plugin_mouse_button_state,
            debug_slow_fn=debug_slow,
            diagnostics_enabled=True,
        )
        if IS_MAC or IS_WINDOWS
        else None
    ),
)
DaVinciWheelManager = create_davinci_wheel_manager_class(_manager_runtime)
wheel_manager = DaVinciWheelManager()
DaVinciWheelAction = create_davinci_wheel_action_class(
    wheel_manager=wheel_manager,
    threading_module=threading,
    time_module=time,
    mouse_drag_end_fn=mouse_drag_end,
    get_cursor_position_fn=(
        _platform_mouse_input.get_cursor_position
    ),
    set_cursor_position_fn=_platform_mouse_input.set_cursor_position,
    debug_slow_fn=debug_slow,
)
