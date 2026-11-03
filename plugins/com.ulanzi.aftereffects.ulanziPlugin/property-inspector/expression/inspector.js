const EXPRESSION_SETTINGS_DEFAULTS = {
  expressionType: "wiggle",
  loopType: "cycle",
  expressionText: piExpressionDefault("wiggle", "cycle")
};
const EXPRESSION_TYPES = ["wiggle", "loop", "stutter", "countdownNumber", "custom"];
const LOOP_TYPES = ["cycle", "pingpong", "continue"];
let expressionSettings = { ...EXPRESSION_SETTINGS_DEFAULTS };
let expressionForm;
let expressionType;
let loopType;
let expressionText;

$UD.connect();

$UD.onConnected(async () => {
  await $UD.localizeUI();
  UlanziPI.setLocalizationReady();
  expressionForm = document.querySelector("#property-inspector");
  expressionType = document.querySelector("#expression-type");
  loopType = document.querySelector("#loop-type");
  expressionText = document.querySelector("#expression-text");

  expressionType.addEventListener("change", () => resetExpressionForCurrentType(true));
  loopType.addEventListener("change", () => resetExpressionForCurrentType(true));
  expressionText.addEventListener("input", Utils.debounce(saveExpressionSettings));
  document.querySelector("#reset-button").addEventListener("click", () => resetExpressionForCurrentType(true));
  document.querySelector(".uspi-wrapper").classList.remove("hidden");
  renderExpressionSettings();
});

$UD.onParamFromApp((message) => {
  const settings = message.param || {};
  const migrated = replaceExpressionSettings(settings);
  const missingExpression = settings.expressionType === "custom"
    ? typeof settings.expressionText !== "string"
    : !settings.expressionText;
  if (migrated || !settings.expressionType || missingExpression) saveExpressionSettings();
});

$UD.onDidReceiveSettings((message) => {
  if (UlanziPI.isCurrentSettings(message) && message.settings) replaceExpressionSettings(message.settings);
});

$UD.onSendToPropertyInspector((message) => UlanziPI.showStatus(message.payload));

function replaceExpressionSettings(settings) {
  const hasExpressionText = settings && typeof settings.expressionText === "string";
  expressionSettings = { ...EXPRESSION_SETTINGS_DEFAULTS, ...(settings || {}) };
  let migrated = false;
  if (!EXPRESSION_TYPES.includes(expressionSettings.expressionType)) {
    expressionSettings.expressionType = "wiggle";
    expressionSettings.expressionText = piExpressionDefault("wiggle", expressionSettings.loopType);
    migrated = true;
  }
  if (!LOOP_TYPES.includes(expressionSettings.loopType)) {
    expressionSettings.loopType = "cycle";
    if (expressionSettings.expressionType === "loop") {
      expressionSettings.expressionText = piExpressionDefault("loop", expressionSettings.loopType);
    }
    migrated = true;
  }
  if (expressionSettings.expressionType === "custom" && !hasExpressionText) {
    expressionSettings.expressionText = "";
  } else if (expressionSettings.expressionType !== "custom" && !expressionSettings.expressionText) {
    expressionSettings.expressionText = piExpressionDefault(expressionSettings.expressionType, expressionSettings.loopType);
  }
  renderExpressionSettings();
  return migrated;
}

function renderExpressionSettings() {
  if (!expressionForm) return;
  Utils.setFormValue(expressionSettings, expressionForm);
  document.querySelector("#loop-type-item").classList.toggle("hidden", expressionSettings.expressionType !== "loop");
}

function resetExpressionForCurrentType(save) {
  expressionSettings = {
    expressionType: expressionType.value,
    loopType: loopType.value,
    expressionText: piExpressionDefault(expressionType.value, loopType.value)
  };
  renderExpressionSettings();
  if (save) saveExpressionSettings();
}

function saveExpressionSettings() {
  if (!expressionForm) return;
  const values = Utils.getFormValue(expressionForm);
  expressionSettings = { ...EXPRESSION_SETTINGS_DEFAULTS, ...values };
  document.querySelector("#loop-type-item").classList.toggle("hidden", expressionSettings.expressionType !== "loop");
  $UD.setSettings(expressionSettings);
}
