"""Small, dependency-free wrappers around the macOS input APIs.

The rest of the worker talks to this module through ordinary Python methods,
which makes every live-input path replaceable with a fake in unit tests.  The
worker can explicitly request the macOS Accessibility and event permissions,
but it still fails closed until every permission is actually available.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from dataclasses import dataclass
import inspect
import math
import os
from pathlib import Path
import plistlib
import sys
from threading import Event, Lock, Thread, current_thread
import time
from typing import Callable, Optional, Tuple


DAVINCI_BUNDLE_ID = "com.blackmagic-design.DaVinciResolve"


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class CGRect(ctypes.Structure):
    _fields_ = [("origin", CGPoint), ("size", CGSize)]


class ProcessSerialNumber(ctypes.Structure):
    _fields_ = [
        ("highLongOfPSN", ctypes.c_uint32),
        ("lowLongOfPSN", ctypes.c_uint32),
    ]


@dataclass(frozen=True)
class AppIdentity:
    pid: Optional[int]
    bundle_id: str
    executable_path: str

    @property
    def is_davinci(self) -> bool:
        return self.bundle_id == DAVINCI_BUNDLE_ID and self.pid is not None


@dataclass(frozen=True)
class PermissionState:
    accessibility: bool
    listen_events: bool
    post_events: bool

    @property
    def ready(self) -> bool:
        return self.accessibility and self.listen_events and self.post_events


@dataclass(frozen=True)
class CapturedBitmap:
    """One in-memory CoreGraphics capture in global logical coordinates."""

    pixels: bytes
    width: int
    height: int
    bytes_per_row: int
    screen_rect: Tuple[float, float, float, float]
    scale_x: float
    scale_y: float
    color_offsets: Tuple[int, int, int] = (0, 1, 2)


# The optional fifth argument contains source evidence.  Four-argument test
# taps/callbacks remain supported; event metadata must not become a safety gate.
TapCallback = Callable[..., None]


class MacOSBindings:
    """Lazy ctypes facade for CoreGraphics, AX, Carbon and libproc."""

    # CoreGraphics event constants.
    LEFT_DOWN = 1
    LEFT_UP = 2
    RIGHT_DOWN = 3
    RIGHT_UP = 4
    MOUSE_MOVED = 5
    LEFT_DRAGGED = 6
    RIGHT_DRAGGED = 7
    SCROLL_WHEEL = 22
    OTHER_DOWN = 25
    OTHER_UP = 26
    OTHER_DRAGGED = 27
    TAP_DISABLED_BY_TIMEOUT = 0xFFFFFFFE
    TAP_DISABLED_BY_USER_INPUT = 0xFFFFFFFF

    # CGEventField values from the macOS SDK's CGEventTypes.h.
    MOUSE_EVENT_NUMBER_FIELD = 0
    MOUSE_CLICK_STATE_FIELD = 1
    MOUSE_DELTA_X_FIELD = 4
    MOUSE_DELTA_Y_FIELD = 5
    TARGET_PID_FIELD = 40
    SOURCE_PID_FIELD = 41
    USER_DATA_FIELD = 42
    SOURCE_STATE_ID_FIELD = 45
    SINGLE_CLICK_STATE = 1
    EVENT_SOURCE_PRIVATE = -1
    EVENT_SOURCE_COMBINED_SESSION = 0
    EVENT_SOURCE_HID_SYSTEM = 1
    MOUSE_BUTTON_LEFT = 0
    HID_EVENT_TAP = 0
    SESSION_EVENT_TAP = 1
    TAIL_APPEND_EVENT_TAP = 1
    LISTEN_ONLY = 1
    MAX_ACTIVE_DISPLAYS = 32

    # CGWindowList/CGWindowImage constants.  The experimental observer uses a
    # small composited screen ROI only while Resolve is frontmost.  Keeping the
    # capture in this process avoids a PNG round trip and a second TCC identity.
    WINDOW_LIST_ON_SCREEN_ONLY = 1
    WINDOW_IMAGE_BOUNDS_IGNORE_FRAMING = 1
    WINDOW_IMAGE_BEST_RESOLUTION = 8
    BITMAP_ALPHA_MASK = 0x1F
    BITMAP_ALPHA_PREMULTIPLIED_LAST = 1
    BITMAP_ALPHA_PREMULTIPLIED_FIRST = 2
    BITMAP_ALPHA_LAST = 3
    BITMAP_ALPHA_FIRST = 4
    BITMAP_ALPHA_NONE_SKIP_LAST = 5
    BITMAP_ALPHA_NONE_SKIP_FIRST = 6
    BITMAP_FLOAT_COMPONENTS = 0x0100
    BITMAP_BYTE_ORDER_MASK = 0x7000
    BITMAP_BYTE_ORDER_DEFAULT = 0x0000
    BITMAP_BYTE_ORDER_32_LITTLE = 0x2000
    BITMAP_BYTE_ORDER_32_BIG = 0x4000
    MAX_CAPTURE_LOGICAL_SIDE = 2048
    MAX_CAPTURE_LOGICAL_AREA = 2048 * 2048
    MAX_CAPTURE_PIXEL_SIDE = 4096
    MAX_CAPTURE_BYTES = 64 * 1024 * 1024

    def __init__(self) -> None:
        self.available = False
        self.unavailable_reason = "not initialized"
        self._as = None
        self._cf = None
        self._libc = None
        self._appkit = None
        self._objc = None
        self._screen_capture_available = False
        self._screen_capture_reason = "screen capture APIs are not initialized"
        self._tap_callback_type = ctypes.CFUNCTYPE(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )

        if sys.platform != "darwin":
            self.unavailable_reason = "live mode requires macOS"
            return

        try:
            self._as = ctypes.CDLL(
                "/System/Library/Frameworks/ApplicationServices.framework/"
                "ApplicationServices"
            )
            self._cf = ctypes.CDLL(
                "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
            )
            libc_path = ctypes.util.find_library("c") or "/usr/lib/libSystem.B.dylib"
            self._libc = ctypes.CDLL(libc_path)
            self._configure_signatures()
            self.available = True
            self.unavailable_reason = ""
            try:
                self._configure_screen_capture_signatures()
                self._screen_capture_available = True
                self._screen_capture_reason = ""
            except Exception as exc:
                # Screen observation is optional. Missing or removed capture
                # symbols must never make the mouse-control bindings unusable.
                self._screen_capture_reason = (
                    "optional screen capture API load failed: %s" % exc
                )
        except Exception as exc:  # pragma: no cover - only macOS loader failures
            self.unavailable_reason = "macOS API load failed: %s" % exc

    def _configure_signatures(self) -> None:
        assert self._as is not None and self._cf is not None and self._libc is not None
        api = self._as
        cf = self._cf

        api.AXIsProcessTrusted.argtypes = []
        api.AXIsProcessTrusted.restype = ctypes.c_bool
        api.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
        api.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
        api.CGPreflightListenEventAccess.argtypes = []
        api.CGPreflightListenEventAccess.restype = ctypes.c_bool
        api.CGPreflightPostEventAccess.argtypes = []
        api.CGPreflightPostEventAccess.restype = ctypes.c_bool
        api.CGRequestListenEventAccess.argtypes = []
        api.CGRequestListenEventAccess.restype = ctypes.c_bool
        api.CGRequestPostEventAccess.argtypes = []
        api.CGRequestPostEventAccess.restype = ctypes.c_bool
        api.CGEventCreate.argtypes = [ctypes.c_void_p]
        api.CGEventCreate.restype = ctypes.c_void_p
        api.CGEventGetLocation.argtypes = [ctypes.c_void_p]
        api.CGEventGetLocation.restype = CGPoint
        api.CGEventSourceButtonState.argtypes = [ctypes.c_int32, ctypes.c_uint32]
        api.CGEventSourceButtonState.restype = ctypes.c_bool

        api.CGEventSourceCreate.argtypes = [ctypes.c_int32]
        api.CGEventSourceCreate.restype = ctypes.c_void_p
        api.CGEventSourceSetUserData.argtypes = [ctypes.c_void_p, ctypes.c_int64]
        api.CGEventSourceSetLocalEventsSuppressionInterval.argtypes = [
            ctypes.c_void_p,
            ctypes.c_double,
        ]
        api.CGEventSourceSetLocalEventsFilterDuringSuppressionState.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
        api.CGEventCreateMouseEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            CGPoint,
            ctypes.c_uint32,
        ]
        api.CGEventCreateMouseEvent.restype = ctypes.c_void_p
        api.CGEventSetIntegerValueField.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int32,
            ctypes.c_int64,
        ]
        api.CGEventGetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_int32]
        api.CGEventGetIntegerValueField.restype = ctypes.c_int64
        api.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        api.CGEventPostToPid.argtypes = [ctypes.c_int32, ctypes.c_void_p]
        api.CGEventPostToPid.restype = None
        api.CGWarpMouseCursorPosition.argtypes = [CGPoint]
        api.CGWarpMouseCursorPosition.restype = ctypes.c_int32
        api.CGAssociateMouseAndMouseCursorPosition.argtypes = [ctypes.c_int32]
        api.CGAssociateMouseAndMouseCursorPosition.restype = ctypes.c_int32
        api.CGGetActiveDisplayList.argtypes = [
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        api.CGGetActiveDisplayList.restype = ctypes.c_int32
        api.CGDisplayBounds.argtypes = [ctypes.c_uint32]
        api.CGDisplayBounds.restype = CGRect

        api.GetFrontProcess.argtypes = [ctypes.POINTER(ProcessSerialNumber)]
        api.GetFrontProcess.restype = ctypes.c_int32
        api.GetProcessPID.argtypes = [
            ctypes.POINTER(ProcessSerialNumber),
            ctypes.POINTER(ctypes.c_int32),
        ]
        api.GetProcessPID.restype = ctypes.c_int32

        api.CGEventTapCreate.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint64,
            self._tap_callback_type,
            ctypes.c_void_p,
        ]
        api.CGEventTapCreate.restype = ctypes.c_void_p
        api.CGEventTapEnable.argtypes = [ctypes.c_void_p, ctypes.c_bool]

        cf.CFRelease.argtypes = [ctypes.c_void_p]
        cf.CFDictionaryCreateMutable.argtypes = [
            ctypes.c_void_p,
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        cf.CFDictionaryCreateMutable.restype = ctypes.c_void_p
        cf.CFDictionarySetValue.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        cf.CFMachPortCreateRunLoopSource.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_long,
        ]
        cf.CFMachPortCreateRunLoopSource.restype = ctypes.c_void_p
        cf.CFRunLoopGetCurrent.argtypes = []
        cf.CFRunLoopGetCurrent.restype = ctypes.c_void_p
        cf.CFRunLoopAddSource.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        cf.CFRunLoopRemoveSource.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        cf.CFRunLoopRunInMode.argtypes = [
            ctypes.c_void_p,
            ctypes.c_double,
            ctypes.c_bool,
        ]
        cf.CFRunLoopRunInMode.restype = ctypes.c_int32

        self._libc.proc_pidpath.argtypes = [
            ctypes.c_int32,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        self._libc.proc_pidpath.restype = ctypes.c_int32

    def _configure_screen_capture_signatures(self) -> None:
        assert self._as is not None and self._cf is not None
        api = self._as
        cf = self._cf

        api.CGPreflightScreenCaptureAccess.argtypes = []
        api.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        api.CGRequestScreenCaptureAccess.argtypes = []
        api.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
        api.CGWindowListCreateImage.argtypes = [
            CGRect,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
        api.CGWindowListCreateImage.restype = ctypes.c_void_p
        api.CGImageGetWidth.argtypes = [ctypes.c_void_p]
        api.CGImageGetWidth.restype = ctypes.c_size_t
        api.CGImageGetHeight.argtypes = [ctypes.c_void_p]
        api.CGImageGetHeight.restype = ctypes.c_size_t
        api.CGImageGetBytesPerRow.argtypes = [ctypes.c_void_p]
        api.CGImageGetBytesPerRow.restype = ctypes.c_size_t
        api.CGImageGetBitsPerComponent.argtypes = [ctypes.c_void_p]
        api.CGImageGetBitsPerComponent.restype = ctypes.c_size_t
        api.CGImageGetBitsPerPixel.argtypes = [ctypes.c_void_p]
        api.CGImageGetBitsPerPixel.restype = ctypes.c_size_t
        api.CGImageGetBitmapInfo.argtypes = [ctypes.c_void_p]
        api.CGImageGetBitmapInfo.restype = ctypes.c_uint32
        api.CGImageGetDataProvider.argtypes = [ctypes.c_void_p]
        api.CGImageGetDataProvider.restype = ctypes.c_void_p
        api.CGDataProviderCopyData.argtypes = [ctypes.c_void_p]
        api.CGDataProviderCopyData.restype = ctypes.c_void_p
        cf.CFDataGetLength.argtypes = [ctypes.c_void_p]
        cf.CFDataGetLength.restype = ctypes.c_long
        cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
        cf.CFDataGetBytePtr.restype = ctypes.POINTER(ctypes.c_ubyte)

    def permissions(self) -> PermissionState:
        if not self.available:
            return PermissionState(False, False, False)
        assert self._as is not None
        try:
            return PermissionState(
                bool(self._as.AXIsProcessTrusted()),
                bool(self._as.CGPreflightListenEventAccess()),
                bool(self._as.CGPreflightPostEventAccess()),
            )
        except Exception:
            return PermissionState(False, False, False)

    def request_permissions(self) -> dict:
        """Ask macOS for any missing input permissions.

        Accessibility prompting is asynchronous.  The CoreGraphics request
        calls may also require the application to be restarted after the user
        changes System Settings, so callers must re-check ``permissions()``
        and must never treat this request as authorization by itself.
        """

        self._require_available()
        assert self._as is not None and self._cf is not None
        before = self.permissions()
        requested = {
            "accessibility": not before.accessibility,
            "listenEvents": not before.listen_events,
            "postEvents": not before.post_events,
        }
        errors = {}

        if requested["accessibility"]:
            options = None
            try:
                prompt_key = ctypes.c_void_p.in_dll(
                    self._as, "kAXTrustedCheckOptionPrompt"
                ).value
                true_value = ctypes.c_void_p.in_dll(
                    self._cf, "kCFBooleanTrue"
                ).value
                if not prompt_key or not true_value:
                    raise RuntimeError("macOS permission prompt constants are unavailable")
                options = self._cf.CFDictionaryCreateMutable(None, 0, None, None)
                if not options:
                    raise RuntimeError("CFDictionaryCreateMutable returned NULL")
                self._cf.CFDictionarySetValue(options, prompt_key, true_value)
                self._as.AXIsProcessTrustedWithOptions(options)
            except Exception as exc:
                errors["accessibility"] = str(exc)
            finally:
                if options:
                    self._cf.CFRelease(options)

        if requested["listenEvents"]:
            try:
                self._as.CGRequestListenEventAccess()
            except Exception as exc:
                errors["listenEvents"] = str(exc)

        if requested["postEvents"]:
            try:
                self._as.CGRequestPostEventAccess()
            except Exception as exc:
                errors["postEvents"] = str(exc)

        after = self.permissions()
        return {
            "requested": requested,
            "before": {
                "accessibility": before.accessibility,
                "listenEvents": before.listen_events,
                "postEvents": before.post_events,
                "ready": before.ready,
            },
            "after": {
                "accessibility": after.accessibility,
                "listenEvents": after.listen_events,
                "postEvents": after.post_events,
                "ready": after.ready,
            },
            "errors": errors,
        }

    def screen_capture_supported(self) -> bool:
        """Whether the optional in-process capture symbols are usable."""

        return bool(
            self.available and getattr(self, "_screen_capture_available", False)
        )

    def screen_capture_allowed(self) -> bool:
        """Return the screen-recording TCC state without prompting."""

        if not self.screen_capture_supported():
            return False
        assert self._as is not None
        try:
            return bool(self._as.CGPreflightScreenCaptureAccess())
        except Exception:
            return False

    def request_screen_capture_access(self) -> dict:
        """Request optional screen capture access and report the observed state.

        A previous denial is not re-prompted by macOS.  Screen capture is an
        observer enhancement, so this method is deliberately separate from
        the input permission gate used to arm live control.
        """

        if not self.screen_capture_supported() or self._as is None:
            return {
                "requested": False,
                "before": False,
                "after": False,
                "requestReturned": False,
                "error": str(
                    getattr(self, "_screen_capture_reason", "")
                    or self.unavailable_reason
                    or "screen capture APIs are unavailable"
                ),
            }
        before = self.screen_capture_allowed()
        requested = not before
        request_returned = before
        error = ""
        if requested:
            try:
                request_returned = bool(self._as.CGRequestScreenCaptureAccess())
            except Exception as exc:
                error = str(exc)
        return {
            "requested": requested,
            "before": before,
            "after": self.screen_capture_allowed(),
            "requestReturned": request_returned,
            "error": error,
        }

    def capture_screen_region(
        self, x: float, y: float, width: float, height: float
    ) -> CapturedBitmap:
        """Capture one small screen ROI directly into a Python-owned byte buffer.

        CoreGraphics screen and event coordinates share the upper-left origin
        and downward-positive Y axis.  Retina pixels are kept at native scale;
        callers convert through ``scale_x``/``scale_y`` rather than resizing.
        """

        self._require_available()
        assert self._as is not None and self._cf is not None
        if not self.screen_capture_supported():
            raise RuntimeError(
                str(
                    getattr(self, "_screen_capture_reason", "")
                    or "screen capture APIs are unavailable"
                )
            )
        values = tuple(float(value) for value in (x, y, width, height))
        if not all(math.isfinite(value) for value in values):
            raise ValueError("capture rectangle must contain finite values")
        x, y, width, height = values
        if width <= 0.0 or height <= 0.0:
            raise ValueError("capture rectangle must have positive dimensions")
        if not self.screen_capture_allowed():
            raise RuntimeError("screen capture permission is unavailable")

        # Integral global points avoid dropping a sub-pixel edge while keeping
        # the returned mapping exact on 1x and Retina displays.
        left = math.floor(x)
        top = math.floor(y)
        right = math.ceil(x + width)
        bottom = math.ceil(y + height)
        logical_width = right - left
        logical_height = bottom - top
        if (
            logical_width > self.MAX_CAPTURE_LOGICAL_SIDE
            or logical_height > self.MAX_CAPTURE_LOGICAL_SIDE
            or logical_width * logical_height > self.MAX_CAPTURE_LOGICAL_AREA
        ):
            raise ValueError("capture rectangle exceeds the bounded ROI limit")
        image = None
        data = None
        try:
            image = self._as.CGWindowListCreateImage(
                CGRect(
                    CGPoint(float(left), float(top)),
                    CGSize(float(logical_width), float(logical_height)),
                ),
                self.WINDOW_LIST_ON_SCREEN_ONLY,
                0,
                self.WINDOW_IMAGE_BOUNDS_IGNORE_FRAMING
                | self.WINDOW_IMAGE_BEST_RESOLUTION,
            )
            if not image:
                raise RuntimeError("CGWindowListCreateImage returned NULL")
            captured_width = int(self._as.CGImageGetWidth(image))
            captured_height = int(self._as.CGImageGetHeight(image))
            bytes_per_row = int(self._as.CGImageGetBytesPerRow(image))
            bits_per_component = int(self._as.CGImageGetBitsPerComponent(image))
            bits_per_pixel = int(self._as.CGImageGetBitsPerPixel(image))
            bitmap_info = int(self._as.CGImageGetBitmapInfo(image))
            color_offsets = self._bitmap_color_offsets(bitmap_info)
            required = bytes_per_row * captured_height
            if (
                captured_width <= 0
                or captured_height <= 0
                or bytes_per_row < captured_width * 4
            ):
                raise RuntimeError("CoreGraphics returned invalid bitmap dimensions")
            if bits_per_component != 8 or bits_per_pixel != 32:
                raise RuntimeError(
                    "unsupported CoreGraphics bitmap format: %d/%d"
                    % (bits_per_component, bits_per_pixel)
                )
            if (
                captured_width > self.MAX_CAPTURE_PIXEL_SIDE
                or captured_height > self.MAX_CAPTURE_PIXEL_SIDE
                or required > self.MAX_CAPTURE_BYTES
            ):
                raise RuntimeError("CoreGraphics bitmap exceeds the memory safety limit")
            provider = self._as.CGImageGetDataProvider(image)
            if not provider:
                raise RuntimeError("CGImageGetDataProvider returned NULL")
            data = self._as.CGDataProviderCopyData(provider)
            if not data:
                raise RuntimeError("CGDataProviderCopyData returned NULL")
            data_length = int(self._cf.CFDataGetLength(data))
            pointer = self._cf.CFDataGetBytePtr(data)
            if data_length < required or not pointer:
                raise RuntimeError("CoreGraphics returned incomplete bitmap data")
            pixels = ctypes.string_at(pointer, required)
            return CapturedBitmap(
                pixels=pixels,
                width=captured_width,
                height=captured_height,
                bytes_per_row=bytes_per_row,
                screen_rect=(
                    float(left),
                    float(top),
                    float(logical_width),
                    float(logical_height),
                ),
                scale_x=captured_width / logical_width,
                scale_y=captured_height / logical_height,
                color_offsets=color_offsets,
            )
        finally:
            if data:
                self._cf.CFRelease(data)
            if image:
                self._cf.CFRelease(image)

    @classmethod
    def _bitmap_color_offsets(cls, bitmap_info: int) -> Tuple[int, int, int]:
        """Return the three non-alpha byte offsets for a 32-bit bitmap."""

        alpha = int(bitmap_info) & cls.BITMAP_ALPHA_MASK
        byte_order = int(bitmap_info) & cls.BITMAP_BYTE_ORDER_MASK
        if int(bitmap_info) & cls.BITMAP_FLOAT_COMPONENTS:
            raise RuntimeError(
                "unsupported floating-point CoreGraphics bitmap: 0x%x" % bitmap_info
            )
        first_alpha = {
            cls.BITMAP_ALPHA_PREMULTIPLIED_FIRST,
            cls.BITMAP_ALPHA_FIRST,
            cls.BITMAP_ALPHA_NONE_SKIP_FIRST,
        }
        last_alpha = {
            cls.BITMAP_ALPHA_PREMULTIPLIED_LAST,
            cls.BITMAP_ALPHA_LAST,
            cls.BITMAP_ALPHA_NONE_SKIP_LAST,
        }
        if alpha not in first_alpha | last_alpha:
            raise RuntimeError(
                "unsupported CoreGraphics alpha layout: 0x%x" % bitmap_info
            )
        if byte_order == cls.BITMAP_BYTE_ORDER_32_LITTLE:
            return (0, 1, 2) if alpha in first_alpha else (1, 2, 3)
        if byte_order in (
            cls.BITMAP_BYTE_ORDER_DEFAULT,
            cls.BITMAP_BYTE_ORDER_32_BIG,
        ):
            return (1, 2, 3) if alpha in first_alpha else (0, 1, 2)
        raise RuntimeError(
            "unsupported CoreGraphics byte order: 0x%x" % bitmap_info
        )

    def current_mouse_position(self) -> Tuple[float, float]:
        self._require_available()
        assert self._as is not None and self._cf is not None
        event = self._as.CGEventCreate(None)
        if not event:
            raise RuntimeError("CGEventCreate returned NULL")
        try:
            point = self._as.CGEventGetLocation(event)
            result = (float(point.x), float(point.y))
            if not all(math.isfinite(value) for value in result):
                raise RuntimeError("CoreGraphics returned a non-finite mouse position")
            return result
        finally:
            self._cf.CFRelease(event)

    def active_display_bounds(self) -> Tuple[Tuple[float, float, float, float], ...]:
        """Return active display rectangles in global logical coordinates."""

        self._require_available()
        assert self._as is not None
        identifiers = (ctypes.c_uint32 * self.MAX_ACTIVE_DISPLAYS)()
        count = ctypes.c_uint32()
        error = int(
            self._as.CGGetActiveDisplayList(
                ctypes.c_uint32(self.MAX_ACTIVE_DISPLAYS),
                identifiers,
                ctypes.byref(count),
            )
        )
        if error != 0:
            raise RuntimeError(
                "CGGetActiveDisplayList failed with CGError %d" % error
            )
        display_count = int(count.value)
        if display_count <= 0:
            raise RuntimeError("CoreGraphics reported no active displays")
        if display_count > self.MAX_ACTIVE_DISPLAYS:
            raise RuntimeError(
                "CoreGraphics reported more active displays than the safety limit"
            )

        result = []
        for index in range(display_count):
            rect = self._as.CGDisplayBounds(identifiers[index])
            bounds = (
                float(rect.origin.x),
                float(rect.origin.y),
                float(rect.size.width),
                float(rect.size.height),
            )
            if (
                not all(math.isfinite(value) for value in bounds)
                or bounds[2] <= 0.0
                or bounds[3] <= 0.0
            ):
                raise RuntimeError("CoreGraphics returned invalid display bounds")
            result.append(bounds)
        return tuple(result)

    def display_bounds_for_point(
        self, position: Tuple[float, float]
    ) -> Tuple[float, float, float, float]:
        """Return the active display containing one global logical point."""

        try:
            x, y = float(position[0]), float(position[1])
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError("display point must contain two finite numbers") from exc
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("display point must contain two finite numbers")
        displays = self.active_display_bounds()
        for left, top, width, height in displays:
            if left <= x < left + width and top <= y < top + height:
                return (left, top, width, height)
        raise RuntimeError(
            "mouse point is not contained by any active display: %.3f, %.3f"
            % (x, y)
        )

    def left_button_down(self) -> bool:
        self._require_available()
        assert self._as is not None
        combined = bool(
            self._as.CGEventSourceButtonState(
                self.EVENT_SOURCE_COMBINED_SESSION, self.MOUSE_BUTTON_LEFT
            )
        )
        hid = bool(
            self._as.CGEventSourceButtonState(
                self.EVENT_SOURCE_HID_SYSTEM, self.MOUSE_BUTTON_LEFT
            )
        )
        return combined or hid

    def double_click_interval(self) -> float:
        """Read ``+[NSEvent doubleClickInterval]`` in seconds, or use 0.5.

        The public AppKit class property is documented in NSEvent.h.  This is
        a read-only preference query, not an input event or permission request.
        Failure to query it must not make live input available or shorten the
        conservative fallback used by the gesture guard.
        """

        if not self.available:
            return 0.5
        try:
            interval = float(self._read_double_click_interval())
            if math.isfinite(interval) and interval > 0.0:
                return interval
        except Exception:
            pass
        return 0.5

    def _read_double_click_interval(self) -> float:
        if getattr(self, "_appkit", None) is None:
            self._appkit = ctypes.CDLL(
                "/System/Library/Frameworks/AppKit.framework/AppKit"
            )
        if getattr(self, "_objc", None) is None:
            self._objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        objc = self._objc
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        event_class = objc.objc_getClass(b"NSEvent")
        selector = objc.sel_registerName(b"doubleClickInterval")
        if not event_class or not selector:
            raise RuntimeError("NSEvent.doubleClickInterval is unavailable")
        # objc/message.h requires an appropriately typed function pointer.
        # NSTimeInterval is double on both supported macOS architectures.
        send_double = ctypes.CFUNCTYPE(
            ctypes.c_double, ctypes.c_void_p, ctypes.c_void_p
        )(("objc_msgSend", objc))
        return float(send_double(event_class, selector))

    def frontmost_app(self) -> AppIdentity:
        self._require_available()
        assert self._as is not None and self._libc is not None
        psn = ProcessSerialNumber()
        if self._as.GetFrontProcess(ctypes.byref(psn)) != 0:
            return AppIdentity(None, "", "")
        pid = ctypes.c_int32()
        if self._as.GetProcessPID(ctypes.byref(psn), ctypes.byref(pid)) != 0:
            return AppIdentity(None, "", "")

        buffer = ctypes.create_string_buffer(4096)
        length = self._libc.proc_pidpath(pid.value, buffer, len(buffer))
        executable = os.fsdecode(buffer.value) if length > 0 else ""
        bundle_id = self._bundle_id_for_executable(executable)
        return AppIdentity(int(pid.value), bundle_id, executable)

    @staticmethod
    def _bundle_id_for_executable(executable: str) -> str:
        if not executable:
            return ""
        candidate = Path(executable)
        app_root: Optional[Path] = None
        for path in (candidate,) + tuple(candidate.parents):
            if path.suffix.lower() == ".app":
                app_root = path
                break
        if app_root is None:
            return ""
        info_path = app_root / "Contents" / "Info.plist"
        try:
            with info_path.open("rb") as stream:
                info = plistlib.load(stream)
            value = info.get("CFBundleIdentifier", "")
            return value if isinstance(value, str) else ""
        except (OSError, plistlib.InvalidFileException):
            return ""

    def create_mouse_source(self, tag: int) -> ctypes.c_void_p:
        """Create one configured source for the lifetime of an armed session."""

        self._require_available()
        assert self._as is not None and self._cf is not None
        if not isinstance(tag, int) or tag <= 0 or tag >= 2**63:
            raise ValueError("tag must be a positive signed 64-bit integer")
        source = self._as.CGEventSourceCreate(self.EVENT_SOURCE_PRIVATE)
        if not source:
            raise RuntimeError("CGEventSourceCreate returned NULL")
        try:
            self._as.CGEventSourceSetUserData(source, ctypes.c_int64(tag))
            self._as.CGEventSourceSetLocalEventsSuppressionInterval(source, 0.0)
            # Explicitly keep real local mouse/keyboard/system input enabled in
            # both suppression states.  Physical input is a cancellation path.
            permit_all_local = 1 | 2 | 4
            self._as.CGEventSourceSetLocalEventsFilterDuringSuppressionState(
                source, permit_all_local, 0
            )
            self._as.CGEventSourceSetLocalEventsFilterDuringSuppressionState(
                source, permit_all_local, 1
            )
            return source
        except Exception:
            self._cf.CFRelease(source)
            raise

    def release_mouse_source(self, source: ctypes.c_void_p) -> None:
        self._require_available()
        assert self._cf is not None
        if source:
            self._cf.CFRelease(source)

    def associate_mouse_and_cursor(self, connected: bool) -> None:
        """Connect or disconnect hardware mouse motion from cursor position.

        The CoreGraphics call is process-global for the foreground application,
        so every caller must reconnect in an unconditional cleanup path.
        """

        self._require_available()
        assert self._as is not None
        error = int(
            self._as.CGAssociateMouseAndMouseCursorPosition(
                ctypes.c_int32(1 if connected else 0)
            )
        )
        if error != 0:
            state = "connect" if connected else "disconnect"
            raise RuntimeError(
                "CGAssociateMouseAndMouseCursorPosition failed to %s mouse and cursor: %d"
                % (state, error)
            )

    def warp_mouse_cursor(self, position: Tuple[float, float]) -> None:
        """Move the CoreGraphics logical cursor without synthesizing a MOVE."""

        self._require_available()
        assert self._as is not None
        x, y = float(position[0]), float(position[1])
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("mouse position must be finite")
        error = int(self._as.CGWarpMouseCursorPosition(CGPoint(x, y)))
        if error != 0:
            raise RuntimeError(
                "CGWarpMouseCursorPosition failed to move mouse cursor: %d" % error
            )

    def post_left_mouse(
        self,
        source: ctypes.c_void_p,
        kind: str,
        position: Tuple[float, float],
        tag: int,
    ) -> None:
        """Post one tagged absolute event; only its event object is transient."""

        self._post_left_mouse(source, kind, position, tag, relative_delta=None)

    def post_left_mouse_relative(
        self,
        source: ctypes.c_void_p,
        position: Tuple[float, float],
        delta: Tuple[int, int],
        tag: int,
    ) -> None:
        """Post a tagged drag at ``position`` with explicit integer deltas.

        CoreGraphics mouse delta fields are signed integer fields. The caller
        is responsible for keeping ``position`` and ``delta`` consistent.
        """

        self._post_left_mouse(source, "drag", position, tag, relative_delta=delta)

    def post_left_mouse_to_pid(
        self,
        source: ctypes.c_void_p,
        target_pid: int,
        kind: str,
        position: Tuple[float, float],
        tag: int,
    ) -> None:
        """Post one tagged absolute mouse event directly to a process."""

        if (
            not isinstance(target_pid, int)
            or isinstance(target_pid, bool)
            or target_pid <= 0
            or target_pid >= 2**31
        ):
            raise ValueError("target_pid must be a positive signed 32-bit integer")
        self._post_left_mouse(
            source,
            kind,
            position,
            tag,
            relative_delta=None,
            target_pid=target_pid,
        )

    def _post_left_mouse(
        self,
        source: ctypes.c_void_p,
        kind: str,
        position: Tuple[float, float],
        tag: int,
        relative_delta: Optional[Tuple[int, int]],
        target_pid: Optional[int] = None,
    ) -> None:
        self._require_available()
        assert self._as is not None and self._cf is not None
        event_type = {
            "down": self.LEFT_DOWN,
            "drag": self.LEFT_DRAGGED,
            "up": self.LEFT_UP,
        }.get(kind)
        if event_type is None:
            raise ValueError("unsupported mouse event kind: %s" % kind)
        x, y = float(position[0]), float(position[1])
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("mouse position must be finite")
        if not isinstance(tag, int) or tag <= 0 or tag >= 2**63:
            raise ValueError("tag must be a positive signed 64-bit integer")
        delta = None
        if relative_delta is not None:
            try:
                values = tuple(relative_delta)
            except TypeError as exc:
                raise ValueError(
                    "relative mouse delta must contain two signed integers"
                ) from exc
            if kind != "drag":
                raise ValueError("relative mouse delta is only valid for drag events")
            if (
                len(values) != 2
                or not all(
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and -(2**63) <= value < 2**63
                    for value in values
                )
            ):
                raise ValueError("relative mouse delta must contain two signed integers")
            delta = (int(values[0]), int(values[1]))
        if not source:
            raise RuntimeError("mouse event source is closed")
        event = None
        try:
            event = self._as.CGEventCreateMouseEvent(
                source,
                event_type,
                CGPoint(x, y),
                self.MOUSE_BUTTON_LEFT,
            )
            if not event:
                raise RuntimeError("CGEventCreateMouseEvent returned NULL")
            self._as.CGEventSetIntegerValueField(event, self.USER_DATA_FIELD, tag)
            self._as.CGEventSetIntegerValueField(
                event, self.MOUSE_CLICK_STATE_FIELD, self.SINGLE_CLICK_STATE
            )
            if delta is not None:
                self._as.CGEventSetIntegerValueField(
                    event, self.MOUSE_DELTA_X_FIELD, delta[0]
                )
                self._as.CGEventSetIntegerValueField(
                    event, self.MOUSE_DELTA_Y_FIELD, delta[1]
                )
            if target_pid is None:
                self._as.CGEventPost(self.HID_EVENT_TAP, event)
            else:
                self._as.CGEventPostToPid(ctypes.c_int32(target_pid), event)
        finally:
            if event:
                self._cf.CFRelease(event)

    def start_event_tap(self, callback: TapCallback, timeout: float = 0.5) -> "MacEventTap":
        self._require_available()
        tap = MacEventTap(self, callback)
        tap.start(timeout)
        return tap

    def _require_available(self) -> None:
        if not self.available:
            raise RuntimeError(self.unavailable_reason)


class MacEventTap:
    """Listen-only session event tap running on a private CFRunLoop thread."""

    _EVENT_TYPES = (
        MacOSBindings.LEFT_DOWN,
        MacOSBindings.LEFT_UP,
        MacOSBindings.RIGHT_DOWN,
        MacOSBindings.RIGHT_UP,
        MacOSBindings.MOUSE_MOVED,
        MacOSBindings.LEFT_DRAGGED,
        MacOSBindings.RIGHT_DRAGGED,
        MacOSBindings.SCROLL_WHEEL,
        MacOSBindings.OTHER_DOWN,
        MacOSBindings.OTHER_UP,
        MacOSBindings.OTHER_DRAGGED,
    )

    def __init__(self, bindings: MacOSBindings, callback: TapCallback) -> None:
        self._bindings = bindings
        self._callback = callback
        try:
            inspect.signature(callback).bind(0, 0, (0.0, 0.0), 0.0, {})
            self._callback_accepts_metadata = True
        except TypeError:
            self._callback_accepts_metadata = False
        except (ValueError, AttributeError):
            self._callback_accepts_metadata = True
        self._ready = Event()
        self._stop = Event()
        self._thread: Optional[Thread] = None
        self._lock = Lock()
        self._error = ""
        self._alive = False
        self._c_callback = bindings._tap_callback_type(self._on_event)

    @property
    def alive(self) -> bool:
        with self._lock:
            return self._alive and self._thread is not None and self._thread.is_alive()

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    def start(self, timeout: float = 0.5) -> None:
        self._thread = Thread(target=self._run, name="wheel-event-tap", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            self.stop()
            raise RuntimeError("event tap did not become ready")
        if not self.alive:
            raise RuntimeError(self.error or "event tap creation failed")

    def stop(self, timeout: float = 0.75) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout)

    def _on_event(
        self,
        _proxy: ctypes.c_void_p,
        event_type: int,
        event: ctypes.c_void_p,
        _refcon: ctypes.c_void_p,
    ) -> ctypes.c_void_p:
        bindings = self._bindings
        if event_type in (
            bindings.TAP_DISABLED_BY_TIMEOUT,
            bindings.TAP_DISABLED_BY_USER_INPUT,
        ):
            try:
                self._dispatch_event(int(event_type), 0, (0.0, 0.0), {})
            except Exception:
                pass
            return event

        try:
            assert bindings._as is not None
            tag = int(
                bindings._as.CGEventGetIntegerValueField(
                    event, bindings.USER_DATA_FIELD
                )
            )
            point = bindings._as.CGEventGetLocation(event)
            metadata = self._event_metadata(event)
            self._dispatch_event(
                int(event_type),
                tag,
                (float(point.x), float(point.y)),
                metadata,
            )
        except Exception:
            # A callback exception must never unwind into CoreFoundation.  The
            # tap thread remains alive; controller watchdogs provide fail-stop.
            pass
        return event

    def _event_metadata(self, event: ctypes.c_void_p) -> dict:
        bindings = self._bindings
        assert bindings._as is not None
        metadata = {}
        for name, field in (
            ("sourcePid", bindings.SOURCE_PID_FIELD),
            ("sourceStateId", bindings.SOURCE_STATE_ID_FIELD),
            ("clickState", bindings.MOUSE_CLICK_STATE_FIELD),
            ("deltaX", bindings.MOUSE_DELTA_X_FIELD),
            ("deltaY", bindings.MOUSE_DELTA_Y_FIELD),
            ("eventNumber", bindings.MOUSE_EVENT_NUMBER_FIELD),
            ("targetPid", bindings.TARGET_PID_FIELD),
        ):
            try:
                metadata[name] = int(
                    bindings._as.CGEventGetIntegerValueField(event, field)
                )
            except Exception:
                # Missing diagnostic fields must never hide an input event.
                metadata[name] = None
        return metadata

    def _dispatch_event(
        self,
        event_type: int,
        tag: int,
        position: Tuple[float, float],
        metadata: dict,
    ) -> None:
        timestamp = time.monotonic()
        if self._callback_accepts_metadata:
            self._callback(event_type, tag, position, timestamp, metadata)
        else:
            self._callback(event_type, tag, position, timestamp)

    def _run(self) -> None:  # pragma: no cover - exercised only on macOS host
        api = self._bindings._as
        cf = self._bindings._cf
        assert api is not None and cf is not None
        tap = None
        source = None
        run_loop = None
        mode = None
        try:
            mask = 0
            for event_type in self._EVENT_TYPES:
                mask |= 1 << event_type
            tap = api.CGEventTapCreate(
                self._bindings.SESSION_EVENT_TAP,
                self._bindings.TAIL_APPEND_EVENT_TAP,
                self._bindings.LISTEN_ONLY,
                ctypes.c_uint64(mask),
                self._c_callback,
                None,
            )
            if not tap:
                raise RuntimeError(
                    "CGEventTapCreate returned NULL (Input Monitoring permission may be missing)"
                )
            source = cf.CFMachPortCreateRunLoopSource(None, tap, 0)
            if not source:
                raise RuntimeError("CFMachPortCreateRunLoopSource returned NULL")
            run_loop = cf.CFRunLoopGetCurrent()
            mode = ctypes.c_void_p.in_dll(cf, "kCFRunLoopDefaultMode").value
            if not run_loop or not mode:
                raise RuntimeError("CoreFoundation run loop initialization failed")
            cf.CFRunLoopAddSource(run_loop, source, mode)
            api.CGEventTapEnable(tap, True)
            with self._lock:
                self._alive = True
            self._ready.set()

            while not self._stop.is_set():
                cf.CFRunLoopRunInMode(mode, 0.05, True)
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
            self._ready.set()
        finally:
            with self._lock:
                self._alive = False
            if source and run_loop and mode:
                cf.CFRunLoopRemoveSource(run_loop, source, mode)
            if source:
                cf.CFRelease(source)
            if tap:
                cf.CFRelease(tap)
