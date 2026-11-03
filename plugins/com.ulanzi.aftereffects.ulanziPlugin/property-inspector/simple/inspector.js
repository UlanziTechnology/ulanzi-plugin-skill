const SIMPLE_COPY = {
  referenceOn: { type: "reference", prefixKey: "pi.reference_on_prefix", suffixKey: "pi.reference_on_suffix", secondaryKey: "pi.reference_scope", tipKey: "pi.reference_tip" },
  referenceOff: { type: "reference", prefixKey: "pi.reference_off_prefix", suffixKey: "pi.reference_off_suffix", secondaryKey: "pi.reference_scope", tipKey: "pi.reference_tip" },
  marker: { primaryKey: "pi.marker_description", secondaryKey: "pi.marker_tip", tipKey: "pi.generic_tip" }
};

$UD.connect();

$UD.onConnected(async () => {
  await $UD.localizeUI();
  UlanziPI.setLocalizationReady();
  const copy = SIMPLE_COPY[UlanziPI.actionName()] || { primaryKey: "pi.generic_description", tipKey: "pi.generic_tip" };
  renderSummary(copy);
  document.querySelector("#action-tip").textContent = $UD.t(copy.tipKey);
  document.querySelector(".uspi-wrapper").classList.remove("hidden");
});

$UD.onParamFromApp(() => {});
$UD.onSendToPropertyInspector((message) => UlanziPI.showStatus(message.payload));

function renderSummary(copy) {
  const primary = document.querySelector("#action-description");
  const secondary = document.querySelector("#action-secondary");
  primary.textContent = "";

  if (copy.type === "reference") {
    primary.append(document.createTextNode(`${$UD.t(copy.prefixKey)} `));
    primary.append(createKeyword(localizedText("pi.reference_keyword")));
    primary.append(document.createTextNode(` ${$UD.t("pi.reference_joiner")} `));
    primary.append(createKeyword("ref"));
    const suffix = localizedText(copy.suffixKey);
    if (suffix) primary.append(document.createTextNode(` ${suffix}`));
  } else {
    primary.textContent = $UD.t(copy.primaryKey);
  }

  const secondaryText = copy.secondaryKey ? $UD.t(copy.secondaryKey) : "";
  secondary.textContent = secondaryText;
  secondary.classList.toggle("hidden", !secondaryText);
}

function localizedText(key) {
  const localization = $UD.localization;
  if (localization && Object.prototype.hasOwnProperty.call(localization, key)) {
    return localization[key];
  }
  return $UD.t(key);
}

function createKeyword(text) {
  const keyword = document.createElement("span");
  keyword.className = "action-keyword";
  keyword.textContent = text;
  return keyword;
}
