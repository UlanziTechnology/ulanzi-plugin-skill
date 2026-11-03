import { normalizeSettings } from "./defaults.js";

const COMMANDS = Object.freeze({
  referenceOn: ["reference.setEnabled", { enabled: true }],
  referenceOff: ["reference.setEnabled", { enabled: false }]
});

const ANCHOR_IMAGES = Object.freeze({
  topLeft: "assets/states/anchor-top-left.svg",
  topCenter: "assets/states/anchor-top-center.svg",
  topRight: "assets/states/anchor-top-right.svg",
  middleLeft: "assets/states/anchor-middle-left.svg",
  center: "assets/states/anchor.svg",
  middleRight: "assets/states/anchor-middle-right.svg",
  bottomLeft: "assets/states/anchor-bottom-left.svg",
  bottomCenter: "assets/states/anchor-bottom-center.svg",
  bottomRight: "assets/states/anchor-bottom-right.svg"
});

const LOOP_IMAGES = Object.freeze({
  cycle: "assets/states/expression-loop-cycle.svg",
  pingpong: "assets/states/expression-loop-pingpong.svg",
  continue: "assets/states/expression-loop-continue.svg"
});

const EXPRESSION_IMAGES = Object.freeze({
  wiggle: "assets/states/expression-wiggle.svg",
  loop: LOOP_IMAGES.cycle,
  stutter: "assets/states/expression-stutter.svg",
  countdownNumber: "assets/states/expression-countdown.svg",
  custom: "assets/states/expression-custom.svg"
});

function controllerSegment(value) {
  return String(value || "").trim().replace(/\s+/g, "_");
}

export function buildExpressionControllerNames($UD) {
  const translated = (key, fallback) => {
    const value = $UD.t(key);
    return controllerSegment(value && value !== key ? value : fallback);
  };
  const wiggle = translated("controller.wiggle", "Wiggle");
  const stutter = translated("controller.stutter", "Stutter");
  const countdown = translated("controller.countdown", "Countdown");
  const frequency = translated("controller.frequency", "Frequency");
  const amplitude = translated("controller.amplitude", "Amplitude");
  const value = translated("controller.value", "Value");
  const decimalPlaces = translated("controller.decimal_places", "Decimals");
  return {
    wiggleFrequencyPrefix: `ulanzi_${wiggle}_${frequency}_`,
    wiggleAmplitudePrefix: `ulanzi_${wiggle}_${amplitude}_`,
    stutterFrequencyPrefix: `ulanzi_${stutter}_${frequency}_`,
    countdownValue: `ulanzi_${countdown}_${value}`,
    countdownDecimalPlaces: `ulanzi_${countdown}_${decimalPlaces}`
  };
}

export default class Action {
  constructor(context, $UD, bridge, onResult) {
    this.context = context;
    this.$UD = $UD;
    this.bridge = bridge;
    this.onResult = onResult;
    this.pendingMarkerSteps = 0;
    this.markerTimer = null;
    this.feedbackTimer = null;
    this.imagePath = "";
    const decoded = $UD.decodeContext(context);
    this.actionName = decoded.uuid.split(".").pop();
    this.settings = normalizeSettings(this.actionName, {});
  }

  updateSettings(settings) {
    this.settings = normalizeSettings(this.actionName, settings);
    if (this.actionName === "anchorGrid" || this.actionName === "expression") this.syncImage();
  }

  syncImage() {
    let imagePath;
    if (this.actionName === "anchorGrid") {
      imagePath = ANCHOR_IMAGES[this.settings.anchorPoint] || ANCHOR_IMAGES.center;
    } else if (this.actionName === "expression") {
      imagePath = this.settings.expressionType === "loop"
        ? LOOP_IMAGES[this.settings.loopType] || LOOP_IMAGES.cycle
        : EXPRESSION_IMAGES[this.settings.expressionType] || EXPRESSION_IMAGES.wiggle;
    } else {
      return;
    }
    if (imagePath === this.imagePath) return;
    this.imagePath = imagePath;
    this.$UD.setPathIcon(this.context, imagePath);
  }

  async run(settings) {
    if (settings) this.updateSettings(settings);
    let command;
    let payload;
    if (COMMANDS[this.actionName]) {
      [command, payload] = COMMANDS[this.actionName];
    } else if (this.actionName === "anchorGrid") {
      command = "anchor.setGridPoint";
      payload = { point: this.settings.anchorPoint };
    } else if (this.actionName === "expression") {
      await this.$UD.localizeUI();
      command = "expression.apply";
      payload = {
        expressionType: this.settings.expressionType,
        loopType: this.settings.loopType,
        expressionText: this.settings.expressionText,
        controllerNames: buildExpressionControllerNames(this.$UD)
      };
    } else {
      return;
    }
    await this.execute(command, payload);
  }

  async dialDown(settings) {
    if (settings) this.updateSettings(settings);
    await this.flushMarkerNavigation();
    await this.execute("marker.add", {});
  }

  dialRotateLeft(settings) {
    if (settings) this.updateSettings(settings);
    this.queueMarkerNavigation(-1);
  }

  dialRotateRight(settings) {
    if (settings) this.updateSettings(settings);
    this.queueMarkerNavigation(1);
  }

  queueMarkerNavigation(step) {
    if (this.actionName !== "marker") return;
    this.pendingMarkerSteps += step;
    if (this.markerTimer) clearTimeout(this.markerTimer);
    this.markerTimer = setTimeout(() => {
      this.markerTimer = null;
      void this.flushMarkerNavigation();
    }, 45);
  }

  async flushMarkerNavigation() {
    if (this.actionName !== "marker" || this.pendingMarkerSteps === 0) return;
    const steps = this.pendingMarkerSteps;
    this.pendingMarkerSteps = 0;
    await this.execute("marker.navigate", { steps });
  }

  async execute(command, payload) {
    const result = await this.bridge.request(command, payload, { context: this.context });
    await this.onResult(this, result);
    return result;
  }

  showTemporaryTitle(text, duration = 1200) {
    if (this.feedbackTimer) clearTimeout(this.feedbackTimer);
    this.$UD.setTitle(this.context, String(text || ""));
    this.feedbackTimer = setTimeout(() => {
      this.feedbackTimer = null;
      this.$UD.setTitle(this.context, "");
    }, duration);
  }

  clear() {
    if (this.markerTimer) clearTimeout(this.markerTimer);
    this.markerTimer = null;
    this.pendingMarkerSteps = 0;
    if (this.feedbackTimer) clearTimeout(this.feedbackTimer);
    this.feedbackTimer = null;
  }
}
