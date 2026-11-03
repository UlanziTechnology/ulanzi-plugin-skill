# Plugin examples: fetch only what is needed

The skill installation contains no plugin source or application dependencies. The full source collection remains in [the main branch's plugins directory](https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/main/plugins).

| Download ID | Application | Runtime / useful pattern |
| --- | --- | --- |
| `photoshop` | Adobe Photoshop | Bundled JS + UXP companion; layers, tools, image adjustments |
| `lightroom` | Adobe Lightroom Classic | Node + Lua `.lrplugin`; editing parameters and sliders |
| `aftereffects` | Adobe After Effects | Node + CEP/ExtendScript; reference layers, anchors, expressions |
| `premiere` | Adobe Premiere Pro | Node + CEP; timeline controls, Lumetri, export queues |
| `davinci` | DaVinci Resolve | Python; color-wheel interaction, overlays, timeline |
| `jianying` | Jianying Pro | Python; shortcuts, timeline, sliders, native input |

## Download

Resolve helper paths from the loaded skill directory. These commands assume it is the current directory:

```bash
# Offline catalog
python3 scripts/fetch_example.py --list

# Download one example into a workspace, keeping its original folder name
python3 scripts/fetch_example.py premiere --dest /path/to/workspace/plugin-examples
```

The helper requires Python 3.9+ and Git. It uses a shallow partial clone (`--filter=blob:none`) and sparse checkout of only `plugins/<selected-folder>`. GitHub supports this mode; a Git server that ignores partial-clone filters may transfer more data. The helper downloads files without loading the plugin or running companion installers. It preserves licenses, dependencies, and native files belonging to the selected plugin, refuses to overwrite an existing destination, and reports the source commit. `--ref` can select a source branch or tag; it defaults to `main`.

Keep downloads outside the installed skill. An installed CLI copy does not contain the main repository's sibling `plugins/` directory. When working in a full source checkout and the selected example already exists locally, inspect that copy instead of downloading it again.

## Before adapting

Read the selected manifest, entrypoint, inspector code, dependency licenses, and available documentation. Use new UUIDs for a new plugin and preserve the original UUIDs when repairing that plugin.

These are legacy snapshots, not a uniform V3.1 template set. SVG assets are valid in the older examples even though `--strict-icons` enforces PNG delivery. Some state entries lack the V3.1-required `Name`; Photoshop retains a deprecated host-version field. Some native helpers and original build projects are not included. Detailed installation and source-completeness notes are in [the main repository's plugin index](https://github.com/UlanziTechnology/ulanzi-plugin-skill/blob/main/plugins/README.md).

DaVinci and Jianying use their own Python SDK/runtime contract. The JavaScript protocol and validator do not validate their Python behavior. Obtain the appropriate Python documentation before creating new Python integrations.

The DaVinci source snapshot excludes PyQt5/Qt runtimes. Its macOS overlay needs a separate, version-pinned local dependency installation; read the downloaded plugin README and THIRD_PARTY_NOTICES before using or packaging it. Restored third-party notices are accompanied by provenance hashes.
