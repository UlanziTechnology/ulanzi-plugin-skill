# Third-party notices

The plugin's first-party source and documentation use [MIT](LICENSE). The components below retain their own copyright notices and licenses. No upstream code or binary is relicensed by the plugin's MIT license.

## Included components

| Component | Snapshot version | License notices |
| --- | --- | --- |
| comtypes | 1.4.16 | [MIT](licenses/comtypes-1.4.16/LICENSE.txt) |
| pywin32 | 311 | Upstream component-specific notices: [win32](licenses/pywin32-311/win32/license.txt), [win32com](licenses/pywin32-311/win32com/License.txt), [Pythonwin](licenses/pywin32-311/pythonwin/license.txt) |
| pywinauto | 0.6.9 | [BSD 3-clause](licenses/pywinauto-0.6.9/LICENSE.txt) |
| six | 1.17.0 | [MIT](licenses/six-1.17.0/LICENSE.txt) |
| websocket-client | 1.9.0 | [Apache-2.0](licenses/websocket-client-1.9.0/LICENSE.txt) |
| pyobjc-core | 12.2.1 | [MIT](licenses/pyobjc-core-12.2.1/License.txt) |
| pyobjc-framework-ApplicationServices | 12.2.1 | [MIT](licenses/pyobjc-framework-ApplicationServices-12.2.1/License.txt) |
| pyobjc-framework-Cocoa | 12.2.1 | [MIT](licenses/pyobjc-framework-Cocoa-12.2.1/LICENSE.txt) |
| pyobjc-framework-CoreText | 12.2.1 | [MIT](licenses/pyobjc-framework-CoreText-12.2.1/LICENSE.txt) |
| pyobjc-framework-Quartz | 12.2.1 | [MIT](licenses/pyobjc-framework-Quartz-12.2.1/LICENSE.txt) |
| Ulanzi plugin-common-python (`libs/ulanzi_api`) | Supplied source snapshot; version not recorded | [MIT](licenses/plugin-common-python/LICENSE), [upstream](https://github.com/UlanziTechnology/plugin-common-python) |
| Ulanzi plugin-common-html (`libs/js`) | Supplied source snapshot; version not recorded | [Apache-2.0](licenses/plugin-common-html/LICENSE), [upstream](https://github.com/UlanziTechnology/plugin-common-html) |

Existing in-package license files and source headers are retained. Missing PyObjC notices were restored from their exact-version PyPI source distributions. pywin32 notices for included win32, win32com, and Pythonwin components were restored from the 311 CPython 3.14 Windows x86-64 wheel. The separate adodbapi component is not included in this trimmed snapshot. The restored source archives were checked against PyPI SHA-256 digests before extracting notices. [provenance.json](licenses/provenance.json) records archive URLs, archive hashes, license hashes, and upstream member paths; retained notices are identified separately from restored ones. The SDK license records do not assert that the supplied SDK code is identical to current upstream main.

The included PyObjC native modules link to macOS's system `libffi.dylib`; this snapshot does not bundle a separate libffi library or source tree. Preserve the complete PyObjC notice, including its distinction between PyObjC and libffi.

## PyQt5 and Qt: not redistributed

The public snapshot excludes the following installed packages, including their Python modules, native libraries, Qt frameworks/plugins, and distribution metadata:

- PyQt5 5.15.11
- PyQt5-Qt5 5.15.19
- PyQt5-sip 12.18.0

PyQt5's upstream release is available under GPL v3 or a commercial license; it is not MIT. The previous binary bundle was removed rather than distributed without corresponding-source arrangements. This repository does not offer a source-code link as a substitute for the obligations of redistributing those binaries: it no longer supplies them.

macOS color-wheel overlays still require a separately obtained PyQt5/Qt environment. [README.md](README.md) explains the pinned dependency installation. Local installation does not include those packages in this repository or grant permission to repackage them under MIT. Anyone creating a binary distribution with PyQt5/Qt must separately satisfy the applicable upstream licenses, including corresponding-source requirements where applicable, or obtain an appropriate commercial license.

Upstream versioned releases: [PyQt5 5.15.11](https://pypi.org/project/PyQt5/5.15.11/), [PyQt5-Qt5 5.15.19](https://pypi.org/project/PyQt5-Qt5/5.15.19/), [PyQt5-sip 12.18.0](https://pypi.org/project/PyQt5-sip/12.18.0/). `requirements-qt-macos.txt` records versions only; it is not a redistribution license or a claim to provide the complete corresponding source of a Qt binary bundle.

DaVinci Resolve is a Blackmagic Design product. Product names and trademarks identify the integration and do not imply endorsement.
