# Ulanzi Plugin Workflow Reference

## Table Of Contents

- Recommended Layout
- Manifest Checklist
- Protocol V3.1.0 Notes
- Runtime Lifecycle
- Property Inspector
- Architecture Patterns
- D200X And Encoder Feedback
- AI Agent Protocol
- Icon Requirements
- Banner Requirements
- README And Localization
- Build And Packaging
- Publishing To UGC
- Reference Code Sources
- Positive Examples

Read `protocol-v3.1-notes.md` for compatibility and source inconsistencies, then `js-plugin-protocol-V3.1.0.md` for exact command payloads, startup arguments, D200X layout schema, AI Agent payloads, data types, UI sizing, and protocol QA. Keep this file as the daily implementation guide.

## Recommended Layout

Simple HTML plugin:

```text
com.ulanzi.example.ulanziPlugin/
├── manifest.json
├── libs/
├── assets/
│   ├── icons/
│   ├── banners/
│   └── actions/
├── plugin/
│   ├── app.html
│   ├── app.js
│   └── actions/
├── property-inspector/
│   └── action/inspector.html
├── README.md
├── README.zh.md
├── en.json
└── zh_CN.json
```

Node plugin:

```text
com.ulanzi.example.ulanziPlugin/
├── manifest.json
├── package.json
├── webpack.config.js
├── dist/app.js
├── plugin/app.js
├── plugin/plugin-common-node/
├── libs/
├── assets/
├── property-inspector/
└── README*.md
```

### Package identity

Keep these identities distinct:

| Field | Purpose | Example |
| --- | --- | --- |
| Folder | Documented package naming format for new plugins | `com.ulanzi.weathercard.ulanziPlugin` |
| Manifest `UUID` | Stable plugin identity: exactly four nonempty segments | `com.example.tools.weathercard` |
| Action `UUID` | Plugin UUID extended with the action identifier | `com.example.tools.weathercard.current` |
| `Name` and localized names | Human-readable labels shown in Studio | `Weather Card` / `天气卡片` |

The protocol's folder convention is separate from the publisher's UUID namespace. Keep existing UUIDs stable during repairs or folder renames so saved actions retain their identity. Check affected paths and rebuild the ZIP after a rename; when an installed copy moves, reload the host and check its inspector paths. A plugin that loads may still depart from documented packaging conventions.

## Manifest Checklist

Required top-level fields:

- `Author`
- `Name`
- `Description`
- `Icon`
- `Version`
- `UUID`
- `Type: "JavaScript"`
- `CodePath`
- `Actions`

Recommended top-level fields:

- `Category`
- `CategoryIcon`
- `Detail` for detailed marketplace setup/usage text (the required `Description` is the short introduction); `URL` for an optional related link
- `Banner` as an array of plugin-relative Banner image paths. Put the primary/first Banner first, for example `["assets/banners/plugin-banner-1.png", "assets/banners/plugin-banner-2.png"]`
- `OS`
- `Software.MinVersion` when host features require a minimum Ulanzi Studio version. Use `"3.3.0"` when requiring V3.1 features; see the compatibility matrix in `protocol-v3.1-notes.md` for earlier features. `Software.MinimumVersion` is deprecated
- `ApplicationsToMonitor` when the host should notify app launch/quit
- `Inspect` for Node remote debugging, for example `--inspect=127.0.0.1:9201`; use unique ports and the host `--nodeRemoteDebug` flag
- `PrivateAPI` only when the plugin intentionally uses private APIs
- `Profiles` when installing profile templates with the plugin
- `InstallToDepsApp` when the plugin must install an additional JavaScript script into a dependent third-party app

Action fields:

- `Name`
- `Icon`
- `UUID`
- `PropertyInspectorPath` when configurable
- `States` with at least one `{ "Name", "Image" }`
- `state` when the action has a default state index
- `Tooltip` for action help text
- `SupportedInMultiActions: false` when the action must not be used in multi-actions
- `SupportedInKeyLogicActions` to control availability in action triggers (defaults to true)
- Optional `States[].MultiActionImage` for the multi-action icon; each state must have a nonempty `Name`
- `DisableAutomaticStates: true` when plugin code controls state updates
- `Controllers`, usually `["Keypad"]`, `["Encoder"]`, or both
- `Encoder` layout when using Encoder
- `Devices` only when an action should be device-specific

UUID rules:

- Main service UUID: exactly 4 dot-separated segments, for example `com.ulanzi.ulanzistudio.vmix`.
- Action UUID: more than 4 segments and prefixed by the main UUID, for example `com.ulanzi.ulanzistudio.vmix.switchScene`.
- Folder name: `com.ulanzi.{pluginName}.ulanziPlugin`.

Device targeting:

- Missing or empty `Devices` means all devices.
- Device models documented across the source tables are `D200`, `D200H`, `Dial`, `D200X`, `D100N` (DialMini), and `AU05` (Vibe Key). See the notes for the AU05 filter verification caveat.
- Prefix a model with `~` to exclude it, for example `["~Dial"]`.
- `Controllers` controls whether the action appears for Keypad or Encoder surfaces; if omitted, treat it as Keypad-only.

CodePath rules:

- `.html` main services run in QWebEngineView and receive URL query params.
- `.js` main services run under Node.js 20.12.2 and receive CLI args.
- Startup params include address, port, and language; V3.1 adds host `softwareVersion` (see the notes for the incomplete Node example). Property Inspector also receives uuid, actionid, key, controller, and device.
- The main service must keep a persistent WebSocket connection even when no Property Inspector is visible.

## Protocol V3.1.0 Notes

- V2.0+ recommends `keydown`/`keyup` for button semantics. `run` is equivalent to a simple `keydown` path and is still useful for legacy/simple actions.
- `actionid` is the unique action instance identity. Use `key` for device position and include it in context strings only when helper APIs require it.
- `add` is sent when an action instance is configured or loaded; `setactive` toggles visibility/current-page active state; page switches do not call `clear`; `clear` is for deletion/removal.
- Active state matters: inactive actions should not emit recent display results, and `setSettings`/`getSettings` behavior is constrained for inactive instances.
- New work should not use `paramfromplugin` for setting sync. Use settings APIs for persisted data and send APIs for messages.
- Protocol responses from plugin-to-host requests may include `cmdType` such as `NOTIFY` or `REQUEST`.

## Runtime Lifecycle

Main service:

```js
import UlanziApi from "./plugin-common-node/index.js";

const ud = new UlanziApi();
const actionCache = new Map();

ud.connect("com.ulanzi.ulanzistudio.example");

ud.onAdd((event) => {
  const action = ensureAction(event);
  action.updateSettings(event.param || {});
});

ud.onParamFromApp((event) => {
  ensureAction(event).updateSettings(event.param || {});
});

ud.onKeyDown((event) => {
  ensureAction(event).invoke(event);
});

ud.onKeyUp((event) => {
  ensureAction(event).release?.(event);
});

ud.onDialRotate((event) => {
  ensureAction(event).handleDial?.(event.rotateEvent, event);
});

ud.onSetActive((event) => {
  ensureAction(event).setActive?.(event.active);
});

ud.onClear((event) => {
  for (const item of event.param || []) {
    const context = item.context || ud.encodeContext(item);
    actionCache.get(context)?.destroy?.();
    actionCache.delete(context);
  }
});
```

Property Inspector:

```js
$UD.connect();

$UD.onConnected(() => {
  form = document.querySelector("#property-inspector");
  form.addEventListener("input", Utils.debounce(() => {
    $UD.setSettings(Utils.getFormValue(form));
  }));
});

$UD.onAdd((message) => Utils.setFormValue(message.param || {}, form));
$UD.onDidReceiveSettings((message) => Utils.setFormValue(message.settings || {}, form));
```

Property Inspector rules:

- Set the page background to transparent.
- Load saved params/settings, render controls, and send settings or transient messages.
- Use `sendToPlugin` for UI-to-main messages that are not persisted.
- Avoid durable business logic; the main service owns long-running state.
- Fit the host's available panel rather than a full browser page. Keep the primary inputs, selection, save action, and status visible; use responsive widths and expandable secondary instructions. Measure the actual viewport when available instead of inventing a universal panel size.
- Render the form immediately with a loading/connection status. Keep useful errors visible if startup arguments, WebSocket connection, settings retrieval, or external requests fail; an empty panel is not an acceptable error state.
- Verify the manifest's `PropertyInspectorPath`, relative scripts/styles, host-supplied startup parameters, connection handshake, restored settings, save acknowledgement, and main-service feedback. Use the supplied host address/port rather than assuming port 3906.
- For a blank panel, distinguish document load failure from script errors, connection failure, and layout clipping. Inspect the installed files, resolved paths and available host logs/console; after a directory rename, verify whether the host still references the old path. Reload once when needed and retest the same action. Treat a cache issue as a hypothesis until the observed result supports it.
- Browser mocks help exercise settings and error states; host acceptance also requires opening the inspector in Studio, saving a value, reselecting the action to verify persistence, and observing the resulting key/dial feedback. Report unavailable checks explicitly.

## Architecture Patterns

Use an action cache when multiple instances can exist. Key by `actionid` unless an SDK requires its encoded context string; raw messages need not have `message.context`.

Use action classes when their lifecycle responsibilities justify them; a small plugin can use functions. Keep action methods conventional: `updateSettings`, `invoke`, `handleDial`, `onState`, `destroy`.

Use a shared client object for external apps or services. The client owns connection state and emits normalized state to actions.

Use a poller for external APIs that do not push state. Emit only when state changes to avoid redundant icon updates.

Use `setSettings/getSettings/didReceiveSettings` for persistent settings that must survive PI destruction. Use `setGlobalSettings/getGlobalSettings/didReceiveGlobalSettings` only for plugin-wide values shared across actions. Use `sendToPlugin/sendToPropertyInspector` for transient data like lists, bootstrap payloads, and status messages.

Use `RandomPort` only for local direct PI-to-main-service communication. Ordinary PI-to-main sync should go through UlanziStudio.

Use host utility commands sparingly:

- `openurl` for browser login or external docs; local plugin-relative URLs are supported with local mode.
- `openview` for modal HTML; the opened page should close itself.
- `selectdialog` for file/folder picking.
- `toast` for lightweight feedback.
- `hotkey` for host-executed shortcuts; macOS may require system permissions.
- `logMessage` for plugin logs, with levels `info`, `debug`, `warn`, and `error`.
- `showAlert` for temporary error display on a key.

## D200X And Encoder Feedback

D200X feedback requires host 3.0.1+. Use Encoder support when the action naturally responds to dial press/release/rotate or needs D200X feedback.

Manifest:

```json
{
  "Controllers": ["Keypad", "Encoder"],
  "Devices": ["D200X"],
  "Encoder": { "layout": "$UA1" }
}
```

Layout rules:

- D200X layout coordinates are 126 by 140.
- Preset `$UA1` is icon plus title; `$UA2` is text plus title.
- A custom layout path is relative to `manifest.json`.
- Element `key: "icon"` maps to the standard icon, and `key: "title"` maps to the standard title.
- Supported layout elements are `text` and `pixmap`. The protocol documents `bar`, but marks it unavailable because of device limitations.
- Update whole layouts with `setFeedbackLayout`; update specific elements with `setFeedback`.

## AI Agent Protocol

Only the plugin main service should subscribe to AI Agent state and context capabilities.

Flow:

Prerequisites: host 3.2.0+; the source currently requires an online AU05 to enable subscriptions. Treat unsupported/unavailable subscriptions as a user-visible unavailable capability.

1. Connect the main service.
2. Send `subscribeAiAgentState` with `agent_ids`, optional `states` and `events`, and `include_raw: false` by default.
3. Receive async `didReceiveAiAgentState` notifications from the host.
4. Query `getAiAgentProjects` or `getAiAgentSessions` only after subscribing to that `agent_id`.
5. Forward relevant status to actions or Property Inspectors through `sendToPropertyInspector` or `sendToPlugin`.
6. Resubscribe after reconnect, because subscriptions last only for the current WebSocket connection.

State values:

- `idle`
- `thinking`
- `working`
- `attention`
- `notification`
- `error`
- `sleeping`
- `sweeping`

Sensitive fields such as raw hook payloads, tool input, cwd, process ids, and pid chains are not forwarded unless `include_raw` is explicitly true. Avoid enabling it unless the user specifically needs raw debugging data.

## Icon Requirements

Create PNG icons at 196x196 pixels:

- Plugin icon
- Category icon
- Action icon
- Each state image

Keep icons centered, high contrast, readable at small size, and matched to the function. Prefer symbolic visual metaphors over long text. Use state pairs for toggles: off/on, disconnected/connected, inactive/active, failed/success.

Choose artwork in this order:

1. For a plugin integrating an application, first inspect supplied assets, the relevant example, and official application resources for the application's icon. For each action, look for that application's corresponding feature/tool icon, including suitable state variants. Reuse recognizable assets where available rather than inventing replacements.
2. Check the asset's source and terms for the intended plugin use and redistribution; retain attribution and notices where required. An installed application or a public download alone does not establish redistribution permission. If reuse is restricted or unclear, use an original functional symbol instead of copying the logo or restricted artwork.
3. For missing or unsuitable assets, design icons around each action's meaning. Keep new icons consistent with the reused set in weight, palette, contrast, and padding; distinguish related actions and states. A plugin with no target application needs its own visual identity.

For original artwork, discover the image-generation/editing tools and relevant skills actually available in the current session and follow their instructions. Choose by available capability rather than agent brand: ChatGPT/Codex, Claude, Gemini, WorkBuddy, and Doubao clients may expose different tools. When an image-generation tool such as `imagegen` is available, use it for artwork that benefits from generation. Otherwise, use available SVG/Canvas drawing and PNG export tools for clear functional symbols, or suitable user-supplied assets. If the environment cannot produce final assets, report that limitation and label any remaining placeholders explicitly. The fallback helper generates development placeholders; replace them before calling the icons finished.

Inspect every selected or created icon at full resolution and at the target key's thumbnail size. Check recognizable meaning, clean edges, padding, background/alpha behavior, consistent style, and distinguishable states. Size validation alone does not establish visual quality. Normalize final assets and verify the plugin, category, action, and state paths in the manifest.

Run these helpers from the skill directory (or resolve their paths from the loaded skill):

Image normalization uses Pillow (`python3 -m pip install Pillow`) or macOS `sips`. Pillow preserves aspect ratio with transparent padding; the `sips` fallback resizes to a square, so use square source artwork there. Image-generation services are optional.

Normalize generated art:

```bash
python3 scripts/icon_tool.py --from draft.png --out assets/icons/pluginIcon.png
```

Generate fallback icon:

```bash
python3 scripts/icon_tool.py --name "OBS Record" --kind record --out assets/actions/record.png
```

## Banner Requirements

Create marketplace/intro Banners under `assets/banners/` when requested or when delivering a publish-ready plugin:

- Use the user's requested size and ratio; 960x640 PNG is a suggested 3:2 default, not a protocol requirement.
- Banner 1 should be icon-led: show the plugin icon prominently, include the plugin name, and communicate the core function at a glance.
- Additional Banners may show the plugin configured on real Ulanzi hardware, configuration UI, or feature states. Prefer one clear key/dial example over cluttering many controls; two Banners are usually enough unless the user asks for a third.
- For hardware Banners, use supplied real device assets when available and compose deterministically. Use D200/D200H only for 3-row key devices. For D200X, combine the D200/D200H key area image with the D200X dial area image when the device is represented as two source images. For Dial/D100-focused plugins, use the full Dial/D100 device image.
- Show the actual runtime key display, not generic placeholder art, when demonstrating the plugin on a device.
- Use `imagegen` for creative bitmap backgrounds or icon-focused hero artwork; use local SVG/canvas/Pillow-style compositing for exact product imagery, device mockups, or text edits that must preserve an existing image.
- Verify final Banner dimensions and visually inspect the result before claiming completion; check that hardware is not cropped into accidental black bars and that any configured key display is readable.

Device asset lookup:

- Check plugin/project-provided images first. If none are provided, use the bundled portable device assets in this skill before searching local Ulanzi Studio resources or generating hardware.
- Bundled device asset root: `assets/devices/` relative to the `ulanzi-plugin` skill directory.
- D200/D200H 3-row key device image: `assets/devices/d200-bg.png`.
- D200X is composed from `assets/devices/d200-bg.png` plus `assets/devices/d200x-dial-area.png`.
- Dial/D100 full device image: `assets/devices/dial-d100.png`. Use this image when a plugin is primarily for Dial/D100 hardware.
- DialMini/D100N image: `assets/devices/dialmini.png`.
- Vibe Key/AU05 image: `assets/devices/au05.png`.
- Use user-supplied newer artwork when needed. Bundled images are licensed only for Ulanzi plugin development and promotion. Include `assets/devices/LICENSE` when redistributing source or modified artwork; the code/documentation MIT license does not cover these images.
- These images are composition resources, not screen-coordinate specifications. D200X geometry does not establish DialMini/AU05 geometry.

## README And Localization

`README.md` and `README.zh.md` should include:

- What the plugin does
- Actions provided
- Setup requirements
- Configuration fields
- Runtime behavior
- Troubleshooting

Language JSON files can include:

```json
{
  "Name": "Plugin Name",
  "Description": "Short marketplace summary",
  "Detail": "Detailed description with setup and configuration steps",
  "Actions": [
    { "Name": "Action Name", "Tooltip": "Action tooltip" }
  ],
  "Localization": {
    "Host": "Host",
    "Port": "Port",
    "Save": "Save"
  }
}
```

Supported localization filenames include `zh_CN.json`, `zh_HK.json`, `en.json`, `ja_JP.json`, `de_DE.json`, `ko_KR.json`, `pt_PT.json`, and `es_ES.json`. For marketplace publishing, localize `Name`, short `Description`, and detailed `Detail` across present language files. Choose the languages required by the audience; eight files are not mandatory.

## Build And Packaging

Run bundled helpers with Python 3.9+, resolving paths from the loaded skill directory. Structure validation and placeholder icon generation need only the standard library.

`validate_plugin.py` checks JavaScript plugin manifests and paths. `--strict-icons` requires 196x196 PNG icons; `--marketplace` also checks `Description`, `Detail`, Banner paths, and corresponding metadata in locale files that exist. It does not require fixed Banner dimensions or all eight locales. Legacy SVG assets and missing state names can fail these delivery checks without proving the older plugin cannot run. The helper does not validate Python plugins or establish application/device compatibility.

If `CodePath` points to source (`plugin/app.js` or `plugin/app.html`), no build may be required.

If `CodePath` points to `dist/`, rebuild after source changes:

```bash
npm install
npm run build
```

Run cheap checks when available:

```bash
node --check plugin/app.js
npm run check
npm run smoke
```

Do not claim a repaired plugin is complete until manifest paths, icons, CodePath, and PI paths validate.

## Local installation and host acceptance

When the user requests installation or host testing:

1. Establish the running host version, OS, selected device and actual plugin directory before changing files. Common locations are `~/Library/Application Support/Ulanzi/UlanziDeck/Plugins/` on macOS and `%APPDATA%\Ulanzi\UlanziDeck\Plugins\` on Windows; confirm them from the local installation rather than creating a guessed path. Prefer available supported installation/reload mechanisms; direct copying is a development fallback.
2. Build and validate the deliverable, then install the complete `.ulanziPlugin` folder with `manifest.json` directly inside it. Check for an existing package/UUID first, preserve local changes and settings, and back up a copy before replacing it. Verify the destination files and version before reporting installation complete.
3. Reload plugins through a supported host mechanism when available. If the host has not rescanned, normally quit and reopen it within the user's authorized testing scope, preserving ongoing work. Verify that the management page recognizes the expected name, version, and running status.
4. Select the target device and surface, clear the action-list search, and look for the current UI language's plugin/category/action names. If still absent, inspect `Devices`, `Controllers`, manifest action entries, and load errors in that order. A search for the English name may hide a Chinese-localized action.
5. Add the action to an unused key/slot or dedicated test page, preserving existing assignments. Open its inspector, configure it, save, reselect it, and exercise the key/dial behavior. Check the actual external result and visible success/failure feedback, not just process status.
6. Report installation, registration, inspector/settings, runtime result, and hardware verification separately. If hardware is disconnected, distinguish the Studio preview from a physical-device test. Rebuild the final ZIP after any fixes so installed and delivered files agree.

## Publishing To UGC

Public marketplace: [Ulanzi UGC](https://ugc.ulanzistudio.com/). The homepage exposes **Upload Works**; unauthenticated visitors are redirected to sign in. See the [official plugin publishing tutorial](https://bbs.ulanzistudio.com/forum.php?mod=viewthread&tid=464) for the upload workflow.

### Prepare the package

1. Finish relevant build/runtime checks and run `validate_plugin.py <plugin-dir> --strict-icons --marketplace`. Confirm manifest paths, `Description`, `Detail`, `Banner`, `Software.MinVersion`, state labels, and the translations for the languages actually provided.
2. Zip the `.ulanziPlugin` folder itself as the archive root, including its entrypoint, runtime dependencies, configuration pages, icons, and locale files. Keep the package's version consistent with the release being submitted.
3. Prepare a separate cover and at least one Banner for the upload form. Keep uploaded artwork consistent with package metadata and confirm that third-party code and artwork can be redistributed with the required notices.
4. Check the current form's package-size limits and image requirements before uploading. The linked tutorial contradicts itself about cover ratios (1:1 in its resource table, 2:1 later); follow the live form rather than treating either value as universal. The tutorial describes 3:2 Banners, with Banner 01 required and additional Banners optional. A 960x640 Banner is a convenient default when the form accepts it, not a fixed protocol requirement.

### Guide the user through publishing

1. Open [ugc.ulanzistudio.com](https://ugc.ulanzistudio.com/), sign in with the user's account, and choose **Upload Works**. Select the plugin work type if prompted; use this public publishing flow rather than an internal administrator site.
2. Upload the ZIP in **Main work file** and wait for parsing. Review the detected name, author, UUID, version, and action information. Resolve parsing errors before proceeding.
3. Upload the cover and at least **Banner 01**, following the live size/ratio prompts. Additional banners can show settings, device use, or distinct feature states.
4. Review the name, short introduction (`Description`), detailed usage/setup text (`Detail`), and supported language versions. The form can populate these from manifest and language files; verify the imported values instead of assuming they are complete.
5. Resolve the form's **Auto check** findings. Review the package, preview, and publication details together before submitting.
6. Submit when the user has requested publication. Read the actual receipt/status, and tell the user whether it is submitted, under review, approved, or listed according to what the site shows. A completed upload alone is not proof the plugin is public. If the result is unclear, inspect the user's work record before retrying to avoid duplicates.

Page labels and requirements may change. If login prevents inspection, report that limitation and use the official tutorial as guidance without claiming that the authenticated form was verified. The assistant can guide the user without signing in or uploading. When assisting in the browser, use the user's existing authenticated session or let them sign in; keep credentials out of files, logs, and packages.

## Reference Code Sources

When implementation details need examples, use remote Ulanzi reference code by required pattern rather than by the new plugin's name:

1. Start with `examples.md` and select a creative application plugin by integration pattern and runtime. Fetch it with `scripts/fetch_example.py` (relative to the skill directory) only when needed; keep the download in the development workspace. Existing examples may predate V3.1; see their migration and build caveats.
2. Prefer the public SDK demos: `https://github.com/UlanziTechnology/UlanziDeckPlugin-SDK/tree/main/demo`.
3. Use `https://github.com/UlanziTechnology/Plugins-HHY` as an additional pattern source when accessible. The skill must remain usable without that repository.
4. Match examples by architecture or feature: HTML main service, Node/webpack main service, Property Inspector settings sync, external app/API polling, Encoder/D200X feedback, local self-hosted service, packaging metadata, or runtime icon drawing.
5. Treat remote examples as patterns to adapt, not as plugin-name templates. Keep the new plugin's UUIDs, action IDs, names, assets, localization, and package layout internally consistent.

## Debugging Flags

Use these host startup flags during debugging when relevant:

- `--log` enables host and plugin logs.
- `--logLevel=info|debug|warn|error` controls `logMessage` output.
- `--webRemoteDebug` and `--webRemotePort=<port>` enable HTML plugin remote debugging.
- `--nodeRemoteDebug` enables Node plugin remote debugging with manifest `Inspect`.
- `--doubleClick` enables double-click triggering of `run` and `keydown`.

## Positive Examples

Look these up in the remote reference sources above when their pattern is relevant:

- `analogclock`: minimal HTML main service, canvas-generated runtime icon, simple PI param sync.
- `APIRequest`: Node/webpack, HTTP request settings, polling, JSON field parsing, generated text/icon feedback.
- `OBS Web`: shared external WebSocket client, multi-action state sync, Encoder handling.
- `vMix`: clean modern structure with `BaseAction`, action registry, external API client, state poller, smoke tests.
- `windowActions`: modern system integration with action definitions, helper client, transient PI bootstrap messages.
- `timestamp`: self-hosted local service and random port pattern for PI direct connection.
