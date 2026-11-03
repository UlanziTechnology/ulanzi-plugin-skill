"""Settings update helpers for DaVinci wheel actions."""


def normalize_dial_mode(value, default):
    if value in {'orbit', 'diameter'}:
        return value
    return default


def migrate_legacy_settings(settings):
    if (
        settings.get('settings_version') is None
        and settings.get('dial_mode') == 'orbit'
        and settings.get('hold_dial_mode') == 'diameter'
    ):
        return {**settings, 'dial_mode': 'diameter', 'hold_dial_mode': 'orbit'}
    return settings


def has_explicit_wheel_mode_settings(settings):
    return any(
        key in settings
        for key in ('dial_mode', 'hold_dial_mode', 'settings_version')
    )


def update_action_settings(action, settings, *, wheel_manager):
    action.wheel_settings_explicit = (
        getattr(action, 'wheel_settings_explicit', False)
        or has_explicit_wheel_mode_settings(settings)
    )
    settings = migrate_legacy_settings(settings)
    action.settings.update(settings)

    target = action.settings.get('target_wheel', 'auto')
    action.target_wheel = None if target == 'auto' else target

    sensitivity = action.settings.get('sensitivity', 1.0)
    wheel_manager.set_sensitivity(float(sensitivity))
    action.dial_mode = normalize_dial_mode(action.settings.get('dial_mode'), 'diameter')
    action.hold_dial_mode = normalize_dial_mode(action.settings.get('hold_dial_mode'), 'orbit')


__all__ = [
    'has_explicit_wheel_mode_settings',
    'migrate_legacy_settings',
    'normalize_dial_mode',
    'update_action_settings',
]
