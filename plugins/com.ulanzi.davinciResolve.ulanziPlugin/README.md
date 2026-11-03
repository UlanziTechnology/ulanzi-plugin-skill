# DaVinci Resolve plugin — source example

Color-wheel and timeline controls for Ulanzi Studio. Entry: `plugin/app.py`. This source snapshot retains the supplied permissively licensed Python/native dependencies and their notices, but excludes PyQt5/Qt runtime packages.

## Runtime and dependency setup

Use the Python interpreter that Ulanzi Studio actually uses to launch this plugin, with the same architecture and ABI. The supplied PyObjC and Windows native files target CPython 3.14; another system interpreter may not load them. The optional `core.cp314-win_amd64.pyd` has a pure-Python fallback in `plugin/app.py`.

Windows uses the included Win32/pywinauto dependencies and can select the existing tkinter or native Win32 overlay fallback. macOS uses the included PyObjC dependencies and **requires separately installed PyQt5/Qt for color-wheel overlays**. Without Qt, that capability is unavailable and the plugin reports a dependency message. Downloading this example does not install the missing runtime or prove full application/device compatibility.

For local macOS development, run this from the plugin folder using the compatible interpreter (replace the interpreter path):

```bash
/path/to/host-compatible/python3.14 -m pip install \
  --index-url https://pypi.org/simple --only-binary=:all: --no-deps \
  --target ./site-packages-macos -r requirements-qt-macos.txt
```

All three Qt runtime dependencies are pinned. The command selects wheels for the executing interpreter's architecture, installs into this plugin rather than the system environment, and does not run automatically. If the embedded host interpreter lacks pip, use a matching CPython 3.14 interpreter and architecture with pip; do not install arbitrary ABI/platform wheels. Restart the plugin through Ulanzi Studio after installation and verify its connection and macOS Accessibility/Screen Recording permissions.

`requirements-macos.txt` and `requirements-windows.txt` document versions of the other supplied dependencies. They are not instructions to overwrite a working runtime environment. Native dependencies and application permissions still require testing on the intended machine.

## Distribution boundary

[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [licenses/](licenses/) contain the license inventory and restored notices with provenance. The first-party code remains MIT; third-party terms remain separate.

The public Git snapshot intentionally excludes the Qt runtime directories. The plugin-local `.gitignore` also excludes them if installed locally. **Git ignore rules do not apply to manually created ZIP archives.** Do not describe a ZIP containing locally installed PyQt5/Qt as the no-Qt source example. Either distribute the source example without those packages and retain these setup instructions, or arrange a separate binary release that complies with its upstream licenses, including any corresponding-source duties.

Before publishing the source snapshot, run the offline distribution check from the plugin folder:

```bash
python3 scripts/check_distribution.py
```

It verifies versioned license hashes, catches dependencies without notices, and rejects locally installed PyQt5/Qt packages. It does not certify licensing of a different binary bundle or run the plugin.

## 中文说明

本插件提供 DaVinci Resolve 色轮与时间线控制，入口为 `plugin/app.py`。公开源码快照保留已有宽松许可依赖及其许可通知，移除了 PyQt5/Qt 运行库；原有已安装 skill 未作修改。

macOS 色轮浮层需要自行安装 PyQt5/Qt。请从插件目录执行上方命令，并将解释器替换为与 Ulanzi Studio 启动插件的 Python 相同版本和架构的解释器。当前随附原生依赖针对 CPython 3.14；如果上位机解释器没有 pip，可使用同版本、同架构且带 pip 的解释器安装到指定目录。安装后重启插件并检查辅助功能、屏幕录制权限；缺少 Qt 时，色轮浮层功能不可用，不能将此源码示例描述为 macOS 开箱即用的完整安装包。

第三方许可全文与来源校验信息见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本地安装依赖不会将其变为 MIT，也不代表可以直接重新分发。`.gitignore` 只约束 Git，手动 ZIP 不会自动排除这些文件。公开分发时保留无 Qt 的源码边界；若另行制作包含 PyQt5/Qt 的二进制发布包，须按相应许可落实源码提供及其他义务，或取得适用的商业授权。

发布此源码快照前，在插件目录运行 `python3 scripts/check_distribution.py`，检查许可通知与版本、文件校验值，以及 Qt 运行库排除边界。检查不会运行插件，也不能替代另行制作二进制发布包时的许可核对。
