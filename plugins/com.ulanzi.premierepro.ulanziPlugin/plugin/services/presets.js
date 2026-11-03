import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { failure } from './errors.js';

export async function presetRoots(env = process.env, home = os.homedir(), platform = process.platform, warnings = []) {
  const roots = [];
  async function directories(directory, pattern) {
    try {
      return (await fs.readdir(directory, { withFileTypes: true }))
        .filter(entry => entry.isDirectory() && !entry.isSymbolicLink() && pattern.test(entry.name))
        .map(entry => path.join(directory, entry.name));
    } catch (error) {
      if (!['ENOENT', 'ENOTDIR'].includes(error.code)) warnings.push('PRESET_DIRECTORY_UNREADABLE');
      return [];
    }
  }
  const userBases = [path.join(home, 'Documents', 'Adobe'), platform === 'win32'
    ? path.join(env.APPDATA || path.join(home, 'AppData', 'Roaming'), 'Adobe')
    : path.join(home, 'Library', 'Application Support', 'Adobe')];
  if (platform !== 'win32') userBases.push(path.join(home, 'Library', 'Preferences', 'Adobe'));
  for (const base of userBases) {
    for (const application of ['Premiere Pro', 'Adobe Media Encoder']) {
      const applicationRoot = path.join(base, application);
      for (const version of [applicationRoot, ...await directories(applicationRoot, /^\d+(?:\.\d+)*$/)]) {
        roots.push(path.join(version, 'Presets'), path.join(version, 'Settings', 'Custom'));
        for (const profile of await directories(version, /^Profile-/i)) roots.push(path.join(profile, 'Settings', 'Custom'), path.join(profile, 'Presets'));
      }
    }
    // Shared encoding presets only; never scan Adobe Common caches or other applications.
    const shared = path.join(base, 'Common', 'AME');
    roots.push(shared, path.join(base, 'Common', 'ExportSettings'));
  }
  const installationBases = platform === 'win32'
    ? [...new Set([env.ProgramFiles || 'C:\\Program Files', env['ProgramFiles(x86)']].filter(Boolean))].map(base => path.join(base, 'Adobe'))
    : ['/Applications'];
  for (const base of installationBases) {
    for (const application of await directories(base, /^Adobe (?:Premiere Pro|Media Encoder)(?: \d{4})?(?:\.app)?$/i)) {
      const bundles = platform === 'win32' || /\.app$/i.test(application) ? [application]
        : await directories(application, /^Adobe (?:Premiere Pro|Media Encoder).*\.app$/i);
      for (const bundle of bundles) {
        const resourceRoots = platform === 'win32' ? [bundle]
          : [path.join(bundle, 'Contents'), path.join(bundle, 'Contents', 'Resources')];
        for (const resources of resourceRoots) roots.push(path.join(resources, 'MediaIO', 'systempresets'), path.join(resources, 'Settings', 'EncoderPresets'));
      }
    }
  }
  // Premiere's own system presets take precedence over identical AME presets.
  return [...new Set(roots)].sort((a, b) => Number(/Adobe Media Encoder/i.test(a)) - Number(/Adobe Media Encoder/i.test(b)));
}

function xmlText(value) {
  return value.replace(/&#x([\da-f]+);|&#(\d+);|&(amp|lt|gt|quot|apos);/gi, (_, hex, dec, entity) => hex || dec
    ? String.fromCodePoint(parseInt(hex || dec, hex ? 16 : 10))
    : { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" }[entity.toLowerCase()]);
}
async function presetMetadata(file) {
  const handle = await fs.open(file, 'r');
  try {
    const buffer = Buffer.alloc(16384);
    const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
    const header = buffer.subarray(0, bytesRead).toString('utf8');
    const id = header.match(/<PresetID>([^<]*)<\/PresetID>/i)?.[1] || '';
    let name = xmlText(header.match(/<PresetName>([^<]*)<\/PresetName>/i)?.[1] || '');
    // Adobe embeds a localization key and English fallback in system preset files.
    if (/^\(\$\$\$\//.test(name)) name = name.slice(name.indexOf('=') + 1, -1);
    return { id, name };
  } finally { await handle.close(); }
}

// Only preset metadata is inspected. Never crawl a drive or follow directory symlinks.
export async function discoverPresets(customDirectory = '', roots) {
  const presets = [], warnings = [], seen = new Set(), systemIds = new Set();
  roots ??= await presetRoots(process.env, os.homedir(), process.platform, warnings);
  let visited = 0;
  const deadline = Date.now() + 4000;
  let limited = false;
  const limitReached = () => visited >= 6000 || Date.now() > deadline || presets.length >= 2000;
  const nonExportDirectory = /^(?:Ingest|SequencePreview|ConsolidateAndTranscode)$/i;
  async function scan(directory, depth, custom) {
    if (depth > 8 || limitReached()) { limited = true; return; }
    let entries;
    try {
      if ((await fs.lstat(directory)).isSymbolicLink()) return;
      entries = await fs.readdir(directory, { withFileTypes: true });
    } catch (error) {
      if (custom || !['ENOENT', 'ENOTDIR'].includes(error.code)) warnings.push('PRESET_DIRECTORY_UNREADABLE');
      return;
    }
    for (const entry of entries) {
      if (limitReached()) { limited = true; break; }
      visited++;
      const candidate = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) continue;
      if (entry.isFile() && /\.epr$/i.test(entry.name)) {
        const key = process.platform === 'win32' ? candidate.toLowerCase() : candidate;
        if (!seen.has(key)) {
          seen.add(key);
          let metadata = {};
          try { metadata = await presetMetadata(candidate); }
          catch { warnings.push('PRESET_DIRECTORY_UNREADABLE'); continue; }
          const system = /[\\/]MediaIO[\\/]systempresets[\\/]/i.test(candidate);
          if (!custom && system && metadata.id && systemIds.has(metadata.id)) continue;
          if (system && metadata.id) systemIds.add(metadata.id);
          presets.push({ name: metadata.name || entry.name.replace(/\.epr$/i, ''), path: candidate, id: metadata.id || '' });
        }
      } else if (entry.isDirectory() && (custom || !nonExportDirectory.test(entry.name))) await scan(candidate, depth + 1, custom);
    }
  }
  if (customDirectory) {
    if (!path.isAbsolute(customDirectory) || path.parse(path.resolve(customDirectory)).root === path.resolve(customDirectory)) warnings.push('PRESET_DIRECTORY_INVALID');
    else await scan(path.resolve(customDirectory), 0, true);
  }
  for (const root of roots) await scan(root, 0, false);
  if (limited) warnings.push('PRESET_SCAN_LIMIT');
  return { presets: presets.sort((a, b) => a.name.localeCompare(b.name) || a.path.localeCompare(b.path)), warnings: [...new Set(warnings)] };
}

// The PR API supplies localized names / identifiers; exports still require a real .epr path.
export async function resolvePremierePresets(local, hostPresets) {
  const byId = new Map(), byName = new Map(), resolved = [], paths = new Set();
  let unresolved = 0;
  for (const preset of local) {
    if (preset.id && !byId.has(preset.id.toLowerCase())) byId.set(preset.id.toLowerCase(), preset);
    const name = preset.name.toLowerCase();
    if (!byName.has(name)) byName.set(name, []);
    byName.get(name).push(preset);
  }
  for (const host of hostPresets) {
    let preset;
    if (typeof host.matchName === 'string' && path.isAbsolute(host.matchName) && /\.epr$/i.test(host.matchName)) {
      try { await validatePreset(host.matchName); preset = { path: host.matchName }; } catch { /* Resolve known identifiers below. */ }
    }
    preset ||= byId.get(String(host.matchName || '').replace(/^\{|\}$/g, '').toLowerCase());
    // Name matching is safe only when it identifies a single local preset.
    const matches = byName.get(String(host.name || '').toLowerCase()) || [];
    if (!preset && matches.length === 1) preset = matches[0];
    if (!preset) { unresolved++; continue; }
    if (paths.has(preset.path)) continue;
    paths.add(preset.path);
    resolved.push({ ...preset, name: host.name || preset.name, format: host.format || '' });
  }
  return { presets: resolved.sort((a, b) => a.name.localeCompare(b.name)), unresolved };
}

export function favoritePresetFiles(env = process.env, home = os.homedir(), platform = process.platform) {
  const bases = platform === 'win32'
    ? [path.join(env.APPDATA || path.join(home, 'AppData', 'Roaming'), 'Adobe')]
    : [path.join(home, 'Library', 'Preferences', 'Adobe'), path.join(home, 'Library', 'Application Support', 'Adobe')];
  return bases.map(base => path.join(base, 'Common', 'ExportSettings', 'FavoritePresets.json'));
}

// Read PR's saved stars. Never create or edit Adobe's favorites/preferences.
export async function applyFavoritePresets(presets, files = favoritePresetFiles()) {
  const result = presets.map(preset => ({ ...preset, favorite: false }));
  const warnings = [];
  const normalize = value => String(value || '').replace(/\\/g, '/').toLowerCase();
  let records = [];
  for (const file of files) {
    try {
      const stat = await fs.lstat(file);
      if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 512 * 1024) throw new Error('Invalid favorites file');
      const contents = await fs.readFile(file, 'utf8');
      if (Buffer.byteLength(contents, 'utf8') > 512 * 1024) throw new Error('Favorites file too large');
      const data = JSON.parse(contents);
      if (!Array.isArray(data) || data.length > 2000) throw new Error('Invalid favorites list');
      records = data;
      break;
    } catch (error) {
      if (!['ENOENT', 'ENOTDIR'].includes(error.code)) warnings.push('PRESET_FAVORITES_UNREADABLE');
    }
  }
  let favoriteCount = 0, missing = 0;
  let systemRoots;
  const seen = new Set();
  for (const record of records) {
    if (!record || typeof record !== 'object' || typeof record.uniqueID !== 'string' || typeof record.filePath !== 'string') {
      warnings.push('PRESET_FAVORITES_UNREADABLE'); continue;
    }
    const id = normalize(record.uniqueID), filePath = normalize(record.filePath);
    const key = id || filePath;
    if (seen.has(key)) continue;
    seen.add(key); favoriteCount++;
    let matches = result.filter(preset => (id && normalize(preset.id) === id) || normalize(preset.path) === filePath
      || (record.systemPreset === true && /^MediaIO\/systempresets\//i.test(record.filePath.replace(/\\/g, '/')) && normalize(preset.path).endsWith('/' + filePath)));
    // Resolve saved favorites independently of scan truncation or live API omissions.
    if (!matches.length && /\.epr$/i.test(record.filePath)) {
      const candidates = [];
      if (record.systemPreset !== true && path.isAbsolute(record.filePath)) candidates.push(record.filePath);
      else if (record.systemPreset === true && /^MediaIO\/systempresets\//i.test(record.filePath.replace(/\\/g, '/'))) {
        systemRoots ??= (await presetRoots()).filter(root => /[\\/]MediaIO[\\/]systempresets$/i.test(root));
        for (const root of systemRoots) {
          const candidate = path.resolve(root, record.filePath.replace(/\\/g, '/').replace(/^MediaIO\/systempresets\//i, ''));
          if (candidate.startsWith(path.resolve(root) + path.sep)) candidates.push(candidate);
        }
      }
      for (const candidate of candidates) {
        try {
          const stat = await fs.lstat(candidate);
          if (!stat.isFile() || stat.isSymbolicLink()) continue;
          const metadata = await presetMetadata(candidate);
          const preset = { name: metadata.name || path.basename(candidate).replace(/\.epr$/i, ''), path: candidate, id: metadata.id || record.uniqueID };
          result.push(preset); matches = [preset]; break;
        } catch { /* A stale favorite remains reported below, never given a guessed path. */ }
      }
    }
    if (!matches.length) { missing++; continue; }
    for (const preset of matches) {
      preset.favorite = true;
      if (!preset.format && typeof record.format === 'string') preset.format = record.format;
    }
  }
  if (missing) warnings.push('PRESET_FAVORITES_MISSING');
  return { presets: result.sort((a, b) => Number(b.favorite) - Number(a.favorite) || a.name.localeCompare(b.name)), favoriteCount, warnings: [...new Set(warnings)] };
}

export async function validatePreset(presetPath) {
  if (!presetPath) throw failure('PRESET_REQUIRED');
  if (!path.isAbsolute(presetPath) || !/\.epr$/i.test(presetPath)) throw failure('PRESET_NOT_FOUND');
  try { if (!(await fs.stat(presetPath)).isFile()) throw new Error(); } catch { throw failure('PRESET_NOT_FOUND'); }
}

export function safeFileName(value) {
  return String(value || '').replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').replace(/[. ]+$/g, '').slice(0, 120) || 'Sequence';
}
export async function chooseOutputPath(directory, fileName, sequenceName, extension, reservations = new Set()) {
  if (!directory) throw failure('OUTPUT_DIRECTORY_REQUIRED');
  if (!path.isAbsolute(directory)) throw failure('OUTPUT_DIRECTORY_INVALID');
  try { if (!(await fs.stat(directory)).isDirectory()) throw new Error(); await fs.access(directory, fs.constants.W_OK); } catch { throw failure('OUTPUT_DIRECTORY_INVALID'); }
  const ext = String(extension || '').replace(/^\./, '');
  if (!/^[a-z0-9]{1,12}$/i.test(ext)) throw failure('EXPORT_EXTENSION_UNKNOWN');
  if (fileName && (safeFileName(fileName) !== fileName || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(fileName))) throw failure('INVALID_OUTPUT_NAME');
  let base = safeFileName(fileName || sequenceName);
  if (/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(base)) base = `_${base}`;
  if (base.toLowerCase().endsWith(`.${ext.toLowerCase()}`)) base = base.slice(0, -(ext.length + 1));
  for (let i = 0; i < 10000; i++) {
    const candidate = path.join(directory, `${base}${i ? `_${i}` : ''}.${ext}`);
    const key = process.platform === 'win32' ? candidate.toLowerCase() : candidate;
    if (reservations.has(key)) continue;
    try { await fs.access(candidate); } catch (e) { if (e.code === 'ENOENT') { reservations.add(key); return candidate; } throw e; }
  }
  throw failure('OUTPUT_NAME_EXHAUSTED');
}
