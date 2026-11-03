import { randomBytes } from 'node:crypto';
import { ACTIONS, PARAMETERS, DIRECT_EXPORT_TIMEOUT_MS, actionName, settingsFor } from '../shared/config.js';
import { PresetCache, presetCacheKey } from '../shared/preset-cache.js';
import { ActionQueue } from './services/ActionQueue.js';
import { failure, publicError } from './services/errors.js';
import { discoverPresets, resolvePremierePresets, applyFavoritePresets, validatePreset, chooseOutputPath, safeFileName } from './services/presets.js';
import { ensureMediaEncoderAvailable } from './services/mediaEncoder.js';
import { isZoomInterruption, zoomNeedsUserAction, ZOOM_LOCATION_GRACE_MS, ZOOM_FAILURE_GAP_MS } from './services/zoomFeedback.js';

export class PluginController {
  constructor(api, bridge, { platform = process.platform, wheelSupported = true, wheelZoom = null, connectionStatus = bridge, mediaEncoderAvailability = ensureMediaEncoderAvailable, presetDiscovery = discoverPresets, presetFavorites = applyFavoritePresets, queue = new ActionQueue(), now = Date.now } = {}) {
    Object.assign(this, { api, bridge, platform, wheelSupported, wheelZoom, connectionStatus, mediaEncoderAvailability, presetDiscovery, presetFavorites, queue, now });
    this.zoomErrors = new Set();
    this.zoomFailures = new Map();
    this.dialPresses = new Map();
    this.instances = new Map(); this.groups = new Map(); this.dirtyGroups = new Set();
    this.activePI = null; this.reservations = new Set(); this.exportBusy = new Set();
    this.lastExport = new Map(); this.revision = 0; this.presetRequest = 0; this.globalLoaded = false; this.safetyStop = false;
    this.directExportRunning = false;
    this.presetCache = new PresetCache({ now });
  }
  t(value) { return this.api.t?.(value) || value; }
  bind() {
    this.api.onAdd(m => this.ensure(m, true));
    this.api.onDidReceiveSettings(m => this.ensure(m, true));
    this.api.onParamFromApp(m => {
      const instance = this.ensure(m, true);
      if (!instance) return;
      this.activePI = m.context; this.sendPI({ type: 'bridgeStatus', ...this.connectionStatus.status });
    });
    this.api.onDidReceiveGlobalSettings(m => {
      const groups = m.settings?.groups;
      if (groups && typeof groups === 'object') for (const [group, parameter] of Object.entries(groups).slice(0, 1000)) {
        if (PARAMETERS[parameter] && !this.dirtyGroups.has(group)) this.groups.set(group, parameter);
      }
      const firstLoad = !this.globalLoaded;
      this.globalLoaded = true;
      if (firstLoad && this.dirtyGroups.size) this.persistGroups();
      this.renderAll();
    });
    this.api.onRun(m => this.onRun(m));
    this.api.onDialDown(m => this.onPress(m));
    this.api.onDialUp(m => this.onRelease(m));
    // The protocol emits one dialrotate with rotateEvent. Do not subscribe to
    // directional aliases too, or the same detent would execute twice.
    this.api.onDialRotate(m => this.onRotate(m));
    this.api.onSetActive?.(m => { if (m.active) { const instance = this.ensure(m); if (instance) this.render(instance); } });
    this.api.onSendToPlugin(m => { void this.onPI(m); });
    this.api.onClear(m => {
      for (const item of Array.isArray(m.param) ? m.param : []) {
        this.instances.delete(item.context); this.queue.cancelContext(item.context); this.zoomErrors.delete(item.context); this.zoomFailures.delete(item.context);
        this.wheelZoom?.cancelContext(item.context);
        this.lastExport.delete(item.context);
        this.dialPresses.delete(item.context);
        if (this.activePI === item.context) this.activePI = null;
      }
    });
    this.bridge.on('status', status => {
      if (!status.connected) { this.dialPresses.clear(); this.queue.clear(failure(status.code || 'BRIDGE_DISCONNECTED')); }
      else this.safetyStop = false; // A fresh CEP connection is explicit recovery after a partial mutation.
    });
    this.connectionStatus.on('status', status => this.sendPI({ type: 'bridgeStatus', ...status }));
    return this;
  }
  connected() { this.api.getGlobalSettings(); this.renderAll(); }
  persistGroups() { if (this.globalLoaded) this.api.setGlobalSettings({ version: 1, groups: Object.fromEntries(this.groups) }); }
  ensure(message, replace = false) {
    const action = actionName(message.uuid);
    if (!action || !message.context) return null;
    let instance = this.instances.get(message.context);
    if (!instance) {
      instance = { context: message.context, action, generation: 0, settings: settingsFor(action, message.settings ?? message.param) };
      this.instances.set(message.context, instance); this.render(instance);
    } else if (replace && (message.settings !== undefined || message.param !== undefined)) {
      instance.settings = settingsFor(action, message.settings ?? message.param);
      instance.generation++;
      this.zoomFailures.delete(instance.context);
      this.dialPresses.delete(instance.context);
      this.queue.cancelContext(instance.context); this.render(instance);
      this.wheelZoom?.cancelContext(instance.context);
    }
    return instance;
  }
  parameter(instance) {
    return instance.settings.source === 'fixed' ? instance.settings.parameter : this.groups.get(instance.settings.groupId) || 'exposure';
  }
  select(groupId, parameter) {
    this.queue.barrier(); this.groups.set(groupId, parameter); this.dirtyGroups.add(groupId);
    this.persistGroups();
    this.renderAll(); this.bridge.notifyStatus?.(parameter, this.t(PARAMETERS[parameter].name));
  }
  save(instance) { this.api.setSettings({ ...instance.settings }, instance.context); this.render(instance); }
  renderAll() { for (const instance of this.instances.values()) this.render(instance); }
  render(instance, result) {
    const { context, action, settings } = instance;
    let title, iconPath;
    if (action === 'parameterSelect') {
      const active = (this.groups.get(settings.groupId) || 'exposure') === settings.parameter;
      title = `${active ? '● ' : ''}${this.t(PARAMETERS[settings.parameter].name)}`;
      this.api.setPathIcon(context, `./assets/states/parameterSelect${active ? '-active' : ''}-${settings.parameter}.svg`, title);
    } else if (action === 'parameterDial') {
      const parameter = this.parameter(instance);
      title = this.t(PARAMETERS[parameter].name);
      // Keep the device label to the parameter name; numeric feedback is hidden.
      iconPath = `./assets/states/parameterSelect-${parameter}.svg`;
      this.api.setPathIcon(context, iconPath, title);
    } else if (action === 'trimControl') title = this.t({ rippleIn: 'Ripple In', rippleOut: 'Ripple Out', rollingNext: 'Rolling next edit' }[settings.mode]);
    else if (action === 'timelineJog') title = this.t('Timeline Jog');
    else if (action === 'timelineZoom') title = this.t('Timeline Zoom');
    else title = this.t('Queue Export');
    if (action !== 'parameterSelect') {
      this.api.setTitle(context, title);
      if (!['queueExport'].includes(action)) this.api.setFeedback(context, { title: { text: title }, ...(iconPath ? { icon: { value: iconPath } } : {}) });
    }
  }
  sendPI(payload, context = this.activePI) {
    if (context && context === this.activePI && this.instances.has(context)) this.api.sendToPropertyInspector(payload, context);
  }
  isCurrent(instance, generation = instance.generation) { return this.instances.get(instance.context) === instance && instance.generation === generation; }
  assertCurrent(instance, generation) { if (!this.isCurrent(instance, generation)) throw failure('ACTION_CANCELLED'); }
  zoomInterrupted(instance, generation = instance.generation) {
    if (!this.isCurrent(instance, generation)) return;
    this.zoomFailures.delete(instance.context);
    if (this.zoomErrors.delete(instance.context)) this.sendPI({ type: 'zoomPaused' }, instance.context);
  }
  failed(instance, error, generation = instance.generation) {
    if (instance.action === 'timelineZoom') {
      if (!this.isCurrent(instance, generation)) return;
      if (isZoomInterruption(error)) { this.zoomInterrupted(instance, generation); return; }
      const now = this.now();
      let state = this.zoomFailures.get(instance.context);
      const locationFailure = error.code === 'ZOOM_TIMELINE_UNAVAILABLE';
      // Allow brief layout/recognition transitions. Once shown, the same error
      // stays in the inspector without raising a toast on every dial turn.
      if (!state || state.code !== error.code || (!state.shown && now - state.lastAt > ZOOM_FAILURE_GAP_MS)) {
        state = { code: error.code, since: now, lastAt: now, attempts: 0, shown: false };
        this.zoomFailures.set(instance.context, state);
      }
      state.lastAt = now; state.attempts++;
      if (locationFailure && (state.attempts < 3 || now - state.since < ZOOM_LOCATION_GRACE_MS)) return;
      if (state.shown) return;
      state.shown = true;
      this.zoomErrors.add(instance.context);
      if (zoomNeedsUserAction(error)) {
        this.api.showAlert(instance.context);
        this.api.toast(this.t(`error.${error.code}`));
      }
      this.sendPI({ type: 'actionResult', ok: false, error: publicError(error) }, instance.context);
      return;
    }
    if (['PARTIAL_MUTATION', 'RESULT_UNKNOWN', 'REQUEST_TIMEOUT', 'EXPORT_QUEUE_REJECTED'].includes(error.code) && !this.safetyStop) {
      this.safetyStop = true; this.queue.clear(failure('SAFETY_STOP_RECONNECT'));
      this.sendPI({ type: 'actionResult', ok: false, error: publicError(error) });
      this.bridge.requireRecovery?.(error.code, error.message);
    }
    if (!this.isCurrent(instance, generation)) return;
    this.api.showAlert(instance.context);
    const errorKey = `error.${error.code || 'ACTION_FAILED'}`;
    const message = this.t(errorKey);
    this.api.toast(message === errorKey ? this.t('Action failed') : message);
    this.sendPI({ type: 'actionResult', ok: false, error: publicError(error) }, instance.context);
  }
  succeeded(instance, result, generation = instance.generation) {
    if (!this.isCurrent(instance, generation)) return;
    if (instance.action === 'timelineZoom') {
      this.zoomFailures.delete(instance.context);
      // Avoid repainting the dial and sending a PI result for every detent.
      if (this.zoomErrors.delete(instance.context)) this.sendPI({ type: 'actionResult', ok: true, result }, instance.context);
      return;
    }
    this.render(instance, result);
    this.sendPI({ type: 'actionResult', ok: true, result }, instance.context);
    if (instance.action === 'parameterDial' && result?.parameter === this.parameter(instance)) this.bridge.notifyStatus?.(result.parameter, this.t(PARAMETERS[result.parameter]?.name || result.parameter), result.value);
  }
  onRun(message) {
    const instance = this.ensure(message); if (!instance) return;
    if (instance.action === 'parameterSelect') this.select(instance.settings.groupId, instance.settings.parameter);
    else if (instance.action === 'queueExport') void this.exportSequence(instance);
    // Encoder gestures use dialdown/dialup, never the keypad run alias.
  }
  onPress(message) {
    const instance = this.ensure(message); if (!instance) return;
    this.queue.barrier();
    if (instance.action === 'trimControl') {
      const steps = [1, 5, 10]; instance.settings.step = steps[(steps.indexOf(instance.settings.step) + 1) % steps.length]; this.save(instance);
    } else if (instance.action === 'parameterDial') {
      // Wait for release so pressing to begin a held turn never resets a value.
      if (!this.dialPresses.has(instance.context)) this.dialPresses.set(instance.context, {
        instance, generation: instance.generation, settings: settingsFor(instance.action, instance.settings),
        parameter: this.parameter(instance), rotated: false,
      });
    }
  }
  onRelease(message) {
    const press = this.dialPresses.get(message.context);
    this.dialPresses.delete(message.context);
    if (!press || press.rotated || !this.isCurrent(press.instance, press.generation) || this.parameter(press.instance) !== press.parameter) return;
    const { instance, generation, settings, parameter } = press;
    if (this.directExportRunning) { this.failed(instance, failure('EXPORT_BUSY')); return; }
    this.queue.barrier();
    this.queue.enqueue({ key: `${instance.context}|reset|${++this.revision}`, delta: 0,
      execute: () => {
        this.assertCurrent(instance, generation);
        if (this.safetyStop) throw failure('SAFETY_STOP_RECONNECT');
        if (!this.bridge.connected) throw failure('BRIDGE_DISCONNECTED');
        return this.bridge.request('parameterDial', settings, { parameter, reset: true });
      },
      onSuccess: result => this.succeeded(instance, result, generation), onError: error => this.failed(instance, error, generation),
    });
  }
  onRotate(message) {
    const instance = this.ensure(message); if (!instance) return;
    if (this.directExportRunning) { this.failed(instance, failure('EXPORT_BUSY')); return; }
    const direction = message.rotateEvent;
    if (!['left', 'right', 'hold-left', 'hold-right'].includes(direction)) return;
    if (!['timelineJog', 'trimControl', 'timelineZoom', 'parameterDial'].includes(instance.action)) return;
    if (instance.action === 'parameterDial' && direction.startsWith('hold-')) {
      const press = this.dialPresses.get(instance.context);
      if (press) press.rotated = true;
      this.queue.barrier();
      const order = instance.settings.cycle, index = order.indexOf(this.parameter(instance));
      const next = index < 0 ? (direction === 'hold-left' ? order.length - 1 : 0)
        : (index + (direction === 'hold-left' ? -1 : 1) + order.length) % order.length;
      const parameter = order[next];
      if (instance.settings.source === 'group') this.select(instance.settings.groupId, parameter);
      else { instance.settings.parameter = parameter; this.save(instance); this.bridge.notifyStatus?.(parameter, this.t(PARAMETERS[parameter].name)); }
      return;
    }
    if (instance.action !== 'timelineZoom' && this.safetyStop) { this.failed(instance, failure('SAFETY_STOP_RECONNECT')); return; }
    if (instance.action !== 'timelineZoom' && !this.bridge.connected) { this.failed(instance, failure('BRIDGE_DISCONNECTED')); return; }
    const settings = settingsFor(instance.action, instance.settings);
    const generation = instance.generation;
    const parameter = instance.action === 'parameterDial' ? this.parameter(instance) : undefined;
    let delta = direction.endsWith('left') ? -1 : 1;
    if (instance.action === 'timelineZoom') {
      if (!['darwin', 'win32'].includes(this.platform) || !this.wheelSupported) { this.failed(instance, failure('ZOOM_UNSUPPORTED')); return; }
      if (!this.wheelZoom) { this.failed(instance, failure('ZOOM_HELPER_UNAVAILABLE')); return; }
      const key = `${instance.context}|${JSON.stringify(settings)}|${generation}`;
      this.wheelZoom.enqueue({ key, context: instance.context, delta, anchor: 'auto',
        beforeSend: () => this.assertCurrent(instance, generation),
        onSuccess: result => this.succeeded(instance, result, generation),
        onError: error => this.failed(instance, error, generation),
        onInterrupted: () => this.zoomInterrupted(instance, generation),
      });
      return;
    }
    if (instance.action === 'parameterDial') delta *= PARAMETERS[parameter].step * settings.stepMultiplier;
    else delta *= instance.action === 'timelineJog' && direction.startsWith('hold-') ? settings.heldStep : settings.step;
    const key = `${instance.context}|${JSON.stringify(settings)}|${parameter || ''}|${this.revision}`;
    this.queue.enqueue({ key, delta, coalesceLimit: 10000,
      execute: amount => {
        this.assertCurrent(instance, generation);
        if (this.safetyStop) throw failure('SAFETY_STOP_RECONNECT');
        return this.executeRotation(instance.action, settings, parameter, amount);
      },
      onSuccess: result => this.succeeded(instance, result, generation), onError: error => this.failed(instance, error, generation),
    });
  }
  async executeRotation(action, settings, parameter, delta) {
    const payload = action === 'parameterDial' ? { parameter, delta } : { deltaFrames: delta };
    return this.bridge.request(action, settings, payload);
  }
  async exportSequence(instance) {
    if (this.safetyStop) { this.failed(instance, failure('SAFETY_STOP_RECONNECT')); return; }
    const now = Date.now();
    if (this.exportBusy.size || now - (this.lastExport.get(instance.context) || 0) < 1500) { this.failed(instance, failure('EXPORT_BUSY')); return; }
    this.exportBusy.add(instance.context); this.lastExport.set(instance.context, now);
    const settings = settingsFor('queueExport', instance.settings);
    const direct = settings.exportTarget === 'premiere';
    const generation = instance.generation;
    try {
      if (!this.bridge.connected) throw failure('BRIDGE_DISCONNECTED');
      await validatePreset(settings.presetPath);
      this.assertCurrent(instance, generation);
      if (!direct) await this.mediaEncoderAvailability();
      this.assertCurrent(instance, generation);
      const info = await this.bridge.request('exportInfo', settings);
      // Unique suffix protects pending AME jobs too (their output file may not
      // exist yet), including after a plugin restart.
      const suffix = `${new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 17)}_${randomBytes(3).toString('hex')}`;
      if (settings.fileName && safeFileName(settings.fileName) !== settings.fileName) throw failure('INVALID_OUTPUT_NAME');
      const base = (settings.fileName || safeFileName(info.sequenceName)).replace(new RegExp(`\\.${String(info.extension).replace(/^\./, '')}$`, 'i'), '').slice(0, 119 - suffix.length);
      const outputPath = await chooseOutputPath(settings.outputDirectory, `${base}_${suffix}`, info.sequenceName, info.extension, this.reservations);
      this.assertCurrent(instance, generation);
      if (this.safetyStop) throw failure('SAFETY_STOP_RECONNECT');
      if (direct) {
        this.directExportRunning = true;
        this.queue.clear(failure('EXPORT_BUSY')); this.wheelZoom?.clear(); this.dialPresses.clear();
      }
      const result = await this.bridge.request(direct ? 'directExport' : 'queueExport', { ...settings, outputPath, expectedSequenceId: info.sequenceId }, {}, { timeoutMs: direct ? DIRECT_EXPORT_TIMEOUT_MS : 30000 });
      this.succeeded(instance, { ...result, outputPath }, generation);
    } catch (error) { this.failed(instance, error, generation); }
    finally { this.directExportRunning = false; this.exportBusy.delete(instance.context); }
  }
  async onPI(message) {
    const instance = this.ensure(message); if (!instance || message.context !== this.activePI) return;
    const payload = message.payload;
    if (!payload || typeof payload !== 'object') return;
    try {
      if (payload.type === 'refreshPresets' && instance.action === 'queueExport') {
        const request = ++this.presetRequest;
        const custom = instance.settings.presetScope === 'custom';
        const directory = custom ? instance.settings.presetDirectory : '';
        const connected = Boolean(this.bridge.connected);
        const cacheKey = presetCacheKey(instance.settings.presetScope, directory, connected);
        const current = () => request === this.presetRequest && this.instances.get(instance.context) === instance && this.activePI === instance.context
          && custom === (instance.settings.presetScope === 'custom') && directory === (custom ? instance.settings.presetDirectory : '')
          && (custom || connected === Boolean(this.bridge.connected));
        const respond = (entry) => this.sendPI({ type: 'presets', ...entry.value, cacheExpiresAt: entry.expiresAt, requestId: payload.requestId }, instance.context);
        if (payload.force === true) this.presetCache.delete(cacheKey);
        const cached = this.presetCache.get(cacheKey);
        if (cached) { respond(cached); return; }
        const result = custom
          ? (directory ? await this.presetDiscovery(directory, []) : { presets: [], warnings: ['PRESET_DIRECTORY_REQUIRED'] })
          : await this.presetDiscovery('');
        if (!current()) return;
        if (custom) {
          respond(this.presetCache.set(cacheKey, { ...result, favoriteCount: 0 }));
          return;
        }
        // On macOS, host preset enumeration can time out and lock the bridge,
        // including immediately after reconnect when the inspector refreshes.
        // Read installed .epr files and saved favorites without a host RPC.
        if (connected && this.platform !== 'darwin') {
          try {
            const hostPresets = [];
            let offset = 0, supported = false;
            do {
              const page = await this.bridge.request('exportPresets', {}, { offset });
              if (!current()) return;
              if (!page.supported || !Array.isArray(page.presets)) break;
              supported = true; hostPresets.push(...page.presets);
              const next = page.nextOffset;
              if (next === null) break;
              if (!Number.isInteger(next) || next <= offset || next >= 2000) { result.warnings.push('PRESET_SCAN_LIMIT'); break; }
              offset = next;
            } while (true);
            if (supported && hostPresets.length) {
              const resolved = await resolvePremierePresets(result.presets, hostPresets);
              if (resolved.presets.length) {
                result.presets = resolved.presets;
                if (resolved.unresolved) result.warnings.push('PRESET_PATH_UNRESOLVED');
              } else result.warnings.push('PRESET_PATH_UNRESOLVED');
            }
          } catch { result.warnings.push('PRESET_HOST_UNAVAILABLE'); }
        }
        if (!current()) return;
        const favorites = await this.presetFavorites(result.presets);
        if (current()) respond(this.presetCache.set(cacheKey, { ...result, presets: favorites.presets, favoriteCount: favorites.favoriteCount, warnings: [...new Set([...result.warnings, ...favorites.warnings])] }));
      } else if (payload.type === 'diagnostics') {
        this.sendPI({ type: 'bridgeStatus', ...this.connectionStatus.status }, instance.context);
        const result = await this.bridge.request('capabilities');
        this.sendPI({ type: 'actionResult', ok: true, result }, instance.context);
      }
    } catch (error) { this.failed(instance, error); }
  }
  close() { this.queue.close(); this.wheelZoom?.close(); this.zoomErrors.clear(); this.zoomFailures.clear(); this.dialPresses.clear(); this.instances.clear(); this.presetCache.clear(); }
}
