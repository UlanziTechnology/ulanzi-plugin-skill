// These are expected hand-offs to the user, not failed editing operations.
export function isZoomInterruption(error) {
  return ['ZOOM_USER_INPUT_ACTIVE', 'PREMIERE_NOT_FOREGROUND', 'ACTION_CANCELLED', 'STALE_ACTION'].includes(error?.code);
}

export const ZOOM_LOCATION_GRACE_MS = 900;
export const ZOOM_FAILURE_GAP_MS = 1500;

export function zoomNeedsUserAction(error) {
  return ['ZOOM_HELPER_UNAVAILABLE', 'ZOOM_OCR_UNAVAILABLE', 'ZOOM_ACCESS_REQUIRED', 'ZOOM_UNSUPPORTED', 'FOREGROUND_UNAVAILABLE'].includes(error?.code);
}
