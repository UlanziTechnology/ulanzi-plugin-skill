// Shared by the Node service and the Property Inspector (ES module).
export const PLUGIN_UUID = 'com.ulanzi.ulanzistudio.premierepro';
export const DIRECT_EXPORT_TIMEOUT_MS = 12 * 60 * 60 * 1000;
export const ACTIONS = ['queueExport', 'timelineJog', 'trimControl', 'timelineZoom', 'parameterSelect', 'parameterDial'];
export const PARAMETERS = {
  temperature: { name: 'Temperature', min: -100, max: 100, step: 1 },
  tint: { name: 'Tint', min: -100, max: 100, step: 1 },
  saturation: { name: 'Saturation', min: 0, max: 200, step: 1 },
  exposure: { name: 'Exposure', min: -5, max: 5, step: 0.1 },
  contrast: { name: 'Contrast', min: -100, max: 100, step: 1 },
  highlights: { name: 'Highlights', min: -100, max: 100, step: 1 },
  shadows: { name: 'Shadows', min: -100, max: 100, step: 1 },
  whites: { name: 'Whites', min: -100, max: 100, step: 1 },
  blacks: { name: 'Blacks', min: -100, max: 100, step: 1 },
};
const legacyDefaultCycle = ['exposure', 'contrast', 'highlights', 'shadows', 'saturation', 'temperature'];
export const DEFAULTS = {
  queueExport: { exportTarget: 'ame', presetPath: '', presetDirectory: '', presetScope: 'favorites', outputDirectory: '', fileName: '', range: 'entire', startQueue: true },
  timelineJog: { step: 1, heldStep: 10 },
  trimControl: { mode: 'rippleOut', step: 1 },
  // Fixed native-wheel behavior; discard legacy zoom controls on read.
  timelineZoom: {},
  parameterSelect: { groupId: '1', parameter: 'exposure' },
  parameterDial: { source: 'group', groupId: '1', parameter: 'exposure', cycle: Object.keys(PARAMETERS), stepMultiplier: 5 },
};
export function actionName(uuid = '') { return ACTIONS.find(name => uuid === `${PLUGIN_UUID}.${name}`) || null; }
export function settingsFor(action, value = {}) {
  const input = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const result = { ...DEFAULTS[action] };
  for (const key of Object.keys(result)) if (Object.hasOwn(input, key)) result[key] = input[key];
  if ('startQueue' in result) result.startQueue = result.startQueue === true;
  if ('exportTarget' in result && !['ame', 'premiere'].includes(result.exportTarget)) result.exportTarget = 'ame';
  for (const key of ['step', 'heldStep']) if (key in result) result[key] = Math.max(1, Math.min(100, Math.round(Number(result[key]) || DEFAULTS[action][key])));
  if ('parameter' in result && !PARAMETERS[result.parameter]) result.parameter = 'exposure';
  if ('groupId' in result) result.groupId = String(result.groupId || '1').trim().slice(0, 64) || '1';
  if ('mode' in result && !['rippleIn', 'rippleOut', 'rollingNext'].includes(result.mode)) result.mode = 'rippleOut';
  if ('range' in result && !['entire', 'inOut'].includes(result.range)) result.range = 'entire';
  if ('presetScope' in result && !['favorites', 'all', 'custom'].includes(result.presetScope)) result.presetScope = 'favorites';
  if ('source' in result && !['group', 'fixed'].includes(result.source)) result.source = 'group';
  if ('cycle' in result) {
    if (Array.isArray(result.cycle) && result.cycle.length === legacyDefaultCycle.length && result.cycle.every((name, index) => name === legacyDefaultCycle[index])) result.cycle = Object.keys(PARAMETERS);
    result.cycle = [...new Set((Array.isArray(result.cycle) ? result.cycle : []).filter(name => PARAMETERS[name]))];
    if (!result.cycle.length) result.cycle = ['exposure'];
  }
  if ('stepMultiplier' in result) result.stepMultiplier = Math.max(0.1, Math.min(100, Number(result.stepMultiplier) || DEFAULTS[action].stepMultiplier));
  for (const key of ['presetPath', 'presetDirectory', 'outputDirectory', 'fileName']) if (key in result) result[key] = String(result[key] || '').trim();
  return result;
}
