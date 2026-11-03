import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { PLUGIN_UUID } from '../../shared/config.js';

// Bounded local timing log. Records input submission, not Premiere's repaint time.
export function createZoomDiagnostic({ directory } = {}) {
  const root = directory || (process.platform === 'win32'
    ? path.join(process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming'), 'Ulanzi', 'UlanziDeck', 'logs', PLUGIN_UUID)
    : path.join(os.homedir(), 'Library', 'Application Support', 'Ulanzi', 'UlanziDeck', 'logs', PLUGIN_UUID));
  const file = path.join(root, 'timeline-zoom.log');
  let writes = 0, warned = false;
  const write = record => {
    try {
      if (writes++ % 100 === 0) {
        fs.mkdirSync(root, { recursive: true });
        if (fs.existsSync(file) && fs.statSync(file).size >= 2 * 1024 * 1024) {
          const previous = path.join(root, 'timeline-zoom.previous.log');
          fs.rmSync(previous, { force: true }); fs.renameSync(file, previous);
        }
      }
      fs.appendFileSync(file, JSON.stringify({ time: new Date().toISOString(), pid: process.pid, ...record }) + '\n', 'utf8');
    } catch (error) {
      if (!warned) { warned = true; console.warn(`[Zoom diagnostics] ${error.code || 'LOG_UNAVAILABLE'}`); }
    }
  };
  const windowsWheelSupported = process.platform === 'win32' && process.arch === 'x64' && Number(os.release().split('.')[2]) >= 19041;
  write({ event: 'zoom-runtime-start', route: process.platform === 'darwin' && Number.parseInt(os.release(), 10) >= 22 ? 'mac-native-wheel' : windowsWheelSupported ? 'windows-native-wheel' : 'unsupported' });
  return write;
}
