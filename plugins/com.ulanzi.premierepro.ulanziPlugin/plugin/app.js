import UlanziApi from '../libs/node/index.js';
import os from 'node:os';
import { PLUGIN_UUID } from '../shared/config.js';
import { PremiereBridge } from './bridge/PremiereBridge.js';
import { PluginController } from './PluginController.js';
import { PremiereConnectionMonitor } from './services/PremiereConnectionMonitor.js';
import { createZoomDiagnostic } from './services/zoomDiagnostics.js';
import { MacTimelineZoom } from './services/MacTimelineZoom.js';
import { WindowsTimelineZoom } from './services/WindowsTimelineZoom.js';
import { initializeCep, configureCepDebugMode } from './services/cepInitialization.js';

const api = new UlanziApi();
let cepInstallError = null;
try {
  const installation = await initializeCep({ home: process.env.ULZI_PR_CEP_HOME });
  if (installation.changed || installation.debugMode.changed) console.info('[Premiere CEP] Initialized bundled extension and unsigned extension loading. Save and restart Premiere if it is already running.');
} catch (error) {
  cepInstallError = error.code || 'CEP_INSTALL_FAILED';
  console.error(`[Premiere CEP] ${cepInstallError}: ${error.cause?.message || error.message}`);
}
const bridge = new PremiereBridge({ pairingPath: process.env.ULZI_PR_PAIRING_PATH });
const connectionMonitor = new PremiereConnectionMonitor(bridge, {
  cepInstallError,
  recoverCepDebugMode: async () => {
    await configureCepDebugMode();
    console.info('[Premiere CEP] Debug preferences verified; cleared the startup setup error.');
  }
});
const zoomDiagnostic = createZoomDiagnostic({ directory: process.env.ULZI_PR_ZOOM_LOG_DIRECTORY });
const macWheelSupported = process.platform === 'darwin' && Number.parseInt(os.release(), 10) >= 22;
const windowsWheelSupported = process.platform === 'win32' && process.arch === 'x64' && Number(os.release().split('.')[2]) >= 19041;
const wheelSupported = macWheelSupported || windowsWheelSupported;
const wheelZoom = macWheelSupported ? new MacTimelineZoom({ diagnostic: zoomDiagnostic })
  : windowsWheelSupported ? new WindowsTimelineZoom({ diagnostic: zoomDiagnostic }) : null;
void wheelZoom?.start().catch(error => zoomDiagnostic({ event: 'wheel-helper-unavailable', code: error.code }));
const controller = new PluginController(api, bridge, { wheelSupported, wheelZoom, connectionStatus: connectionMonitor }).bind();
let stopping = false, reconnectTimer;
api.onConnected(async () => { await api.localizeUI(); controller.connected(); });
api.onError(() => { /* SDK reports connection detail; no modal error spam. */ });
api.onClose(() => {
  controller.queue.clear();
  wheelZoom?.clear();
  if (!stopping) reconnectTimer = setTimeout(() => api.connect(PLUGIN_UUID, api.port, api.address), 2000);
});
bridge.on('error', error => {
  controller.sendPI({ type: 'actionResult', ok: false, error: { code: error.code || 'BRIDGE_ERROR', message: error.message } });
});
async function shutdown() {
  if (stopping) return;
  stopping = true; clearTimeout(reconnectTimer); connectionMonitor.stop(); controller.close();
  api.websocket?.close(); await bridge.stop();
}
process.on('SIGINT', () => { void shutdown(); });
process.on('SIGTERM', () => { void shutdown(); });
await bridge.start().catch(error => {
  console.error(`[Premiere bridge] ${error.code || 'START_FAILED'}: ${error.message}`);
});
await connectionMonitor.start();
api.connect(PLUGIN_UUID);
