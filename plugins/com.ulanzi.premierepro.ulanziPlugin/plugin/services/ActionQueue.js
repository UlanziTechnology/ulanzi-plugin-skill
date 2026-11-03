import { failure } from './errors.js';

// A bounded queue merges only adjacent, same-direction rotations with identical
// context + config + parameter. Crossing a parameter selection creates a barrier.
export class ActionQueue {
  constructor({ maxItems = 64, maxAgeMs = 750, delayMs = 24, clock = Date.now } = {}) {
    Object.assign(this, { maxItems, maxAgeMs, delayMs, clock });
    this.queue = []; this.running = false; this.timer = null; this.closed = false;
  }
  enqueue({ key, delta, execute, onSuccess, onError, maxAgeMs = this.maxAgeMs, coalesceLimit = 10000 }) {
    if (this.closed) { onError?.(failure('BRIDGE_DISCONNECTED')); return; }
    const last = this.queue.at(-1);
    if (key && last?.key === key && Math.sign(last.delta) === Math.sign(delta) && Math.abs(last.delta + delta) <= coalesceLimit) {
      last.delta += delta; return;
    }
    if (this.queue.length >= this.maxItems) { onError?.(failure('QUEUE_FULL')); return; }
    this.queue.push({ key, delta, execute, onSuccess, onError, queuedAt: this.clock(), maxAgeMs });
    if (!this.running && !this.timer) this.timer = setTimeout(() => { this.timer = null; void this.drain(); }, this.delayMs);
  }
  barrier() { if (this.queue.length) this.queue.at(-1).key += '|barrier'; }
  cancelContext(context) {
    this.queue = this.queue.filter(item => !item.key?.startsWith(`${context}|`));
  }
  clear(error = failure('BRIDGE_DISCONNECTED')) {
    clearTimeout(this.timer); this.timer = null;
    const pending = this.queue.splice(0);
    for (const item of pending) item.onError?.(error);
  }
  async drain() {
    if (this.running || this.closed) return;
    this.running = true;
    try {
      while (this.queue.length && !this.closed) {
        const item = this.queue.shift();
        try {
          if (this.clock() - item.queuedAt > item.maxAgeMs) throw failure('STALE_ACTION');
          const result = await item.execute(item.delta);
          item.onSuccess?.(result);
        } catch (error) { item.onError?.(error); }
      }
    } finally { this.running = false; }
  }
  close() { this.closed = true; this.clear(); }
}
