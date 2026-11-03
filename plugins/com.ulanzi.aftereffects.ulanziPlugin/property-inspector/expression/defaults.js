const PI_EXPRESSION_DEFAULTS = {
  wiggle: 'wiggle(effect("{{FREQUENCY_CONTROLLER}}")(1), effect("{{AMPLITUDE_CONTROLLER}}")(1))',
  loop: 'loopOut("{{LOOP_TYPE}}")',
  countdownNumber: [
    'var decimals = Math.min(20, Math.max(0, Math.floor(effect("{{COUNTDOWN_DECIMALS_CONTROLLER}}")(1).value)));',
    'effect("{{COUNTDOWN_VALUE_CONTROLLER}}")(1).value.toFixed(decimals);'
  ].join("\n"),
  stutter: 'var frequency = Math.max(effect("{{FREQUENCY_CONTROLLER}}")(1), 0.001);\nvalueAtTime(Math.round(time * frequency) / frequency)',
  custom: ""
};

function piExpressionDefault(type, loopType) {
  const base = Object.prototype.hasOwnProperty.call(PI_EXPRESSION_DEFAULTS, type)
    ? PI_EXPRESSION_DEFAULTS[type]
    : PI_EXPRESSION_DEFAULTS.wiggle;
  return base
    .replace(/\{\{LOOP_TYPE\}\}/g, loopType || "cycle");
}
