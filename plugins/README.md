# Creative application plugins

[简体中文](README.zh.md)

Six Ulanzi plugins for photo editing, video editing, motion graphics, and color grading, copied from the supplied skill's `plugins/` directory. These are reference snapshots with different runtimes and host baselines, not six newly generated V3.1 plugins. Existing versions and UUIDs are preserved. No application or device runtime acceptance was performed for this repository import.

| Plugin | Version / actions | Entry | Useful implementation patterns |
| --- | --- | --- | --- |
| [Photoshop](com.ulanzi.photoshop.ulanziPlugin/) | 2.2.0 / 19 | `main.js` | UXP companion, key/dial controls, layer and adjustment operations |
| [Lightroom Classic](com.ulanzi.AdobeLightroomClassic.ulanziPlugin/) | 1.3.1 / 12 | `plugin/app.js` | Node service, Lua `.lrplugin` companion, editing parameters and sliders |
| [After Effects](com.ulanzi.aftereffects.ulanziPlugin/) | 1.0.0 / 5 | `plugin/app.js` | Node + CEP/ExtendScript bridge, reference layers, anchor points, expressions and markers |
| [Premiere Pro](com.ulanzi.premierepro.ulanziPlugin/) | 1.0.1 / 6 | `plugin/app.js` | Node + CEP bridge, timeline controls, Lumetri parameters and export |
| [DaVinci Resolve](com.ulanzi.davinciResolve.ulanziPlugin/) | 1.2.8 / 2 | `plugin/app.py` | Python SDK, color-wheel interaction, overlays and timeline control |
| [Jianying Pro](com.ulanzi.jianying.ulanziPlugin/) | 1.0.3 / 4 | `plugin/app.py` | Python SDK, shortcuts, timeline and slider/color-wheel controls |

## Use as a creation reference

Ask the agent to read the relevant manifest and source, for example:

> Use $ulanzi-plugin to create my own editing plugin, using the Lightroom example's Node/Lua communication pattern. Give the new plugin its own UUIDs and implement only the actions I request.

Choose examples by the integration pattern. The JS skill and validator do not define the Python runtime contract. For Python plugins, inspect their included SDK, startup handling, and platform dependencies; obtain the appropriate Python host documentation before creating a new Python implementation.

## Local checks and installation

For Lightroom, After Effects, and Premiere, run `npm run check` in the plugin folder. This checks entrypoint syntax only. Their copied `node_modules/ws` dependency and license are retained; `npm install` can restore the declared dependency if needed. A lockfile is present for Premiere; use `npm ci` there for a locked install. Source snapshots did not contain Lightroom's referenced webpack config or After Effects' version helper, so those unavailable commands were replaced by the entrypoint check.

For Photoshop, run `node --check main.js`. Its JavaScript is bundled output, and its UXP companion is provided as `uxp-plugin/*.ccx` (a ZIP-format extension containing files). No original bundler project is provided.

Python sources can be syntax-checked with Python's `ast.parse`; this does not import them or validate host dependencies. DaVinci retains permissively licensed Windows/macOS dependencies for CPython 3.14; its macOS color-wheel overlay requires [separately installed PyQt5/Qt](com.ulanzi.davinciResolve.ulanziPlugin/README.md). Jianying bundles Python transport dependencies and native helpers. Use the compatible Ulanzi Studio runtime; a system Python interpreter is not a substitute for the required host environment.

Install a selected `.ulanziPlugin` folder using the host's plugin workflow. Adobe integrations require their respective companion: Photoshop UXP, Lightroom's `plugin/ulanzi.lrplugin`, or the After Effects/Premiere CEP extension. Inspect the companion installer/configuration before running it; installing a companion can modify the application's user extension directory and CEP debug settings. See each plugin's source and existing documentation for its actual installation behavior. No installers are run by this repository's checks.

## Known publication gaps

- The JavaScript examples use protocol-supported SVG icons. `--strict-icons` intentionally rejects those under its PNG-only delivery policy; this alone does not show the legacy plugin is broken.
- Lightroom, After Effects, and Premiere have legacy state entries without `Name`, which the V3.1 validator rejects. Update and localize state names when migrating those plugins to V3.1.
- Photoshop still has deprecated `Software.MinimumVersion`; its value is not sufficient evidence to select a replacement host minimum.
- Native helper source/build inputs are absent for the copied Premiere and Jianying helpers; DaVinci includes a compiled `core` module without its source. Photoshop has no original bundler project. The import does not establish fully reproducible builds.
- Premiere's existing README contains historical workspace references (`plugin/native`, tests and validation documents) not included in this snapshot. Treat those as historical notes, not available build instructions. The same applies to historical runtime verification claims: this import has not repeated them.
- DaVinci licensing notices are restored with [versioned provenance](com.ulanzi.davinciResolve.ulanziPlugin/THIRD_PARTY_NOTICES.md). The public source snapshot excludes PyQt5/Qt runtime packages; macOS overlays require a separate local dependency installation. Any later binary release containing those packages needs its own compliant redistribution arrangements.

## License

First-party source and documentation follow the repository [MIT license](../LICENSE). Preserve all third-party notices, headers, `licenses/` directories, vendored license files, and package metadata; third-party components retain their own licenses. Bundled application logos and trademarks are not granted a separate trademark license by MIT. The separate restricted [device artwork license](../skills/ulanzi-plugin/assets/devices/LICENSE) applies when that artwork is copied into a plugin.
