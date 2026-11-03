export const BRIDGE_PORT = 39731;
export const BRIDGE_PROTOCOL = "ulanzi-aftereffects-v1";
export const BRIDGE_TOKEN = "ulanzi-aftereffects-local-bridge-v1";
export const MAX_MESSAGE_BYTES = 1024 * 1024;
export const REQUEST_TIMEOUT_MS = 5000;

export function failure(errorCode, messageKey, data = {}) {
  return { ok: false, errorCode, messageKey, data };
}
