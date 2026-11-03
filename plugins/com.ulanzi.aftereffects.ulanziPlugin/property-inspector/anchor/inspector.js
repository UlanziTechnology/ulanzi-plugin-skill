const ANCHOR_DEFAULTS = { anchorPoint: "center" };
const ANCHOR_POINTS = ["topLeft", "topCenter", "topRight", "middleLeft", "center", "middleRight", "bottomLeft", "bottomCenter", "bottomRight"];
let anchorSettings = { ...ANCHOR_DEFAULTS };
let anchorForm;
let anchorInput;
let anchorButtons = [];

$UD.connect();

$UD.onConnected(async () => {
  await $UD.localizeUI();
  UlanziPI.setLocalizationReady();
  anchorForm = document.querySelector("#property-inspector");
  anchorInput = anchorForm.querySelector('[name="anchorPoint"]');
  anchorButtons = Array.from(anchorForm.querySelectorAll("[data-anchor-point]"));
  anchorButtons.forEach((button) => {
    const localizedLabel = $UD.t(button.dataset.labelKey);
    button.title = localizedLabel;
    button.setAttribute("aria-label", localizedLabel);
    button.addEventListener("click", () => selectAnchorPoint(button.dataset.anchorPoint));
  });
  renderAnchorPoint();
  document.querySelector(".uspi-wrapper").classList.remove("hidden");
});

$UD.onParamFromApp((message) => {
  const settings = message.param || {};
  replaceAnchorSettings(settings);
  if (!settings.anchorPoint) saveAnchorSettings();
});

$UD.onDidReceiveSettings((message) => {
  if (UlanziPI.isCurrentSettings(message) && message.settings) replaceAnchorSettings(message.settings);
});

$UD.onSendToPropertyInspector((message) => UlanziPI.showStatus(message.payload));

function replaceAnchorSettings(settings) {
  anchorSettings = { ...ANCHOR_DEFAULTS, ...(settings || {}) };
  if (!ANCHOR_POINTS.includes(anchorSettings.anchorPoint)) anchorSettings.anchorPoint = ANCHOR_DEFAULTS.anchorPoint;
  renderAnchorPoint();
}

function saveAnchorSettings() {
  if (!anchorForm || !anchorInput) return;
  $UD.setSettings(anchorSettings);
}

function selectAnchorPoint(anchorPoint) {
  if (!ANCHOR_POINTS.includes(anchorPoint)) return;
  anchorSettings = { ...anchorSettings, anchorPoint };
  renderAnchorPoint();
  saveAnchorSettings();
}

function renderAnchorPoint() {
  if (!anchorInput) return;
  anchorInput.value = anchorSettings.anchorPoint;
  anchorButtons.forEach((button) => {
    const selected = button.dataset.anchorPoint === anchorSettings.anchorPoint;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-checked", String(selected));
  });
}
