// Describe only what was observed: a running process does not prove the CEP extension loaded.
export function connectionNotice(state = {}, hostOffline = false) {
  if (hostOffline) return { key: 'Host disconnected', kind: 'warn' };
  if (state.cepInstallError === 'CEP_DEBUG_MODE_FAILED') return { key: 'CEP debug mode setup failed', kind: 'error' };
  if (state.cepInstallError) return { key: 'CEP installation failed', kind: 'error' };
  if (state.connected) return { key: 'Bridge connected', kind: 'success' };
  if (state.uncertain) return { key: 'Bridge recovery required', kind: 'error' };
  if (state.code === 'PORT_IN_USE') return { key: 'Bridge port occupied', kind: 'error' };
  if (['PAIRING_INVALID', 'PAIRING_FAILED', 'PROTOCOL_MISMATCH'].includes(state.code)) return { key: 'Bridge pairing failed', kind: 'error' };
  if (['STOPPED', 'BRIDGE_START_FAILED', 'BRIDGE_ERROR', 'EACCES', 'EPERM', 'ENOENT'].includes(state.code)) return { key: 'Bridge service unavailable', kind: 'error' };
  if (state.applicationState === 'notRunning') return { key: 'Premiere not running', kind: 'warn' };
  if (state.applicationState === 'running') return state.waitingForBridge
    ? { key: 'Bridge waiting', kind: 'info' }
    : { key: 'Bridge extension disconnected', kind: 'warn' };
  if (state.applicationState === 'unknown') return { key: 'Premiere status unknown', kind: 'warn' };
  if (!state.applicationState && state.code) return { key: 'Premiere status unknown', kind: 'warn' };
  return { key: 'Checking Premiere', kind: 'info' };
}
