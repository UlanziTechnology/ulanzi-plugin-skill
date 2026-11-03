import { execFile, spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { promisify } from 'node:util';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { failure } from './errors.js';
const run = promisify(execFile);

// Keep Windows PowerShell warm; each CHECK still reads the current foreground
// window. Never cache a successful check across a focus change.
export class PremiereForegroundChecker {
  constructor({ platform = process.platform, spawnProcess = spawn, timeoutMs = 2500 } = {}) {
    Object.assign(this, { platform, spawnProcess, timeoutMs });
    this.child = null; this.ready = null; this.pending = []; this.closed = false;
  }
  start() {
    if (this.closed) return Promise.reject(failure('FOREGROUND_UNAVAILABLE'));
    if (this.platform !== 'win32') return Promise.resolve();
    if (this.ready) return this.ready;
    let resolveReady, rejectReady;
    const ready = new Promise((resolve, reject) => { resolveReady = resolve; rejectReady = reject; });
    this.ready = ready;
    const script = fileURLToPath(new URL('../scripts/foreground.ps1', import.meta.url));
    const exe = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
    let child;
    try {
      child = this.spawnProcess(exe, ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', script, '-Persistent'], { windowsHide: true, stdio: ['pipe', 'pipe', 'ignore'] });
    } catch { this.ready = null; rejectReady(failure('FOREGROUND_UNAVAILABLE')); return ready; }
    this.child = child;
    const lines = createInterface({ input: child.stdout });
    let startupTimer = setTimeout(() => fail(), this.timeoutMs);
    const fail = () => {
      clearTimeout(startupTimer); lines.close();
      if (this.child !== child) return;
      this.child = null; this.ready = null;
      rejectReady(failure('FOREGROUND_UNAVAILABLE'));
      for (const request of this.pending.splice(0)) { clearTimeout(request.timer); request.reject(failure('FOREGROUND_UNAVAILABLE')); }
      child.kill();
    };
    this.stopChild = fail;
    child.on('error', fail); child.on('exit', fail); child.stdin.on('error', fail);
    lines.on('line', line => {
      if (line === 'READY') { clearTimeout(startupTimer); startupTimer = null; resolveReady(); return; }
      const request = this.pending.shift();
      if (!request) { fail(); return; }
      clearTimeout(request.timer);
      if (line === 'CHECK_ERROR') request.reject(failure('FOREGROUND_UNAVAILABLE'));
      else if (!/^Adobe Premiere Pro(?: \d{4})?$/i.test(line.trim())) request.reject(failure('PREMIERE_NOT_FOREGROUND'));
      else request.resolve();
    });
    return ready;
  }
  async check() {
    await this.start();
    if (this.closed) throw failure('FOREGROUND_UNAVAILABLE');
    if (this.platform !== 'win32') return ensurePremiereForeground();
    return new Promise((resolve, reject) => {
      const child = this.child;
      if (!child) { reject(failure('FOREGROUND_UNAVAILABLE')); return; }
      const request = { resolve, reject, timer: setTimeout(() => this.stopChild?.(), this.timeoutMs) };
      this.pending.push(request);
      child.stdin.write('CHECK\n');
    });
  }
  close() { this.closed = true; this.stopChild?.(); }
}

export async function ensurePremiereForeground() {
  let output;
  try {
    if (process.platform === 'win32') {
      const script = fileURLToPath(new URL('../scripts/foreground.ps1', import.meta.url));
      const exe = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
      output = (await run(exe, ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', script], { windowsHide: true, timeout: 2500, maxBuffer: 4096 })).stdout;
    } else if (process.platform === 'darwin') {
      output = (await run('/usr/bin/osascript', ['-e', 'tell application "System Events" to get name of first application process whose frontmost is true'], { timeout: 2500, maxBuffer: 4096 })).stdout;
    } else throw new Error('Unsupported operating system');
  } catch { throw failure('FOREGROUND_UNAVAILABLE'); }
  if (!/^Adobe Premiere Pro(?: \d{4})?$/i.test(output.trim())) throw failure('PREMIERE_NOT_FOREGROUND');
}
