let ACTION_SETTING = {};
let actionKind = '';
let saveTimer = 0;
let captureTimer = 0;
let detectedShortcutCatalog = null;
let activeInspectorContext = '';
let shortcutRefreshTimer = 0;
let statusPollTimer = 0;
let connectionStatusPollTimer = 0;

const isMacOS = /Mac/i.test(`${navigator.platform || ''} ${navigator.userAgent || ''}`);
const isWindows = /Win/i.test(`${navigator.platform || ''} ${navigator.userAgent || ''}`);
const supportsSmartHover = isMacOS || isWindows;

const GLOBAL_SHORTCUT_CATALOG_KEY = 'jianyingShortcutCatalog';
const GLOBAL_SHORTCUT_CATALOG_SCHEMA = 1;
const validColorWheelModes = new Set(['diameter', 'orbit']);

const timelineModes = [
  ['frame_step', 'Previous / next frame'],
  ['track_height', 'Track height'],
  ['timeline_zoom', 'Timeline zoom'],
  ['vertical_scroll', 'Timeline vertical scroll'],
  ['horizontal_scroll', 'Timeline horizontal scroll'],
  ['large_seek', 'Large timeline seek'],
  ['marker', 'Previous / next marker'],
  ['split_point', 'Previous / next split point']
];

const shortcuts = [
  ['split', 'Split', '⌘B', 'Ctrl+B'],
  ['undo', 'Undo', '⌘Z', 'Ctrl+Z'],
  ['redo', 'Redo', '⌘⇧Z', 'Ctrl+Shift+Z'],
  ['copy', 'Copy', '⌘C', 'Ctrl+C'],
  ['paste', 'Paste', '⌘V', 'Ctrl+V'],
  ['cut', 'Cut', '⌘X', 'Ctrl+X'],
  ['delete', 'Delete', '⌫', 'Delete'],
  ['play_pause', 'Play / Pause', 'Space', 'Space'],
  ['fullscreen', 'Fullscreen preview', '⌘⇧F', 'Ctrl+Shift+F'],
  ['previous_frame', 'Previous frame', '⌘←', 'Ctrl+←'],
  ['next_frame', 'Next frame', '⌘→', 'Ctrl+→'],
  ['previous_edit', 'Previous split point', '↑', '↑'],
  ['next_edit', 'Next split point', '↓', '↓'],
  ['zoom_in', 'Timeline zoom in', '⌘=', 'Ctrl+='],
  ['zoom_out', 'Timeline zoom out', '⌘-', 'Ctrl+-'],
  ['fast_forward', 'Fast forward', '→', '→'],
  ['rewind', 'Rewind', '←', '←'],
  ['previous_marker', 'Previous marker', '⌥⇧M', 'Alt+Shift+M'],
  ['next_marker', 'Next marker', '⇧M', 'Shift+M'],
  ['export', 'Export', '⌘E', 'Ctrl+E'],
  ['record', 'Record', '⌘R', 'Ctrl+R']
];

const shortcutAliases = {
  timeline_start: 'previous_frame',
  timeline_end: 'next_frame'
};

const basicParameters = [
  'temperature|Temperature', 'tint|Tint', 'saturation|Saturation', 'vibrance|Vibrance',
  'exposure|Exposure', 'brightness|Brightness', 'contrast|Contrast', 'highlights|Highlights',
  'shadows|Shadows', 'whites|Whites', 'blacks|Blacks', 'sharpen|Sharpen',
  'clarity|Clarity', 'fade|Fade', 'vignette|Vignette', 'grain|Grain'
].map(item => item.split('|'));

const hslParameters = [['hue', 'Hue'], ['saturation', 'Saturation'], ['luminance', 'Luminance']];
const colorWheelParameters = [['intensity', 'Intensity']].concat(['shadows', 'midtones', 'highlights', 'global'].flatMap(wheel => [
  [`${wheel}.x`, `${wheel[0].toUpperCase() + wheel.slice(1)} Color X`],
  [`${wheel}.y`, `${wheel[0].toUpperCase() + wheel.slice(1)} Color Y`],
  [`${wheel}.luma`, `${wheel[0].toUpperCase() + wheel.slice(1)} Luminance`]
]));

function tr(key, replacements = {}) {
  let value = ($UD && typeof $UD.t === 'function') ? $UD.t(key) : key;
  Object.entries(replacements).forEach(([name, replacement]) => {
    value = value.replace(`{${name}}`, String(replacement));
  });
  return value;
}

function setJianyingConnectionStatus(key, level = 'info') {
  const status = document.getElementById('jianying-connection-status');
  status.classList.remove('info', 'success', 'warn', 'error');
  status.classList.add(level);
  status.textContent = tr(key);
}

function requestJianyingStatus() {
  $UD.sendToPlugin({type: 'requestJianyingStatus'});
}

function startConnectionStatusPolling() {
  window.clearInterval(connectionStatusPollTimer);
  requestJianyingStatus();
  connectionStatusPollTimer = window.setInterval(requestJianyingStatus, 1000);
}

function stopConnectionStatusPolling() {
  window.clearInterval(connectionStatusPollTimer);
  connectionStatusPollTimer = 0;
}

function identifyAction() {
  const value = String(($UD && $UD.uuid) || window.location.search || '');
  if (value.includes('timelineScrub') || value.includes('timelineZoom')) return 'timeline_control';
  if (value.includes('basicAdjustments') || value.includes('.hsl')) return 'selected_slider';
  if (value.includes('colorWheels')) return 'color_wheels';
  return 'shortcut';
}

function show(id, visible) {
  document.getElementById(id).style.display = visible ? '' : 'none';
}

function fillSelect(id, items) {
  const select = document.getElementById(id);
  select.innerHTML = '';
  items.forEach(([value, label], index) => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = tr(label);
    option.setAttribute('data-localize', label);
    option.dataset.index = String(index);
    select.appendChild(option);
  });
}

function renderShortcutPreview() {
  const command = document.getElementById('command').value;
  const shortcut = shortcuts.find(([key]) => key === command) || shortcuts[0];
  const source = document.getElementById('shortcut-source');
  const help = document.getElementById('shortcut-help');
  const display = document.getElementById('shortcut-display');
  const detected = detectedShortcutCatalog?.shortcuts?.[command];
  const isUnassigned = Boolean(detectedShortcutCatalog?.autoDetected && detected && !detected.assigned);
  display.classList.toggle('warn', isUnassigned);
  help.classList.toggle('hidden', !isUnassigned);
  help.textContent = isUnassigned ? tr('Shortcut unassigned help') : '';
  if (detectedShortcutCatalog === null) {
    display.textContent = '—';
    source.textContent = tr('Shortcut loading');
    return;
  }

  const mac = isUnassigned ? '' : (detected?.mac || shortcut[2]);
  const windows = isUnassigned ? '' : (detected?.windows || shortcut[3]);
  display.textContent = isUnassigned
    ? tr('Shortcut unassigned')
    : (mac === windows ? mac : `${windows}(Win) / ${mac}(Mac)`);

  source.textContent = detectedShortcutCatalog?.autoDetected
    ? tr('Detected shortcut profile', {profile: detectedShortcutCatalog.profile || '-'})
    : tr('Shortcut fallback');
}

function requestShortcutCatalog(force = false) {
  if (actionKind !== 'shortcut') return;
  const refresh = document.getElementById('refresh-shortcuts');
  window.clearTimeout(shortcutRefreshTimer);
  if (force) refresh.disabled = true;
  $UD.sendToPlugin({type: 'requestShortcutCatalog', force});
  if (force) {
    shortcutRefreshTimer = window.setTimeout(() => {
      refresh.disabled = false;
    }, 2000);
  }
}

function applyShortcutCatalog(catalog) {
  if (!catalog || catalog.schemaVersion !== GLOBAL_SHORTCUT_CATALOG_SCHEMA) return;

  const incomingUpdatedAt = Number(catalog.updatedAt || 0);
  const currentUpdatedAt = Number(detectedShortcutCatalog?.updatedAt || 0);
  if (currentUpdatedAt && incomingUpdatedAt && incomingUpdatedAt < currentUpdatedAt) return;

  detectedShortcutCatalog = catalog;
  window.clearTimeout(shortcutRefreshTimer);
  document.getElementById('refresh-shortcuts').disabled = false;
  if (actionKind === 'shortcut') renderShortcutPreview();
}

function receiveGlobalSettings(message) {
  const settings = message && (message.settings || message.param || message.payload) || {};
  applyShortcutCatalog(settings[GLOBAL_SHORTCUT_CATALOG_KEY]);
}

function requestGlobalShortcutCatalog() {
  if (actionKind !== 'shortcut') return;
  $UD.getGlobalSettings(activeInspectorContext || undefined);
}

function relocalizeShortcutPreview() {
  if (typeof $UD.localizeUI !== 'function') return;
  const localization = $UD.localizeUI();
  if (!localization || typeof localization.then !== 'function') return;
  localization.then(
    () => {
      if (actionKind === 'shortcut') renderShortcutPreview();
    },
    () => {}
  );
}

function syncInspectorIdentity(message) {
  const decoded = message?.context && typeof $UD.decodeContext === 'function'
    ? $UD.decodeContext(message.context)
    : {};
  const uuid = message?.uuid || decoded.uuid;
  const key = message?.key || decoded.key;
  const actionid = message?.actionid || decoded.actionid;
  if (uuid) $UD.uuid = uuid;
  if (key) $UD.key = key;
  if (actionid) $UD.actionid = actionid;

  const identity = [uuid || $UD.uuid, key || $UD.key, actionid || $UD.actionid];
  const context = identity.every(Boolean) ? identity.join('___') : '';
  const changed = Boolean(context && context !== activeInspectorContext);
  if (context) activeInspectorContext = context;

  const nextKind = identifyAction();
  if (actionKind && nextKind !== actionKind) {
    actionKind = nextKind;
    configureForm();
  }
  return changed;
}

function parameterItemsForKind() {
  if (actionKind === 'selected_slider') return basicParameters.concat(hslParameters);
  if (actionKind === 'color_wheels') return colorWheelParameters;
  return [];
}

function enabledParameterKeys() {
  return Array.from(document.querySelectorAll('#parameter-subset input:checked'))
    .map(input => input.value);
}

function fillParameterFromSubset(preferredKey = '') {
  const allItems = parameterItemsForKind();
  const enabled = new Set(enabledParameterKeys());
  const items = allItems.filter(([key]) => enabled.has(key));
  fillSelect('parameter', items.length ? items : allItems.slice(0, 1));
  const parameter = document.getElementById('parameter');
  const preferredIndex = items.findIndex(([key]) => key === preferredKey);
  parameter.selectedIndex = preferredIndex >= 0 ? preferredIndex : 0;
}

function renderParameterSubset() {
  const container = document.getElementById('parameter-subset');
  const items = parameterItemsForKind();
  const configured = Array.isArray(ACTION_SETTING.enabledParameters)
    ? ACTION_SETTING.enabledParameters.filter(key => items.some(([itemKey]) => itemKey === key))
    : items.map(([key]) => key);
  const enabled = new Set(configured.length ? configured : items.map(([key]) => key));
  container.innerHTML = '';
  items.forEach(([key, label]) => {
    const option = document.createElement('label');
    option.className = 'subset-option';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.value = key;
    input.checked = enabled.has(key);
    const text = document.createElement('span');
    text.textContent = tr(label);
    text.setAttribute('data-localize', label);
    option.append(input, text);
    container.appendChild(option);
  });
  fillParameterFromSubset();
}

function fillTimelineModeSelect(preferredId = '') {
  fillSelect('timeline-mode', timelineModes);
  const selected = timelineModes.some(([id]) => id === preferredId)
    ? preferredId
    : timelineModes[0][0];
  document.getElementById('timeline-mode').value = selected;
}

function configureForm() {
  const isShortcut = actionKind === 'shortcut';
  const isTimeline = actionKind === 'timeline_control';
  const isAdjustment = !isShortcut && !isTimeline;
  const isSmartSlider = actionKind === 'selected_slider' && supportsSmartHover;
  const isSmartColorWheel = actionKind === 'color_wheels' && supportsSmartHover;
  const isSmartAdjustment = isSmartSlider || isSmartColorWheel;
  if (!isSmartAdjustment && statusPollTimer) {
    window.clearInterval(statusPollTimer);
    statusPollTimer = 0;
  }
  show('command-row', isShortcut);
  show('shortcut-preview', isShortcut);
  show('timeline-mode-row', isTimeline);
  show('basic-hover-turn-row', isSmartSlider);
  show('basic-hover-press-row', isSmartSlider);
  show('selected-slider-hover-help', isSmartSlider);
  show('color-wheel-dial-mode-row', isSmartColorWheel);
  show('color-wheel-hold-dial-mode-row', isSmartColorWheel);
  show('color-wheel-hover-help', isSmartColorWheel);
  show('require-active-row', isAdjustment && !isSmartAdjustment);
  show('status', isAdjustment && !isSmartAdjustment);
  show('parameter-row', isAdjustment && !isSmartAdjustment);
  show('parameter-subset-row', isAdjustment && !isSmartAdjustment);
  show('color-row', false);
  show('sensitivity-row', isAdjustment && !isSmartAdjustment);
  show('calibration-panel', isAdjustment && !isSmartAdjustment);
  show('gesture-help', isAdjustment && !isSmartAdjustment);
  show('wheel-radius-label', false);

  fillSelect('command', shortcuts);
}

function calibrationKey() {
  const parameter = document.getElementById('parameter').value;
  return parameter;
}

function renderCalibration() {
  const calibrations = ACTION_SETTING.calibrations || {};
  const key = calibrationKey();
  let calibration = calibrations[key];
  if (!calibration && actionKind === 'color_wheels' && /\.(x|y)$/.test(key)) {
    const siblingKey = key.endsWith('.x') ? key.replace(/\.x$/, '.y') : key.replace(/\.y$/, '.x');
    calibration = calibrations[siblingKey];
  }
  calibration = calibration || {};
  show('wheel-radius-label', actionKind === 'color_wheels' && /\.(x|y)$/.test(key));
  document.getElementById('target-x').value = calibration.x ?? '';
  document.getElementById('target-y').value = calibration.y ?? '';
  document.getElementById('pixels-per-step').value = calibration.pixelsPerStep ?? 2;
  document.getElementById('wheel-radius').value = calibration.wheelRadius ?? 45;
  document.getElementById('axis').value = calibration.axis || 'horizontal';
  const panel = ACTION_SETTING.panelTarget || {};
  document.getElementById('panel-x').value = panel.x ?? '';
  document.getElementById('panel-y').value = panel.y ?? '';
  document.getElementById('panel-delay').value = panel.delay ?? 0.12;
}

function render(settings) {
  ACTION_SETTING = Object.assign({}, settings || {});
  const parsedParameterIndex = Number(ACTION_SETTING.parameterIndex || 0);
  const savedParameterIndex = Number.isFinite(parsedParameterIndex) && parsedParameterIndex >= 0
    ? Math.floor(parsedParameterIndex)
    : 0;
  const savedCommand = ACTION_SETTING.command || 'split';
  document.getElementById('command').value = shortcutAliases[savedCommand] || savedCommand;
  renderShortcutPreview();
  document.getElementById('require-active').checked = ACTION_SETTING.requireActive !== false;
  document.getElementById('sensitivity').value = String(ACTION_SETTING.sensitivity || 1);
  document.getElementById('hsl-color').value = ACTION_SETTING.hslColor || 'red';
  document.getElementById('color-wheel-dial-mode').value = validColorWheelModes.has(ACTION_SETTING.dialMode)
    ? ACTION_SETTING.dialMode
    : 'diameter';
  document.getElementById('color-wheel-hold-dial-mode').value = validColorWheelModes.has(ACTION_SETTING.holdDialMode)
    ? ACTION_SETTING.holdDialMode
    : 'orbit';
  fillTimelineModeSelect(ACTION_SETTING.timelineMode || 'frame_step');
  renderParameterSubset();
  const parameter = document.getElementById('parameter');
  if (parameter.options.length) {
    const index = savedParameterIndex % parameter.options.length;
    parameter.selectedIndex = index;
    ACTION_SETTING.parameterIndex = index;
  }
  renderCalibration();
}

function collect() {
  if (actionKind === 'timeline_control') {
    return {
      timelineMode: document.getElementById('timeline-mode').value || 'frame_step'
    };
  }

  const settings = Object.assign({}, ACTION_SETTING, {
    requireActive: document.getElementById('require-active').checked,
    command: document.getElementById('command').value,
    sensitivity: Number(document.getElementById('sensitivity').value || 1),
    dialMode: validColorWheelModes.has(document.getElementById('color-wheel-dial-mode').value)
      ? document.getElementById('color-wheel-dial-mode').value
      : 'diameter',
    holdDialMode: validColorWheelModes.has(document.getElementById('color-wheel-hold-dial-mode').value)
      ? document.getElementById('color-wheel-hold-dial-mode').value
      : 'orbit',
    hslColor: document.getElementById('hsl-color').value,
    parameterIndex: Math.max(0, document.getElementById('parameter').selectedIndex),
    enabledParameters: enabledParameterKeys(),
    calibrations: Object.assign({}, ACTION_SETTING.calibrations || {})
  });
  if (actionKind === 'color_wheels' && isWindows) {
    delete settings.wheelMotion;
  }

  const x = document.getElementById('target-x').value;
  const y = document.getElementById('target-y').value;
  if (x !== '' && y !== '' && !actionKind.startsWith('timeline_') && actionKind !== 'shortcut') {
    settings.calibrations[calibrationKey()] = {
      x: Number(x), y: Number(y),
      pixelsPerStep: Number(document.getElementById('pixels-per-step').value || 2),
      wheelRadius: Number(document.getElementById('wheel-radius').value || 45),
      axis: document.getElementById('axis').value
    };
  }
  const panelX = document.getElementById('panel-x').value;
  const panelY = document.getElementById('panel-y').value;
  if (panelX !== '' && panelY !== '' && !actionKind.startsWith('timeline_') && actionKind !== 'shortcut') {
    settings.panelTarget = {
      x: Number(panelX),
      y: Number(panelY),
      delay: Number(document.getElementById('panel-delay').value || 0.12)
    };
  }
  return settings;
}

function scheduleSave() {
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => {
    ACTION_SETTING = collect();
    $UD.setSettings(ACTION_SETTING);
  }, 120);
}

function startPointerCapture(captureTarget = 'parameter') {
  const button = document.getElementById(
    captureTarget === 'panel' ? 'capture-panel' : 'capture-pointer'
  );
  const hint = document.getElementById('capture-hint');
  button.disabled = true;
  let remaining = 3;
  hint.textContent = tr('Capture countdown move', {seconds: remaining});
  window.clearInterval(captureTimer);
  captureTimer = window.setInterval(() => {
    remaining -= 1;
    hint.textContent = remaining > 0
      ? tr('Capture countdown hold', {seconds: remaining})
      : tr('Reading pointer position');
    if (remaining <= 0) window.clearInterval(captureTimer);
  }, 1000);
  $UD.sendToPlugin({type: 'capturePointer', delay: 3, captureTarget});
}

function clearCalibration() {
  const calibrations = Object.assign({}, ACTION_SETTING.calibrations || {});
  delete calibrations[calibrationKey()];
  ACTION_SETTING.calibrations = calibrations;
  renderCalibration();
  $UD.setSettings(collect());
  document.getElementById('capture-hint').textContent = tr('Parameter calibration cleared');
}

function clearPanelTarget() {
  delete ACTION_SETTING.panelTarget;
  document.getElementById('panel-x').value = '';
  document.getElementById('panel-y').value = '';
  $UD.setSettings(collect());
  document.getElementById('capture-hint').textContent = tr('Panel linkage cleared');
}

function receiveSettings(message) {
  const contextChanged = syncInspectorIdentity(message || {});
  const settings = message && (message.settings || message.param);
  if (settings) render(settings);
  if (actionKind === 'shortcut' && (contextChanged || detectedShortcutCatalog === null)) {
    requestGlobalShortcutCatalog();
    requestShortcutCatalog();
  }
}

$UD.onDidReceiveGlobalSettings(receiveGlobalSettings);
$UD.onConnected(() => {
  actionKind = identifyAction();
  configureForm();
  render({});
  document.getElementById('wrapper').classList.remove('hidden');
  setJianyingConnectionStatus('Checking Jianying Pro', 'info');
  startConnectionStatusPolling();
  document.getElementById('property-inspector').addEventListener('input', scheduleSave);
  document.getElementById('command').addEventListener('change', () => {
    renderShortcutPreview();
    scheduleSave();
  });
  document.getElementById('timeline-mode').addEventListener('change', event => {
    ACTION_SETTING.timelineMode = event.currentTarget.value || 'frame_step';
    scheduleSave();
  });
  document.getElementById('refresh-shortcuts').addEventListener('click', event => {
    event.currentTarget.disabled = true;
    requestShortcutCatalog(true);
  });
  document.getElementById('parameter').addEventListener('change', () => {
    ACTION_SETTING.parameterIndex = document.getElementById('parameter').selectedIndex;
    renderCalibration();
    scheduleSave();
  });
  document.getElementById('parameter-subset').addEventListener('change', event => {
    const previousKey = document.getElementById('parameter').value;
    if (!enabledParameterKeys().length && event.target instanceof HTMLInputElement) {
      event.target.checked = true;
    }
    ACTION_SETTING.enabledParameters = enabledParameterKeys();
    fillParameterFromSubset(previousKey);
    ACTION_SETTING.parameterIndex = Math.max(0, document.getElementById('parameter').selectedIndex);
    renderCalibration();
    scheduleSave();
  });
  document.getElementById('hsl-color').addEventListener('change', () => {
    renderCalibration();
    scheduleSave();
  });
  document.getElementById('capture-pointer').addEventListener('click', () => startPointerCapture('parameter'));
  document.getElementById('capture-panel').addEventListener('click', () => startPointerCapture('panel'));
  document.getElementById('clear-calibration').addEventListener('click', clearCalibration);
  document.getElementById('clear-panel').addEventListener('click', clearPanelTarget);
  $UD.getSettings();
  if (actionKind === 'shortcut') {
    requestGlobalShortcutCatalog();
    relocalizeShortcutPreview();
  }
  else if (!actionKind.startsWith('timeline_')) {
    $UD.sendToPlugin({type: 'requestStatus'});
    if ((actionKind === 'selected_slider' || actionKind === 'color_wheels') && supportsSmartHover) {
      window.clearInterval(statusPollTimer);
      statusPollTimer = window.setInterval(() => {
        $UD.sendToPlugin({type: 'requestStatus'});
      }, 1000);
    }
  }
});

$UD.onClose(() => {
  stopConnectionStatusPolling();
  setJianyingConnectionStatus(
    'Plugin connection lost. Jianying status cannot be checked.',
    'error'
  );
});

$UD.onError(() => {
  stopConnectionStatusPolling();
  setJianyingConnectionStatus(
    'Plugin connection lost. Jianying status cannot be checked.',
    'error'
  );
});

$UD.onAdd(receiveSettings);
$UD.onParamFromApp(receiveSettings);
$UD.onDidReceiveSettings(receiveSettings);
$UD.onSendToPropertyInspector(message => {
  const payload = message && message.payload;
  if (!payload) return;
  if (payload.type === 'jianyingStatus') {
    setJianyingConnectionStatus(
      payload.running
        ? 'Jianying Pro detected.'
        : 'Jianying Pro not detected. Open Jianying Pro, then this plugin will reconnect automatically.',
      payload.running ? 'success' : 'warn'
    );
    return;
  }
  if (payload.type === 'pointerCaptureStarted') return;
  if (payload.type === 'pointerPosition') {
    const captureTarget = payload.captureTarget || 'parameter';
    const button = document.getElementById(
      captureTarget === 'panel' ? 'capture-panel' : 'capture-pointer'
    );
    const hint = document.getElementById('capture-hint');
    button.disabled = false;
    window.clearInterval(captureTimer);
    if (payload.position) {
      if (captureTarget === 'panel') {
        document.getElementById('panel-x').value = payload.position.x;
        document.getElementById('panel-y').value = payload.position.y;
      } else {
        document.getElementById('target-x').value = payload.position.x;
        document.getElementById('target-y').value = payload.position.y;
      }
      hint.textContent = tr('Position saved', {x: payload.position.x, y: payload.position.y});
      scheduleSave();
    } else {
      hint.textContent = payload.error || tr('Pointer read failed');
    }
    return;
  }
  if (payload.type !== 'status') return;
  const status = document.getElementById('status');
  const permissionOk = payload.automationPermission !== false;
  const captureOk = payload.screenCapturePermission !== false;
  const smartSlider = actionKind === 'selected_slider' && supportsSmartHover;
  const smartColorWheel = actionKind === 'color_wheels' && supportsSmartHover;
  const smartAdjustment = smartSlider || smartColorWheel;
  if (smartAdjustment) {
    status.style.display = 'none';
    return;
  }
  const hoverStatus = String(
    (smartColorWheel
      ? payload.colorWheelHoverStatus
      : smartSlider
        ? (payload.basicHoverStatus || payload.hslHoverStatus)
        : payload.basicHoverStatus) || ''
  );
  const smartWarning = smartAdjustment && (
    !permissionOk || !captureOk || !payload.targetActive ||
    ['native_helper_unavailable', 'screen_capture_unavailable', 'vision_recognition_failed'].includes(hoverStatus)
  );
  status.style.display = '';
  status.classList.toggle('warn', smartWarning || !payload.targetActive || !permissionOk);
  status.textContent = !permissionOk
    ? tr('Missing automation permission')
    : !captureOk
      ? tr('Missing screen capture permission')
      : payload.targetActive
        ? hoverStatus === 'native_helper_unavailable'
          ? tr(smartColorWheel
            ? 'Color wheel recognition unavailable'
            : 'Basic recognition unavailable')
          : tr('Jianying is frontmost')
        : tr('Switch to Jianying', {target: payload.targetBundleId || 'com.lemon.lvpro'});
  if (payload.targetVersion) status.textContent += ` ${tr('Current version', {version: payload.targetVersion})}`;
  if (payload.automationReason && !smartAdjustment) {
    status.textContent += ` ${tr('Recent status', {status: payload.automationReason})}`;
  }
});

// Register every callback before opening the local WebSocket. A fast local
// connection can otherwise emit onConnected before the PI is ready.
$UD.connect();
