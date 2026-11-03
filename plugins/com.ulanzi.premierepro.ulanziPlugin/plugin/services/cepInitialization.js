import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import path from 'node:path';
import { ensureCepInstalled } from './cepInstallation.js';

const execute = promisify(execFile);
const versions = ['10', '11', '12'];

/** Allow unsigned CEP extensions for this user, as in the After Effects plugin. */
export async function configureCepDebugMode({ platform = process.platform, run = execute } = {}) {
  const changedVersions = [], failures = [];
  const options = { windowsHide: true, timeout: 5000, maxBuffer: 16384, encoding: 'utf8' };
  const windows = platform === 'win32';
  const executable = windows
    ? path.win32.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'reg.exe')
    : '/usr/bin/defaults';
  if (!windows && platform !== 'darwin') {
    throw Object.assign(new Error('CEP debug mode is unavailable on this platform.'), { code: 'CEP_DEBUG_MODE_FAILED' });
  }
  const readCommand = async args => {
    for (let attempt = 0; ; attempt++) {
      try { return await run(executable, args, options); }
      catch (error) {
        const transient = error.killed || ['ETIMEDOUT', 'EAGAIN', 'EBUSY'].includes(error.code);
        if (attempt || !transient) throw error;
      }
    }
  };
  for (const version of versions) {
    const preference = windows ? `HKCU\\Software\\Adobe\\CSXS.${version}` : `com.adobe.CSXS.${version}`;
    const read = async () => {
      try {
        const { stdout } = await readCommand(windows
          ? ['query', preference, '/v', 'PlayerDebugMode']
          : ['read', preference, 'PlayerDebugMode']);
        return windows ? /^\s*PlayerDebugMode\s+REG_SZ\s+1\s*$/im.test(String(stdout)) : String(stdout).trim() === '1';
      } catch (error) {
        if (error.code === 1) return false; // Missing preference; let the write report any permission failure.
        throw error;
      }
    };
    try {
      if (await read()) continue;
      await run(executable, windows
        ? ['add', preference, '/v', 'PlayerDebugMode', '/t', 'REG_SZ', '/d', '1', '/f']
        : ['write', preference, 'PlayerDebugMode', '-string', '1'], options);
      if (!(await read())) throw new Error('PlayerDebugMode did not read back as 1.');
      changedVersions.push(version);
    } catch (cause) { failures.push({ version, cause }); }
  }
  if (failures.length) {
    const cause = new Error(failures.map(({ version, cause }) => `CSXS.${version}: ${cause.message} [code=${cause.code ?? 'unknown'}, signal=${cause.signal ?? 'none'}, killed=${cause.killed === true}]`).join('; '));
    throw Object.assign(new Error('Automatic CEP debug mode setup failed.'), {
      code: 'CEP_DEBUG_MODE_FAILED', cause, failedVersions: failures.map(failure => failure.version), changedVersions
    });
  }
  return { changed: changedVersions.length > 0, changedVersions, versions: [...versions] };
}

export async function initializeCep(options = {}) {
  const installation = await ensureCepInstalled(options);
  const debugMode = await configureCepDebugMode({ platform: options.platform, run: options.runDebugCommand });
  return { ...installation, debugMode };
}
