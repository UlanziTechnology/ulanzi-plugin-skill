"""Fast event-tap bookkeeping for the live mouse safety interlock."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import math
import secrets
from threading import Lock
from typing import Callable, Deque, Optional, Tuple

from .macos import MacOSBindings


@dataclass(frozen=True)
class _PendingPost:
    sequence: int
    kind: str
    posted_at: float
    position: Optional[Tuple[float, float]]


class InputInterlock:
    """Classify observed events without doing blocking work in the tap callback."""

    CONTROLLED_WARP_ECHO_TIMEOUT = 0.075
    CONTROLLED_WARP_ECHO_TOLERANCE = 0.5
    DRAG_CONFIRMATION_TIMEOUT = 0.150
    CONFIRMATION_POSITION_TOLERANCE = 0.5

    def __init__(
        self,
        expected_position: Tuple[float, float],
        movement_tolerance: float = 3.0,
        confirmation_timeout: float = 0.075,
        target_pid: Optional[int] = None,
        trace_callback: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.tag = secrets.randbelow(2**62 - 1) + 1
        self._lock = Lock()
        self._expected = expected_position
        self._movement_tolerance = float(movement_tolerance)
        self._confirmation_timeout = float(confirmation_timeout)
        self._drag_confirmation_timeout = max(
            self._confirmation_timeout,
            self.DRAG_CONFIRMATION_TIMEOUT,
        )
        self._pending_posts: Deque[_PendingPost] = deque()
        self._post_sequence = 0
        self._cancel_reason = ""
        self._owner_down = False
        self._owner_revision = 0
        self._posted = 0
        self._confirmed = 0
        self._confirmed_posts = 0
        self._covered_drag_posts = 0
        self._drag_posts_confirmed_by_drag = 0
        self._drag_posts_confirmed_by_up = 0
        self._coalesced_drag_posts = 0
        self._unmatched_tagged_events = 0
        self._max_pending_confirmations = 0
        self._last_posted_event: Optional[dict] = None
        self._last_tagged_confirmation: Optional[dict] = None
        self._confirmation_failure: Optional[dict] = None
        self._external_events = 0
        self._target_pid = target_pid
        self._trace_callback = trace_callback
        self._observed_click_states = {}
        self._last_external_event: Optional[dict] = None
        self._cancel_event: Optional[dict] = None
        self._controlled_warp_sequence = 0
        self._controlled_warp_echo: Optional[
            Tuple[int, float, float, float, float]
        ] = None
        self._suppressed_controlled_warp_echoes = 0
        self._external_classifications = {
            "target_app": 0,
            "external_or_unknown": 0,
        }

    @property
    def owner_down(self) -> bool:
        with self._lock:
            return self._owner_down

    @property
    def cancel_reason(self) -> str:
        with self._lock:
            return self._cancel_reason

    def set_owner_down(self, value: bool) -> None:
        with self._lock:
            value = bool(value)
            if value != self._owner_down:
                self._owner_revision += 1
            self._owner_down = value
            if not self._owner_down:
                self._controlled_warp_echo = None

    def unowned_button_down(self, read_button_down: Callable[[], bool]) -> bool:
        """Admit only a stable native DOWN sample outside plugin ownership.

        A native read can overlap a complete DOWN/UP or a delayed tagged UP.
        Never combine that old snapshot with the later ownership state. Do
        not hold the tap's lock during native I/O: changed samples are retried
        on the next safety poll, while event-tap cancellation and confirmation
        deadlines remain authoritative throughout the transition.
        """
        with self._lock:
            if self._owner_down or self._pending_posts:
                return False
            token = (self._owner_revision, self._post_sequence)
        down = bool(read_button_down())
        with self._lock:
            return bool(
                down
                and not self._owner_down
                and not self._pending_posts
                and token == (self._owner_revision, self._post_sequence)
            )

    def expect(self, position: Tuple[float, float]) -> None:
        with self._lock:
            self._expected = (float(position[0]), float(position[1]))

    def note_controlled_warp(
        self,
        position: Tuple[float, float],
        timestamp: float,
    ) -> int:
        """Arm one exact, zero-delta echo expected from our next CG warp."""

        x = float(position[0])
        y = float(position[1])
        registered_at = float(timestamp)
        if not all(math.isfinite(value) for value in (x, y, registered_at)):
            raise ValueError("controlled warp position and timestamp must be finite")
        with self._lock:
            if not self._owner_down or self._cancel_reason:
                raise RuntimeError("controlled warp requires an active safe session")
            self._controlled_warp_sequence += 1
            token = self._controlled_warp_sequence
            self._controlled_warp_echo = (
                token,
                x,
                y,
                registered_at,
                registered_at + self.CONTROLLED_WARP_ECHO_TIMEOUT,
            )
            return token

    def cancel_controlled_warp(self, token: int) -> None:
        """Revoke an unconsumed echo ticket without touching a newer warp."""

        with self._lock:
            pending = self._controlled_warp_echo
            if pending is not None and pending[0] == int(token):
                self._controlled_warp_echo = None

    def note_posted(
        self,
        timestamp: float,
        kind: Optional[str] = None,
        position: Optional[Tuple[float, float]] = None,
    ) -> None:
        """Record one posted event before it enters CoreGraphics.

        Production callers provide ``kind`` and ``position`` so motion
        callbacks can acknowledge a coalesced run of DRAG events without ever
        acknowledging a missing DOWN or UP.  ``kind=None`` preserves the old
        one-callback/one-post contract for small fake-backed tests.
        """

        posted_at = float(timestamp)
        if not math.isfinite(posted_at):
            raise ValueError("posted event timestamp must be finite")
        normalized_kind = "any" if kind is None else str(kind)
        if normalized_kind not in ("any", "down", "drag", "up", "move"):
            raise ValueError("posted event kind must be down, drag, up, or move")
        normalized_position = None
        if position is not None:
            x = float(position[0])
            y = float(position[1])
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("posted event position must be finite")
            normalized_position = (x, y)
        with self._lock:
            self._post_sequence += 1
            pending = _PendingPost(
                sequence=self._post_sequence,
                kind=normalized_kind,
                posted_at=posted_at,
                position=normalized_position,
            )
            self._posted += 1
            self._pending_posts.append(pending)
            pending_count = len(self._pending_posts)
            self._max_pending_confirmations = max(
                self._max_pending_confirmations,
                pending_count,
            )
            self._last_posted_event = self._pending_description(pending)

    def mark_cancel(self, reason: str) -> None:
        with self._lock:
            if not self._cancel_reason:
                self._cancel_reason = str(reason)
            self._controlled_warp_echo = None

    def handle_event(
        self,
        event_type: int,
        tag: int,
        position: Tuple[float, float],
        timestamp: float,
        metadata: Optional[dict] = None,
    ) -> None:
        """Tap callback entry point; bookkeeping and an optional queue write."""

        observed = None
        with self._lock:
            if event_type in (
                MacOSBindings.TAP_DISABLED_BY_TIMEOUT,
                MacOSBindings.TAP_DISABLED_BY_USER_INPUT,
            ):
                if not self._cancel_reason:
                    self._cancel_reason = "event_tap_disabled"
                    self._cancel_event = self._describe_event(
                        event_type, tag, position, timestamp, metadata,
                        "event_tap_disabled",
                    )
                self._controlled_warp_echo = None
                return

            if tag == self.tag:
                self._confirmed += 1
                confirmation = self._confirm_tagged_unlocked(
                    event_type,
                    position,
                    timestamp,
                )
                observed = self._describe_event(
                    event_type, tag, position, timestamp, metadata,
                    "tagged_confirmation",
                )
                observed["classification"] = "session_tagged"
                observed["confirmation"] = deepcopy(confirmation)
                click_state = observed["clickState"]
                key = "%s:%s" % (
                    observed["kind"], "unknown" if click_state is None else click_state
                )
                self._observed_click_states[key] = self._observed_click_states.get(key, 0) + 1
            else:
                external_types = {
                    MacOSBindings.LEFT_DOWN,
                    MacOSBindings.LEFT_UP,
                    MacOSBindings.RIGHT_DOWN,
                    MacOSBindings.RIGHT_UP,
                    MacOSBindings.LEFT_DRAGGED,
                    MacOSBindings.RIGHT_DRAGGED,
                    MacOSBindings.SCROLL_WHEEL,
                    MacOSBindings.OTHER_DOWN,
                    MacOSBindings.OTHER_UP,
                    MacOSBindings.OTHER_DRAGGED,
                }
                if event_type in external_types:
                    observed = self._record_external_event(
                        event_type, tag, position, timestamp, metadata,
                        "external_pointer_event",
                    )
                elif event_type == MacOSBindings.MOUSE_MOVED:
                    x, y = position
                    expected_x, expected_y = self._expected
                    distance = math.hypot(x - expected_x, y - expected_y)
                    fields = metadata if isinstance(metadata, dict) else {}
                    delta_x = fields.get("deltaX")
                    delta_y = fields.get("deltaY")
                    has_exact_zero_deltas = all(
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        and math.isfinite(value)
                        and value == 0
                        for value in (delta_x, delta_y)
                    )
                    has_relative_motion = any(
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        and math.isfinite(value)
                        and value != 0
                        for value in (delta_x, delta_y)
                    )
                    controlled_warp_echo = self._controlled_warp_echo
                    suppress_controlled_warp_echo = False
                    if controlled_warp_echo is not None:
                        (
                            _token,
                            warp_x,
                            warp_y,
                            registered_at,
                            expires_at,
                        ) = controlled_warp_echo
                        warp_distance = math.hypot(x - warp_x, y - warp_y)
                        event_time = float(timestamp)
                        suppress_controlled_warp_echo = (
                            has_exact_zero_deltas
                            and math.isfinite(warp_distance)
                            and warp_distance
                            <= self.CONTROLLED_WARP_ECHO_TOLERANCE
                            and math.isfinite(event_time)
                            and registered_at <= event_time <= expires_at
                        )
                        if suppress_controlled_warp_echo:
                            # One ticket suppresses one exact CGWarp echo only.
                            # It intentionally survives tagged anchor events,
                            # which can overtake the untagged system callback.
                            self._controlled_warp_echo = None
                            self._suppressed_controlled_warp_echoes += 1
                        elif (
                            not math.isfinite(event_time)
                            or event_time > expires_at
                        ):
                            self._controlled_warp_echo = None
                    # While mouse/cursor association is disconnected, genuine
                    # hardware motion keeps a constant absolute location and is
                    # visible only through the delta fields.  It remains an
                    # immediate cancellation path just like an absolute move.
                    if not suppress_controlled_warp_echo and (
                        has_relative_motion
                        or not math.isfinite(distance)
                        or distance > self._movement_tolerance
                    ):
                        observed = self._record_external_event(
                            event_type, tag, position, timestamp, metadata,
                            "external_pointer_move",
                        )
        # Never invoke a diagnostic callback while holding the interlock lock.
        # The callback may only enqueue this record, and failure cannot undo
        # confirmation accounting or the cancellation decision above.
        if observed is not None:
            self._trace_observed(observed)

    @staticmethod
    def _event_kind(event_type: int) -> str:
        return {
            MacOSBindings.LEFT_DOWN: "down",
            MacOSBindings.LEFT_UP: "up",
            MacOSBindings.LEFT_DRAGGED: "drag",
            MacOSBindings.MOUSE_MOVED: "move",
            MacOSBindings.RIGHT_DOWN: "right_down",
            MacOSBindings.RIGHT_UP: "right_up",
            MacOSBindings.RIGHT_DRAGGED: "right_drag",
            MacOSBindings.SCROLL_WHEEL: "scroll",
            MacOSBindings.OTHER_DOWN: "other_down",
            MacOSBindings.OTHER_UP: "other_up",
            MacOSBindings.OTHER_DRAGGED: "other_drag",
            MacOSBindings.TAP_DISABLED_BY_TIMEOUT: "tap_disabled_timeout",
            MacOSBindings.TAP_DISABLED_BY_USER_INPUT: "tap_disabled_user_input",
        }.get(event_type, "unknown")

    @staticmethod
    def _pending_description(pending: _PendingPost) -> dict:
        position = pending.position
        return {
            "sequence": pending.sequence,
            "kind": pending.kind,
            "postedAt": pending.posted_at,
            "position": (
                None
                if position is None
                else {"x": position[0], "y": position[1]}
            ),
        }

    @classmethod
    def _positions_match(
        cls,
        pending: _PendingPost,
        observed: Tuple[float, float],
    ) -> bool:
        if pending.position is None:
            return True
        try:
            x = float(observed[0])
            y = float(observed[1])
        except (TypeError, ValueError, IndexError):
            return False
        if not math.isfinite(x) or not math.isfinite(y):
            return False
        return math.hypot(
            x - pending.position[0],
            y - pending.position[1],
        ) <= cls.CONFIRMATION_POSITION_TOLERANCE

    def _confirm_tagged_unlocked(
        self,
        event_type: int,
        position: Tuple[float, float],
        timestamp: float,
    ) -> dict:
        """Account for one tagged callback without crossing button barriers."""

        observed_kind = self._event_kind(event_type)
        covered = []
        pending_before = len(self._pending_posts)
        if self._pending_posts and self._pending_posts[0].kind == "any":
            covered.append(self._pending_posts.popleft())
        elif observed_kind == "move" and self._pending_posts:
            # An unpressed positioning MOVE is a strict ordered barrier.
            # Never let its callback acknowledge a button or an earlier DRAG.
            pending = self._pending_posts[0]
            if pending.kind == "move" and self._positions_match(pending, position):
                covered.append(self._pending_posts.popleft())
        elif observed_kind == "drag" and self._pending_posts:
            # Find the newest matching event in the leading DRAG run.  Seeing
            # that endpoint proves every earlier motion event in the same run
            # has either arrived or was legitimately coalesced by CoreGraphics.
            match_index = None
            for index, pending in enumerate(self._pending_posts):
                if pending.kind != "drag":
                    break
                if self._positions_match(pending, position):
                    match_index = index
            if match_index is None and self._pending_posts[0].kind == "drag":
                # Some fake/event routes normalize coordinates.  In that case
                # acknowledge only the oldest DRAG; never guess across a run.
                match_index = 0
            if match_index is not None:
                for _ in range(match_index + 1):
                    covered.append(self._pending_posts.popleft())
        elif observed_kind in ("down", "up") and self._pending_posts:
            strict_index = 0
            if observed_kind == "up":
                # A confirmed UP is also an ordered boundary for the DRAG run
                # immediately before it, but it may never cross DOWN/another UP.
                while (
                    strict_index < len(self._pending_posts)
                    and self._pending_posts[strict_index].kind == "drag"
                ):
                    strict_index += 1
            if strict_index < len(self._pending_posts):
                strict = self._pending_posts[strict_index]
                if (
                    strict.kind == observed_kind
                    and self._positions_match(strict, position)
                ):
                    for _ in range(strict_index + 1):
                        covered.append(self._pending_posts.popleft())

        covered_count = len(covered)
        covered_drag_count = sum(item.kind == "drag" for item in covered)
        if covered_count:
            self._confirmed_posts += covered_count
            self._covered_drag_posts += covered_drag_count
            if observed_kind == "drag":
                self._drag_posts_confirmed_by_drag += covered_drag_count
                self._coalesced_drag_posts += max(
                    0,
                    covered_drag_count - 1,
                )
            elif observed_kind == "up":
                self._drag_posts_confirmed_by_up += covered_drag_count
        else:
            self._unmatched_tagged_events += 1
        confirmation = {
            "kind": observed_kind,
            "callbackAt": float(timestamp),
            "coveredPosts": covered_count,
            "coveredDragPosts": covered_drag_count,
            "coveredThroughSequence": (
                covered[-1].sequence if covered else None
            ),
            "pendingBefore": pending_before,
            "pendingAfter": len(self._pending_posts),
        }
        self._last_tagged_confirmation = deepcopy(confirmation)
        return confirmation

    def _trace_observed(self, evidence: dict) -> None:
        if self._trace_callback is None:
            return
        try:
            record = deepcopy(evidence)
            record["event"] = "pointer_observed"
            self._trace_callback(record)
        except Exception:
            pass

    def _describe_event(
        self,
        event_type: int,
        tag: int,
        position: Tuple[float, float],
        timestamp: float,
        metadata: Optional[dict],
        reason: str,
    ) -> dict:
        """Build source evidence while holding the lock; never infer hardware."""

        fields = metadata if isinstance(metadata, dict) else {}
        source_pid = fields.get("sourcePid")
        target_source = (
            isinstance(source_pid, int)
            and source_pid > 0
            and self._target_pid is not None
            and source_pid == self._target_pid
        )
        distance = math.hypot(
            position[0] - self._expected[0], position[1] - self._expected[1]
        )

        def finite(value: float) -> Optional[float]:
            return float(value) if math.isfinite(value) else None

        evidence = {
            "eventType": int(event_type),
            "kind": self._event_kind(event_type),
            "tag": int(tag),
            "sourcePid": source_pid,
            "sourceStateId": fields.get("sourceStateId"),
            "clickState": fields.get("clickState"),
            "deltaX": fields.get("deltaX"),
            "deltaY": fields.get("deltaY"),
            "eventNumber": fields.get("eventNumber"),
            "targetPid": self._target_pid,
            "eventTargetPid": fields.get("targetPid"),
            **{key: fields[key] for key in (
                "injected", "nativeTime", "nativeFlags", "nativeMessage", "deltaSource"
            ) if key in fields},
            "position": {"x": finite(position[0]), "y": finite(position[1])},
            "expected": {
                "x": finite(self._expected[0]), "y": finite(self._expected[1])
            },
            "distance": finite(distance),
            "ownerDown": self._owner_down,
            "monotonic": finite(timestamp),
            "classification": "target_app" if target_source else "external_or_unknown",
            "reason": reason,
        }
        return evidence

    def _record_external_event(
        self,
        event_type: int,
        tag: int,
        position: Tuple[float, float],
        timestamp: float,
        metadata: Optional[dict],
        reason: str,
    ) -> Optional[dict]:
        self._controlled_warp_echo = None
        evidence = self._describe_event(
            event_type, tag, position, timestamp, metadata, reason
        )
        self._last_external_event = evidence
        self._external_events += 1
        self._external_classifications[evidence["classification"]] += 1
        # Even an event reported as coming from Resolve remains untrusted when
        # it lacks our tag.  Source PID does not prove a physical move or warp.
        if not self._cancel_reason:
            self._cancel_reason = reason
            self._cancel_event = evidence
            return evidence
        return None

    @property
    def last_external_event(self) -> Optional[dict]:
        with self._lock:
            return deepcopy(self._last_external_event)

    def get_diagnostics(self) -> dict:
        with self._lock:
            return self._diagnostics_unlocked()

    def _diagnostics_unlocked(self) -> dict:
        return {
            "targetPid": self._target_pid,
            "lastExternalEvent": deepcopy(self._last_external_event),
            "cancelEvent": deepcopy(self._cancel_event),
            "externalClassifications": dict(self._external_classifications),
            "suppressedControlledWarpEchoes": (
                self._suppressed_controlled_warp_echoes
            ),
            # Only our tagged observations contribute: external double-clicks
            # must not be mistaken for a rewritten plugin click state.
            "observedClickStates": dict(self._observed_click_states),
            "lastPostedEvent": deepcopy(self._last_posted_event),
            "lastTaggedConfirmation": deepcopy(
                self._last_tagged_confirmation
            ),
            "confirmationFailure": deepcopy(self._confirmation_failure),
        }

    def watchdog_reason(self, now: float) -> str:
        with self._lock:
            if self._cancel_reason:
                return self._cancel_reason
            checked_at = float(now)
            expired = None
            for pending in self._pending_posts:
                timeout = (
                    self._drag_confirmation_timeout
                    if pending.kind == "drag"
                    else self._confirmation_timeout
                )
                age = checked_at - pending.posted_at
                if age > timeout:
                    deadline = pending.posted_at + timeout
                    candidate = (deadline, pending.sequence, pending, age, timeout)
                    if expired is None or candidate[:2] < expired[:2]:
                        expired = candidate
            if expired is not None:
                _deadline, _sequence, pending, age, timeout = expired
                self._cancel_reason = "tagged_event_not_confirmed"
                self._confirmation_failure = {
                    "reason": self._cancel_reason,
                    "checkedAt": checked_at,
                    "ageMs": age * 1000.0,
                    "timeoutMs": timeout * 1000.0,
                    "expired": self._pending_description(pending),
                    "pendingConfirmations": len(self._pending_posts),
                    "pendingKinds": [
                        item.kind for item in self._pending_posts
                    ],
                }
                return self._cancel_reason
            return ""

    def statistics(self) -> dict:
        with self._lock:
            result = {
                "sessionTag": self.tag,
                "postedEvents": self._posted,
                "confirmedEvents": self._confirmed,
                "confirmedPosts": self._confirmed_posts,
                "coveredDragPosts": self._covered_drag_posts,
                "dragPostsConfirmedByDrag": (
                    self._drag_posts_confirmed_by_drag
                ),
                "dragPostsConfirmedByUp": self._drag_posts_confirmed_by_up,
                "coalescedDragPosts": self._coalesced_drag_posts,
                "pendingConfirmations": len(self._pending_posts),
                "pendingConfirmationKinds": [
                    item.kind for item in self._pending_posts
                ],
                "unmatchedTaggedEvents": self._unmatched_tagged_events,
                "maxPendingConfirmations": self._max_pending_confirmations,
                "externalEvents": self._external_events,
                "ownerDown": self._owner_down,
            }
            result.update(self._diagnostics_unlocked())
            return result
