"""Bounded observational correlation; never used to authorize pointer output."""
from collections import deque
from copy import deepcopy
import math
from threading import RLock


def point(value):
    if isinstance(value, dict):
        return {'x': float(value['x']), 'y': float(value['y'])}
    return None


def delta(a, b):
    return {'x': a['x']-b['x'], 'y': a['y']-b['y']}


class TransportTrace:
    def __init__(self):
        self._lock = RLock()
        self._events = deque(maxlen=256)
        self._sequence = 0
        self._last_logical = None
        self._previous = None

    def record(self, event, received_at):
        scale = event.get('locationScale') or {}
        logical = event.get('logical') or {}
        row = {'kind': event.get('kind'), 'postStartedAt': event.get('monotonic'),
               'traceReceivedAt': received_at, 'ok': event.get('ok', True),
               'postedMouseEvent': event.get('postedMouseEvent', False),
               'eventPosition': point(event.get('position')),
               'fromPosition': point(event.get('fromPosition')),
               'toPosition': point(event.get('toPosition')),
               'logicalBefore': point(logical.get('before')),
               'logicalAfter': point(logical.get('after')),
               'plannedLogicalPosition': point(event.get('logicalPosition')),
               'mode': logical.get('mode'), 'purpose': logical.get('purpose'),
               'requestedDelta': point((event.get('relativeDelta') or {}).get('requested')),
               'scaledLocationDelta': point((event.get('relativeDelta') or {}).get('scaledLocationDelta')),
               'rebaseCount': scale.get('rebaseCount'), 'rebasePhase': scale.get('rebasePhase'),
               'logicalAnchor': point(scale.get('mappingLogicalAnchor')),
               'eventAnchor': point(scale.get('mappingEventAnchor')),
               'rebaseBounds': dict(scale.get('rebaseBounds') or {}),
               'transportTiming': dict(event.get('details') or {}),
               'scale': scale.get('effective')}
        with self._lock:
            self._sequence += 1
            row['sequence'] = self._sequence
            self._events.append(row)
            # Sentinel, duplicate anchors, warp and clamped no-ops must never
            # count as ordinary logical displacement.
            if (row['ok'] and row['logicalAfter'] and row['postedMouseEvent']
                    and row['kind'] in ('drag', 'edge_rebase_anchor')):
                self._last_logical = row

    def capture_window(self, start, end):
        with self._lock:
            rows = list(self._events)
            recent = [r for r in rows if start-.150 <= r['traceReceivedAt'] <= end]
            prior = [r for r in rows if r['traceReceivedAt'] <= start]
            logical = [r for r in rows if r['traceReceivedAt'] <= start and r['ok']
                       and r['logicalAfter'] and r['postedMouseEvent']
                       and r['kind'] in ('drag', 'edge_rebase_anchor')]
            result = {'version': 'transporttrace.1', 'captureStart': start, 'captureEnd': end,
                'lookbackMs': 150, 'note': 'post return is not proof of Resolve application',
                'oldestRetainedSequence': rows[0]['sequence'] if rows else None,
                'latestSequence': self._sequence,
                'historyTruncated': bool(rows and rows[0]['sequence'] > 1 and rows[0]['traceReceivedAt'] > start-.150),
                'windowTruncated': len(recent)>64,
                'beforeCapture': prior[-1] if prior else None,
                'logicalBeforeCapture': logical[-1] if logical else None,
                'logicalAtWindowRead': self._last_logical,
                'events': recent[-64:]}
        return deepcopy(result)

    def measurement(self, actual, predicted, center, capture_start, capture_end, revision, gesture):
        actual, predicted, center = point(actual), point(predicted), point(center)
        error = delta(actual, predicted)
        offset = delta(predicted, center)
        radius = math.hypot(offset['x'], offset['y'])
        result = {'actualMinusPredicted': error,
                  'actualRadius': math.hypot(actual['x']-center['x'], actual['y']-center['y']),
                  'predictedRadius': radius,
                  'radialError': (error['x']*offset['x']+error['y']*offset['y'])/radius if radius else None,
                  'tangentialError': (-error['x']*offset['y']+error['y']*offset['x'])/radius if radius else None}
        with self._lock:
            previous = self._previous
            if previous and previous['gesture'] == gesture:
                events = [e for e in self._events if previous['captureEnd'] < e['traceReceivedAt'] <= capture_end]
                result['sincePreviousCapture'] = {
                    'previousRevision': previous['revision'],
                    'previousCaptureEnd': previous['captureEnd'],
                    'elapsedMs': (capture_end-previous['captureEnd'])*1000,
                    'actualDelta': delta(actual, previous['actual']),
                    'predictedDelta': delta(predicted, previous['predicted']),
                    'errorDelta': delta(error, previous['error']),
                    'rebaseCompletions': sum(e['kind']=='edge_rebase' for e in events),
                    'alignmentFrames': sum(e['purpose'] in ('orbit_alignment','axis_alignment') for e in events),
                    'historyTruncated': bool(self._events and self._events[0]['sequence']>1
                        and self._events[0]['traceReceivedAt']>previous['captureEnd'])}
            self._previous = dict(actual=actual, predicted=predicted, error=error,
                captureStart=capture_start, captureEnd=capture_end, revision=revision, gesture=gesture)
        return result
