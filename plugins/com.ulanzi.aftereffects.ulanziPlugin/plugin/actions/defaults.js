export const EXPRESSION_TYPES = Object.freeze({
  WIGGLE: "wiggle",
  LOOP: "loop",
  COUNTDOWN_NUMBER: "countdownNumber",
  STUTTER: "stutter",
  CUSTOM: "custom"
});

export const LOOP_TYPES = Object.freeze({
  CYCLE: "cycle",
  PINGPONG: "pingpong",
  CONTINUE: "continue"
});

export const EXPRESSION_DEFAULTS = Object.freeze({
  wiggle: 'wiggle(effect("{{FREQUENCY_CONTROLLER}}")(1), effect("{{AMPLITUDE_CONTROLLER}}")(1))',
  loop: 'loopOut("{{LOOP_TYPE}}")',
  countdownNumber: [
    'var decimals = Math.min(20, Math.max(0, Math.floor(effect("{{COUNTDOWN_DECIMALS_CONTROLLER}}")(1).value)));',
    'effect("{{COUNTDOWN_VALUE_CONTROLLER}}")(1).value.toFixed(decimals);'
  ].join("\n"),
  stutter: 'var frequency = Math.max(effect("{{FREQUENCY_CONTROLLER}}")(1), 0.001);\nvalueAtTime(Math.round(time * frequency) / frequency)',
  custom: ""
});

export function expressionDefault(type, loopType = LOOP_TYPES.CYCLE) {
  const base = Object.prototype.hasOwnProperty.call(EXPRESSION_DEFAULTS, type)
    ? EXPRESSION_DEFAULTS[type]
    : EXPRESSION_DEFAULTS.wiggle;
  return base.replace(/\{\{LOOP_TYPE\}\}/g, loopType);
}

export function defaultsForAction(actionName) {
  if (actionName === "anchorGrid") return { anchorPoint: "center" };
  if (actionName === "expression") {
    return {
      expressionType: EXPRESSION_TYPES.WIGGLE,
      loopType: LOOP_TYPES.CYCLE,
      expressionText: expressionDefault(EXPRESSION_TYPES.WIGGLE)
    };
  }
  return {};
}

export function normalizeSettings(actionName, settings) {
  const defaults = defaultsForAction(actionName);
  const hasExpressionText = settings && typeof settings.expressionText === "string";
  const value = { ...defaults, ...(settings || {}) };
  if (actionName === "anchorGrid") {
    const valid = ["topLeft", "topCenter", "topRight", "middleLeft", "center", "middleRight", "bottomLeft", "bottomCenter", "bottomRight"];
    if (!valid.includes(value.anchorPoint)) value.anchorPoint = "center";
  }
  if (actionName === "expression") {
    const invalidExpressionType = !Object.values(EXPRESSION_TYPES).includes(value.expressionType);
    if (invalidExpressionType) {
      value.expressionType = EXPRESSION_TYPES.WIGGLE;
      value.expressionText = expressionDefault(value.expressionType, value.loopType);
    }
    if (!Object.values(LOOP_TYPES).includes(value.loopType)) value.loopType = LOOP_TYPES.CYCLE;
    if (value.expressionType === EXPRESSION_TYPES.CUSTOM && !hasExpressionText) {
      value.expressionText = "";
    } else if (value.expressionType !== EXPRESSION_TYPES.CUSTOM && (typeof value.expressionText !== "string" || !value.expressionText.trim())) {
      value.expressionText = expressionDefault(value.expressionType, value.loopType);
    }
  }
  return value;
}
