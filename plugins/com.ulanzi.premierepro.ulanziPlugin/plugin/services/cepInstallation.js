import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { createHash, randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const extensionId = 'com.ulanzi.premierepro.bridge';
const bundledSource = fileURLToPath(new URL('../cep/com.ulanzi.premierepro.bridge/', import.meta.url));
const missing = error => error.code === 'ENOENT';
const hash = data => createHash('sha256').update(data).digest('hex');

export function cepInstallPaths({ platform = process.platform, appData = process.env.APPDATA, home = os.homedir() } = {}) {
  let cepRoot;
  if (platform === 'win32' && appData && path.isAbsolute(appData)) cepRoot = path.join(appData, 'Adobe', 'CEP');
  else if (platform === 'darwin' && home && path.isAbsolute(home)) cepRoot = path.join(home, 'Library', 'Application Support', 'Adobe', 'CEP');
  else throw new Error('The user CEP directory is unavailable.');
  cepRoot = path.resolve(cepRoot);
  return { root: cepRoot, extensions: path.join(cepRoot, 'extensions'), backups: path.join(cepRoot, 'UlanziBackups'), target: path.join(cepRoot, 'extensions', extensionId) };
}

// Check every ancestor before creating directories or replacing our extension.
async function safeDirectory(directory, create = false) {
  const parent = path.dirname(directory);
  if (parent !== directory) await safeDirectory(parent, create);
  let stat;
  try { stat = await fs.lstat(directory); }
  catch (error) { if (!missing(error) || !create) throw error; await fs.mkdir(directory); stat = await fs.lstat(directory); }
  if (stat.isSymbolicLink() || !stat.isDirectory()) throw new Error('A CEP directory is linked or is not a directory.');
}

async function fileMap(directory) {
  await safeDirectory(directory);
  const result = new Map();
  async function walk(current) {
    for (const entry of await fs.readdir(current, { withFileTypes: true })) {
      const filename = path.join(current, entry.name);
      const stat = await fs.lstat(filename);
      if (stat.isSymbolicLink()) throw new Error('A CEP file or directory is linked.');
      if (stat.isDirectory()) await walk(filename);
      else if (stat.isFile()) result.set(path.relative(directory, filename), hash(await fs.readFile(filename)));
      else throw new Error('Unsupported CEP file type.');
    }
  }
  await walk(directory);
  return result;
}
const sameFiles = (a, b) => a.size === b.size && [...a].every(([file, value]) => b.get(file) === value);

async function acquireLock(filename) {
  try { return await fs.open(filename, 'wx'); }
  catch (error) { if (error.code !== 'EEXIST') throw error; }
  const stat = await fs.lstat(filename);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 256) throw new Error('Invalid CEP installation lock.');
  let dead = false;
  try {
    const owner = JSON.parse(await fs.readFile(filename, 'utf8'));
    if (Number.isSafeInteger(owner.pid) && owner.pid > 0) {
      try { process.kill(owner.pid, 0); } catch (error) { if (error.code === 'ESRCH') dead = true; }
    }
  } catch { /* An incomplete lock is left untouched unless it has aged. */ }
  if (!dead && !(stat.size === 0 && Date.now() - stat.mtimeMs > 60000)) throw new Error('Another CEP installation is running.');
  const current = await fs.lstat(filename);
  if (current.ino !== stat.ino || current.mtimeMs !== stat.mtimeMs) throw new Error('The CEP installation lock changed.');
  // Preserve a dead initializer's lock, then claim a fresh exclusive lock.
  await fs.rename(filename, `${filename}-stale-${randomUUID()}`);
  return fs.open(filename, 'wx');
}

/** Install only our bundled extension. No subprocess, registry changes, or application restart. */
export async function ensureCepInstalled(options = {}) {
  const source = path.resolve(options.source || bundledSource);
  let lock, lockPath, staging, backup, moved = false, installed = false;
  try {
    const paths = cepInstallPaths(options);
    const manifest = await fs.readFile(path.join(source, 'CSXS', 'manifest.xml'), 'utf8');
    if (!manifest.includes(`ExtensionBundleId="${extensionId}"`)) throw new Error('The bundled CEP manifest is invalid.');
    const expected = await fileMap(source);
    // No writes for an already matching installation.
    try {
      if (sameFiles(expected, await fileMap(paths.target))) return { changed: false, target: paths.target };
    } catch (error) { if (!missing(error)) throw error; }
    await safeDirectory(paths.extensions, true);
    await safeDirectory(paths.backups, true);
    lockPath = path.join(paths.root, '.ulanzi-premiere-install.lock');
    lock = await acquireLock(lockPath);
    await lock.writeFile(JSON.stringify({ pid: process.pid }));
    // Recheck after acquiring the lock; another initializer may have finished.
    try {
      if (sameFiles(expected, await fileMap(paths.target))) return { changed: false, target: paths.target };
    } catch (error) { if (!missing(error)) throw error; }
    const suffix = `${Date.now()}-${randomUUID()}`;
    staging = path.join(paths.backups, `${extensionId}-staging-${suffix}`);
    backup = path.join(paths.backups, `${extensionId}-${suffix}`);
    await fs.cp(source, staging, { recursive: true, errorOnExist: true, force: false });
    if (!sameFiles(expected, await fileMap(staging))) throw new Error('The staged CEP copy differs from the plugin.');
    try { await fs.rename(paths.target, backup); moved = true; }
    catch (error) { if (!missing(error)) throw error; }
    await fs.rename(staging, paths.target); installed = true; staging = null;
    if (!sameFiles(expected, await fileMap(paths.target))) throw new Error('The installed CEP copy differs from the plugin.');
    return { changed: true, target: paths.target, backup: moved ? backup : undefined };
  } catch (cause) {
    // Preserve failed copies for diagnosis, and restore the original on failure.
    let restored = !moved;
    if (moved) {
      try {
        const paths = cepInstallPaths(options);
        if (installed) await fs.rename(paths.target, `${backup}-failed`);
        await fs.rename(backup, paths.target); restored = true;
      } catch { restored = false; }
    }
    throw Object.assign(new Error('Automatic CEP installation failed.'), { code: 'CEP_INSTALL_FAILED', cause, rollbackComplete: restored });
  } finally {
    if (lock) { await lock.close(); await fs.unlink(lockPath); }
  }
}
