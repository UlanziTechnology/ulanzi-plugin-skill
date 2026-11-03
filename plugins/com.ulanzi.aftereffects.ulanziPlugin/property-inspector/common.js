(function () {
  const hiddenStatuses = new Set(["STARTING", "CONNECTED"]);
  let localizationReady = false;
  let pendingStatus = null;

  function hideStatus() {
    pendingStatus = null;
    const element = document.querySelector("#status-message");
    const divider = document.querySelector("#status-divider");
    if (element) {
      element.className = "tip hidden";
      element.textContent = "";
    }
    if (divider) divider.classList.add("hidden");
  }

  function statusDetail(payload) {
    const detail = payload.detail || {};
    const parts = [];
    const target = [detail.layerName, detail.propertyName].filter(Boolean).join(" → ");
    if (target) parts.push(target);
    if (detail.controllerName) parts.push(String(detail.controllerName));
    if (detail.token) parts.push(String(detail.token));
    if (detail.reason) {
      const reason = String(detail.reason).replace(/^Error:\s*/i, "");
      if (reason && !parts.includes(reason)) parts.push(reason);
    }
    return parts.join("；");
  }

  function showStatus(payload) {
    if (!payload) return;
    if (payload.kind === "actionResult" && payload.ok) {
      hideStatus();
      return;
    }
    const code = payload.code || payload.errorCode || "UNKNOWN_ERROR";
    if (payload.kind === "bridgeStatus" && hiddenStatuses.has(code)) {
      hideStatus();
      return;
    }
    if (!localizationReady) {
      pendingStatus = payload;
      return;
    }
    const element = document.querySelector("#status-message");
    if (!element) return;
    const divider = document.querySelector("#status-divider");
    const severity = payload.kind === "actionResult" || payload.severity === "error" ? "error" : "warn";
    const statusKey = payload.statusKey || "status.communication_failed";
    const detail = payload.kind === "actionResult" ? statusDetail(payload) : "";
    element.textContent = `${$UD.t(statusKey)}${detail ? `：${detail}` : ""}`;
    element.className = `tip ${severity}`;
    if (divider) divider.classList.remove("hidden");
  }

  function setLocalizationReady() {
    localizationReady = true;
    if (!pendingStatus) return;
    const payload = pendingStatus;
    pendingStatus = null;
    showStatus(payload);
  }

  function actionName() {
    const uuid = $UD.uuid || "";
    return uuid.split(".").pop();
  }

  function isCurrentSettings(message) {
    return !message || !$UD.actionid || !message.actionid || message.actionid === $UD.actionid;
  }

  function isInsideForm(target) {
    return target && typeof target.closest === "function" && Boolean(target.closest("form"));
  }

  document.addEventListener("input", (event) => {
    if (isInsideForm(event.target)) hideStatus();
  }, true);

  document.addEventListener("change", (event) => {
    if (isInsideForm(event.target)) hideStatus();
  }, true);

  document.addEventListener("click", (event) => {
    const button = event.target && typeof event.target.closest === "function"
      ? event.target.closest("form button")
      : null;
    if (button) hideStatus();
  }, true);

  window.UlanziPI = { showStatus, hideStatus, setLocalizationReady, actionName, isCurrentSettings };
})();
