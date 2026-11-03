import { EventEmitter } from 'node:events';
import { randomBytes, timingSafeEqual } from 'node:crypto';
import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { WebSocket, WebSocketServer } from 'ws';
import { DIRECT_EXPORT_TIMEOUT_MS } from '../../shared/config.js';

export const BRIDGE_ACTIONS = Object.freeze(['capabilities', 'exportPresets', 'exportInfo', 'queueExport', 'directExport', 'timelineJog', 'trimControl', 'timelineZoom', 'parameterDial']);
const ALLOWED = new Set(BRIDGE_ACTIONS);
const MAX_BYTES = 65536;
const error = (code, message, details) => Object.assign(new Error(message || code), { code, details });
const plain = value => !!value && typeof value === 'object' && !Array.isArray(value) && [Object.prototype, null].includes(Object.getPrototypeOf(value));

function jsonObject(value) {
  if (!plain(value)) throw error('INVALID_REQUEST', 'Settings and payload must be JSON objects.');
  let count = 0;
  const seen = new Set();
  function visit(node, depth) {
    if (++count > 2048 || depth > 10) throw error('INVALID_REQUEST', 'Request is too complex.');
    if (node === null || typeof node === 'boolean' || typeof node === 'string') return;
    if (typeof node === 'number' && Number.isFinite(node)) return;
    if (typeof node !== 'object' || (!Array.isArray(node) && !plain(node)) || seen.has(node)) throw error('INVALID_REQUEST', 'Only finite JSON values are allowed.');
    seen.add(node);
    for (const key of Object.keys(node)) {
      if (['__proto__', 'constructor', 'prototype'].includes(key)) throw error('INVALID_REQUEST', 'Unsafe property name.');
      visit(node[key], depth + 1);
    }
    seen.delete(node);
  }
  visit(value, 0);
  return JSON.parse(JSON.stringify(value));
}

/** Local-only, authenticated, serialized RPC. Never retries a host mutation. */
export class PremiereBridge extends EventEmitter {
  constructor(options = {}) {
    super();
    const rawPort = options.port ?? process.env.ULZI_PR_BRIDGE_PORT ?? 49631;
    this.port = Number(rawPort);
    if (!Number.isInteger(this.port) || this.port < 0 || this.port > 65535) throw error('INVALID_PORT', 'Invalid bridge port.');
    this.pairingPath = options.pairingPath || path.join(os.homedir(), '.ulanzi-premiere', 'bridge.json');
    this.timeoutMs = options.timeoutMs ?? 10000;
    this.maxQueue = options.maxQueue ?? 32;
    this.authTimeoutMs = options.authTimeoutMs ?? 3000;
    this.server = null;
    this.peer = null;
    this.queue = [];
    this.current = null;
    this.sequence = 0;
    this.session = randomBytes(12).toString('hex');
    this._status = { connected: false, code: 'STOPPED', port: this.port };
    this.stopping = false;
  }

  get connected() { return !!this.peer && this.peer.readyState === WebSocket.OPEN; }
  get status() { return { ...this._status }; }
  _setStatus(code, extra = {}) {
    this._status = { connected: this.connected, code, port: this.port, ...extra };
    this.emit('status', this.status);
  }

  async _readPairing() {
    try {
      const stat = await fs.lstat(this.pairingPath);
      if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 4096) throw error('PAIRING_INVALID', 'Pairing file must be a small regular file.');
      const data = JSON.parse(await fs.readFile(this.pairingPath, 'utf8'));
      if (!/^[a-f0-9]{64}$/.test(data.token || '')) throw error('PAIRING_INVALID', 'Pairing token is invalid; back up and remove the pairing file to pair again.');
      return data.token;
    } catch (e) {
      if (e.code === 'ENOENT') return randomBytes(32).toString('hex');
      throw error('PAIRING_INVALID', 'Unable to read the local pairing file.', { reason: e.code || 'INVALID_JSON' });
    }
  }

  async _writePairing(token) {
    await fs.mkdir(path.dirname(this.pairingPath), { recursive: true, mode: 0o700 });
    const temporary = `${this.pairingPath}.${process.pid}.${randomBytes(5).toString('hex')}.tmp`;
    try {
      await fs.writeFile(temporary, JSON.stringify({ protocol: 1, port: this.port, token }) + '\n', { flag: 'wx', mode: 0o600 });
      await fs.rename(temporary, this.pairingPath);
      if (process.platform !== 'win32') await fs.chmod(this.pairingPath, 0o600);
    } finally {
      await fs.unlink(temporary).catch(e => { if (e.code !== 'ENOENT') throw e; });
    }
  }

  async start() {
    if (this.server) return this.status;
    this.stopping = false;
    try { this.token = await this._readPairing(); }
    catch (e) { this._setStatus(e.code || 'PAIRING_INVALID'); throw e; }
    const server = new WebSocketServer({
      host: '127.0.0.1', port: this.port, maxPayload: MAX_BYTES, perMessageDeflate: false,
      verifyClient: ({ origin, req }) => {
        const remote = req.socket.remoteAddress;
        return (remote === '127.0.0.1' || remote === '::ffff:127.0.0.1') && (!origin || origin === 'null' || origin === 'file://');
      }
    });
    this.server = server;
    server.on('connection', socket => this._accept(socket));
    try {
      await new Promise((resolve, reject) => { server.once('listening', resolve); server.once('error', reject); });
      this.port = server.address().port;
      await this._writePairing(this.token);
      server.on('error', e => this._setStatus(e.code || 'BRIDGE_ERROR'));
      this._setStatus('WAITING_FOR_PREMIERE');
      return this.status;
    } catch (e) {
      this.server = null;
      for (const socket of server.clients) socket.terminate();
      server.close(() => {});
      this._setStatus(e.code === 'EADDRINUSE' ? 'PORT_IN_USE' : (e.code || 'BRIDGE_START_FAILED'));
      throw error(this.status.code, e.code === 'EADDRINUSE' ? 'The Premiere bridge port is already in use. Close the other plugin instance.' : 'Premiere bridge could not start.');
    }
  }

  _accept(socket) {
    let authenticated = false;
    const authTimer = setTimeout(() => socket.close(4001, 'Authentication required'), this.authTimeoutMs);
    authTimer.unref?.();
    socket.on('error', () => {});
    socket.on('message', (data, binary) => {
      let message;
      try { if (binary) throw new Error(); message = JSON.parse(data.toString()); if (!plain(message)) throw new Error(); }
      catch { socket.close(4002, 'Invalid message'); return; }
      if (!authenticated) {
        const candidate = typeof message.token === 'string' && /^[a-f0-9]{64}$/.test(message.token) ? Buffer.from(message.token, 'hex') : Buffer.alloc(0);
        const expected = Buffer.from(this.token, 'hex');
        if (message.type !== 'hello' || message.protocol !== 1 || message.host !== 'PPRO' || candidate.length !== expected.length || !timingSafeEqual(candidate, expected)) {
          if (!this.peer && message.type === 'hello' && message.host === 'PPRO') {
            this._setStatus(message.protocol === 1 ? 'PAIRING_FAILED' : 'PROTOCOL_MISMATCH');
          }
          socket.close(4001, 'Authentication failed'); return;
        }
        if (this.peer) { socket.close(4009, 'A Premiere session is already connected'); return; }
        clearTimeout(authTimer);
        authenticated = true;
        this.peer = socket;
        socket.send(JSON.stringify({ type: 'ready', protocol: 1 }));
        this._setStatus('CONNECTED', { appVersion: String(message.appVersion || '').slice(0, 40) });
        this._pump();
        return;
      }
      if (socket !== this.peer) return;
      if (message.type === 'pong') return;
      const current = this.current;
      // Ignore late or unrelated replies. A result can complete exactly one request.
      if (message.type !== 'response' || typeof message.id !== 'string' || !current || message.id !== current.id) return;
      if (typeof message.ok !== 'boolean' || (!message.ok && (!plain(message.error) || typeof message.error.code !== 'string'))) {
        this._poison('INVALID_RESPONSE', 'Premiere returned an invalid response. The result may be unknown.'); return;
      }
      if (!message.ok && message.error.code === 'HOST_RESPONSE_INVALID') {
        this._poison('INVALID_RESPONSE', 'Premiere response could not be decoded. Check the project before reconnecting.'); return;
      }
      if (!message.ok && ['PARTIAL_MUTATION', 'EXPORT_QUEUE_REJECTED', 'RESULT_UNKNOWN'].includes(message.error.code)) {
        this._poison(message.error.code, String(message.error.message || 'Premiere result is uncertain. Check the project and queue before reconnecting.'), message.error.details); return;
      }
      clearTimeout(current.timer);
      this.current = null;
      if (message.ok) current.resolve(message.result);
      else current.reject(error(message.error.code.slice(0, 80), String(message.error.message || message.error.code).slice(0, 1000), message.error.details));
      this._pump();
    });
    socket.on('close', () => {
      clearTimeout(authTimer);
      if (this.peer !== socket) return;
      const uncertain = !!this.current;
      this.peer = null;
      this._rejectAll(error(uncertain ? 'RESULT_UNKNOWN' : 'DISCONNECTED', uncertain ? 'Premiere disconnected during a request. Check the project before trying again.' : 'Premiere disconnected.'));
      this._setStatus(this.stopping ? 'STOPPED' : (uncertain ? 'RESULT_UNKNOWN' : 'WAITING_FOR_PREMIERE'), { uncertain });
    });
  }

  request(action, settings = {}, payload = {}, options = {}) {
    return new Promise((resolve, reject) => {
      try {
        if (!ALLOWED.has(action)) throw error('UNKNOWN_ACTION', 'This Premiere action is not permitted.');
        if (!this.connected) throw error('NOT_CONNECTED', 'Waiting for the Premiere background bridge. Ensure Premiere and Ulanzi are running; use Ulanzi Premiere Bridge Diagnostics only if connection problems persist.');
        if (this.current?.action === 'directExport' || this.queue.some(item => item.action === 'directExport')) throw error('EXPORT_BUSY', 'Premiere is exporting. Wait for the current export to finish.');
        if (this.queue.length + (this.current ? 1 : 0) >= this.maxQueue) throw error('BUSY', 'Too many requests; wait for Premiere to catch up.');
        const timeoutMs = options.timeoutMs ?? this.timeoutMs;
        if (!Number.isFinite(timeoutMs) || timeoutMs < 10 || timeoutMs > (action === 'directExport' ? DIRECT_EXPORT_TIMEOUT_MS : 120000)) throw error('INVALID_REQUEST', 'Invalid timeout.');
        const id = `${this.session}-${++this.sequence}`;
        const message = JSON.stringify({ type: 'request', id, action, settings: jsonObject(settings), payload: jsonObject(payload) });
        if (Buffer.byteLength(message) > MAX_BYTES) throw error('INVALID_REQUEST', 'Request is too large.');
        this.queue.push({ id, action, message, resolve, reject, timeoutMs });
        this._pump();
      } catch (e) { reject(e); }
    });
  }

  _pump() {
    if (this.current || !this.connected || !this.queue.length) return;
    const item = this.current = this.queue.shift();
    item.timer = setTimeout(() => this._poison('REQUEST_TIMEOUT', 'Premiere did not confirm the result. Check the project and export queue, then explicitly reconnect from Ulanzi Premiere Bridge Diagnostics; this request will not be retried.'), item.timeoutMs);
    item.timer.unref?.();
    this.peer.send(item.message, e => { if (e && this.current === item) this._poison('RESULT_UNKNOWN', 'Unable to confirm delivery to Premiere.'); });
  }

  _rejectAll(e) {
    if (this.current) { clearTimeout(this.current.timer); this.current.reject(e); this.current = null; }
    for (const item of this.queue.splice(0)) item.reject(error('REQUEST_CANCELLED', 'Queued request was cancelled without being sent.', { cause: e.code }));
  }

  requireRecovery(code = 'RESULT_UNKNOWN', message = 'Check the Premiere project and export queue before reconnecting.', details) {
    const safeCode = typeof code === 'string' && /^[A-Z0-9_]{1,80}$/.test(code) ? code : 'RESULT_UNKNOWN';
    this._poison(safeCode, String(message).slice(0, 1000), details);
    return this.status;
  }

  _poison(code, message, details) {
    const socket = this.peer;
    this.peer = null;
    this._rejectAll(error(code, message, details));
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'fatal', code }));
      socket.close(4008, 'Manual recovery required');
    }
    this._setStatus(code, { uncertain: true });
  }

  notifyStatus(parameter, name, value) {
    if (!this.connected) return false;
    this.peer.send(JSON.stringify({ type: 'parameterStatus', parameter: String(parameter).slice(0, 80), name: String(name).slice(0, 100), value: value == null ? null : String(value).slice(0, 60) }));
    return true;
  }

  async stop() {
    this.stopping = true;
    this._rejectAll(error('STOPPED', 'Bridge stopped.'));
    const server = this.server;
    this.server = null;
    this.peer = null;
    if (server) {
      for (const socket of server.clients) socket.terminate();
      await new Promise(resolve => server.close(() => resolve()));
    }
    this._setStatus('STOPPED');
  }
}

export default PremiereBridge;
