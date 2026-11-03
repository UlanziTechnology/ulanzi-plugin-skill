import { UlanziApi, Utils } from "./actions/ulanzi-api/index.js";
import Action from "./actions/action.js";
import AeBridge from "./bridge/AeBridge.js";

const PLUGIN_UUID = "com.ulanzi.ulanzistudio.aftereffects";
const $UD = new UlanziApi();
const bridge = new AeBridge();
const actions = new Map();
let lastPropertyInspectorContext = "";

function ensureAction(message) {
  const context = message.context;
  if (!context) return null;
  let action = actions.get(context);
  let created = false;
  if (!action) {
    action = new Action(context, $UD, bridge, handleActionResult);
    actions.set(context, action);
    created = true;
  }
  const settings = message.settings || message.param;
  if (settings) action.updateSettings(settings);
  if (created) action.syncImage();
  return action;
}

async function handleActionResult(action, result) {
  if (!result || !result.ok) {
    if (result?.errorCode !== "MARKER_EXISTS") {
      action.showTemporaryTitle($UD.t(result?.messageKey || "status.communication_failed"), 1600);
    }
    $UD.showAlert(action.context);
    if (lastPropertyInspectorContext === action.context) {
      $UD.sendToPropertyInspector({
        kind: "actionResult",
        ok: false,
        statusKey: result?.messageKey || "status.communication_failed",
        errorCode: result?.errorCode || "UNKNOWN_ERROR",
        detail: result?.data || {}
      }, action.context);
    }
    return;
  }

  if (lastPropertyInspectorContext === action.context) {
    $UD.sendToPropertyInspector({
      kind: "actionResult",
      ok: true,
      statusKey: result.messageKey || "status.ae_connected"
    }, action.context);
  }

  if (action.actionName === "marker") {
    const markerText = result.data?.markerName || result.data?.positionLabel || $UD.t(result.messageKey || "status.marker_ready");
    $UD.setFeedback(action.context, { title: { text: String(markerText) } });
  } else {
    action.showTemporaryTitle($UD.t(result.messageKey || "status.ae_connected"));
  }
}

function pushBridgeStatus(context = lastPropertyInspectorContext) {
  if (!context) return;
  $UD.sendToPropertyInspector({ kind: "bridgeStatus", ...bridge.status }, context);
}

$UD.connect(PLUGIN_UUID);

$UD.onConnected(async () => {
  await $UD.localizeUI();
  Utils.log("After Effects plugin connected to Ulanzi Studio");
});

$UD.onAdd((message) => ensureAction(message));

$UD.onRun((message) => {
  const action = ensureAction(message);
  if (action) void action.run(message.param);
});

$UD.onDialDown((message) => {
  const action = ensureAction(message);
  if (action) void action.dialDown(message.param);
});

$UD.onDialRotateLeft((message) => {
  const action = ensureAction(message);
  if (action) action.dialRotateLeft(message.param);
});

$UD.onDialRotateRight((message) => {
  const action = ensureAction(message);
  if (action) action.dialRotateRight(message.param);
});

$UD.onDidReceiveSettings((message) => {
  const action = ensureAction(message);
  if (action && message.settings) action.updateSettings(message.settings);
});

$UD.onParamFromApp((message) => {
  lastPropertyInspectorContext = message.context;
  ensureAction(message);
  pushBridgeStatus(message.context);
});

$UD.onClear((message) => {
  for (const item of message.param || []) {
    const action = actions.get(item.context);
    if (action) action.clear();
    actions.delete(item.context);
    if (lastPropertyInspectorContext === item.context) lastPropertyInspectorContext = "";
  }
});

bridge.on("status", () => pushBridgeStatus());
bridge.on("bridgeError", (error) => Utils.warn("After Effects bridge error", error.message));

void bridge.start().catch((error) => {
  Utils.error("Unable to start After Effects bridge", error.message);
});
