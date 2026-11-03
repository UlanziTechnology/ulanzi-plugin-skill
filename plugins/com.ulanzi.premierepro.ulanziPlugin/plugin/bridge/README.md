# Premiere CEP bridge / 开发版安装

此桥接只监听 `127.0.0.1:49631`。Ulanzi 主服务生成 `%USERPROFILE%\.ulanzi-premiere\bridge.json`（macOS 为 `~/.ulanzi-premiere/bridge.json`），CEP 使用内置 Node 的 `os.homedir()` 读取同一文件。文件中含随机配对令牌，不要提交、共享或记录其内容。POSIX 权限为 0600，Windows 使用当前用户配置目录的继承 ACL；此桥接不是同一用户下恶意本地程序的安全隔离边界。

`ULZI_PR_BRIDGE_PORT` 可显式更改主服务监听端口；CEP 自动读取配对文件。固定端口冲突时主服务报 `PORT_IN_USE`，不会强占已有进程。测试可传入独立的 `pairingPath`、`port: 0`，不影响真实配对。

## 安装 CEP 扩展

Ulanzi 主服务初始化时调用 `initializeCep()`：先用 `ensureCepInstalled()` 安装或更新插件内附带的 CEP 文件，再自动开启当前用户的未签名扩展加载。文件安装以完整文件列表及 SHA-256 检查内容，一致则不写入；有变化则校验暂存副本、备份旧目录、替换并核对，失败恢复旧副本。文件操作只处理本扩展，不修改其他扩展文件或 PR 进程。安装失败通过配置页连接状态和主服务日志报告，修复后重启 Ulanzi 重试。PR 已运行时，安装文件或调试设置变化后需保存工程并重启 PR。

以下手动脚本保留作安装修复及显式开启开发调试的工具，正常初始化无需单独运行：

从本插件的 `plugin/scripts` 运行：

- Windows：`powershell -NoProfile -File .\install-cep.ps1`
- macOS：`sh ./install-cep.sh`

脚本只复制此 CEP 扩展到当前用户的 Adobe CEP 扩展目录，不安装 Ulanzi 插件、不关闭 Premiere。已有扩展会移到同级 `Adobe/CEP/UlanziBackups` 文件夹，可手动恢复。更新时请停止设备操作；安装后保存工程并重启 Premiere，加载的旧代码不会因文件复制而热更新。新版自动在后台启动和连接，不需要打开窗口。

可选诊断入口：“窗口 → 扩展（或扩展〔旧版〕）→ Ulanzi Premiere Bridge Diagnostics”。诊断面板只通过 CEP 事件查询状态和转发用户的重连点击，不创建 WebSocket、不读取令牌、不调用 JSX；关闭面板不影响后台。手动打开诊断时会请求加载后台作为故障恢复后备，但正常启动不依赖此入口。

后台扩展 ID 保持 `com.ulanzi.premierepro.bridge`，使用 `Type=Custom`、`AutoVisible=false` 和 Premiere 的 `com.adobe.csxs.events.ApplicationActivate` 启动事件；诊断扩展为 `.diagnostics`。后台使用 CEP 独立 Node 上下文 `cep_node.require`（不使用 `--mixed-context`），只在后台启用 Node。依据 Adobe CEP 12 Cookbook 的隐形扩展及 Node 集成规则实现；实际宿主冷启动行为仍需真机验证。

当前为**未签名版本**，参考 AE 插件自动开启调试设置。初始化检查当前用户 CSXS 10/11/12 的 `PlayerDebugMode`，缺失或未启用时设置字符串 `1` 并回读确认；已开启则跳过写入。Windows 使用系统 `reg.exe` 写 HKCU，macOS 使用 `/usr/bin/defaults` 写用户偏好设置；每条命令最多 5 秒，不启动 shell、不显示命令行窗口。查询超时或临时进程资源错误立即重试一次，权限错误不立即重试。任一版本失败都返回 `CEP_DEBUG_MODE_FAILED`，配置页八语言提示，日志注明失败版本、原因及 code/signal/killed；不会因其他版本成功而误报全部成功。设置失败保留已经安装的 CEP 文件。

初始化检查失败后，连接监视器在后台复查，仍失败时每 10 秒再试；同一时刻只有一次复查。只有所有版本设置都回读成功才清除错误，即使 CEP 已连接也不能仅凭连接隐藏实际设置问题。复查成功向配置页发布当前连接状态；关闭服务时清除复查定时器、忽略迟到结果。CEP 文件安装失败不通过此复查清除。

调试设置影响当前用户对应版本的所有 CEP 扩展。恢复默认时手动移除相应 `PlayerDebugMode` 值；下次启动本插件会再次启用。手动修复脚本的 Windows `-EnableDebug` / macOS `--enable-debug` 参数仍保留，作用于 CSXS 11/12。本流程不生成签名。macOS 偏好缓存和实际 CEP 加载仍需实机验收，必要时注销后重新登录。

## 运行和安全策略

- 只接受拥有配对令牌的本机 PPRO CEP 客户端，拒绝 HTTP/HTTPS 网页 Origin；只有一个已认证 CEP 会话，后来的会话不能接管。
- 只暴露 `capabilities`、`exportInfo`、`queueExport`、`timelineJog`、`trimControl`、`timelineZoom`、`parameterDial`。不提供任意脚本执行 RPC。
- Node 队列单请求串行，最多 32 项，JSON 大小 64 KiB；关闭压缩。每次调用使用独立 ID，未知/迟到结果不能完成另一项请求。
- 超时或发送状态不确定后，立即取消未发送队列，关闭连接；**不自动重试修改工程的操作**。用户检查工程与导出队列后，在诊断面板主动重连。若 evalScript 仍在运行，重连按钮不可用，需等待或检查 Premiere。
- 断线期间的请求立即失败，不缓存到重连后执行。普通空闲断线按 0.5–10 秒退避重连。
- CEP 的参数提示仅在已打开的诊断面板显示，约 2.2 秒自动隐藏，不是 Premiere 全局 toast，也不会自动打开面板、弹出模态对话框或抢焦点。

## Node API

`new PremiereBridge(options)` → `start()` / `stop()`；监听 `status` 事件，读取 `.connected` 和 `.status`。`request(action, settings, payload, { timeoutMs })` 返回 host result，失败为带 `.code` 的 Error。`notifyStatus(parameter, name, value)` 仅发面板提示，不修改工程。

`requireRecovery(code, message, details?)` 用于主服务发现不确定结果时主动停止桥接并要求人工检查后重连。Host 返回 `PARTIAL_MUTATION`、`EXPORT_QUEUE_REJECTED` 或 `RESULT_UNKNOWN` 时桥接也会同步停机，阻止排队中的后续修改先于错误处理发送。

ExtendScript 入口是 `$._ulanziPremiere.dispatch(requestJson)`，返回 `{ok:true,result}` 或 `{ok:false,error:{code,message,details}}` 的 JSON 字符串。数据经过 JSON 字符串双层编码，不能拼接成任意执行代码。

第三方 `CSInterface.js` 来自官方 Adobe-CEP/Samples 的 PProPanel，原始文件和 MIT LICENSE 均保留在 CEP 的 `lib/` 中。桥接的单元测试只证明协议和队列行为，不证明 Premiere DOM 的真实效果。
