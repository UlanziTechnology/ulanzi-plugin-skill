"""Same-frame, read-only YRGB evidence. Nothing here drives the wheel model.

The observer only prepares geometry, crops its original ROI and enqueues a
reference to immutable captured bytes. PNG encoding, disk I/O and Vision run
on a bounded daemon worker. No AX calls or additional captures are made.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
from queue import Empty, Full, Queue
import re
import struct
import subprocess
from threading import Event, Lock, Thread, current_thread
import time
import uuid
import zlib

from .host_trace import _default_directory
from .macos import CapturedBitmap


CHANNELS = ("Y", "R", "G", "B")
_NUMBER = re.compile(r"^[+-]?\d+\.\d+$", re.ASCII)
_METADATA_KEYS = (
    "sessionId", "generation", "revision", "gestureId", "trigger", "mode",
    "motionRevision", "freshHandleEpoch", "timing", "captureStartedAt",
    "captureFinishedAt", "requestedAt", "observationStartedAt",
    "captureId", "modelBeforeCapture", "actual", "observationResult",
    "observationReason",
    "wheelCenter", "visualMaxRadius",
    "handleDetection", "wheelTarget",
)


def _rect(value):
    if isinstance(value, dict):
        value = (value.get("x"), value.get("y"),
                 value.get("w", value.get("width")),
                 value.get("h", value.get("height")))
    try:
        result = tuple(float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if (len(result) != 4 or not all(math.isfinite(v) for v in result)
            or result[2] <= 0 or result[3] <= 0):
        return None
    return result


def _integral(rect):
    x, y, w, h = rect
    left, top = math.floor(x), math.floor(y)
    return (left, top, math.ceil(x + w) - left, math.ceil(y + h) - top)


def _contains(outer, inner):
    x, y, w, h = outer
    ix, iy, iw, ih = inner
    return x <= ix and y <= iy and ix + iw <= x + w and iy + ih <= y + h


def _select_numeric_frames(center, radius, areas):
    """Fail closed on ambiguous rows; never infer channels from tree order."""
    cx, cy = center
    candidates = []
    for area in areas or ():
        if not isinstance(area, dict) or area.get("type") != "numeric":
            continue
        frame = _rect(area.get("source_frame"))
        if frame is None:
            continue
        x, y, w, h = frame
        if (2 <= w <= 90 and 4 <= h <= 40
                and cx - radius - 20 <= x + w / 2 <= cx + radius + 20
                and cy + radius - 4 <= y <= cy + radius + 70):
            if frame not in candidates:
                candidates.append(frame)
    rows = []
    for frame in sorted(candidates, key=lambda r: (r[1] + r[3] / 2, r[0])):
        center_y = frame[1] + frame[3] / 2
        row = next((r for r in rows if abs(r[0] - center_y) <= 6), None)
        if row is None:
            rows.append([center_y, [frame]])
        else:
            row[1].append(frame)
    valid = []
    for _y, frames in rows:
        frames.sort(key=lambda r: r[0])
        if len(frames) != 4:
            continue
        if any(a[0] + a[2] > b[0] + 0.5 for a, b in zip(frames, frames[1:])):
            continue
        middle = (frames[0][0] + frames[-1][0] + frames[-1][2]) / 2
        if abs(middle - cx) <= max(16.0, radius * 0.35):
            valid.append(tuple(frames))
    return valid[0] if len(valid) == 1 else ()


def _validate_bitmap(bitmap):
    if (not isinstance(bitmap, CapturedBitmap) or not isinstance(bitmap.pixels, bytes)
            or bitmap.width <= 0 or bitmap.height <= 0
            or bitmap.width > 4096 or bitmap.height > 4096
            or bitmap.bytes_per_row < bitmap.width * 4
            or len(bitmap.pixels) < bitmap.bytes_per_row * bitmap.height
            or not math.isfinite(bitmap.scale_x) or bitmap.scale_x <= 0
            or not math.isfinite(bitmap.scale_y) or bitmap.scale_y <= 0
            or _rect(bitmap.screen_rect) is None
            or len(bitmap.color_offsets) != 3
            or len(set(bitmap.color_offsets)) != 3
            or any(v not in (0, 1, 2, 3) for v in bitmap.color_offsets)):
        raise ValueError("invalid numeric capture bitmap")


@dataclass(frozen=True)
class ScopedNumericCapture:
    owner: "NumericWheelTrace"
    frames: tuple
    _reported: set = field(default_factory=set, compare=False, repr=False)

    def _unavailable(self, reason):
        if reason not in self._reported:
            self._reported.add(reason)
            self.owner._notice({"event": "numeric_capture_unavailable", "reason": reason})
        return None

    def prepare(self, roi, display_bounds):
        """Expand only the integral bottom; None keeps the ordinary capture."""
        roi, display = _rect(roi), _rect(display_bounds)
        if not self.frames and not self.owner._archive_wheel:
            return None
        if roi is None or display is None:
            return self._unavailable("invalid_roi_or_display_bounds")
        if not self.owner._accepting:
            return self._unavailable("numeric_recorder_unavailable")
        wheel = _integral(roi)
        left, top, width, height = wheel
        if self.owner._archive_wheel and (
                width > 2048 or height > 2048 or not _contains(display, wheel)):
            return self._unavailable("original_wheel_roi_outside_display_or_limit")
        if not self.frames:
            return NumericCapturePlan(self.owner, wheel, wheel, None, ())
        # Two logical pixels of context are sufficient for the text ROI and
        # remain inside the original horizontal wheel-capture footprint.
        strip_left = math.floor(min(r[0] for r in self.frames)) - 2
        strip_top = math.floor(min(r[1] for r in self.frames)) - 2
        strip_right = math.ceil(max(r[0] + r[2] for r in self.frames)) + 2
        strip_bottom = math.ceil(max(r[1] + r[3] for r in self.frames)) + 2
        strip = (strip_left, strip_top, strip_right - strip_left,
                 strip_bottom - strip_top)
        capture = (left, top, width, max(top + height, strip_bottom) - top)
        if (strip_left < left or strip_right > left + width or strip_top < top
                or capture[3] > height + 100 or width > 2048 or capture[3] > 2048
                or not _contains(display, capture) or not _contains(capture, strip)):
            self._unavailable("numeric_strip_cannot_fit_downward_same_display")
            if self.owner._archive_wheel:
                return NumericCapturePlan(self.owner, wheel, wheel, None, ())
            return None
        return NumericCapturePlan(self.owner, wheel, capture, strip, self.frames)


@dataclass(frozen=True)
class NumericCapturePlan:
    owner: "NumericWheelTrace"
    wheel_roi: tuple
    capture_roi: tuple
    strip_roi: tuple | None
    frames: tuple

    def crop_wheel(self, bitmap):
        """The original capture is an exact top prefix, including row padding."""
        _validate_bitmap(bitmap)
        if tuple(bitmap.screen_rect) != tuple(self.capture_roi):
            raise ValueError("capture bitmap does not match numeric plan")
        left, top, width, height = self.wheel_roi
        pixel_width = int(round(width * bitmap.scale_x))
        pixel_height = int(round(height * bitmap.scale_y))
        if (pixel_width != bitmap.width or pixel_height > bitmap.height
                or abs(pixel_height - height * bitmap.scale_y) > 1e-6):
            raise ValueError("numeric capture changed the original pixel grid")
        return CapturedBitmap(
            pixels=bitmap.pixels[:bitmap.bytes_per_row * pixel_height],
            width=pixel_width, height=pixel_height,
            bytes_per_row=bitmap.bytes_per_row,
            screen_rect=(float(left), float(top), float(width), float(height)),
            scale_x=bitmap.scale_x, scale_y=bitmap.scale_y,
            color_offsets=bitmap.color_offsets,
        )

    def submit(self, bitmap, metadata):
        return self.owner._submit(self, bitmap, metadata)


class NumericWheelTrace:
    """Bounded optional evidence capture; callbacks must only enqueue logs."""

    def __init__(self, trace_callback, directory=None, helper_path=None, *,
                 queue_capacity=8, max_bytes=32 * 1024 * 1024,
                 ocr_timeout=3.0, ocr_runner=None, ocr_enabled=False,
                 archive_wheel=False):
        if int(queue_capacity) < 1 or int(max_bytes) < 1:
            raise ValueError("numeric queue and byte budget must be positive")
        self._callback = trace_callback
        self._archive_wheel = bool(archive_wheel)
        self._run_id = "numeric-%s-%s-%s" % (os.getpid(), time.time_ns(), uuid.uuid4().hex[:8])
        self._directory = (Path(directory) if directory is not None else _default_directory()) / self._run_id
        self._helper = Path(helper_path) if helper_path else Path(__file__).parent / "native" / "numeric_ocr"
        self._queue = Queue(maxsize=int(queue_capacity))
        self._ocr_queue = Queue(maxsize=8)
        self._max_bytes = int(max_bytes)
        self._timeout = max(0.01, min(3.0, float(ocr_timeout)))
        self._ocr_runner = ocr_runner or self._run_ocr
        # Production defaults to archival only. Supplying an explicit fake
        # runner also opts in for isolated tests; no native OCR process or OCR
        # thread is started merely by constructing the default recorder.
        self._ocr_enabled = bool(ocr_enabled or ocr_runner is not None)
        self._lock = Lock()
        self._stop = Event()
        self._archive_finished = Event()
        self.ready = Event()
        self.finished = Event()
        self._accepting = True
        self._sequence = self._enqueued = self._dropped = self._written = 0
        self._bytes = self._errors = self._callback_errors = 0
        self._files_written = 0
        self._ocr_dropped = self._ocr_completed = 0
        self._budget_exhausted = False
        self._error = None
        self._thread = Thread(target=self._run, name="wheel-numeric-trace", daemon=True)
        self._ocr_thread = (Thread(target=self._run_ocr_worker, name="wheel-numeric-ocr", daemon=True)
                            if self._ocr_enabled else None)
        try:
            if self._ocr_thread is not None:
                self._ocr_thread.start()
            self._thread.start()
        except Exception as exc:
            self._accepting = False
            self._error = str(exc)
            self._archive_finished.set()
            self.finished.set()

    def scope(self, center, max_radius, areas):
        reason = "four_unambiguous_numeric_frames_not_found"
        try:
            center = tuple(float(v) for v in center)
            radius = float(max_radius)
            if (len(center) != 2 or not all(math.isfinite(v) for v in center)
                    or not math.isfinite(radius) or radius < 4):
                raise ValueError("invalid numeric scope geometry")
            frames = _select_numeric_frames(center, radius, areas)
        except (TypeError, ValueError):
            frames = ()
            reason = "invalid_scope_geometry"
        if not frames:
            self._notice({"event": "numeric_layout_unavailable", "reason": reason})
        return ScopedNumericCapture(self, frames)

    def _notice(self, event):
        # Known-safe tiny metadata goes directly to the host in-memory queue;
        # unlike _emit, it does not serialize on the caller's thread.
        try:
            self._callback({**event, "monotonic": time.monotonic(),
                            "wallTimeMs": time.time() * 1000})
        except Exception:
            with self._lock:
                self._callback_errors += 1

    def _submit(self, plan, bitmap, metadata):
        # O(1) buffer handoff. No bytes conversion, PNG, JSON, filesystem or OCR.
        meta = {key: metadata[key] for key in _METADATA_KEYS if key in metadata} if isinstance(metadata, dict) else {}
        with self._lock:
            self._sequence += 1
            sample_id = "%s-%06d" % (self._run_id, self._sequence)
            result = {"sampleId": sample_id, "status": "queued"}
            if not self._accepting:
                self._dropped += 1
                result["status"] = "budget_exhausted" if self._budget_exhausted else "closed"
            else:
                try:
                    self._queue.put_nowait((sample_id, plan, bitmap, meta))
                except Full:
                    self._dropped += 1
                    result["status"] = "queue_full"
                else:
                    self._enqueued += 1
            result.update(dropped=self._dropped, queued=self._queue.qsize())
            return result

    def status(self):
        with self._lock:
            return {"directory": str(self._directory), "ready": self.ready.is_set(),
                    "finished": self.finished.is_set(), "accepting": self._accepting,
                    "queued": self._queue.qsize(), "enqueued": self._enqueued,
                    "dropped": self._dropped, "written": self._written,
                    "ocrQueued": self._ocr_queue.qsize(), "ocrDropped": self._ocr_dropped,
                    "ocrCompleted": self._ocr_completed, "ocrTimeoutSeconds": self._timeout,
                    "ocrEnabled": self._ocr_enabled,
                    "archiveWheel": self._archive_wheel, "filesWritten": self._files_written,
                    "errors": self._errors, "callbackErrors": self._callback_errors,
                    "error": self._error,
                    "budget": {"max_bytes": self._max_bytes, "bytes_written": self._bytes,
                               "exhausted": self._budget_exhausted}}

    def close(self, timeout=0.25):
        try:
            timeout = float(timeout)
            if not math.isfinite(timeout):
                timeout = 0.25
        except (TypeError, ValueError):
            timeout = 0.25
        with self._lock:
            self._accepting = False
            self._stop.set()
        deadline = time.monotonic() + max(0.0, min(timeout, 1.0))
        for thread in (self._thread, self._ocr_thread):
            if thread is not None and thread.ident is not None and thread is not current_thread():
                thread.join(max(0, deadline - time.monotonic()))
        return self.status()

    def _emit(self, event):
        # Worker-only serialization validation keeps malformed diagnostic data
        # from poisoning the host trace. No transport or model callbacks exist.
        try:
            json.dumps(event, allow_nan=False)
            self._callback(event)
        except Exception as exc:
            with self._lock:
                self._callback_errors += 1
                self._error = "callback: %s" % exc

    @staticmethod
    def _png(bitmap, strip_roi, frames):
        _validate_bitmap(bitmap)
        bx, by, _, _ = bitmap.screen_rect
        sx, sy, sw, sh = strip_roi
        left = int(round((sx - bx) * bitmap.scale_x))
        top = int(round((sy - by) * bitmap.scale_y))
        width, height = int(round(sw * bitmap.scale_x)), int(round(sh * bitmap.scale_y))
        if left < 0 or top < 0 or left + width > bitmap.width or top + height > bitmap.height:
            raise ValueError("numeric strip is outside captured bitmap")
        rgb_row_bytes = width * 3 + 1
        rgb = bytearray(height * rgb_row_bytes)
        output = memoryview(rgb)
        r, g, b = bitmap.color_offsets
        for y in range(top, top + height):
            # PNG filter byte stays zero. Extended slices copy whole channels
            # in C, avoiding a Python/GIL loop for every full-frame pixel.
            source_start = y * bitmap.bytes_per_row + left * 4
            source_end = source_start + width * 4
            row_start = (y - top) * rgb_row_bytes + 1
            row = output[row_start:row_start + width * 3]
            row[0::3] = bitmap.pixels[source_start + r:source_end:4]
            row[1::3] = bitmap.pixels[source_start + g:source_end:4]
            row[2::3] = bitmap.pixels[source_start + b:source_end:4]

        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)

        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(rgb, 3)) + chunk(b"IEND", b""))
        boxes = []
        for channel, (x, y, w, h) in zip(CHANNELS, frames):
            px = max(0, math.floor((x - sx) * bitmap.scale_x) - 1)
            py = max(0, math.floor((y - sy) * bitmap.scale_y) - 1)
            right = min(width, math.ceil((x + w - sx) * bitmap.scale_x) + 1)
            bottom = min(height, math.ceil((y + h - sy) * bitmap.scale_y) + 1)
            boxes.append({"channel": channel, "x": px, "y": py, "w": right - px, "h": bottom - py})
        return png, boxes, (width, height)

    def _run_ocr(self, path, boxes):
        result = subprocess.run([str(self._helper), str(path), json.dumps(boxes)],
                                capture_output=True, text=True, timeout=self._timeout,
                                check=True)
        if len(result.stdout) > 64 * 1024:
            raise ValueError("numeric OCR response too large")
        return json.loads(result.stdout)

    @staticmethod
    def _channels(output):
        records = output.get("channels", []) if isinstance(output, dict) else []
        if not isinstance(records, list):
            records = []
        result = {}
        for channel in CHANNELS:
            matches = [r for r in records if isinstance(r, dict) and r.get("channel") == channel]
            record = matches[0] if len(matches) == 1 else {}
            observations = record.get("observations") or []
            if not isinstance(observations, list):
                observations = []
            candidates = observations[0].get("candidates", []) if len(observations) == 1 and isinstance(observations[0], dict) else []
            if not isinstance(candidates, list):
                candidates = []
            first = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
            raw = first.get("text")
            confidence = first.get("confidence")
            numeric = isinstance(raw, str) and bool(_NUMBER.fullmatch(raw.strip()))
            value = float(raw) if numeric else None
            precision = len(raw.strip().rsplit(".", 1)[1]) if numeric else None
            if not isinstance(confidence, (float, int)) or not math.isfinite(confidence):
                confidence = None
            valid = (numeric and math.isfinite(value) and confidence is not None
                     and 0.6 <= confidence <= 1.0)
            result[channel] = {"status": "recognized" if valid else "unknown",
                               "raw": raw, "value": value if valid else None,
                               "displayPrecision": precision,
                               "valueKind": "displayed_text_not_internal_precision",
                               "confidence": confidence, "observations": observations,
                               "error": record.get("error")}
        return result

    def _process(self, job):
        sample_id, plan, bitmap, meta = job
        has_numeric = plan.strip_roi is not None and len(plan.frames) == 4
        event = {**meta, "event": "wheel_numeric_capture", "sampleId": sample_id,
                 "monotonic": time.monotonic(), "wallTimeMs": time.time() * 1000,
                 "channelOrder": list(CHANNELS) if has_numeric else [],
                 "source": ("same_frame_wheel_and_numeric" if has_numeric else "same_frame_wheel_only")
                 if self._archive_wheel else "same_frame_vision_ocr",
                 "captureRoi": list(plan.capture_roi),
                 "stripRoi": list(plan.strip_roi) if has_numeric else None,
                 "sourceFrames": [list(r) for r in plan.frames],
                 "hasNumericStrip": has_numeric}
        processing_started = time.monotonic()
        ocr_job = None
        try:
            _validate_bitmap(bitmap)
            if tuple(bitmap.screen_rect) != tuple(plan.capture_roi):
                raise ValueError("numeric bitmap does not match its plan")
            artifacts = []
            if self._archive_wheel:
                wheel_png, _unused_boxes, wheel_size = self._png(bitmap, bitmap.screen_rect, ())
                artifacts.append(("wheel", wheel_png, wheel_size, [],
                                  self._directory / (sample_id + "-wheel.png")))
                event.update(wheelRoi=list(plan.wheel_roi),
                             wheelImageRoi=list(bitmap.screen_rect),
                             scale={"x": bitmap.scale_x, "y": bitmap.scale_y},
                             colorOffsets=list(bitmap.color_offsets),
                             bytesPerRow=bitmap.bytes_per_row, pngPixelFormat="RGB8")
            if has_numeric:
                png, boxes, size = self._png(bitmap, plan.strip_roi, plan.frames)
                artifacts.append(("numeric", png, size, boxes,
                                  self._directory / (sample_id + ".png")))
            if not artifacts:
                raise ValueError("capture has neither numeric strip nor enabled wheel archive")
            required_bytes = sum(len(item[1]) for item in artifacts)
            with self._lock:
                exceeds = self._bytes + required_bytes > self._max_bytes
                if exceeds:
                    self._budget_exhausted = True
                    self._accepting = False
                    self._dropped += 1
            if exceeds:
                event.update(status="budget_exhausted", channels=self._channels(None),
                             requiredBytes=required_bytes, diagnostics=self.status())
                self._emit(event)
                return
            for kind, payload, size, boxes, path in artifacts:
                if kind == "wheel":
                    event.update(wheelImagePath=str(path), wheelImageSize=list(size))
                else:
                    event.update(imagePath=str(path), imageSize=list(size), boxes=boxes)
                self._write_png(path, payload)
            with self._lock:
                self._written += 1
            event["status"] = "pending" if self._ocr_enabled and has_numeric else "archived"
            event["ocrDisabled"] = not self._ocr_enabled or not has_numeric
            if not has_numeric:
                event["ocrSkippedReason"] = "numeric_strip_unavailable"
            # Disk evidence has already been saved. OCR saturation can drop
            # recognition work, never the PNG or its same-frame metadata.
            if not self._ocr_enabled or not has_numeric:
                pass
            elif self._ocr_queue.full():
                event["status"] = "ocr_queue_full"
                with self._lock:
                    self._ocr_dropped += 1
            else:
                ocr_job = dict(event)
        except Exception as exc:
            event.update(status="capture_error", error="%s: %s" % (type(exc).__name__, exc), channels=self._channels(None))
            with self._lock:
                self._errors += 1
                self._dropped += 1
                self._error = event["error"]
        event["diagnostics"] = self.status()
        event["processingMs"] = (time.monotonic() - processing_started) * 1000
        self._emit(event)
        if ocr_job is not None:
            # Only this archival thread produces OCR jobs, so after full() was
            # false the consumer can only create more space. Publish the disk
            # record first, before a fast OCR result can overtake it.
            self._ocr_queue.put_nowait(ocr_job)

    def _write_png(self, path, payload):
        """Worker-only exclusive write, including partial bytes in the cap."""
        with path.open("xb") as stream:
            count = 0
            complete = False
            try:
                returned = stream.write(payload)
                if isinstance(returned, int):
                    count = max(0, returned)
                if returned != len(payload):
                    raise OSError("short diagnostic PNG write")
                stream.flush()
                complete = True
            finally:
                # tell() also accounts for a write which raised after copying
                # some bytes. Never erase or overwrite that partial evidence.
                try:
                    count = max(count, int(stream.tell()))
                except Exception:
                    pass
                with self._lock:
                    self._bytes += count
                    self._files_written += int(complete)

    def _run_ocr_worker(self):
        try:
            while True:
                if self._archive_finished.is_set() and self._ocr_queue.empty():
                    break
                try:
                    event = self._ocr_queue.get(timeout=0.025)
                except Empty:
                    continue
                event["event"] = "wheel_numeric_sample"
                event["ocrStartedAt"] = time.monotonic()
                try:
                    output = self._ocr_runner(Path(event["imagePath"]), event["boxes"])
                    event["channels"] = self._channels(output)
                    event["status"] = "recognized" if all(v["status"] == "recognized" for v in event["channels"].values()) else "unknown"
                except Exception as exc:
                    event.update(status="ocr_error", error="%s: %s" % (type(exc).__name__, exc), channels=self._channels(None))
                    with self._lock:
                        self._errors += 1
                        self._error = event["error"]
                event["ocrFinishedAt"] = time.monotonic()
                event["ocrMs"] = (event["ocrFinishedAt"] - event["ocrStartedAt"]) * 1000
                with self._lock:
                    self._ocr_completed += 1
                event["diagnostics"] = self.status()
                self._emit(event)
        finally:
            self.finished.set()

    def _run(self):
        try:
            self._directory.mkdir(parents=True, exist_ok=False)
            self.ready.set()
            while True:
                if (self._stop.is_set() or self._budget_exhausted) and self._queue.empty():
                    break
                try:
                    job = self._queue.get(timeout=0.025)
                except Empty:
                    continue
                if self._budget_exhausted:
                    with self._lock:
                        self._dropped += 1
                    continue
                self._process(job)
        except Exception as exc:
            with self._lock:
                self._errors += 1
                self._error = "worker: %s: %s" % (type(exc).__name__, exc)
        finally:
            with self._lock:
                self._accepting = False
            while True:
                try:
                    self._queue.get_nowait()
                except Empty:
                    break
                with self._lock:
                    self._dropped += 1
            self._archive_finished.set()
            if not self._ocr_enabled:
                self.finished.set()


__all__ = ["NumericWheelTrace", "ScopedNumericCapture", "NumericCapturePlan"]
