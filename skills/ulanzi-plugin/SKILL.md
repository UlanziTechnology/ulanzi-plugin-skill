---
name: ulanzi-plugin
description: Turn ideas into working Ulanzi Studio JavaScript .ulanziPlugin plugins using protocol V3.1.0; adapt open-source examples, repair, validate, and package plugins. Use for creative application integrations, plugin manifests, main services, Property Inspectors, Keypad/Encoder actions, device adaptation, AI Agent subscriptions, icons, banners, localization, and marketplace preparation.
---

# Ulanzi Plugin

- Project repository: [UlanziTechnology/ulanzi-plugin-skill](https://github.com/UlanziTechnology/ulanzi-plugin-skill).
- Plugin examples: [plugins/ on main](https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/main/plugins).
- Publish and discover plugins: [Ulanzi UGC](https://ugc.ulanzistudio.com/).

Focus on plugin creation: turn a user idea into a working plugin, using relevant open-source plugins as examples when available. Produce complete `.ulanziPlugin` folders: manifest, working main service, assets, configuration UI when needed, localization, and relevant validation. Prepare marketplace metadata and artwork when requested. Protocol V3.1.0 is the current reference; choose the host minimum from the features actually used.

## Capabilities: creative application integrations

When the user asks what this skill can do or explores creative workflows, proactively introduce plugin creation and the existing creative application plugins below. Describe concrete operations in the user's language, rather than only naming applications or linking to source. When the user names an application or task, lead with the relevant integration and operations instead of listing every plugin.

| Application | Existing plugin capabilities to introduce |
| --- | --- |
| Adobe Photoshop | Play actions; control layers, blend modes and opacity; select tools; adjust brushes, zoom, hue/saturation and brightness/contrast; transform layers and create adjustment layers. |
| Adobe Lightroom Classic | Basic photo adjustments, tone curves, HSL color mixing, local adjustments, filter labels and view modes; dial control of selected sliders. |
| Adobe After Effects | Enable/disable reference layers, position anchor points with a grid, apply expression presets, and control composition markers. |
| Adobe Premiere Pro | Move the playhead, trim clips, zoom the timeline, switch and adjust Lumetri parameters, and trigger quick export. |
| DaVinci Resolve | Adjust color wheels and control the timeline through the Python plugin. |
| Jianying Pro | Trigger editing shortcuts and control the timeline, selected sliders, and color wheels through the Python plugin. |

Present these as capabilities represented by the repository's existing plugins. Separate existing operations from new features that would need implementation. Check the selected example's application version, platform, companion extension, and source completeness before promising it will work in the user's environment. Use the [example catalog](references/examples.md) to fetch the relevant source only when implementation or diagnosis requires it; introducing capabilities does not require downloading every example.

## Start

1. Identify whether the task is create, repair, validate, or explain. For an existing plugin, inspect `manifest.json`, `CodePath`, Property Inspector files, assets, `package.json`, and unbuilt source before editing.
2. Read [references/plugin-workflow.md](references/plugin-workflow.md) for implementation and packaging. Read [references/protocol-v3.1-notes.md](references/protocol-v3.1-notes.md) for device names, host compatibility, new display commands, or multi-action behavior.
3. Consult [references/js-plugin-protocol-V3.1.0.md](references/js-plugin-protocol-V3.1.0.md) for exact payloads. Its examples include comments, placeholders, and legacy material; use the clarification notes to resolve documented inconsistencies rather than copying examples as executable JSON.
4. Choose the smallest suitable architecture: HTML for simple canvas/timer/HTTP work; Node for filesystem, OS integration, npm dependencies, external app control, or long-lived clients. Use a separate local service only when the inspector must connect directly to the plugin.
5. When examples are needed, first read the [example catalog](references/examples.md). Examples are fetched on demand with `scripts/fetch_example.py` into the development workspace, outside the installed skill. Download only the example needed for the task, then inspect its source. Examples focus on photo/video editing, motion graphics, and color grading integrations. Read the selected plugin's README, manifest, source/build entrypoints, and license; choose by implementation pattern, not just its name. Use remote examples when no suitable local example exists. Prefer the public [UlanziDeckPlugin-SDK demos](https://github.com/UlanziTechnology/UlanziDeckPlugin-SDK/tree/main/demo). Use [Plugins-HHY](https://github.com/UlanziTechnology/Plugins-HHY) as an additional reference if accessible. Match the required pattern, and check protocol compatibility before reusing helper methods.

The optional DaVinci and Jianying examples use Python; this JS protocol skill and validator do not establish their Python runtime contract. Use them only with their own SDK/startup documentation and obtain the Python protocol before implementing new Python behavior. Prefer the JS examples for a new JS plugin.

## Create from an idea

1. Turn the request into an action design using the interview below. Reuse decisions already supplied; a concrete request can proceed without an interview.
2. Choose a relevant example or a minimal HTML/Node structure. When creating a new plugin from an example, assign a new plugin UUID and action UUIDs, update names and paths consistently, and keep required upstream license notices. Preserve UUIDs when repairing the original plugin.
3. Implement one complete interaction from inspector settings through the main service to a key/dial result, then add the remaining requested actions. Keep external clients shared and action instances isolated.
4. Finish assets, user instructions, build output when needed, and validation. If Studio is installed on the local target desktop, deploy the usable plugin for iteration using the workflow below unless the user requests source/package only. Provide the working `.ulanziPlugin` folder and package when requested; include marketplace artwork and submission only when in scope.

### Interview: from requirements to action design

For an idea such as "control my editing software," ask targeted follow-up questions until the intended workflow can be mapped to actual controls. Organize decisions by dependency: desired outcome and target environment first, then actions and interactions, then feedback, settings, and failure behavior.

- Ask one to three related questions per round, limited to decisions whose prerequisites are known. Explain each choice through its effect on the user's workflow and give a recommended answer with a brief reason.
- After each reply, retain settled decisions and ask only what the answers newly unblock. Reconcile contradictory requirements explicitly. For example, settle whether the dial controls the playhead or clip boundaries before asking about movement increments.
- Detect the current desktop OS from supplied environment context or local system tools before asking questions; use it as the default development and test target. State the detected OS briefly instead of asking the user to confirm it. In a remote/container environment, distinguish the execution OS from the desktop running Studio. Ask about the target OS only when it cannot be established or the user requests another system or cross-platform support.
- Discover facts from available manifests, source, protocol documents, and environment tools. Ask the user about preferences or an application/version/device only when that information is missing and cannot be established locally. Let the assistant choose SDK methods, UUID structure, and internal architecture.
- Resolve gaps that change behavior, scope, compatibility, or integration before implementing dependent code. Continue independent source/protocol inspection while waiting. State reasonable defaults for low-impact presentation choices; explicit user decisions take precedence.

Use the following dimensions to turn the answers into an implementable design. Cover only those relevant to the requested plugin:

| Dimension | Decisions to resolve |
| --- | --- |
| Goal and scope | What task becomes easier? Which application/service, versions, and device are involved? Use the automatically detected desktop OS unless another target is requested. Which operations belong in the first usable version? |
| Key actions | What does a press do: trigger once, toggle, select a mode, or apply an explicit state? Does release matter? If a hold has another meaning, define its threshold and ensure one gesture does not execute both short-press and hold actions. |
| Dial actions | What value or position changes with rotation? Define direction, unit, step size, and bounds. Resolve dial press, held rotation, or rapid input only when the task and target controls need them. |
| Display | What should the key/dial show before use, during execution, and after success or failure? Distinguish application-confirmed state from a last-commanded value when the integration cannot read state back. Verify that the target surface can present the proposed feedback. |
| Configuration | Which choices should ordinary users edit in the inspector? Define units, defaults, valid ranges, and whether values apply per action or across the plugin. Keep internal routing and implementation details out of these decisions. |
| Failure and recovery | What happens when the target app is closed, disconnected, unauthorized, or incompatible? Define the visible response and a recovery path; decide whether a failed operation is safe to retry rather than replaying it blindly. |

Present a compact action map before coding, scaled to the number of actions:

| Action / user goal | Key interaction | Dial interaction | Display feedback | Inspector settings | Failure behavior / acceptance |
| --- | --- | --- | --- | --- | --- |
| Application volume, illustrative | Press toggles mute | Turn changes volume by the configured step, clamped to 0–100% | Confirmed percentage and mute state, or an explicit unconfirmed indication | Target application; step size with a stated default and range | A closed app produces unavailable feedback; one press toggles once; repeated turns respect bounds |

Use "not used" for controls the action does not need. Split unrelated operations into separate actions; use a configurable mode only when switching is part of the intended workflow. Base the integration choice on verified application capabilities, especially before promising selected-slider control or state feedback.

The design is ready when every in-scope action has an unambiguous trigger, result, relevant feedback/settings, and an observable acceptance condition, and no unresolved user decision could change those behaviors. Summarize agreed choices and stated defaults, then implement within the user's existing authorization. If a material choice remains open, ask about that choice rather than requesting a blanket confirmation of the entire design.

## Runtime and manifest rules

- `CodePath` may be `.html` or `.js`; the documented embedded Node runtime is 20.12.2. Build for that runtime.
- For new packages, follow the documented folder format `com.ulanzi.{pluginName}.ulanziPlugin`. This folder name, manifest UUID, and localized display name are separate fields; see [Package identity](references/plugin-workflow.md#package-identity). Host acceptance alone does not establish naming compliance.
- Main UUIDs have exactly four nonempty dot-separated segments. Action UUIDs extend the main UUID with at least one segment. Use the publisher's namespace; preserve existing UUIDs when repairing a plugin.
- Treat `actionid` as the unique instance identity. Use `uuid___key___actionid` only where SDK context helpers require it; `key` alone is not an instance identity.
- The main service owns external clients, timers, and instance state. Property Inspectors load saved values, render controls, and send settings/messages. Set inspector backgrounds to transparent.
- `add` loads an instance; `setactive` controls whether it emits display updates; page switches do not delete instances; `clear` removes instances and their resources.
- Use `keydown`/`keyup` for press/release semantics; retain `run` for simple or legacy actions. Encoder events are `dialdown`, `dialup`, and `dialrotate`. See the notes for the rotation spelling inconsistency.
- Persist action settings with `setSettings` / `getSettings` / `didReceiveSettings`. Use global settings for plugin-wide values and `sendToPlugin` / `sendToPropertyInspector` for transient messages. Adapt SDK wrappers only after checking their actual signatures.
- For V3.1 display updates on host 3.3.0+, use `setState`, `setImage`, and `setTitle`. Preserve legacy `state`/SDK icon helpers when supporting older hosts. Follow the notes for default versus temporary icons.
- Add `Controllers` and an `Encoder.layout` for Encoder actions. Device filters use protocol models `D200`, `D200H`, `Dial`, `D200X`, `D100N`, and `AU05`; product names such as Vibe Key and DialMini are labels, not manifest values. See the device table and filtering caveat in the notes.
- For new D200-series actions, default to `Devices: ["D200", "D200H", "D200X"]` together unless the user explicitly narrows the target or a verified hardware limitation requires a narrower filter. Declare supported surfaces separately with `Controllers`; the family filter does not grant every model Encoder capability or identical display geometry. Preserve intentional filters when repairing existing actions.
- Use `Software.MinVersion` for the minimum supported host, not the protocol version. V3.1-specific features need `3.3.0`; see the feature matrix for lower compatible baselines. `Software.MinimumVersion` is deprecated.
- V3.1 requires `States[].Name`; use `MultiActionImage` and `SupportedInKeyLogicActions` when relevant. Honor `isInMultiAction` and `multiActionState` when executing a selected state.
- AI Agent subscriptions belong in the main service: subscribe after connection, resubscribe after reconnect, keep `include_raw` false by default, and query only subscribed agents. The documented host/device prerequisites are in the notes.
- Node debugging uses manifest `Inspect`, a unique local port, and the host `--nodeRemoteDebug` flag. Include it only when debugging is needed.

## User experience

- External CLI dependencies need actionable install/auth instructions and short errors for missing binaries or expired login. Resolve an explicit configured path, then the platform's installed command locations; use existing package-manager shims when relevant.
- For refresh plugins, show loading before the first usable snapshot, then retain the last display during routine refreshes.
- Expose settings ordinary users need. Keep internal paths/IDs in advanced settings only when useful. Synchronize defaults across code, UI, and translations; refresh the preview after saved settings change.
- Build Property Inspectors for the host's compact panel: keep primary controls visible, move secondary help into expandable content, and show loading/connection errors. Verify rendering and saved settings in the actual host when available; see the workflow's Property Inspector rules.
- Keep runtime labels stable and readable at 196x196. Separate labels, status, progress, and secondary metrics to avoid overlap.

## Icons, banners, and copy

- Prefer 196x196 PNG for plugin/category/action/state icons. Existing protocol-supported formats may be retained unless the delivery requirements demand PNG.
- For application integrations, first look for the application's existing icon for the plugin and its corresponding feature icons for actions. Reuse suitable assets when their terms permit the intended use and distribution, preserving required notices. Create original artwork only where suitable reusable assets are unavailable. Follow [Icon Requirements](references/plugin-workflow.md#icon-requirements) for asset discovery, tool selection, and visual acceptance; placeholders are development assets, not finished icons.
- For hardware mockups, use the real images under `assets/devices/`, mapped in the workflow. These images have a separate license limited to Ulanzi plugin development and promotion; include `assets/devices/LICENSE` when redistributing source or modified artwork. Compose precise screens and typography locally. Show actual runtime output on the correct device; inspect final artwork at full and thumbnail sizes.
- Create marketplace banners when requested. A 960x640 PNG is a suggested 3:2 default, not a protocol requirement. Honor the destination's specifications. Put relative paths in top-level `Banner`, primary first.
- In V3.1, `Description` is the short introduction and `Detail` is the detailed setup/usage text. `URL` is an optional related link. `Overview` may be retained for an existing integration that uses it; it is not a documented V3.1 requirement.
- Localize the plugin's user-facing strings and provide setup, usage, dependency/permission, and troubleshooting documentation in the languages requested. The eight documented locale filenames are in the workflow; their existence does not require every plugin to ship all eight.

## Validate and package

Resolve `SKILL_DIR` to the directory containing this `SKILL.md`; all helper paths are relative to that directory. The following shell examples assume the skill directory is the current directory:

```bash
python3 scripts/validate_plugin.py /path/to/com.ulanzi.example.ulanziPlugin --strict-icons
python3 scripts/validate_plugin.py /path/to/com.ulanzi.example.ulanziPlugin --strict-icons --marketplace
```

The second command also checks marketplace metadata, Banner paths, and present locale metadata. This is a static check, not proof of host or hardware compatibility. Run relevant project build/check commands and verify connection, add/settings, press/dial, active-page changes, deletion, and reconnect in the host when available. Report checks that could not be performed.

For local creation or repair with Studio installed, proactively follow [Local installation and host acceptance](references/plugin-workflow.md#local-installation-and-host-acceptance) before final delivery; a separate installation request is unnecessary. Prefer a platform-appropriate directory link to the stable development package, with copying as a fallback. Honor source/package-only requests and report deployment blockers. Verify the installed files, plugin registration, action visibility, inspector, and real result separately. A browser simulation or green plugin status alone does not prove the complete interaction works.

For generated `dist/` output, rebuild after source edits. Inspect final assets and package contents. Zip the `.ulanziPlugin` folder itself as the archive root; in Python use `plugin.parent / f"{plugin.name}.zip"` to preserve the full folder name.

## Share a plugin on Ulanzi UGC

After delivering a usable plugin, briefly tell the user they can share it on [Ulanzi UGC](https://ugc.ulanzistudio.com/). When they want to publish, explain the workflow: sign in → open **Upload Works** → upload the plugin ZIP → verify parsed metadata → add the cover, banners, and localized introduction → resolve **Auto check** findings → submit and inspect the returned status. Read [Publishing To UGC](references/plugin-workflow.md#publishing-to-ugc) for preparation and submission details.

Offering the link does not authorize an upload. Submit only when the user requests publishing, using their authenticated session. Keep credentials out of source, documentation, logs, and packages. Distinguish successful submission from review approval or a publicly listed plugin.


## Repair

Reproduce or localize the failure, run the validator, then trace connection → add/settings → input event → display update → clear. Fix the smallest responsible layer, rebuild generated output if necessary, and rerun validation plus the relevant runtime checks.

For missing actions, first check the selected device, clear search, and inspect localized names before changing filters or registration. If an action is visible but cannot be dropped onto a dial, verify actual Encoder assignment and the [D200X host compatibility caveat](references/protocol-v3.1-notes.md#d200x-encoder-dragdrop-compatibility); visibility alone is insufficient. For a blank inspector, follow the workflow's inspector diagnosis and establish the cause from observable evidence before claiming a fix.
