# Ulanzi Plugin Skill

**Turn your workflow into a key press or a dial turn.**

[简体中文](README.md) · [Installation](#installation) · [Usage](#usage) · [Creative applications](#creative-applications)

Ulanzi Plugin Skill is an open-source project for **creating Ulanzi Studio plugins**, with an agent skill, protocol documentation, development helpers, and creative application plugin examples.

Put everyday actions a key press away and fine adjustments on a dial. Work with an AI coding assistant to turn your ideas into custom Ulanzi plugins: build hands-on controls for photo editing, video editing, and color grading, or create a small tool that makes your day easier. Make the device part of your workflow.

## Installation

### Skills CLI (recommended)

With Node.js (including `npx`) and Git installed, run this in your plugin development project:

```bash
npx skills add https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/skill --skill ulanzi-plugin
```

Select your coding assistant. Installation is project-scoped by default; append `--global` to use the skill across projects. To target Codex only, append `--agent codex`; for Claude Code, use `--agent claude-code`. See the [Skills CLI reference](https://github.com/vercel-labs/skills/blob/main/docs/commands.md) for options.

### Install through a Codex conversation

```text
Use $skill-installer to install the skill at the lightweight branch root (path: .)
from https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/skill.
Set the installation name to ulanzi-plugin.
```

<details>
<summary>Manual installation into the Codex user skills directory</summary>

**macOS / Linux**

```bash
git clone --depth 1 --branch skill https://github.com/UlanziTechnology/ulanzi-plugin-skill.git "$HOME/.agents/skills/ulanzi-plugin"
```

**Windows PowerShell**

```powershell
$skillPath = Join-Path $HOME '.agents/skills/ulanzi-plugin'
git clone --depth 1 --branch skill https://github.com/UlanziTechnology/ulanzi-plugin-skill.git $skillPath
```

Compare or back up an existing directory before replacing it. Current [OpenAI documentation for Codex](https://developers.openai.com/codex/skills/) lists `~/.agents/skills/` for user skills and `.agents/skills/` for project skills. Other coding assistants should load the complete skill folder according to their conventions, preserving scripts, references, and assets alongside `SKILL.md`. Plugin examples are downloaded separately.

</details>

The recommended command uses the generated **`skill` lightweight branch**: approximately **1.4 MiB** of protocol documentation, helpers, instructions, and device artwork. The six plugins and their dependencies remain under `plugins/` on the main branch and are not installed with the skill. Publish the lightweight branch before using its GitHub URL. Python 3.9+ is needed only when running the helper scripts.

The shorthand `UlanziTechnology/ulanzi-plugin-skill --skill ulanzi-plugin` also discovers `skills/ulanzi-plugin/` on main, but the CLI's Git path may first download the entire main branch. Use the lightweight branch URL above to reduce transfer size as well as installed size.

**Verify installation:** start a new conversation in your coding assistant and try invoking `ulanzi-plugin`. In Codex CLI, use `/skills` or type `$ulanzi-plugin` in the prompt. If it does not appear, restart and try again. Then send the creation request below.

## Usage

Start with a specific idea and ask the assistant to build actions, settings UI, display feedback, and user instructions. You can also extend an existing plugin, repair a problem, or prepare a package for release.

### Create your first plugin

Invoke `$ulanzi-plugin` in your plugin development workspace. Specify the target device, interaction, and expected feedback:

```text
Use $ulanzi-plugin to create a focus timer for Ulanzi Studio.

Device: a D200 key.
Interaction: press to start or pause; hold for one second to reset.
Display: minutes and seconds remaining, with a paused indicator.
Settings: a configurable duration, defaulting to 25 minutes.
Deliver: a loadable .ulanziPlugin folder, icons, and user instructions.
```

You can also name a reference plugin and integration pattern. Assign new plugin/action UUIDs for a new creation, and preserve required upstream copyright notices when adapting code.

### Load and iterate

Follow the generated instructions to load the plugin in Ulanzi Studio, configure its actions, and try it on your device. Share the results, error logs, or new ideas with the assistant to refine it.

A coding assistant can generate code and run static checks. Application connections, system permissions, and device interaction still need verification in your environment.

### Creative applications

To connect your photo editing, video editing, motion graphics, or color grading workflow to a Ulanzi device, use the following creative application plugins as references. Specify the target application and version, common operations, and the interactions you want on keys or dials.

| Plugin | Focus | Reference patterns |
| --- | --- | --- |
| [Adobe Photoshop](https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/main/plugins/com.ulanzi.photoshop.ulanziPlugin/) | Layers, tools, and image adjustments | UXP companion and key/dial controls |
| [Adobe Lightroom Classic](https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/main/plugins/com.ulanzi.AdobeLightroomClassic.ulanziPlugin/) | Basic adjustments, curves, HSL, and sliders | Node main service communicating with a Lua plugin |
| [Adobe After Effects](https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/main/plugins/com.ulanzi.aftereffects.ulanziPlugin/) | Reference layers, anchor points, expressions, and markers | CEP / ExtendScript integration |
| [Adobe Premiere Pro](https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/main/plugins/com.ulanzi.premierepro.ulanziPlugin/) | Timeline, Lumetri, and export | CEP bridge, continuous dial events, and task queues |
| [DaVinci Resolve](https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/main/plugins/com.ulanzi.davinciResolve.ulanziPlugin/) | Color wheels and timeline controls | Python SDK, UI interaction, and overlay feedback |
| [Jianying Pro](https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/main/plugins/com.ulanzi.jianying.ulanziPlugin/) | Shortcuts, timeline, sliders, and color wheels | Python SDK and platform input adapters |

For example, create a plugin for an editing workflow:

```text
Use $ulanzi-plugin to create a timeline control plugin based on the Premiere Pro example.

Start with two dial actions: playhead movement and timeline zoom.
Assign new plugin/action UUIDs and provide configuration instructions.
Check the example's bridge, dependencies, and source completeness before choosing what to reuse.
```

The skill primarily guides JavaScript development with JS plugin protocol V3.1.0. DaVinci and Jianying use Python with their own SDKs and runtime requirements. Adobe integrations may also need a UXP, CEP, or Lua companion; see the [plugin directory](https://github.com/UlanziTechnology/ulanzi-plugin-skill/blob/main/plugins/README.md) for installation details.

#### Download examples on demand

Plugin source is not installed by default. Ask the assistant to reference an example, and the skill guides it to fetch only the one needed. For manual use, these commands assume a project-scoped installation at `.agents/skills/ulanzi-plugin`:

```bash
# List the six example IDs without network access
python3 .agents/skills/ulanzi-plugin/scripts/fetch_example.py --list

# Download only the Premiere plugin into your workspace
python3 .agents/skills/ulanzi-plugin/scripts/fetch_example.py premiere --dest ./plugin-examples
```

Available IDs: `photoshop`, `lightroom`, `aftereffects`, `premiere`, `davinci`, `jianying`. Adjust the script path for a global install; in a full source checkout it is `skills/ulanzi-plugin/scripts/fetch_example.py`.

The helper needs Git and Python 3.9+. It uses partial clone and sparse checkout to fetch the selected plugin with its bundled dependencies and license files. Use `--ref` to select another source branch or tag. Existing destination folders are never overwritten; downloading does not install a plugin or run its companion installers. Keep downloads in the workspace so the installed skill stays small. See [example download notes](references/examples.md).

Examples retain their own versions and runtimes and have not all migrated to V3.1. Some native helpers or bundled projects lack build sources. See the [plugin directory notes](https://github.com/UlanziTechnology/ulanzi-plugin-skill/blob/main/plugins/README.md) for dependencies, installation details, and source completeness.

## Devices and compatibility

Device identifiers and adaptation references cover D200, D200H, Dial / D100, D200X, **DialMini / D100N**, and **Vibe Key / AU05**. Available features depend on the control surface, host version, and plugin implementation.

Protocol and Ulanzi Studio versions are different: V3.1 additions correspond to host 3.3.0; AI Agent subscriptions correspond to 3.2.0 and currently require an online AU05 according to the protocol. See the [compatibility notes](references/protocol-v3.1-notes.md) for feature requirements, device identifiers, and source ambiguities.

## Contributing

Report problems in [Issues](https://github.com/UlanziTechnology/ulanzi-plugin-skill/issues), or submit a PR to improve plugins, documentation, and translations.

## License

First-party code and documentation use [MIT](LICENSE). Third-party SDKs and dependencies retain their respective licenses.

Device images use a separate [artwork license](assets/devices/LICENSE), limited to Ulanzi plugin development and promotion, including commercial Ulanzi plugins. Include that license when redistributing original or modified artwork. It does not separately grant trademark rights or imply endorsement by the application brands depicted.
