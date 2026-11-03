import { PLUGIN_UUID, PARAMETERS, actionName, settingsFor } from '../shared/config.js';
import { connectionNotice } from '../shared/connection-status.js';
import { PresetCache, presetCacheKey } from '../shared/preset-cache.js';

let selectedAction = actionName(new URLSearchParams(location.search).get('uuid') || '');
let context = '';
let settings = settingsFor(selectedAction);
let presets = [];
let presetsLoaded = false;
let presetLoadKey = null;
let presetRequestId = 0;
const presetCache = new PresetCache();
let pendingDialog = null;
let ready = false;
let settingsLoaded = false;
let reconnectTimer = null;
let reconnectAttempt = 0;
let connectionState = { connected: false };
let hostOffline = false;
let disposed = false;
let criticalFailure = false;
let editing = null;
let composition = null;
const form = document.getElementById('settings-form');
const status = document.getElementById('status');
const connectionStatus = document.getElementById('connection-status');
const connectionRecovery = document.getElementById('connection-recovery');
const t = key => $UD.t(key);
const section = () => document.querySelector(`[data-action="${selectedAction}"]`);

function notice(key, kind = 'error', detail = '') {
  status.textContent = `${t(key)}${detail ? ` (${detail})` : ''}`;
  status.className = `tip ${kind}`;
  renderConnectionStatus();
}
function clearNotice(force = false) {
  if (criticalFailure && !force) return;
  status.textContent = ''; status.className = 'tip hidden';
  renderConnectionStatus();
}
function renderConnectionStatus() {
  const notice = connectionNotice(connectionState, hostOffline);
  connectionStatus.textContent = t(notice.key);
  connectionStatus.className = `tip ${notice.kind}`;
  connectionStatus.hidden = !status.classList.contains('hidden');
  // Keep the instructions available when an action error replaces the connection message.
  connectionRecovery.hidden = notice.key !== 'Bridge recovery required';
  if (connectionRecovery.hidden) connectionRecovery.open = false;
}
function scheduleReconnect() {
  if (disposed || reconnectTimer || reconnectAttempt >= 8) return;
  const delay = Math.min(10000, 2000 * (2 ** reconnectAttempt));
  reconnectAttempt += 1;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    if (!disposed) $UD.connect(PLUGIN_UUID);
  }, delay);
}
function request(type, payload = {}) { if (ready && selectedAction) $UD.sendToPlugin({ type, ...payload }); }
const listCacheKey = () => presetCacheKey(settings.presetScope, settings.presetDirectory, connectionState.connected);
const presetSourceKey = () => JSON.stringify([context, listCacheKey()]);
function presetSearchNotice(text = '') {
  const element = document.getElementById('preset-search-notice');
  element.textContent = text; element.hidden = !text;
}
function displayPresetResult(payload) {
  presets = Array.isArray(payload.presets) ? payload.presets : []; presetsLoaded = true; renderPresets();
  const warningKeys = { PRESET_SCAN_LIMIT: 'Preset scan limit', PRESET_DIRECTORY_UNREADABLE: 'Preset directory unreadable', PRESET_DIRECTORY_INVALID: 'Preset directory invalid', PRESET_DIRECTORY_REQUIRED: 'Custom preset folder required', PRESET_PATH_UNRESOLVED: 'Preset path unresolved', PRESET_HOST_UNAVAILABLE: 'Preset host unavailable', PRESET_FAVORITES_UNREADABLE: 'Preset favorites unreadable', PRESET_FAVORITES_MISSING: 'Preset favorites missing' };
  if (payload.warnings?.length) presetSearchNotice(`${t('Preset search warning')} (${payload.warnings.map(code => t(warningKeys[code] || 'Preset search warning')).join(' ')})`);
  else presetSearchNotice(!presets.length ? t('No presets found') : '');
}
function refreshPresets(force = false) {
  if (!ready || !settingsLoaded || !context || selectedAction !== 'queueExport') return;
  const key = presetSourceKey();
  // Even cache hits invalidate earlier requests, so late results cannot replace this list.
  ++presetRequestId;
  if (force) presetCache.delete(listCacheKey());
  const cached = !force && presetCache.get(listCacheKey());
  if (cached) { presetLoadKey = key; displayPresetResult(cached.value); return; }
  if (presetLoadKey !== key) { presets = []; presetsLoaded = false; renderPresets(); }
  presetLoadKey = key; presetSearchNotice();
  request('refreshPresets', { requestId: presetRequestId, force });
}
function renderCurrentPreset() {
  const field = document.getElementById('presetPath');
  const path = settings.presetPath || '';
  const fileKey = value => {
    const key = String(value || '').replace(/\\/g, '/');
    return /^[a-z]:/i.test(key) || key.startsWith('//') ? key.toLowerCase() : key;
  };
  const matches = preset => fileKey(preset.path) === fileKey(path) && typeof preset.name === 'string' && preset.name.trim() && preset.name !== preset.path;
  let selected = path ? presets.find(matches) : null;
  // A mode switch may hide the selected file; reuse names from other valid lists.
  if (path && !selected) for (const key of [...presetCache.entries.keys()]) {
    const cachedPresets = presetCache.get(key)?.value.presets;
    selected = Array.isArray(cachedPresets) ? cachedPresets.find(matches) : null;
    if (selected) break;
  }
  field.value = selected ? `${selected.name.trim()} · ${path}` : path;
  field.title = field.value;
}
function renderPresets() {
  const select = document.getElementById('presets');
  const visible = presets.filter(preset => settings.presetScope !== 'favorites' || preset.favorite === true)
    .sort((a, b) => Number(b.favorite === true) - Number(a.favorite === true) || String(a.name || '').localeCompare(String(b.name || '')));
  const options = [new Option(t('Choose a preset'), '')];
  const known = new Set();
  for (const preset of visible) {
    if (typeof preset.path !== 'string' || known.has(preset.path)) continue;
    known.add(preset.path);
    const option = new Option(`${preset.favorite ? '★ ' : ''}${preset.name || preset.path}${preset.format ? ` (${preset.format})` : ''}`, preset.path);
    option.title = preset.path;
    options.push(option);
  }
  select.replaceChildren(...options);
  select.value = known.has(settings.presetPath) ? settings.presetPath : '';
  renderCurrentPreset();
}
function render() {
  renderConnectionStatus();
  document.querySelectorAll('[data-action]').forEach(element => { element.hidden = element.dataset.action !== selectedAction; });
  const zoom = selectedAction === 'timelineZoom';
  const help = selectedAction === 'queueExport' && settings.exportTarget === 'premiere' ? t('directExport help') : selectedAction ? t(`${selectedAction} help`) : t('Unknown action');
  const paragraphs = zoom ? help.match(/[\s\S]+?(?:[。！？]|[.!?](?=\s|$)|$)/gu) || [] : [help];
  document.getElementById('action-help').replaceChildren(...paragraphs.map(text => {
    const paragraph = document.createElement('p');
    paragraph.className = 'description';
    paragraph.textContent = text.trim();
    return paragraph;
  }));
  form.hidden = !selectedAction || zoom;
  for (const control of section()?.querySelectorAll('[name]') || []) {
    // Host settings/status updates must not replace a draft or move its caret.
    if (editing?.context === context && editing.control === control && document.activeElement === control) continue;
    const value = settings[control.name];
    if (control.type === 'checkbox') control.checked = value === true;
    else control.value = value ?? '';
  }
  for (const control of form.querySelectorAll('input, select, button')) control.disabled = !(ready && settingsLoaded);
  document.querySelectorAll('[data-source]').forEach(element => { element.hidden = element.dataset.source !== settings.source; });
  document.getElementById('preset-directory-row').hidden = selectedAction !== 'queueExport' || settings.presetScope !== 'custom';
  document.getElementById('ame-queue-row').hidden = selectedAction !== 'queueExport' || settings.exportTarget === 'premiere';
  if (selectedAction === 'queueExport') document.getElementById('option-check-1').disabled = !(ready && settingsLoaded) || settings.exportTarget === 'premiere';
  renderPresets();
  const typingDirectory = editing?.context === context && editing.control.name === 'presetDirectory' && document.activeElement === editing.control;
  if (!typingDirectory && ready && settingsLoaded && context && selectedAction === 'queueExport' && presetLoadKey !== presetSourceKey()) refreshPresets();
}
function save({ renderForm = true } = {}) {
  if (!ready || !settingsLoaded || !selectedAction || !context) return;
  settings = settingsFor(selectedAction, settings);
  $UD.setSettings(settings, context);
  clearNotice();
  if (renderForm) render();
}
function receiveSettings(message) {
  const nextAction = actionName(message.uuid || $UD.uuid);
  if (!nextAction) return;
  const nextContext = message.context || $UD.encodeContext(message);
  if (context !== nextContext) {
    editing = null; composition = null;
    pendingDialog = null; presets = []; presetsLoaded = false; presetLoadKey = null; criticalFailure = false; clearNotice(true);
    presetSearchNotice();
  }
  selectedAction = nextAction;
  context = nextContext;
  settingsLoaded = true;
  // Full replacement is intentional: dragging another copy must never inherit this form's values.
  const incoming = settingsFor(selectedAction, message.settings ?? message.param ?? {});
  // An older same-context reply must not undo the field currently being typed.
  if (editing?.context === context && document.activeElement === editing.control) incoming[editing.control.name] = settings[editing.control.name];
  settings = incoming;
  render();
}
form.addEventListener('submit', event => event.preventDefault());
function editableInput(control) {
  return control.tagName === 'INPUT' && ['text', 'number'].includes(control.type) && !control.readOnly;
}
function saveControl(control, live = false) {
  if (!ready || !settingsLoaded || !control.name || control.disabled || control.readOnly || !section()?.contains(control)) return;
  // Empty, partial and out-of-range numbers are drafts, not a request to reset.
  if (control.type === 'number' && (!control.value.trim() || !control.validity.valid || !Number.isFinite(Number(control.value)))) {
    if (!live) render();
    return;
  }
  settings[control.name] = control.type === 'checkbox' ? control.checked : (control.type === 'number' || control.hasAttribute('data-number')) ? Number(control.value) : control.value;
  // Send immediately to this button's context. A debounce/unload flush can lose
  // the last edit when the host destroys the inspector during a button switch.
  save({ renderForm: !live });
}
form.addEventListener('input', event => {
  if (!ready || !settingsLoaded || !editableInput(event.target) || event.target.disabled || !section()?.contains(event.target) || event.isComposing || composition) return;
  editing = { control: event.target, context };
  saveControl(event.target, true);
});
form.addEventListener('compositionstart', event => {
  if (!editableInput(event.target) || !section()?.contains(event.target)) return;
  composition = editing = { control: event.target, context };
});
form.addEventListener('compositionend', event => {
  const completed = composition; composition = null;
  if (completed?.control !== event.target || completed.context !== context) return;
  saveControl(event.target, true);
});
form.addEventListener('change', event => {
  if (event.isComposing || composition) return;
  editing = null;
  saveControl(event.target);
});
document.getElementById('presets').addEventListener('change', event => { settings.presetPath = event.target.value; save(); });
document.getElementById('refresh-presets').addEventListener('click', () => { clearNotice(); refreshPresets(true); });
for (const button of document.querySelectorAll('[data-browse]')) button.addEventListener('click', () => {
  if (!ready || !context || pendingDialog) return;
  pendingDialog = { field: button.dataset.browse, context };
  $UD.selectFolderDialog();
});
$UD.onParamFromApp(receiveSettings);
$UD.onDidReceiveSettings(message => {
  const receivedContext = message.context || $UD.encodeContext(message);
  // A delayed settings response for the previous button must not select it again.
  if (settingsLoaded && context && receivedContext !== context) return;
  receiveSettings(message);
});
$UD.onSelectdialog(message => {
  const pending = pendingDialog; pendingDialog = null;
  if (!pending || pending.context !== context || (message.context && message.context !== context)) return;
  const path = message.path ?? message.param?.path;
  if (typeof path !== 'string' || !path.trim()) return;
  settings[pending.field] = path.trim(); save();
});
$UD.onSendToPropertyInspector(message => {
  if (message.context && context && message.context !== context) return;
  const payload = message.payload;
  if (!payload || typeof payload !== 'object') return;
  if (payload.type === 'presets' && selectedAction === 'queueExport') {
    if (payload.requestId !== presetRequestId || presetLoadKey !== presetSourceKey()) return;
    presetCache.set(listCacheKey(), { presets: payload.presets, warnings: payload.warnings }, payload.cacheExpiresAt);
    displayPresetResult(payload);
    clearNotice();
  } else if (payload.type === 'bridgeStatus') {
    const becameConnected = payload.connected && !connectionState.connected;
    connectionState = payload; renderConnectionStatus();
    if (becameConnected && settings.presetScope !== 'custom') refreshPresets(true);
  } else if (payload.type === 'zoomPaused' && selectedAction === 'timelineZoom') {
    clearNotice();
  } else if (payload.type === 'actionResult') {
    if (payload.ok) {
      clearNotice();
    } else {
      const code = String(payload.error?.code || 'UNKNOWN_ERROR'); const key = `error.${code}`;
      if (['PARTIAL_MUTATION', 'SAFETY_STOP_RECONNECT', 'RESULT_UNKNOWN'].includes(code)) criticalFailure = true;
      notice(t(key) === key ? 'Action failed' : key, 'error', code);
    }
  }
});
$UD.onClose(() => { hostOffline = true; ready = false; settingsLoaded = false; pendingDialog = null; editing = null; composition = null; render(); scheduleReconnect(); });
$UD.onError(() => { hostOffline = true; renderConnectionStatus(); scheduleReconnect(); });
$UD.onConnected(async () => {
  clearTimeout(reconnectTimer); reconnectTimer = null; reconnectAttempt = 0;
  hostOffline = false; connectionState = { connected: false }; ready = true; settingsLoaded = false; presetLoadKey = null; render();
  await $UD.localizeUI();
  document.getElementById('refresh-presets').setAttribute('aria-label', t('Refresh presets'));
  for (const select of document.querySelectorAll('.parameter-options')) {
    select.replaceChildren(...Object.entries(PARAMETERS).map(([name, metadata]) => new Option(t(metadata.name), name)));
  }
  render();
  $UD.getSettings();
});
window.addEventListener('unload', () => { disposed = true; clearTimeout(reconnectTimer); });
$UD.connect(PLUGIN_UUID);
render();
