export function failure(code, message = code, details) {
  return Object.assign(new Error(message), { code, details });
}
export function publicError(error) {
  return { code: error?.code || 'ACTION_FAILED', message: error?.message || 'Action failed', ...(error?.details ? { details: error.details } : {}) };
}
