#!/usr/bin/env python3
"""
DaVinci Color Wheels - UlanziDeck Python 插件
主服务入口

功能：
1. 实时检测 DaVinci 色轮区域坐标
2. 鼠标进入色轮区域时显示 overlay，移出后隐藏
3. 接收调节事件时模拟鼠标拖拽调整色轮值
"""

import sys
import os
import time
import site
import threading
import json

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)

# 添加 SDK 到路径
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.abspath(os.path.join(PLUGIN_DIR, '..'))
if PLUGIN_DIR in sys.path:
    sys.path.remove(PLUGIN_DIR)
sys.path.insert(0, PLUGIN_DIR)
VENDORED_SITE_PACKAGES = os.path.join(PLUGIN_ROOT, 'site-packages')
if os.path.isdir(VENDORED_SITE_PACKAGES):
    if os.name == 'nt':
        site.addsitedir(VENDORED_SITE_PACKAGES)
    else:
        # Avoid executing Windows-only .pth bootstraps (pywin32) on macOS/Linux.
        sys.path.insert(0, VENDORED_SITE_PACKAGES)

    if os.name == 'nt' and hasattr(os, 'add_dll_directory'):
        pywin32_dll_dir = os.path.join(VENDORED_SITE_PACKAGES, 'pywin32_system32')
        if os.path.isdir(pywin32_dll_dir):
            os.add_dll_directory(pywin32_dll_dir)
    vendor_paths = [
        path for path in sys.path
        if os.path.abspath(path).startswith(VENDORED_SITE_PACKAGES)
    ]
    for path in reversed(vendor_paths):
        sys.path.remove(path)
        sys.path.insert(0, path)

# Ulanzi Studio ships its own macOS Python runtime. Keep its native wheels
# separate from the Windows dependencies bundled in site-packages.
MACOS_SITE_PACKAGES = os.path.join(PLUGIN_ROOT, 'site-packages-macos')
if sys.platform == 'darwin' and os.path.isdir(MACOS_SITE_PACKAGES):
    sys.path.insert(0, MACOS_SITE_PACKAGES)

    qt_plugins = os.path.join(MACOS_SITE_PACKAGES, 'PyQt5', 'Qt5', 'plugins')
    qt_platform_plugins = os.path.join(qt_plugins, 'platforms')
    if os.path.isdir(qt_plugins):
        os.environ['QT_PLUGIN_PATH'] = qt_plugins
    if os.path.isdir(qt_platform_plugins):
        os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = qt_platform_plugins
# The official Python SDK is vendored as a normal ``ulanzi_api`` package.
# Add its parent directory instead of importing the former flat compatibility
# module from ``libs/ulanzi-api``.
sys.path.insert(0, os.path.join(PLUGIN_ROOT, 'libs'))

from ulanzi_api import UlanziApi
from action_routing import (
    PLUGIN_UUID,
    action_kind,
    extract_action_id,
)

try:
    from davinci.timeline import DaVinciTimelineAction
    DAVINCI_TIMELINE_AVAILABLE = True
    DAVINCI_TIMELINE_DEPENDENCY_MESSAGE = None
    print("✅ DaVinci 时间线控制模块已加载")
except ImportError as e:
    DaVinciTimelineAction = None
    DAVINCI_TIMELINE_AVAILABLE = False
    DAVINCI_TIMELINE_DEPENDENCY_MESSAGE = str(e)
    print(f"⚠️  DaVinci 时间线控制模块加载失败: {e}")

# 导入 DaVinci 轮盘控制模块
try:
    from davinci_wheel_action import (
        DaVinciWheelAction,
        wheel_manager,
        DAVINCI_AVAILABLE,
        DAVINCI_DEPENDENCY_MESSAGE,
        OVERLAY_AVAILABLE,
        UI_BACKEND,
        PLATFORM_NAME,
    )
    DAVINCI_WHEEL_AVAILABLE = DAVINCI_AVAILABLE and OVERLAY_AVAILABLE
    status_bits = f"Platform: {PLATFORM_NAME}, DaVinci: {DAVINCI_AVAILABLE}, UI: {UI_BACKEND}"
    if DAVINCI_WHEEL_AVAILABLE:
        print(f"✅ DaVinci 轮盘模块已加载 ({status_bits})")
    else:
        reason = DAVINCI_DEPENDENCY_MESSAGE or "依赖或 UI 后端不可用"
        print(f"✅ DaVinci 轮盘模块已加载 ({status_bits}, Reason: {reason})")
except ImportError as e:
    DAVINCI_WHEEL_AVAILABLE = False
    DAVINCI_DEPENDENCY_MESSAGE = str(e)
    print(f"⚠️  DaVinci 轮盘模块加载失败: {e}")

# 尝试导入 Cython 编译的核心模块
try:
    import core
    print("✅ 已加载 Cython 核心模块 (core.so/core.pyd)")
    CYTHON_AVAILABLE = True
except ImportError:
    print("⚠️  未找到 Cython 核心模块，使用纯 Python 模式")
    CYTHON_AVAILABLE = False

# 创建 API 实例
ud_api = UlanziApi()


def register_ulanzi_handler(registrar):
    """Use the official callback API while keeping handlers directly callable.

    Official ``on_*`` methods return the API instance for fluent chaining. A
    normal Python decorator must return the decorated function, because the
    host integration tests and a few internal fallbacks call these handlers
    directly.
    """
    def decorator(handler):
        registrar(handler)
        return handler

    return decorator

# 缓存每个按键实例的状态
ACTION_CACHES = {}
ACTION_KINDS = {}
DIAL_HOLD_ROTATE_EVENTS_HANDLED = set()
DIAL_PRESS_STATES = {}
DIAL_PRESS_LOCK = threading.Lock()
DIAL_CONTEXT_FALLBACK_WARNED = set()
_SINGLE_INSTANCE_HANDLE = None
_WINDOWS_EXIT_REQUESTED = threading.Event()


def normalized_ulanzi_connect_argv(argv=None):
    """Normalize both host launch argument shapes for the official SDK.

    Current Ulanzi Studio launches ``app.py address port language``. Some
    already-observed host builds insert one opaque argument before ``address``.
    The official SDK intentionally accepts an explicit three-item ``argv``;
    normalize the legacy host shape here so the vendored SDK stays unmodified.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    for start_index in (0, 1):
        if len(args) <= start_index + 1:
            continue

        address = str(args[start_index] or '').strip()
        port = args[start_index + 1]
        try:
            normalized_port = str(int(port))
        except (TypeError, ValueError):
            continue
        if not address:
            continue

        normalized = [address, normalized_port]
        if len(args) > start_index + 2 and args[start_index + 2]:
            normalized.append(str(args[start_index + 2]))
        return normalized
    return []


def acquire_single_instance_lock() -> bool:
    """Prevent duplicate plugin processes from drawing multiple overlays."""
    global _SINGLE_INSTANCE_HANDLE

    if os.name != 'nt':
        return True

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        name = 'Local\\UlanziDavinciResolvePluginSingleInstance'
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            return True

        already_exists = ctypes.get_last_error() == 183
        if already_exists:
            kernel32.CloseHandle(handle)
            print('已有 DaVinci 插件进程在运行，本进程退出以避免重复 overlay。')
            return False

        _SINGLE_INSTANCE_HANDLE = handle
        return True
    except Exception as exc:
        print(f'单实例检测失败，继续启动：{exc}')
        return True


def _dial_press_state(instance, rotated=False):
    return {
        'rotated': bool(rotated),
        'instance': instance,
        'updated_at': time.monotonic(),
    }


def get_dial_press_state(context):
    with DIAL_PRESS_LOCK:
        return DIAL_PRESS_STATES.get(context)


def pop_dial_press_state(context):
    with DIAL_PRESS_LOCK:
        return DIAL_PRESS_STATES.pop(context, None)


def discard_dial_press_state(context=None, instance=None):
    """Forget stale physical-press state without committing a mode preview."""
    removed = []
    with DIAL_PRESS_LOCK:
        for candidate_context, state in list(DIAL_PRESS_STATES.items()):
            if candidate_context == context or (instance is not None and state.get('instance') is instance):
                removed.append(DIAL_PRESS_STATES.pop(candidate_context))
    return removed


def mark_dial_rotated(context, instance=None):
    """Refresh press activity, synthesizing state for hold-only host events."""
    with DIAL_PRESS_LOCK:
        press_state = DIAL_PRESS_STATES.get(context)
        auto_release = getattr(instance, 'dial_auto_release_seconds', None)
        if press_state is None and instance is not None and auto_release:
            press_state = _dial_press_state(instance, rotated=True)
            DIAL_PRESS_STATES[context] = press_state
        elif press_state is not None:
            if press_state.get('instance') is None and instance is not None:
                press_state['instance'] = instance
            press_state['rotated'] = True
            press_state['updated_at'] = time.monotonic()
        return press_state


def finalize_stale_dial_presses(now=None):
    """Recover when Ulanzi omits dialup after a press-and-turn gesture."""
    now = time.monotonic() if now is None else now
    expired = []
    with DIAL_PRESS_LOCK:
        for context, state in list(DIAL_PRESS_STATES.items()):
            instance = state.get('instance')
            timeout_attr = (
                'dial_auto_release_seconds'
                if state.get('rotated')
                else 'dial_auto_cancel_seconds'
            )
            timeout = getattr(instance, timeout_attr, None)
            if not timeout:
                continue
            if now - state.get('updated_at', now) < float(timeout):
                continue
            if DIAL_PRESS_STATES.get(context) is state:
                expired.append((context, DIAL_PRESS_STATES.pop(context)))

    for context, state in expired:
        instance = state.get('instance') or get_dial_action_instance(context)
        rotated = bool(state.get('rotated'))
        if instance and hasattr(instance, 'on_dial_release'):
            instance.on_dial_release(rotated=rotated)
        print(f'旋钮释放事件超时，已自动收尾: {context} (rotated={rotated})')
    return len(expired)

# WebSocket 回调运行在后台线程，Qt/NSApplication 相关逻辑必须回到主线程处理。
DAVINCI_INIT_PENDING = False
DAVINCI_INITIALIZED = False
DAVINCI_CLEANUP_PENDING = False
DAVINCI_LAST_INIT_ATTEMPT = 0.0
DAVINCI_LAST_STATUS_CHECK = 0.0
DAVINCI_LAST_INIT_MESSAGE = None
DAVINCI_INIT_RETRY_INTERVAL_SECONDS = 3.0
DAVINCI_STATUS_CHECK_INTERVAL_SECONDS = 2.0
DAVINCI_PI_STATUS_CHECK_INTERVAL_SECONDS = 1.0
MAIN_LOOP_INTERVAL_SECONDS = 0.01
LAST_ACTIVE_PI_CONTEXT = None
DAVINCI_LAST_PI_STATUS = {}
DAVINCI_LAST_PI_STATUS_CHECK = 0.0


def _davinci_status_payload(context=None):
    """Build a PI-only status payload for the currently selected action."""
    instance = ACTION_CACHES.get(context)
    if instance and hasattr(instance, 'get_status_payload'):
        return instance.get_status_payload()

    if not DAVINCI_WHEEL_AVAILABLE:
        return {
            'type': 'davinci_status',
            'level': 'error',
            'statusKey': 'DaVinci detection unavailable. Please check plugin dependencies.',
        }

    if wheel_manager.label_finder and wheel_manager.label_finder.is_app_running():
        return {
            'type': 'davinci_status',
            'level': 'success',
            'statusKey': 'DaVinci Resolve detected.',
        }

    if DAVINCI_LAST_INIT_MESSAGE:
        message = str(DAVINCI_LAST_INIT_MESSAGE)
        lowered = message.lower()
        not_found_markers = ('not found', 'not detected', '未找到', '未检测到')
        if any(marker in lowered for marker in not_found_markers):
            status_key = 'DaVinci Resolve not detected. Open DaVinci Resolve, then this plugin will reconnect automatically.'
        elif 'color wheels' in lowered or 'color' in lowered:
            status_key = 'DaVinci Resolve detected. Switch to the Color page and open Color Wheels.'
        else:
            status_key = 'DaVinci Resolve is not ready yet. Open DaVinci Resolve and keep the Color page visible.'

        return {
            'type': 'davinci_status',
            'level': 'warn',
            'statusKey': status_key,
        }

    return {
        'type': 'davinci_status',
        'level': 'info',
        'statusKey': 'Checking DaVinci Resolve...',
    }


def send_current_pi_davinci_status(context=None, force: bool = False):
    """Push DaVinci availability only to the active property inspector."""
    global DAVINCI_LAST_PI_STATUS

    target_context = context or LAST_ACTIVE_PI_CONTEXT
    if not target_context:
        return

    payload = _davinci_status_payload(target_context)
    signature = (
        payload.get('type'),
        payload.get('level'),
        payload.get('statusKey'),
        payload.get('mode'),
        payload.get('backend'),
        payload.get('detail'),
    )
    previous_signature = DAVINCI_LAST_PI_STATUS.get(target_context)
    if not force and signature == previous_signature:
        return

    ud_api.send_to_property_inspector(payload, target_context)
    DAVINCI_LAST_PI_STATUS[target_context] = signature
    if signature != previous_signature:
        print(
            'property inspector status',
            f'context={target_context}',
            f'level={payload.get("level")}',
            f'key={payload.get("statusKey")}',
        )


def maybe_send_pi_davinci_status():
    """Rate-limit PI status refreshes from the main loop."""
    global DAVINCI_LAST_PI_STATUS_CHECK

    now = time.time()
    if now - DAVINCI_LAST_PI_STATUS_CHECK < DAVINCI_PI_STATUS_CHECK_INTERVAL_SECONDS:
        return

    DAVINCI_LAST_PI_STATUS_CHECK = now
    send_current_pi_davinci_status()


class HelloAction:
    """Hello Action 实现"""

    def __init__(self, context: str, api: UlanziApi):
        self.context = context
        self.ud_api = api
        self.settings = {}
        self.active = False
        self.click_count = 0

        self.update_icon('default')

    def update_settings(self, settings: dict, action_type: str = 'init'):
        """更新配置参数"""
        self.settings.update(settings)
        self.ud_api.log_message(f'设置已更新：{settings}')

        if 'click_count' in settings:
            self.click_count = settings['click_count']

    def set_active(self, active: bool):
        """设置激活状态"""
        self.active = active
        icon = 'active' if active else 'default'
        self.update_icon(icon)
        self.ud_api.log_message(f'激活状态：{active}')

    def update_icon(self, state: str):
        """更新按键图标"""
        self.ud_api.set_state_icon(self.context, 0)

    def execute(self):
        """执行点击逻辑"""
        if CYTHON_AVAILABLE:
            result = core.process_click_logic({
                'click_count': self.click_count,
                'message': self.settings.get('message', 'Hello World!'),
                'custom_text': self.settings.get('custom_text', '')
            })
            self.click_count = result['click_count']
            message = result['display_message']
            bonus = core.calculate_bonus(self.click_count)
        else:
            self.click_count += 1
            message = self.settings.get('custom_text', '') or self.settings.get('message', 'Hello World!')
            bonus = 0

        self.ud_api.set_settings({'click_count': self.click_count}, self.context)

        if CYTHON_AVAILABLE and bonus > 0:
            self.ud_api.toast(f'{message} (点击 {self.click_count} 次，奖励 +{bonus})')
        else:
            self.ud_api.toast(f'{message} (点击 {self.click_count} 次)')

        self.ud_api.set_state_icon(self.context, 0)
        self.ud_api.log_message(f'执行点击，计数：{self.click_count}')

    def destroy(self):
        """清理资源"""
        self.settings.clear()


def on_set_settings(jsn: dict, action_type: str = 'init'):
    """更新参数"""
    settings = jsn.get('settings') or jsn.get('param', {})
    context = jsn.get('context')
    instance = ACTION_CACHES.get(context)

    if not settings or not instance or settings == {}:
        return

    # A host can occasionally omit dialup after press-and-turn. A settings
    # change is authoritative and must recover the live instance immediately.
    discard_dial_press_state(context=context, instance=instance)
    instance.update_settings(settings, action_type)


def get_dial_action_instance(context: str):
    """Resolve the action that should handle a dial event."""
    instance = ACTION_CACHES.get(context)
    if instance and hasattr(instance, 'on_dial_rotate'):
        return instance

    target_action_id = extract_action_id(
        {'context': context},
        decode_context_fn=ud_api.decode_context,
    )
    matching_actions = []
    dial_actions = []
    for fallback_context, candidate in reversed(list(ACTION_CACHES.items())):
        if not hasattr(candidate, 'on_dial_rotate'):
            continue
        dial_actions.append((fallback_context, candidate))
        candidate_action_id = extract_action_id(
            {'context': fallback_context},
            decode_context_fn=ud_api.decode_context,
        )
        if target_action_id and candidate_action_id == target_action_id:
            matching_actions.append((fallback_context, candidate))

    candidates = matching_actions or (dial_actions if len(dial_actions) == 1 else [])
    if candidates:
        fallback_context, candidate = candidates[0]
        if context and context not in DIAL_CONTEXT_FALLBACK_WARNED:
            print(f'⚠️  旋钮事件 context 未匹配，按 Action UUID 路由: {context} -> {fallback_context}')
            DIAL_CONTEXT_FALLBACK_WARNED.add(context)
        return candidate

    return None


def log_dial_event(kind: str, context: str, ticks, rotate_event=None, handled=None):
    action_count = len(ACTION_CACHES)
    context_state = 'matched' if context in ACTION_CACHES else 'fallback'
    parts = [
        f'dial event {kind}',
        f'context={context or "none"}',
        f'context_state={context_state}',
        f'actions={action_count}',
        f'ticks={ticks}',
    ]
    if rotate_event is not None:
        parts.append(f'rotate_event={rotate_event or "none"}')
    if handled is not None:
        parts.append(f'handled={bool(handled)}')
    print(' '.join(parts))


# ==================== DaVinci 轮盘事件处理 ====================

def on_hover_change(wheel_name):
    """鼠标 hover 变化回调"""
    if wheel_name:
        print(f"🎯 鼠标进入轮盘: {wheel_name}")
    else:
        print("🖱️ 鼠标离开轮盘区域")


def has_davinci_actions():
    """Whether at least one DaVinci wheel action exists on the deck."""
    return bool(DAVINCI_WHEEL_AVAILABLE and wheel_manager.action_contexts)


def request_davinci_init():
    """Ask the main loop to initialize DaVinci when an action needs it."""
    global DAVINCI_INIT_PENDING

    if DAVINCI_WHEEL_AVAILABLE and not DAVINCI_INITIALIZED and has_davinci_actions():
        DAVINCI_INIT_PENDING = True


def initialize_davinci_wheel():
    """在主线程初始化 DaVinci 轮盘管理器"""
    global DAVINCI_INITIALIZED, DAVINCI_LAST_INIT_ATTEMPT, DAVINCI_LAST_INIT_MESSAGE

    if DAVINCI_INITIALIZED or not has_davinci_actions():
        return

    DAVINCI_LAST_INIT_ATTEMPT = time.time()

    if DAVINCI_WHEEL_AVAILABLE:
        success, message = wheel_manager.initialize()
        if success:
            print('\n🔧 初始化 DaVinci 轮盘控制器...')
            print(f'✅ {message}')
            DAVINCI_LAST_INIT_MESSAGE = None
            if has_davinci_actions():
                wheel_manager.start_monitoring(on_hover_callback=on_hover_change)
                DAVINCI_INITIALIZED = True
                send_current_pi_davinci_status()
            else:
                wheel_manager.cleanup()
        else:
            if message != DAVINCI_LAST_INIT_MESSAGE:
                print('\n🔧 初始化 DaVinci 轮盘控制器...')
                print(f'DaVinci wheel control is waiting: {message}; retrying while an action exists.')
                DAVINCI_LAST_INIT_MESSAGE = message
                send_current_pi_davinci_status()
    else:
        reason = DAVINCI_DEPENDENCY_MESSAGE or '依赖或 UI 后端不可用'
        print(f'⚠️  DaVinci 轮盘功能不可用：{reason}')


def cleanup_davinci_wheel():
    """在主线程清理 DaVinci 轮盘资源"""
    global DAVINCI_INITIALIZED, DAVINCI_LAST_INIT_MESSAGE

    if DAVINCI_WHEEL_AVAILABLE and (DAVINCI_INITIALIZED or wheel_manager.is_monitoring):
        wheel_manager.cleanup()
        DAVINCI_INITIALIZED = False
        DAVINCI_LAST_INIT_MESSAGE = None
        send_current_pi_davinci_status()


def update_davinci_lifecycle():
    """Start one shared monitor only while at least one action exists."""
    global DAVINCI_INIT_PENDING, DAVINCI_LAST_STATUS_CHECK

    if not DAVINCI_WHEEL_AVAILABLE:
        return

    if not has_davinci_actions():
        DAVINCI_INIT_PENDING = False
        if DAVINCI_INITIALIZED or wheel_manager.is_monitoring:
            cleanup_davinci_wheel()
        return

    if DAVINCI_INITIALIZED:
        now = time.time()
        if now - DAVINCI_LAST_STATUS_CHECK >= DAVINCI_STATUS_CHECK_INTERVAL_SECONDS:
            DAVINCI_LAST_STATUS_CHECK = now
            if wheel_manager.label_finder and not wheel_manager.label_finder.is_app_running():
                cleanup_davinci_wheel()
                request_davinci_init()
                send_current_pi_davinci_status()
                return

        if not wheel_manager.is_monitoring:
            wheel_manager.start_monitoring(on_hover_callback=on_hover_change)
        return

    now = time.time()
    if DAVINCI_INIT_PENDING or now - DAVINCI_LAST_INIT_ATTEMPT >= DAVINCI_INIT_RETRY_INTERVAL_SECONDS:
        DAVINCI_INIT_PENDING = False
        initialize_davinci_wheel()


def process_qt_events():
    """让 Qt 定时器和 UI 更新在主循环里继续工作"""
    if DAVINCI_WHEEL_AVAILABLE and DAVINCI_INITIALIZED:
        wheel_manager.process_events()


# ==================== 事件处理 ====================

@register_ulanzi_handler(ud_api.on_connected)
def on_connected(conn):
    """WebSocket 连接成功"""
    conn = conn if isinstance(conn, dict) else {}
    address = conn.get('address') or conn.get('host') or ud_api.address
    port = conn.get('port') or ud_api.port
    language = conn.get('language') or ud_api.language
    print('✅ 已连接到 UlanziStudio')
    print(f'   主机：{address}:{port}')
    print(f'   语言：{language}')


def suspend_action_inputs():
    """Discard queued dial state and release native modifiers after transport loss."""
    with DIAL_PRESS_LOCK:
        DIAL_PRESS_STATES.clear()
    DIAL_HOLD_ROTATE_EVENTS_HANDLED.clear()
    for instance in ACTION_CACHES.values():
        if hasattr(instance, 'on_connection_lost'):
            instance.on_connection_lost()


@register_ulanzi_handler(ud_api.on_close)
def on_close(conn):
    """WebSocket 连接断开"""
    global DAVINCI_CLEANUP_PENDING

    print('❌ 连接已断开')

    if os.name == 'nt':
        # The SDK's terminal close has no reconnect loop. Let the main thread
        # clean up and exit, releasing the process-owned single-instance lock.
        # A failing action suspension must not leave an orphan process behind.
        try:
            suspend_action_inputs()
        finally:
            _WINDOWS_EXIT_REQUESTED.set()
        return

    suspend_action_inputs()

    # Qt 清理也回到主线程执行。
    DAVINCI_CLEANUP_PENDING = True


@register_ulanzi_handler(ud_api.on_error)
def on_error(err):
    """WebSocket 错误"""
    if isinstance(err, dict):
        message = err.get('error') or err
    else:
        message = err
    print(f'⚠️  错误：{message}')
    suspend_action_inputs()


@register_ulanzi_handler(ud_api.on_add)
def on_add(jsn):
    """Action 被添加到按键"""
    context = jsn.get('context')
    kind = action_kind(jsn, decode_context_fn=ud_api.decode_context)
    action_type = extract_action_id(jsn, decode_context_fn=ud_api.decode_context) or kind
    initial_settings = jsn.get('settings') or jsn.get('param') or {}

    print(f'📌 Action 已添加：{context} (类型: {action_type})')

    previous = ACTION_CACHES.get(context)
    previous_kind = ACTION_KINDS.get(context)
    reuse_existing = previous is not None and previous_kind == kind

    if reuse_existing:
        # Ulanzi Studio emits `add` again when the Property Inspector opens.
        # Rebuilding here briefly applies the default state icon before the
        # saved mode feedback, which is visible as an icon flash.
        print(f'♻️  复用 Action 实例：{context}')
    else:
        previous = ACTION_CACHES.pop(context, None)
        discard_dial_press_state(context=context, instance=previous)
        if previous and hasattr(previous, 'destroy'):
            previous.destroy()

    ACTION_KINDS[context] = kind
    if not reuse_existing and kind == 'timeline' and DAVINCI_TIMELINE_AVAILABLE:
        ACTION_CACHES[context] = DaVinciTimelineAction(
            context,
            ud_api,
            initial_settings=initial_settings,
        )
    elif not reuse_existing and kind == 'color_wheel' and DAVINCI_WHEEL_AVAILABLE:
        ACTION_CACHES[context] = DaVinciWheelAction(context, ud_api)

    if kind == 'color_wheel' and DAVINCI_WHEEL_AVAILABLE:
        wheel_manager.action_contexts.add(context)
        request_davinci_init()
        send_current_pi_davinci_status()
    elif context not in ACTION_CACHES:
        ACTION_CACHES[context] = HelloAction(context, ud_api)

    on_set_settings(jsn, 'init')


@register_ulanzi_handler(ud_api.on_set_active)
def on_set_active(jsn):
    """Action 激活状态变化"""
    context = jsn.get('context')
    instance = ACTION_CACHES.get(context)

    if instance:
        instance.set_active(jsn.get('active', False))
        request_davinci_init()


@register_ulanzi_handler(ud_api.on_run)
def on_run(jsn):
    """按键触发（主入口）"""
    context = jsn.get('context')
    instance = ACTION_CACHES.get(context)

    if not instance:
        print(f'⚠️  实例不存在，触发 add: {context}')
        ud_api.emit('add', jsn)
    else:
        print(f'🔥 执行 Action: {context}')
        if hasattr(instance, 'execute'):
            instance.execute()


@register_ulanzi_handler(ud_api.on_clear)
def on_clear(jsn):
    """Action 从按键移除"""
    global DAVINCI_CLEANUP_PENDING

    param = jsn.get('param', [])
    print(f'🗑️  Action 已移除')

    for item in param:
        context = item.get('context')
        if context in ACTION_CACHES:
            instance = ACTION_CACHES[context]
            discard_dial_press_state(context=context, instance=instance)
            instance.destroy()
            del ACTION_CACHES[context]
            print(f'   清理：{context}')
        kind = ACTION_KINDS.pop(context, None)
        if DAVINCI_WHEEL_AVAILABLE and kind != 'timeline':
            wheel_manager.action_contexts.discard(context)

    if DAVINCI_WHEEL_AVAILABLE and not wheel_manager.action_contexts:
        DAVINCI_CLEANUP_PENDING = True


@register_ulanzi_handler(ud_api.on_param_from_app)
def on_param_from_app(jsn):
    global LAST_ACTIVE_PI_CONTEXT

    LAST_ACTIVE_PI_CONTEXT = jsn.get('context') or LAST_ACTIVE_PI_CONTEXT
    """上位机推送配置参数"""
    print(f'📥  收到配置参数')
    on_set_settings(jsn)
    request_davinci_init()
    send_current_pi_davinci_status(force=True)


@register_ulanzi_handler(ud_api.on_param_from_plugin)
def on_param_from_plugin(jsn):
    """转发插件参数"""
    on_set_settings(jsn)


@register_ulanzi_handler(ud_api.on_send_to_plugin)
def on_send_to_plugin(jsn):
    """Reply to an explicit Property Inspector status request."""
    global LAST_ACTIVE_PI_CONTEXT

    payload = jsn.get('payload') or {}
    if payload.get('type') != 'request_davinci_status':
        return

    context = jsn.get('context') or LAST_ACTIVE_PI_CONTEXT
    if not context:
        return

    LAST_ACTIVE_PI_CONTEXT = context
    send_current_pi_davinci_status(context=context, force=True)


@register_ulanzi_handler(ud_api.on_did_receive_settings)
def on_did_receive_settings(jsn):
    """收到 Settings"""
    context = jsn.get('context', 'unknown')
    settings = jsn.get('settings', {})
    on_set_settings(jsn, 'settings')
    print(f'⚙️  收到 Settings ({context}): {settings}')


# ==================== 旋钮事件处理 ====================

DIAL_INPUT_TRACE_COUNT = 0
DIAL_INPUT_TRACE_ENABLED = os.environ.get('DAVINCI_WHEEL_DEBUG', '0').lower() not in {'0', 'false', 'no', 'off'}
if DIAL_INPUT_TRACE_ENABLED:
    print('dial-input-trace.1 enabled max_events=512 max_chars=8192')


def log_raw_dial_input(jsn):
    """Bounded diagnostic at SDK callback entry, before tick normalization."""
    global DIAL_INPUT_TRACE_COUNT
    if not DIAL_INPUT_TRACE_ENABLED or DIAL_INPUT_TRACE_COUNT >= 512:
        return
    DIAL_INPUT_TRACE_COUNT += 1
    try:
        message = {key: value for key, value in jsn.items() if key != 'settings'}
        for key in ('param', 'payload'):
            if isinstance(message.get(key), dict):
                message[key] = {k: v for k, v in message[key].items() if k != 'settings'}
        encoded = json.dumps(message, ensure_ascii=False, separators=(',', ':'))
        row = {'sequence': DIAL_INPUT_TRACE_COUNT, 'wallTimeMs': time.time() * 1000,
               'callbackAt': time.monotonic(), 'truncated': len(encoded) > 8192,
               'message': encoded[:8192]}
        print('dial-input-trace.1 ' + json.dumps(row, ensure_ascii=False))
    except Exception as exc:
        # Diagnostic failures must never interrupt input routing.
        print('dial-input-trace.1 error=' + type(exc).__name__)


def get_dial_ticks(jsn: dict, fallback: int = 0):
    """Extract dial ticks, falling back to rotateEvent when the host omits ticks."""
    param = jsn.get('param') or {}
    ticks = param.get('ticks', jsn.get('ticks'))
    if ticks not in (None, ''):
        try:
            return int(ticks)
        except (TypeError, ValueError):
            pass

    rotate_event = str(jsn.get('rotateEvent') or param.get('rotateEvent') or '').lower()
    if rotate_event.endswith('left'):
        return -1
    if rotate_event.endswith('right'):
        return 1
    return fallback


def normalize_rotate_event(jsn: dict):
    param = jsn.get('param') or {}
    rotate_event = str(jsn.get('rotateEvent') or param.get('rotateEvent') or '').strip().lower()
    for dash in ('_', ' ', '—', '–', '‑'):
        rotate_event = rotate_event.replace(dash, '-')
    if rotate_event == 'holdleft':
        return 'hold-left'
    if rotate_event == 'holdright':
        return 'hold-right'
    return rotate_event


def handle_unfiltered_hold_rotate(jsn: dict, context: str, rotate_event: str):
    if not rotate_event.startswith('hold'):
        return False

    ticks = abs(get_dial_ticks(jsn, 1))
    if rotate_event.endswith('left'):
        ticks = -ticks

    instance = get_dial_action_instance(context)
    mark_dial_rotated(context, instance)
    if instance and hasattr(instance, 'on_dial_rotate_hold'):
        handled = instance.on_dial_rotate_hold(ticks)
        log_dial_event('hold-unfiltered', context, ticks, rotate_event, handled)
        if handled:
            if len(DIAL_HOLD_ROTATE_EVENTS_HANDLED) > 128:
                DIAL_HOLD_ROTATE_EVENTS_HANDLED.clear()
            DIAL_HOLD_ROTATE_EVENTS_HANDLED.add(id(jsn))
            print(f'旋钮按住旋转: {ticks}')
        return handled
    log_dial_event('hold-unfiltered', context, ticks, rotate_event, False)
    return False


@register_ulanzi_handler(ud_api.on_dial_rotate)
def on_dial_rotate(jsn):
    """旋钮旋转事件"""
    log_raw_dial_input(jsn)
    context = jsn.get('context')
    finalize_stale_dial_presses()
    rotate_event = normalize_rotate_event(jsn)
    if handle_unfiltered_hold_rotate(jsn, context, rotate_event) or rotate_event.startswith('hold'):
        return

    ticks = get_dial_ticks(jsn)
    handled = False

    press_state = get_dial_press_state(context)
    if press_state is not None:
        mark_dial_rotated(context, press_state.get('instance'))
        instance = press_state.get('instance') or get_dial_action_instance(context)
        if instance and hasattr(instance, 'on_dial_rotate_hold'):
            handled = instance.on_dial_rotate_hold(ticks)
            log_dial_event('rotate-pressed', context, ticks, rotate_event, handled)
            if handled:
                print(f'旋钮按下后旋转: {ticks}')
        else:
            log_dial_event('rotate-pressed', context, ticks, rotate_event, False)
        return

    instance = get_dial_action_instance(context)
    if instance and hasattr(instance, 'on_dial_rotate'):
        handled = instance.on_dial_rotate(ticks)
        log_dial_event('rotate', context, ticks, rotate_event, handled)
        if handled:
            print(f'🔄 旋钮旋转: {ticks}')
    else:
        log_dial_event('rotate', context, ticks, rotate_event, False)


@register_ulanzi_handler(ud_api.on_dial_rotate_hold_left)
def on_dial_rotate_hold_left(jsn):
    if id(jsn) in DIAL_HOLD_ROTATE_EVENTS_HANDLED:
        DIAL_HOLD_ROTATE_EVENTS_HANDLED.discard(id(jsn))
        return
    """旋钮按住左旋转事件"""
    context = jsn.get('context')
    ticks = abs(get_dial_ticks(jsn, 1))

    instance = get_dial_action_instance(context)
    mark_dial_rotated(context, instance)
    if instance and hasattr(instance, 'on_dial_rotate_hold'):
        handled = instance.on_dial_rotate_hold(-ticks)
        log_dial_event('hold-left', context, -ticks, 'hold-left', handled)
        if handled:
            print(f'🔄 旋钮按住旋转 (Y轴): {ticks}')
    else:
        log_dial_event('hold-left', context, -ticks, 'hold-left', False)


@register_ulanzi_handler(ud_api.on_dial_rotate_hold_right)
def on_dial_rotate_hold_right(jsn):
    if id(jsn) in DIAL_HOLD_ROTATE_EVENTS_HANDLED:
        DIAL_HOLD_ROTATE_EVENTS_HANDLED.discard(id(jsn))
        return
    """旋钮按住右旋转事件"""
    context = jsn.get('context')
    ticks = abs(get_dial_ticks(jsn, 1))

    instance = get_dial_action_instance(context)
    mark_dial_rotated(context, instance)
    if instance and hasattr(instance, 'on_dial_rotate_hold'):
        handled = instance.on_dial_rotate_hold(ticks)
        log_dial_event('hold-right', context, ticks, 'hold-right', handled)
        if handled:
            print(f'🔄 旋钮按住旋转 (Y轴反向): {ticks}')
    else:
        log_dial_event('hold-right', context, ticks, 'hold-right', False)


@register_ulanzi_handler(ud_api.on_dial_down)
def on_dial_down(jsn):
    """旋钮按下"""
    context = jsn.get('context')
    instance = get_dial_action_instance(context)
    with DIAL_PRESS_LOCK:
        DIAL_PRESS_STATES[context] = _dial_press_state(instance)
    print(f'⬇️ 旋钮按下: {context}')
    if instance and hasattr(instance, 'on_dial_press'):
        instance.on_dial_press()


@register_ulanzi_handler(ud_api.on_dial_up)
def on_dial_up(jsn):
    """旋钮释放"""
    context = jsn.get('context')
    press_state = pop_dial_press_state(context)
    instance = (press_state or {}).get('instance') or get_dial_action_instance(context)
    rotated = bool(press_state and press_state.get('rotated'))
    if instance and hasattr(instance, 'on_dial_release'):
        instance.on_dial_release(rotated=rotated)
    elif press_state and not rotated:
        if instance and hasattr(instance, 'on_dial_down'):
            handled = instance.on_dial_down()
            if handled:
                print('已将当前色轮重置到圆心')
    print(f'⬆️ 旋钮释放: {context}')


# ==================== 主程序 ====================

def _cleanup_windows_shutdown():
    """Attempt every resource cleanup without preventing process termination."""
    try:
        cleanup_davinci_wheel()
    except Exception as exc:
        print(f'退出时轮盘清理失败：{exc}')
    for context, instance in list(ACTION_CACHES.items()):
        try:
            instance.destroy()
        except Exception as exc:
            print(f'退出时 Action 清理失败 ({context})：{exc}')


def run_main_loop():
    """Keep UI work on the main thread, ending a disconnected Windows host."""
    global DAVINCI_CLEANUP_PENDING

    try:
        while os.name != 'nt' or not _WINDOWS_EXIT_REQUESTED.is_set():
            if DAVINCI_CLEANUP_PENDING:
                DAVINCI_CLEANUP_PENDING = False
                cleanup_davinci_wheel()

            update_davinci_lifecycle()
            process_qt_events()
            finalize_stale_dial_presses()
            maybe_send_pi_davinci_status()
            time.sleep(MAIN_LOOP_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print()
        print('正在退出...')
        if os.name != 'nt':
            # Preserve the existing macOS shutdown path.
            cleanup_davinci_wheel()
            for instance in ACTION_CACHES.values():
                instance.destroy()
            print('已清理资源，再见！')
            sys.exit(0)
    finally:
        if os.name == 'nt':
            _cleanup_windows_shutdown()
            print('已清理资源，再见！')


if __name__ == '__main__':
    plugin_uuid = PLUGIN_UUID

    print('=' * 50)
    print('DaVinci Color Wheels - UlanziDeck Python 插件')
    print('=' * 50)
    print(f'插件 UUID: {plugin_uuid}')
    print(f'DaVinci 轮盘功能：{"可用" if DAVINCI_WHEEL_AVAILABLE else "不可用"}')
    print()

    if not acquire_single_instance_lock():
        sys.exit(0)

    if os.name == 'nt':
        print('Windows lifecycle: host-close-exit.1')

    # 连接 UlanziStudio
    connect_argv = normalized_ulanzi_connect_argv()
    ud_api.connect(plugin_uuid, argv=connect_argv, daemon=True)
    print(f'连接目标：{ud_api.address}:{ud_api.port}')
    print(f'语言：{ud_api.language}')

    # 等待连接
    time.sleep(0.5)

    print()
    print('正在等待 UlanziStudio 连接...')
    print('按 Ctrl+C 退出')
    print()

    # 保持运行
    run_main_loop()
