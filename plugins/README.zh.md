# 内容创作软件插件

[English](README.md)

从所提供 skill 的 `plugins/` 目录收录六个插件，覆盖修图、剪辑、动效和调色。它们是运行时和上位机基线各不相同的参考快照，并非六个全新 V3.1 插件；保留已有版本和 UUID。本次收录没有完成应用或设备运行验收。

| 插件 | 版本 / 动作数 | 入口 | 可参考的实现 |
| --- | --- | --- | --- |
| [Photoshop](com.ulanzi.photoshop.ulanziPlugin/) | 2.2.0 / 19 | `main.js` | UXP 配套扩展、按键/旋钮、图层及参数操作 |
| [Lightroom Classic](com.ulanzi.AdobeLightroomClassic.ulanziPlugin/) | 1.3.1 / 12 | `plugin/app.js` | Node 服务、Lua `.lrplugin` 配套扩展、修图参数与滑块 |
| [After Effects](com.ulanzi.aftereffects.ulanziPlugin/) | 1.0.0 / 5 | `plugin/app.js` | Node + CEP/ExtendScript、参考图层、锚点、表达式与标记 |
| [Premiere Pro](com.ulanzi.premierepro.ulanziPlugin/) | 1.0.1 / 6 | `plugin/app.js` | Node + CEP、时间线、Lumetri 参数及导出 |
| [DaVinci Resolve](com.ulanzi.davinciResolve.ulanziPlugin/) | 1.2.8 / 2 | `plugin/app.py` | Python SDK、色轮交互、浮层及时间线控制 |
| [剪映专业版](com.ulanzi.jianying.ulanziPlugin/) | 1.0.3 / 4 | `plugin/app.py` | Python SDK、快捷键、时间线、滑块及色轮控制 |

## 如何用于创作新插件

让 Agent 阅读对应 manifest 和源码，例如：

> 使用 $ulanzi-plugin，参考 Lightroom 示例的 Node/Lua 通信方式，创作我的修图插件。使用新的插件与动作 UUID，只实现我要求的动作。

按集成方式选择示例。JS skill 和校验器不定义 Python 运行时协议；参考 Python 插件时需核对随附 SDK、启动参数、平台依赖，并在创作新的 Python 实现前取得对应的上位机 Python 协议文档。

## 本地检查与安装

Lightroom、After Effects、Premiere 可在各自插件目录运行 `npm run check`，仅检查入口语法。保留随附 `node_modules/ws` 及许可证，必要时可通过 `npm install` 恢复声明的依赖。Premiere 包含锁文件，可用 `npm ci` 锁定安装。原快照缺少 Lightroom 的 webpack 配置和 After Effects 的版本脚本，因此已将不可执行的命令替换为入口检查。

Photoshop 可运行 `node --check main.js`。其 JavaScript 为打包产物，UXP 扩展以 `uxp-plugin/*.ccx` 提供（内含文件的 ZIP 格式扩展包），未提供原始打包工程。

Python 源码可用 `ast.parse` 做语法检查，这不会导入插件或验证上位机依赖。DaVinci 保留针对 CPython 3.14 的宽松许可 Windows/macOS 依赖，macOS 色轮浮层需[单独安装 PyQt5/Qt](com.ulanzi.davinciResolve.ulanziPlugin/README.md)；剪映随附 Python 通信依赖和原生辅助程序。需使用兼容的 Ulanzi Studio 运行环境，系统 Python 不能替代所需的宿主环境。

按照上位机的插件安装流程安装所选 `.ulanziPlugin` 文件夹。Adobe 集成还需要相应配套扩展：Photoshop UXP、Lightroom 的 `plugin/ulanzi.lrplugin`，或 After Effects/Premiere CEP。运行前先检查安装器与配置；安装配套扩展可能修改应用的用户扩展目录及 CEP 调试设置。具体以各插件源码和已有说明为准。本仓库检查不会运行安装器。

## 发布前尚需处理

- JavaScript 示例使用协议支持的 SVG 图标，`--strict-icons` 的 PNG 交付策略会拒绝这些资源；这本身不代表旧插件不能运行。
- Lightroom、After Effects、Premiere 的旧状态项没有 `Name`，会被 V3.1 校验器拒绝；迁移至 V3.1 时需补齐并本地化状态名。
- Photoshop 仍使用弃用字段 `Software.MinimumVersion`，不能仅根据旧值推定新的最低宿主版本。
- Premiere、剪映随附原生辅助程序，但当前目录没有其源码及构建材料；DaVinci 的编译 `core` 模块也没有对应源码，Photoshop 缺少原始打包工程。因此尚不能宣称全部可从源码重建。
- Premiere 原 README 引用了未随快照提供的 `plugin/native`、测试与验收文档，应视为历史记录，不能作为本仓库可执行的构建步骤；其中的历史实测结论本次也未复验。
- DaVinci 已补齐[第三方许可通知与版本来源](com.ulanzi.davinciResolve.ulanziPlugin/THIRD_PARTY_NOTICES.md)，公开源码快照不再包含 PyQt5/Qt 运行库；macOS 浮层需单独安装依赖。以后若另行分发包含这些依赖的二进制包，须重新满足对应的分发条件。

## 许可证

自有代码和文档采用仓库的 [MIT 许可证](../LICENSE)。第三方版权头、声明、`licenses/`、随附许可证及包元数据均须保留，第三方组件继续适用各自许可证。MIT 不单独授予应用 Logo 或商标许可。插件中若使用了本仓库的设备图片，还需遵循单独的[设备素材许可](../skills/ulanzi-plugin/assets/devices/LICENSE)。
