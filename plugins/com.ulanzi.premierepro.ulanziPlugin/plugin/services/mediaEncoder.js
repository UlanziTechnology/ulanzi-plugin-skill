import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { failure } from './errors.js';

const execute = promisify(execFile);

/** Check installation before asking Premiere to enqueue; never launches AME. */
export async function detectMediaEncoder({ platform = process.platform, run = execute, files = fs, applicationRoots = ['/Applications', path.join(os.homedir(), 'Applications')] } = {}) {
  if (platform === 'win32') {
    const script = fileURLToPath(new URL('../scripts/media-encoder.ps1', import.meta.url));
    const executable = path.win32.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
    const { stdout } = await run(executable, ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', script], { windowsHide: true, timeout: 8000, maxBuffer: 16384 });
    const result = JSON.parse(String(stdout).trim());
    if (typeof result.installed !== 'boolean') throw new Error('Invalid AME installation result');
    return result.installed;
  }
  if (platform === 'darwin') {
    async function entries(directory) {
      try { return await files.readdir(directory, { withFileTypes: true }); }
      catch (error) { if (error.code === 'ENOENT') return []; throw error; }
    }
    for (const root of applicationRoots) {
      for (const entry of await entries(root)) {
        if (!/^Adobe Media Encoder(?: \d{4})?(?:\.app)?$/i.test(entry.name)) continue;
        const container = path.join(root, entry.name);
        const bundles = entry.name.endsWith('.app') ? [container] : (await entries(container))
          .filter(item => /^Adobe Media Encoder(?: \d{4})?\.app$/i.test(item.name)).map(item => path.join(container, item.name));
        for (const bundle of bundles) {
          for (const name of ['Adobe Media Encoder', path.basename(bundle, '.app')]) {
            try { if ((await files.stat(path.join(bundle, 'Contents', 'MacOS', name))).isFile()) return true; }
            catch (error) { if (!['ENOENT', 'ENOTDIR'].includes(error.code)) throw error; }
          }
        }
      }
    }
    return false;
  }
  throw new Error('Unsupported AME installation check platform');
}

export async function ensureMediaEncoderAvailable(options) {
  let installed;
  try { installed = await detectMediaEncoder(options); }
  catch { throw failure('AME_CHECK_UNAVAILABLE'); }
  if (!installed) throw failure('AME_UNAVAILABLE');
}
