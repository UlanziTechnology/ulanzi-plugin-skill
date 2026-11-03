import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { MacTimelineZoom } from './MacTimelineZoom.js';

export class WindowsTimelineZoom extends MacTimelineZoom {
  constructor({ spawnProcess = spawn, ...options } = {}) {
    const helper = fileURLToPath(new URL('../bin/timeline-scroll-windows.exe', import.meta.url));
    super({ ...options, spawnProcess: (_file, _args, configuration) => spawnProcess(helper, [], { ...configuration, windowsHide: true }) });
  }
  async send(payload, beforeSend = () => {}) {
    await this.start();
    beforeSend();
    return super.send({ ...payload, deadline: Date.now() + 230 }, beforeSend);
  }
}
