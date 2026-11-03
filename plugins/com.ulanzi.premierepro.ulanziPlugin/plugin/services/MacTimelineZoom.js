import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { failure } from './errors.js';
import { isZoomInterruption } from './zoomFeedback.js';

// One native request in flight, at most six unsent small steps. Reversing or
// switching contexts replaces pending work instead of replaying old rotations.
export class MacTimelineZoom {
  constructor({ spawnProcess = spawn, intervalMs = 16, maxPending = 6, timeoutMs = 1200, now = Date.now, diagnostic = () => {} } = {}) {
    Object.assign(this, { spawnProcess, intervalMs, maxPending, timeoutMs, now, diagnostic });
    this.child = null; this.ready = null; this.request = null; this.pending = null;
    this.running = false; this.timer = null; this.closed = false; this.id = 0; this.epoch = 0; this.nextAt = 0;
    // Windows subclasses this scheduler: keep its diagnostics and validation unchanged.
    this.macDiagnostics = new.target === MacTimelineZoom;
    this.schedulerRevision = 'mac-cancel-diagnostics-v1';
    if (this.macDiagnostics) this.diagnostic({ event: 'zoom-scheduler-config', schedulerRevision: this.schedulerRevision, pendingTtlMs: 250, maxPending: this.maxPending, intervalMs: this.intervalMs });
  }
  cancelled(reason, stage, extra = {}) {
    // Local telemetry only: never attach it to publicError's `details` field.
    const error = failure('ACTION_CANCELLED');
    return this.macDiagnostics ? Object.assign(error, { schedulerDetails: { reason, stage, ...extra } }) : error;
  }
  queueState(item, at = this.now()) {
    return {
      pendingCount: this.pending?.count ?? 0,
      pendingDirection: this.pending?.direction ?? null,
      pendingEpoch: this.pending?.epoch ?? null,
      pendingAgeMs: this.pending ? at - this.pending.receivedAt : null,
      pendingSameKey: this.pending ? this.pending.key === item?.key : null,
      itemRemainingCount: item?.count ?? null,
      itemEpoch: item?.epoch ?? null,
      currentEpoch: this.epoch,
      nativeRequestInFlight: this.request !== null,
      helperAlive: this.child !== null,
      running: this.running, timerScheduled: this.timer !== null, closed: this.closed,
    };
  }
  start() {
    if (this.closed) return Promise.reject(this.cancelled('service-closed', 'helper-start'));
    if (this.ready) return this.ready;
    let resolveReady, rejectReady;
    const ready = new Promise((resolve, reject) => { resolveReady = resolve; rejectReady = reject; });
    this.ready = ready;
    let child;
    try {
      child = this.spawnProcess(fileURLToPath(new URL('../bin/timeline-scroll-macos', import.meta.url)), [], { stdio: ['pipe', 'pipe', 'ignore'] });
    } catch { this.ready = null; rejectReady(failure('ZOOM_HELPER_UNAVAILABLE')); return ready; }
    this.child = child;
    const lines = createInterface({ input: child.stdout });
    const startupTimer = setTimeout(() => fail(), this.timeoutMs);
    const fail = () => {
      if (this.child !== child) return;
      clearTimeout(startupTimer); lines.close(); this.child = null; this.ready = null;
      rejectReady(failure('ZOOM_HELPER_UNAVAILABLE'));
      const request = this.request; this.request = null;
      if (request) { clearTimeout(request.timer); request.reject(failure('ZOOM_HELPER_UNAVAILABLE')); }
      child.kill();
    };
    this.stopChild = fail;
    child.on('error', fail); child.on('exit', fail); child.stdin.on('error', fail);
    lines.on('line', line => {
      if (line === 'READY') { clearTimeout(startupTimer); resolveReady(); return; }
      let message;
      try { message = JSON.parse(line); } catch { fail(); return; }
      const request = this.request;
      if (!request || message.id !== request.id) { fail(); return; }
      this.request = null; clearTimeout(request.timer);
      if (message.ok) request.resolve(message);
      else {
        const error = failure(message.error || 'ACTION_FAILED');
        // Keep native diagnostics local; PI/public action errors only need code.
        if (message.details && typeof message.details === 'object') error.nativeDetails = message.details;
        request.reject(error);
      }
    });
    return ready;
  }
  async send(payload, beforeSend = () => {}, onWritten = () => {}) {
    await this.start();
    beforeSend();
    if (this.closed || !this.child) throw this.cancelled(this.closed ? 'service-closed' : 'helper-unavailable-after-start', 'before-native-write');
    return new Promise((resolve, reject) => {
      const id = ++this.id;
      this.request = { id, resolve, reject, timer: setTimeout(() => this.stopChild?.(), this.timeoutMs) };
      this.child.stdin.write(`${JSON.stringify({ ...payload, id })}\n`);
      onWritten(id);
    });
  }
  enqueue(item) {
    if (this.closed) return;
    const count = Math.min(this.maxPending, Math.abs(Math.trunc(item.delta)));
    if (!count) return;
    const direction = Math.sign(item.delta);
    const same = this.pending?.key === item.key && this.pending?.direction === direction;
    this.pending = { ...item, direction, count: Math.min(this.maxPending, (same ? this.pending.count : 0) + count), receivedAt: this.now(), epoch: this.epoch };
    this.schedule();
  }
  schedule() {
    if (this.closed || !this.pending || this.running || this.timer) return;
    const delay = Math.max(0, this.nextAt - this.now());
    if (delay) this.timer = setTimeout(() => { this.timer = null; void this.pump(); }, delay);
    else void this.pump();
  }
  async pump() {
    const item = this.pending;
    if (!item || this.running || this.closed) return;
    if (--item.count === 0) this.pending = null;
    this.running = true;
    let nativeRequestId = null;
    try {
      const validate = (stage = 'pump-before-start') => {
        if (!this.macDiagnostics) {
          if (item.epoch !== this.epoch || this.now()-item.receivedAt > 250) throw failure('ACTION_CANCELLED');
          item.beforeSend?.();
          return;
        }
        const ageMs = this.now() - item.receivedAt;
        if (item.epoch !== this.epoch) throw this.cancelled('epoch-changed', stage, { ageMs });
        if (ageMs > 250) throw this.cancelled('pending-expired', stage, { ageMs });
        try { item.beforeSend?.(); }
        catch (error) {
          if (error.code === 'ACTION_CANCELLED' && !error.schedulerDetails) {
            error.schedulerDetails = { reason: 'context-invalidated', stage, ageMs };
          }
          throw error;
        }
      };
      validate();
      const result = await this.send({ direction: item.direction, context: item.key, anchor: item.anchor },
        () => validate('before-native-write'), id => { nativeRequestId = id; });
      if (item.epoch === this.epoch) item.onSuccess?.({ ...result, route: 'wheel', verified: false });
      this.diagnostic({ event: 'zoom-wheel-sent', ...result, direction: item.direction });
    } catch (error) {
      const at = this.macDiagnostics ? this.now() : null;
      const queueBefore = this.macDiagnostics ? this.queueState(item, at) : null;
      const pendingBefore = this.pending;
      const pendingCountBefore = pendingBefore?.count ?? 0;
      // Never retry an uncertain scroll as a hotkey: it may have already run.
      if (isZoomInterruption(error)) {
        // Also discard detents received while this request was running. A fresh
        // user turn can start again; never replay a burst after the mouse moves.
        if (this.pending?.key === item.key) this.pending = null;
        if (item.epoch === this.epoch) item.onInterrupted?.(error);
      } else {
        if (this.pending?.key === item.key && this.pending.receivedAt <= item.receivedAt) this.pending = null;
        if (item.epoch === this.epoch) item.onError?.(error);
      }
      this.diagnostic({
        event: 'zoom-wheel-rejected', code: error.code,
        ...(this.macDiagnostics ? { schedulerRevision: this.schedulerRevision,
        scheduler: {
          ...(error.schedulerDetails || { reason: error.nativeDetails ? 'native-rejection' : 'unclassified-error', stage: error.nativeDetails ? 'native-response' : 'scheduler' }),
          ageMs: error.schedulerDetails?.ageMs ?? at - item.receivedAt,
          ttlMs: 250, ageBasis: 'latest-coalesced-input', receivedAt: item.receivedAt, cancelledAt: at,
          maxPending: this.maxPending, intervalMs: this.intervalMs,
          direction: item.direction, nativeRequestId,
          nativeDispatched: nativeRequestId !== null,
          queueBefore, queueAfter: this.queueState(item, at),
          discardedPendingCount: this.pending !== pendingBefore ? pendingCountBefore : 0,
        } } : {}),
        ...(error.nativeDetails ? { nativeDetails: error.nativeDetails } : {}),
      });
    } finally {
      this.running = false;
      this.nextAt = this.now() + this.intervalMs;
      this.schedule();
    }
  }
  cancelContext(context) {
    if (this.pending?.context === context) this.pending = null;
  }
  clear() { this.epoch++; this.pending = null; clearTimeout(this.timer); this.timer = null; }
  close() { this.closed = true; this.clear(); this.stopChild?.(); }
}
