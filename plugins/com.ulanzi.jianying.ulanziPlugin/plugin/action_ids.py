"""Stable plugin and action identifiers."""

PLUGIN_UUID = "com.ulanzi.ulanzistudio.jianying"

ACTION_SUFFIXES = {
    "shortcut": "shortcut",
    # Reuse the former Timeline Scrub UUID so existing Deck placements become
    # the unified Timeline Control action after the upgrade.
    "timeline_control": "timelineScrub",
    # Reuse the former Basic Adjustments UUID so existing placements become
    # the unified selected-slider action after the upgrade.
    "selected_slider": "basicAdjustments",
    "color_wheels": "colorWheels",
}

ACTION_UUIDS = {
    kind: f"{PLUGIN_UUID}.{suffix}"
    for kind, suffix in ACTION_SUFFIXES.items()
}

# Old saved placements may continue emitting their historical action UUID
# until Studio reloads the profile. They route to the unified implementation,
# but are no longer formal Actions in the manifest.
LEGACY_ACTION_SUFFIXES = {
    "timelineZoom": "timeline_control",
    "timelineControl": "timeline_control",
    # The separate HSL action was merged into Adjust Selected Slider. Existing
    # Deck placements can still emit its historical UUID.
    "hsl": "selected_slider",
}


def action_kind(message, decode_context=None):
    """Resolve an Action kind from every event shape observed in Studio."""
    message = message or {}
    candidates = [
        message.get("uuid"),
        message.get("UUID"),
        message.get("actionid"),
        message.get("actionId"),
    ]
    action = message.get("action")
    if isinstance(action, str):
        candidates.append(action)
    elif isinstance(action, dict):
        candidates.extend(
            action.get(key)
            for key in ("uuid", "UUID", "actionid", "actionId", "id", "type")
        )

    context = message.get("context")
    if context and decode_context:
        try:
            decoded = decode_context(context) or {}
            candidates.extend(
                decoded.get(key)
                for key in ("uuid", "UUID", "actionid", "actionId")
            )
        except Exception:
            pass

    for candidate in candidates:
        value = str(candidate or "")
        for kind, action_uuid in ACTION_UUIDS.items():
            if value == action_uuid or value.endswith(f".{ACTION_SUFFIXES[kind]}"):
                return kind
        for suffix, kind in LEGACY_ACTION_SUFFIXES.items():
            if value == f"{PLUGIN_UUID}.{suffix}" or value.endswith(f".{suffix}"):
                return kind
    return ""
