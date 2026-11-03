"""Action identity helpers shared by the Ulanzi event entrypoint."""

PLUGIN_UUID = "com.ulanzi.ulanzistudio.davinciResolve"
COLOR_WHEEL_ACTION_UUID = f"{PLUGIN_UUID}.action"
TIMELINE_ACTION_UUID = f"{PLUGIN_UUID}.timelineControl"


def extract_action_id(message, decode_context_fn=None):
    """Return the manifest action UUID from the host's varying event shapes."""
    message = message or {}

    def known_action_uuid(value):
        value = str(value or "")
        if value in (COLOR_WHEEL_ACTION_UUID, TIMELINE_ACTION_UUID):
            return value
        if value.endswith(".timelineControl"):
            return value
        return ""

    # Real Ulanzi encoder events use `uuid` for the manifest Action UUID and
    # `actionid` for a per-slot instance UUID (for example a random UUID4).
    # Prefer the typed UUID or Timeline Control is silently instantiated as the
    # legacy Color Wheel Action even though its dial events otherwise look valid.
    direct_uuid = known_action_uuid(message.get("uuid") or message.get("UUID"))
    if direct_uuid:
        return direct_uuid

    action = message.get("action")
    deferred_type = ""
    if isinstance(action, str):
        if "." in action:
            return action
        deferred_type = action
    if isinstance(action, dict):
        for key in ("UUID", "uuid"):
            value = action.get(key)
            action_uuid = known_action_uuid(value)
            if action_uuid:
                return action_uuid
        for key in ("actionid", "actionId", "id"):
            value = action.get(key)
            action_uuid = known_action_uuid(value)
            if action_uuid:
                return action_uuid
        deferred_type = str(action.get("type") or "")

    context = message.get("context")
    if context and decode_context_fn:
        try:
            decoded = decode_context_fn(context) or {}
            value = decoded.get("uuid") or decoded.get("UUID")
            action_uuid = known_action_uuid(value)
            if action_uuid:
                return action_uuid
            value = decoded.get("actionid") or decoded.get("actionId")
            action_uuid = known_action_uuid(value)
            if action_uuid:
                return action_uuid
        except Exception:
            pass

    # Older SDK/examples put the manifest Action UUID in `actionid`, so retain
    # that shape only when it actually resembles one of our known Action IDs.
    direct = message.get("actionid") or message.get("actionId")
    direct_action_uuid = known_action_uuid(direct)
    if direct_action_uuid:
        return direct_action_uuid

    return deferred_type


def action_kind(message, decode_context_fn=None):
    action_id = extract_action_id(message, decode_context_fn)
    if action_id == TIMELINE_ACTION_UUID or action_id.endswith(".timelineControl"):
        return "timeline"
    return "color_wheel"


__all__ = [
    "PLUGIN_UUID",
    "COLOR_WHEEL_ACTION_UUID",
    "TIMELINE_ACTION_UUID",
    "extract_action_id",
    "action_kind",
]
