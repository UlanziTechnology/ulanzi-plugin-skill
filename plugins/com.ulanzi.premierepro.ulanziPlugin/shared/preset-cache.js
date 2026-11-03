// Shared in-memory list cache. Selection settings remain owned by each action.
export const PRESET_CACHE_TTL = 5 * 60 * 1000;
export function presetCacheKey(scope, directory = '', connected = false) {
  if (scope !== 'custom') return JSON.stringify(['standard', Boolean(connected)]);
  let folder = String(directory).trim().replace(/\\/g, '/').replace(/\/+$/, '');
  if (/^[a-z]:/i.test(folder) || folder.startsWith('//')) folder = folder.toLowerCase();
  return JSON.stringify(['custom', folder]);
}
export class PresetCache {
  constructor({ now = Date.now, limit = 12 } = {}) { this.now = now; this.limit = limit; this.entries = new Map(); }
  get(key) {
    const entry = this.entries.get(key);
    if (!entry) return null;
    if (entry.expiresAt <= this.now()) { this.entries.delete(key); return null; }
    this.entries.delete(key); this.entries.set(key, entry);
    return entry;
  }
  set(key, value, expiresAt = this.now() + PRESET_CACHE_TTL) {
    const entry = { value, expiresAt: Math.min(expiresAt, this.now() + PRESET_CACHE_TTL) };
    this.entries.delete(key); this.entries.set(key, entry);
    while (this.entries.size > this.limit) this.entries.delete(this.entries.keys().next().value);
    return entry;
  }
  delete(key) { this.entries.delete(key); }
  clear() { this.entries.clear(); }
}
