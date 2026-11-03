# Ulanzi Plugin Skill

**把你的工作流，变成一个按键或一次旋转。**

[English](README.md) · [安装](#安装) · [开始使用](#开始使用) · [创作软件](#创作软件)

Ulanzi Plugin Skill 是一个面向 **Ulanzi Studio 插件创作**的开源项目，包含 Agent Skill、插件协议、开发工具和内容创作软件插件示例。

把常用操作变成一键触发，把精细调节交给旋钮。和 AI 编程助手一起，将你的想法做成专属 Ulanzi 插件：为修图、剪辑、调色打造顺手的控制方式，或创作一个解决日常需求的小工具，让设备真正融入你的工作流。

## 安装

### Skills CLI（推荐）

已安装 Node.js（含 `npx`）和 Git 时，在你的插件开发项目目录运行：

```bash
npx skills add https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/skill --skill ulanzi-plugin
```

选择要使用的编程助手；默认安装到当前项目，跨项目使用可追加 `--global`。只安装到 Codex 可追加 `--agent codex`，Claude Code 可追加 `--agent claude-code`。参数说明见 [Skills CLI 文档](https://github.com/vercel-labs/skills/blob/main/docs/commands.md)。

### Codex 对话安装

```text
使用 $skill-installer，从 https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/skill
安装轻量分支根目录（path 为 .）的 skill，安装名设为 ulanzi-plugin。
```

<details>
<summary>手动安装到 Codex 用户级技能目录</summary>

**macOS / Linux**

```bash
git clone --depth 1 --branch skill https://github.com/UlanziTechnology/ulanzi-plugin-skill.git "$HOME/.agents/skills/ulanzi-plugin"
```

**Windows PowerShell**

```powershell
$skillPath = Join-Path $HOME '.agents/skills/ulanzi-plugin'
git clone --depth 1 --branch skill https://github.com/UlanziTechnology/ulanzi-plugin-skill.git $skillPath
```

已有同名目录时，先比较或备份。当前 [Codex 官方文档](https://developers.openai.com/codex/skills/)列出的用户级目录为 `~/.agents/skills/`，项目级目录为 `.agents/skills/`。其他编程助手按各自规则加载包含 `SKILL.md` 的完整目录，保留相邻的脚本、参考文档和素材。插件示例单独按需下载。

</details>

推荐命令指向自动生成的 **`skill` 轻量分支**，安装内容只有协议、脚本、说明和设备素材，约 **1.4 MiB**。六个插件及其依赖保留在主分支 `plugins/`，不随 skill 安装。GitHub 安装需先发布该分支，辅助脚本所需 Python 3.9+ 仅在运行脚本时需要。

使用普通 `UlanziTechnology/ulanzi-plugin-skill --skill ulanzi-plugin` 也能从主分支发现 `skills/ulanzi-plugin/`，但 CLI 的 Git 路径可能先下载整个主分支；想减少下载量，请使用上面的轻量分支地址。

**确认安装**：在编程助手中新建对话，尝试调用 `ulanzi-plugin`。Codex CLI 可用 `/skills` 查看，或在输入框输入 `$ulanzi-plugin`；若未显示，重启后重试。然后发送下一步的创作需求。

### 更新 skill

通过 Skills CLI 安装后，可从记录的来源更新这个 skill：

```bash
npx skills update ulanzi-plugin
```

全局安装使用：

```bash
npx skills update ulanzi-plugin --global
```

手动安装且没有 Skills CLI 来源记录时，先比较或备份本地修改，再执行上方轻量分支的 `npx skills add` 命令；用户级安装追加 `--global`。更新后新开会话，或让助手重新读取 `SKILL.md`。单独下载的插件示例不会随这些命令更新。

## 开始使用

从一个具体需求开始，让助手完成动作、配置界面、显示反馈和使用说明；也可以为已有插件增加交互、修复问题或准备发布包。

### 创作第一个插件

在插件开发工作区中调用 `$ulanzi-plugin`，说清楚目标设备、动作和预期反馈。例如：

```text
使用 $ulanzi-plugin，创建一个 Ulanzi Studio 专注计时器插件。

设备：D200 的按键。
交互：短按开始或暂停，按住 1 秒重置。
显示：剩余分钟和秒数，暂停时显示暂停状态。
设置：时长默认 25 分钟，可在配置界面修改。
交付：可加载的 .ulanziPlugin 文件夹、图标和中文使用说明。
```

也可以指定参考插件和集成方式。创作新插件时使用新的插件与动作 UUID；二次开发时保留所需的上游版权说明。

### 加载与迭代

根据生成的说明，在 Ulanzi Studio 中加载插件、配置动作，并在设备上验证交互。将实际效果、错误日志或新的想法反馈给助手，继续完善。

编程助手可以生成代码和执行静态检查；应用连接、系统权限与设备手感仍需要在实际环境中验证。

### 创作软件

如果希望把修图、剪辑、动效或调色工作流接到 Ulanzi 设备，可以从以下创作插件中选择参考。描述需求时，请补充目标软件及版本、常用操作，以及希望通过按键或旋钮完成的交互。

| 插件 | 功能方向 | 可以参考什么 |
| --- | --- | --- |
| [Adobe Photoshop](https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/main/plugins/com.ulanzi.photoshop.ulanziPlugin/) | 图层、工具和图像调整 | UXP 配套扩展与按键/旋钮控制 |
| [Adobe Lightroom Classic](https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/main/plugins/com.ulanzi.AdobeLightroomClassic.ulanziPlugin/) | 基础调整、曲线、HSL 与滑块 | Node 主服务与 Lua 插件通信 |
| [Adobe After Effects](https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/main/plugins/com.ulanzi.aftereffects.ulanziPlugin/) | 参考图层、锚点、表达式与标记 | CEP / ExtendScript 集成 |
| [Adobe Premiere Pro](https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/main/plugins/com.ulanzi.premierepro.ulanziPlugin/) | 时间线、Lumetri 与导出 | CEP 桥接、连续旋钮事件与任务队列 |
| [DaVinci Resolve](https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/main/plugins/com.ulanzi.davinciResolve.ulanziPlugin/) | 色轮与时间线控制 | Python SDK、界面交互与浮层反馈 |
| [剪映专业版](https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/main/plugins/com.ulanzi.jianying.ulanziPlugin/) | 快捷键、时间线、滑块与色轮 | Python SDK 与平台输入适配 |

例如，为剪辑工作流创作插件：

```text
使用 $ulanzi-plugin，参考 Premiere Pro 示例，创作一个时间线控制插件。

先实现播放头移动和时间线缩放两个旋钮动作。
使用新的插件与动作 UUID，并提供配置说明。
请先核对示例的桥接方式、依赖和源码完整度，再决定复用哪些部分。
```

Skill 主要指导 JS 插件协议 V3.1.0 的 JavaScript 开发；DaVinci 和剪映示例使用 Python，需参考各自的 SDK 与运行环境。Adobe 集成还可能需要 UXP、CEP 或 Lua 配套扩展，具体安装说明见[插件目录](https://github.com/UlanziTechnology/ulanzi-plugin-skill/blob/main/plugins/README.zh.md)。

#### 按需下载示例

默认安装不包含插件代码。告诉助手“参考 Premiere 示例”时，skill 会引导它只获取需要的插件；也可以手动运行。以下命令假设 skill 已按项目级安装到 `.agents/skills/ulanzi-plugin`：

```bash
# 查看六个示例的下载 ID，不访问网络
python3 .agents/skills/ulanzi-plugin/scripts/fetch_example.py --list

# 只下载 Premiere 插件到当前工作区
python3 .agents/skills/ulanzi-plugin/scripts/fetch_example.py premiere --dest ./plugin-examples
```

可选 ID：`photoshop`、`lightroom`、`aftereffects`、`premiere`、`davinci`、`jianying`。全局安装时替换脚本路径；完整源码仓库中的路径为 `skills/ulanzi-plugin/scripts/fetch_example.py`。

下载工具需要 Git 和 Python 3.9+，使用部分克隆与稀疏检出，仅获取所选插件及其自带依赖，并保留许可证。`--ref` 可指定主分支之外的源分支或标签。已有目标目录不会被覆盖；下载不会安装插件或运行配套扩展。下载内容留在工作区，保持 skill 安装目录轻量。详见[示例获取说明](references/examples.md)。

示例保留各自的版本与运行时，并未统一迁移到 V3.1。部分原生辅助程序或打包工程尚缺构建源码；依赖、安装说明及完整度见[插件目录说明](https://github.com/UlanziTechnology/ulanzi-plugin-skill/blob/main/plugins/README.zh.md)。

## 设备与兼容性

提供 D200、D200H、Dial / D100、D200X、**DialMini / D100N** 和 **Vibe Key / AU05** 的设备标识与适配参考。具体功能取决于设备控制类型、上位机版本和插件实现。

协议版本与 Ulanzi Studio 版本不同：V3.1 新能力对应上位机 3.3.0；AI Agent 订阅对应 3.2.0，且协议当前注明需 AU05 在线。详细版本要求、设备标识及协议歧义见[兼容说明](references/protocol-v3.1-notes.md)。

## 参与贡献

欢迎通过 [Issue](https://github.com/UlanziTechnology/ulanzi-plugin-skill/issues) 反馈问题，或提交 PR 改进插件、文档和翻译。

## 许可证

自有代码和文档采用 [MIT](LICENSE)。第三方 SDK 与依赖继续适用各自许可证。

设备图片单独采用[设备素材许可](assets/devices/LICENSE)，仅限 Ulanzi 插件开发与宣传，允许用于商业 Ulanzi 插件；分发素材或修改版本时须附带许可。素材许可不单独授予商标权，也不表示相关应用品牌认可。
