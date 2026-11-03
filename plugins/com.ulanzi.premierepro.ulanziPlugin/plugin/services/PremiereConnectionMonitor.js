import { EventEmitter } from 'node:events';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import path from 'node:path';
import { connectionNotice } from '../../shared/connection-status.js';

const execute = promisify(execFile);
const unavailable = () => Object.assign(new Error('Premiere process state is unavailable.'), { code: 'PROCESS_CHECK_UNAVAILABLE' });

export async function detectPremiereProcess({ platform = process.platform, run = execute } = {}) {
  const options = { windowsHide: true, timeout: 2500, maxBuffer: 16384 };
  if (platform === 'win32') {
    const executable = path.win32.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'tasklist.exe');
    const { stdout } = await run(executable, ['/FI', 'IMAGENAME eq Adobe Premiere Pro.exe', '/FO', 'CSV', '/NH'], options);
    const output = String(stdout || '').trim();
    if (!output) throw unavailable();
    if (/^"Adobe Premiere Pro\.exe",/im.test(output)) return true;
    // A successful filtered tasklist returns a localized informational line when no process exists.
    if (output.startsWith('"')) throw unavailable();
    return false;
  }
  if (platform === 'darwin') {
    try {
      const { stdout } = await run('/usr/bin/pgrep', ['-x', '^Adobe Premiere Pro( [0-9]{4})?$'], options);
      if (!/^\d+(?:\s+\d+)*\s*$/.test(String(stdout || ''))) throw unavailable();
      return true;
    } catch (error) {
      if (error.code === 1) {
        // Darwin may fall back to a truncated process name when argv[0] is inaccessible.
        // A matching prefix is ambiguous, so report unknown rather than "not running".
        try { await run('/usr/bin/pgrep', ['-x', '^Adobe Premiere( P)?$'], options); }
        catch (fallbackError) { if (fallbackError.code === 1) return false; throw fallbackError; }
        throw unavailable();
      }
      throw error;
    }
  }
  throw unavailable();
}

/** Process checks and recovery of failed CEP preference setup; never sends a Premiere command. */
export class PremiereConnectionMonitor extends EventEmitter {
  constructor(bridge, { detectProcess = detectPremiereProcess, intervalMs = 1000, graceMs = 15000, now = Date.now, cepInstallError = null, recoverCepDebugMode = null, debugRetryMs = 10000 } = {}) {
    super();
    Object.assign(this, { bridge, detectProcess, intervalMs, graceMs, now, cepInstallError, recoverCepDebugMode, debugRetryMs });
    this.applicationState = 'checking';
    this.runningSince = null;
    this.started = false;
    this.epoch = 0;
    this.timer = null;
    this.inFlight = null;
    this.debugRecoveryTimer = null;
    this.debugRecoveryInFlight = null;
    this.lastPublished = '';
    this.onBridgeStatus = () => {
      if (this.bridge.connected) {
        this.applicationState = 'running';
        this.runningSince ??= this.now();
        clearTimeout(this.timer); this.timer = null;
      }
      this.publish();
      if (this.started && !this.bridge.connected) void this.refresh();
    };
  }
  get status() {
    const connected = this.bridge.connected;
    const applicationState = connected ? 'running' : this.applicationState;
    const state = {
      ...this.bridge.status, connected, applicationState, cepInstallError: this.cepInstallError,
      waitingForBridge: !connected && applicationState === 'running' && this.runningSince !== null && this.now() - this.runningSince < this.graceMs
    };
    const notice = connectionNotice(state);
    return { ...state, statusKey: notice.key, statusClass: notice.kind };
  }
  publish() {
    const state = this.status;
    const serialized = JSON.stringify(state);
    if (serialized === this.lastPublished) return;
    this.lastPublished = serialized;
    this.emit('status', state);
  }
  async start() {
    if (this.started) return this.status;
    this.started = true;
    this.bridge.on('status', this.onBridgeStatus);
    void this.retryCepDebugMode();
    return this.refresh();
  }
  retryCepDebugMode() {
    if (!this.started || this.cepInstallError !== 'CEP_DEBUG_MODE_FAILED' || !this.recoverCepDebugMode) return Promise.resolve();
    if (this.debugRecoveryInFlight) return this.debugRecoveryInFlight;
    clearTimeout(this.debugRecoveryTimer); this.debugRecoveryTimer = null;
    const epoch = this.epoch;
    // Defer the callback so the in-flight guard is set even for synchronous failures.
    this.debugRecoveryInFlight = Promise.resolve().then(() => this.recoverCepDebugMode()).then(() => {
      if (!this.started || epoch !== this.epoch) return;
      this.cepInstallError = null;
      this.publish();
    }, () => { /* Keep the error visible until all preferences verify successfully. */ }).finally(() => {
      this.debugRecoveryInFlight = null;
      if (this.started && epoch === this.epoch && this.cepInstallError === 'CEP_DEBUG_MODE_FAILED') {
        this.debugRecoveryTimer = setTimeout(() => { this.debugRecoveryTimer = null; void this.retryCepDebugMode(); }, this.debugRetryMs);
        this.debugRecoveryTimer.unref?.();
      }
    });
    return this.debugRecoveryInFlight;
  }
  refresh() {
    if (!this.started) return Promise.resolve(this.status);
    if (this.inFlight) return this.inFlight;
    clearTimeout(this.timer); this.timer = null;
    if (this.bridge.connected) {
      this.applicationState = 'running'; this.runningSince ??= this.now();
      this.publish();
      return Promise.resolve(this.status);
    }
    const epoch = this.epoch;
    this.inFlight = (async () => {
      let running;
      try { running = await this.detectProcess(); } catch { running = null; }
      if (!this.started || epoch !== this.epoch) return this.status;
      // Authentication may complete while the OS check runs. A late negative result must not undo it.
      if (this.bridge.connected) running = true;
      this.applicationState = running === true ? 'running' : running === false ? 'notRunning' : 'unknown';
      if (running === true) this.runningSince ??= this.now();
      else this.runningSince = null;
      this.publish();
      return this.status;
    })().finally(() => {
      this.inFlight = null;
      if (this.started && epoch === this.epoch && !this.bridge.connected) {
        this.timer = setTimeout(() => { this.timer = null; void this.refresh(); }, this.intervalMs);
        this.timer.unref?.();
      }
    });
    return this.inFlight;
  }
  stop() {
    this.started = false; this.epoch++;
    clearTimeout(this.timer); this.timer = null;
    clearTimeout(this.debugRecoveryTimer); this.debugRecoveryTimer = null;
    this.bridge.removeListener('status', this.onBridgeStatus);
  }
}
