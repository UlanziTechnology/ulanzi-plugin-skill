#!/usr/bin/env python3
import argparse
import json
import struct
import sys
from pathlib import Path


ALLOWED_CONTROLLERS = {"Keypad", "Encoder"}
ALLOWED_DEVICES = {"D200", "D200H", "Dial", "D200X", "D100N", "AU05"}
LOCALES = ("en", "zh_CN", "zh_HK", "ja_JP", "de_DE", "ko_KR", "pt_PT", "es_ES")


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}")


def png_size(path):
    try:
        with path.open("rb") as fh:
            header = fh.read(24)
        if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
            return None
        return struct.unpack(">II", header[16:24])
    except OSError:
        return None


def dot_count(value):
    return len(value.split(".")) if isinstance(value, str) and all(part.strip() for part in value.split(".")) else 0


def rel(root, value):
    # Assets must travel with the package; reject absolute paths and traversal.
    if not isinstance(value, str) or not value:
        return None
    value = value.replace("\\", "/")
    if value.startswith("/") or ":" in value:
        return None
    path = (root / value).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def check_icon(root, value, label, strict, errors, warnings):
    path = rel(root, value)
    if not path:
        errors.append(f"{label}: expected a plugin-relative icon path within the package")
        return
    if not path.is_file():
        errors.append(f"{label}: missing file {value}")
        return

    suffix = path.suffix.lower()
    if suffix != ".png":
        message = f"{label}: {value} is {suffix or 'extensionless'}, expected 196x196 PNG for new generated assets"
        (errors if strict else warnings).append(message)
        return

    size = png_size(path)
    if size != (196, 196):
        message = f"{label}: {value} is {size}, expected (196, 196)"
        (errors if strict else warnings).append(message)


def check_optional_path(root, value, label, errors):
    path = rel(root, value)
    if value and (not path or not path.is_file()):
        errors.append(f"{label}: missing file {value}")


def normalize_device(value):
    value = str(value)
    return value[1:] if value.startswith("~") else value


def validate(plugin_dir, strict_icons=False, marketplace=False):
    root = Path(plugin_dir).resolve()
    errors = []
    warnings = []

    if not root.exists() or not root.is_dir():
        return [f"not a directory: {root}"], warnings
    if not root.name.endswith(".ulanziPlugin"):
        warnings.append(f"folder name does not end with .ulanziPlugin: {root.name}")

    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return [f"missing manifest.json in {root}"], warnings

    try:
        manifest = load_json(manifest_path)
    except ValueError as exc:
        return [str(exc)], warnings

    if not isinstance(manifest, dict):
        return ["manifest: expected object"], warnings

    required = ["Author", "Name", "Description", "Icon", "Version", "UUID", "Type", "CodePath", "Actions"]
    for field in required:
        if field not in manifest or manifest[field] in ("", None):
            errors.append(f"manifest.{field}: required")

    if manifest.get("Type") != "JavaScript":
        errors.append('manifest.Type: expected "JavaScript"')

    main_uuid = manifest.get("UUID", "")
    if dot_count(main_uuid) != 4:
        errors.append(f"manifest.UUID: expected exactly 4 dot-separated segments, got {main_uuid}")

    code_path = rel(root, manifest.get("CodePath"))
    if not code_path or not code_path.is_file():
        errors.append(f"manifest.CodePath: missing file {manifest.get('CodePath')}")
    elif code_path.suffix.lower() not in {".html", ".js"}:
        warnings.append(f"manifest.CodePath: {manifest.get('CodePath')} is not .html or .js per JS plugin protocol V3.1.0")

    software = manifest.get("Software")
    if software is not None and not isinstance(software, dict):
        errors.append("manifest.Software: expected object")
    if isinstance(software, dict):
        if "MinimumVersion" in software:
            warnings.append("manifest.Software.MinimumVersion: deprecated, use Software.MinVersion")
        if "MinVersion" in software and not isinstance(software.get("MinVersion"), str):
            errors.append("manifest.Software.MinVersion: expected string")

    inspect_value = manifest.get("Inspect")
    if inspect_value and not str(inspect_value).startswith("--inspect"):
        warnings.append('manifest.Inspect: expected a Node inspect flag such as "--inspect=127.0.0.1:9201"')

    install_to_deps = manifest.get("InstallToDepsApp")
    if install_to_deps is not None:
        if not isinstance(install_to_deps, dict):
            errors.append("manifest.InstallToDepsApp: expected object")
        else:
            if install_to_deps.get("Type") != "JavaScript":
                errors.append('manifest.InstallToDepsApp.Type: expected "JavaScript"')
            if not install_to_deps.get("CodePath"):
                errors.append("manifest.InstallToDepsApp.CodePath: required")
            else:
                check_optional_path(root, install_to_deps.get("CodePath"), "manifest.InstallToDepsApp.CodePath", errors)

    check_icon(root, manifest.get("Icon"), "manifest.Icon", strict_icons, errors, warnings)
    if manifest.get("CategoryIcon"):
        check_icon(root, manifest.get("CategoryIcon"), "manifest.CategoryIcon", strict_icons, errors, warnings)

    actions = manifest.get("Actions")
    if not isinstance(actions, list) or not actions:
        errors.append("manifest.Actions: expected non-empty array")
        actions = []

    action_uuids = set()
    for idx, action in enumerate(actions):
        prefix = f"Actions[{idx}]"
        if not isinstance(action, dict):
            errors.append(f"{prefix}: expected object")
            continue
        for field in ["Name", "Icon", "UUID", "States"]:
            if field not in action or action[field] in ("", None):
                errors.append(f"{prefix}.{field}: required")

        uuid = action.get("UUID", "")
        if not isinstance(uuid, str):
            errors.append(f"{prefix}.UUID: expected string")
        elif uuid:
            if uuid in action_uuids:
                errors.append(f"{prefix}.UUID: duplicate {uuid}")
            action_uuids.add(uuid)
            if dot_count(uuid) <= 4:
                errors.append(f"{prefix}.UUID: expected more than 4 dot-separated segments, got {uuid}")
            if isinstance(main_uuid, str) and main_uuid and not uuid.startswith(main_uuid + "."):
                errors.append(f"{prefix}.UUID: does not start with plugin UUID {main_uuid}")

        if action.get("PropertyInspectorPath"):
            pi_path = rel(root, action.get("PropertyInspectorPath"))
            if not pi_path or not pi_path.is_file():
                errors.append(f"{prefix}.PropertyInspectorPath: missing file {action.get('PropertyInspectorPath')}")

        check_icon(root, action.get("Icon"), f"{prefix}.Icon", strict_icons, errors, warnings)

        for field in ("SupportedInMultiActions", "SupportedInKeyLogicActions", "DisableAutomaticStates"):
            if field in action and not isinstance(action[field], bool):
                errors.append(f"{prefix}.{field}: expected boolean")

        states = action.get("States") or []
        if not isinstance(states, list) or not states:
            errors.append(f"{prefix}.States: expected non-empty array")
        elif len(states) > 2:
            errors.append(f"{prefix}.States: expected at most 2 states (indices 0 and 1), got {len(states)}; use setImage for dynamic displays")
        if "state" in action:
            default_state = action["state"]
            if type(default_state) is not int or default_state not in (0, 1):
                errors.append(f"{prefix}.state: expected integer 0 or 1")
            elif isinstance(states, list) and default_state >= len(states):
                errors.append(f"{prefix}.state: index {default_state} has no corresponding States entry")
        for state_idx, state in enumerate(states if isinstance(states, list) else []):
            if not isinstance(state, dict):
                errors.append(f"{prefix}.States[{state_idx}]: expected object")
                continue
            if not isinstance(state.get("Name"), str) or not state["Name"].strip():
                errors.append(f"{prefix}.States[{state_idx}].Name: required nonempty string in V3.1")
            if "MultiActionImage" in state:
                check_icon(root, state["MultiActionImage"], f"{prefix}.States[{state_idx}].MultiActionImage", strict_icons, errors, warnings)
            if "Image" not in state:
                errors.append(f"{prefix}.States[{state_idx}].Image: required")
            else:
                check_icon(root, state.get("Image"), f"{prefix}.States[{state_idx}].Image", strict_icons, errors, warnings)

        controllers = action.get("Controllers", ["Keypad"])
        if not isinstance(controllers, list):
            errors.append(f"{prefix}.Controllers: expected array")
        else:
            for controller in controllers:
                if not isinstance(controller, str) or controller not in ALLOWED_CONTROLLERS:
                    errors.append(f"{prefix}.Controllers: invalid controller {controller}")
            if "Encoder" in controllers:
                encoder = action.get("Encoder")
                if not isinstance(encoder, dict):
                    errors.append(f"{prefix}.Encoder: required object when Controllers includes Encoder")
                elif not isinstance(encoder.get("layout"), str) or not encoder.get("layout"):
                    errors.append(f"{prefix}.Encoder.layout: required string when Controllers includes Encoder")
                elif not encoder["layout"].startswith("$"):
                    check_optional_path(root, encoder["layout"], f"{prefix}.Encoder.layout", errors)

        devices = action.get("Devices")
        if devices is not None:
            if not isinstance(devices, list):
                errors.append(f"{prefix}.Devices: expected array")
            else:
                for device in devices:
                    normalized = normalize_device(device)
                    if not isinstance(device, str) or normalized not in ALLOWED_DEVICES:
                        errors.append(f"{prefix}.Devices: invalid device {device}")

    banners = manifest.get("Banner")
    if banners is not None:
        if not isinstance(banners, list):
            errors.append("manifest.Banner: expected array")
        else:
            for idx, banner in enumerate(banners):
                path = rel(root, banner)
                if not path or not path.is_file():
                    errors.append(f"manifest.Banner[{idx}]: expected existing plugin-relative file")

    if marketplace:
        for field in ("Name", "Description", "Detail"):
            if not isinstance(manifest.get(field), str) or not manifest[field].strip():
                errors.append(f"manifest.{field}: required nonempty string for marketplace preparation")
        if not isinstance(banners, list) or not banners:
            errors.append("manifest.Banner: required non-empty array for marketplace preparation")
        for locale in LOCALES:
            path = root / f"{locale}.json"
            if not path.exists():
                continue
            try:
                translated = load_json(path)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if not isinstance(translated, dict):
                errors.append(f"{locale}.json: expected object")
                continue
            for field in ("Name", "Description", "Detail"):
                if not isinstance(translated.get(field), str) or not translated[field].strip():
                    errors.append(f"{locale}.json.{field}: required nonempty translated string")

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description="Validate Ulanzi .ulanziPlugin structure and manifest paths.")
    parser.add_argument("plugin_dir", help="Path to a .ulanziPlugin folder")
    parser.add_argument("--strict-icons", action="store_true", help="Fail when icon assets are not 196x196 PNG files")
    parser.add_argument("--marketplace", action="store_true", help="Also check V3.1 marketplace metadata, Banner paths, and present locale metadata")
    args = parser.parse_args()

    errors, warnings = validate(args.plugin_dir, args.strict_icons, args.marketplace)
    for warning in warnings:
        print(f"WARN: {warning}")
    for error in errors:
        print(f"ERROR: {error}")

    if errors:
        print(f"FAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    print(f"OK: 0 errors, {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
