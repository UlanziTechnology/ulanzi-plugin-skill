# Protocol V3.1.0 implementation notes

These notes reconcile the bundled protocol's version history, manifest examples, and device tables. The bundled Chinese protocol is the payload reference; its code fences contain illustrative pseudocode, comments, and placeholders, not directly runnable JSON. Protocol versions and Ulanzi Studio versions are separate values.

## Host compatibility

| Capability | Minimum host stated in protocol history |
| --- | --- |
| Ordinary existing JS/Node plugin baseline used by this skill | 3.0.0 (recommended baseline, not a claim that every command requires it) |
| D200X feedback layouts | 3.0.1 |
| Global settings | 2.1.19 / 3.0.2, depending on host release line |
| Main-service UUID-only global settings update | 3.0.5 |
| AI Agent subscriptions and context queries | 3.2.0; currently enabled only when AU05 is online |
| V3.1 display commands, new manifest and multi-action fields | 3.3.0 |

Set `Software.MinVersion` to cover the features actually required. Do not set it to `3.1.0` merely because that is the protocol version. If deliberately supporting older hosts, feature-gate new commands and verify the fallback in the host. `softwareVersion` is the new startup field for host capability decisions; it is not a plugin version. Parse version components numerically.

The protocol's HTML query examples include `softwareVersion`. Its Node example only shows address, port, and language even though the parser reads a fourth argument. Confirm Node argument ordering against the target host/SDK instead of assuming the incomplete example guarantees an order.

## Devices and asset names

| Product/model | Protocol model | Bundled artwork |
| --- | --- | --- |
| D200 / D200H | `D200` / `D200H` | `assets/devices/d200-bg.png` |
| Dial / D100 | `Dial` | `assets/devices/dial-d100.png` |
| D200X | `D200X` | `d200-bg.png` plus `d200x-dial-area.png` |
| DialMini / D100N | `D100N` | `assets/devices/dialmini.png` |
| Vibe Key / AU05 | `AU05` | `assets/devices/au05.png` |

The supplied `dialmini.png` visibly carries JOBY branding. Confirm that it is the intended DialMini product image before using it in a public release. All bundled device images use the separate `assets/devices/LICENSE`, limited to Ulanzi plugin development and promotion; this does not separately grant trademark rights.

Model strings are case-sensitive in manifests. Product labels and asset filenames are not protocol identifiers. The supplied source's device-filter section lists D100N but omits AU05; its final device enum lists AU05 but omits D100N. This skill recognizes the union of the two documented lists. Verify AU05-specific filtering on the target host before claiming compatibility. An absent/empty `Devices` accepts all models; prefix a model with `~` to exclude it.

`Controllers` selects Keypad or Encoder surfaces; it is independent of the hardware filter. The source documents D200X feedback coordinates as 126x140. It does not document DialMini or AU05 display geometry; do not reuse D200X coordinates or infer input capabilities from a product photo. Verify runtime events and layout support on each target device.

For new D200-series actions, the skill's default is to include the family together: `Devices: ["D200", "D200H", "D200X"]`. Use canonical `D200X` casing even when a user writes D200x. This is a development default, not a protocol requirement or proof of tested support on all three models. Honor explicit narrower targets and verified hardware constraints; preserve intentional existing filters during repairs. Select Keypad/Encoder surfaces through `Controllers` and adapt runtime feedback to actual device capabilities.

### D200X Encoder drag/drop compatibility

Observed on macOS Studio 3.4.4: an Encoder action with `Devices: ["D200X"]` can appear in the action list but fail to drop onto a D200X dial. The examined host drag/drop path checks the legacy `D200` identifier; allowing both `D200X` and `D200` on the affected Encoder actions restored dial assignment in Studio. This is a host compatibility workaround, not a protocol model rename or evidence that a physical D200 has encoders. Other host versions and Windows need their own verification.

The default family filter above includes the required legacy `D200` alias. When repairing an intentionally D200X-only plugin on this affected host, add `D200` to the affected Encoder actions and preserve UUIDs/settings; leave other intentional filters unchanged unless wider support is requested. Broader filters may also expose the action elsewhere, so check visibility and runtime behavior on intended surfaces; use an absent/empty filter only when broad device support is intended. Do not change reported runtime device identities or infer display geometry from this compatibility identifier.

Acceptance requires dragging each Encoder action onto an unused dial slot, confirming that an instance was created, reopening its inspector, and checking its Encoder layout. Validate dial events on connected hardware when available. Action-list visibility and a valid manifest alone do not establish assignability.

## New manifest metadata

- `Description`: short introduction parsed by UGC.
- `Detail`: detailed introduction parsed by UGC; use readable setup/usage paragraphs.
- `Banner`: ordered array of plugin-relative image paths.
- `URL`: optional related link.
- `States[].Name`: required, nonempty state label. An older explanation in the source says the host does not use it; the V3.1 history supersedes that wording.
- `States[].MultiActionImage`: optional image used in multi-actions.
- `SupportedInKeyLogicActions`: whether an action appears in action triggers; documented default is true.

`Overview` is a legacy convention from earlier skill guidance, not a documented V3.1 field. Preserve it only for consumers that explicitly use it. Translate `Description` and `Detail` in present locale files. Keep action/state labels aligned with the manifest's order.

## Selected state execution

New startup/event fields include `isInMultiAction` and `multiActionState` for configured multi-actions. Query parameters arrive as strings: parse booleans explicitly (`"false"` is truthy in JavaScript) and parse/validate the state index. State 0 is valid.

When an action executes in a multi-action with a selected state, apply that state deterministically instead of blindly toggling it. A repeated "start" invocation must not become "stop". Ordinary key actions may retain their intended toggle behavior. Preserve these fields through SDK/event adapters.

## Display updates on host 3.3.0+

All three commands carry the action routing fields inside `param`:

```json
{
  "cmd": "setState",
  "param": {
    "uuid": "com.example.publisher.plugin.toggle",
    "actionid": "instance-id",
    "key": "0_1",
    "state": 0
  }
}
```

`state` selects an index in the action's `States` array. `setTitle` uses the same routing fields and `text` for title content.

`setImage` distinguishes persistent runtime default imagery from temporary display results:

- `isDefault: true` (default) takes an `icons` array whose entries contain `state` and a documented image source.
- `isDefault: false` takes one `icons` object for the current state's temporary image.
- Runtime default imagery is distinct from saved settings and files in the plugin package.
- Consult the source's Icons section for path/base64/GIF/clear forms; do not invent image-source fields or assume an old SDK exposes new wrapper names.

For older hosts, retain the documented legacy `state` payload or compatible SDK helpers. These commands do not replace D200X `setFeedbackLayout` / `setFeedback`.

## Other source inconsistencies

- The rotation example contains `hold—right` with an em dash and a response named `leftrotate` under `dialrotate`. Treat these as source inconsistencies: check target SDK/host events; normalize observed variants at the protocol boundary. Use canonical internal values `left`, `right`, `hold-left`, `hold-right`.
- Some startup examples use lowercase `dial`; this does not redefine the manifest's `Dial` identifier.
- Deprecated `Software.MinimumVersion` appears in a legacy example. Use `Software.MinVersion` for new manifests.
- Sample UUIDs, paths, optional/private flags, and debugging settings are illustrative, not required defaults.
