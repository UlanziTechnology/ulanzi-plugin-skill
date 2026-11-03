/* Read-only diagnostics. Only the invisible extension owns the bridge connection. */
(function () {
  'use strict';
  var backgroundId = 'com.ulanzi.premierepro.bridge';
  var diagnosticsId = backgroundId + '.diagnostics';
  var eventNames = { request: backgroundId + '.statusRequest', status: backgroundId + '.status', reconnect: backgroundId + '.reconnectRequest' };
  var keys = ['description', 'starting', 'unavailable', 'reconnect', 'refresh', 'footer', 'recovery', 'runtimeError'];
  var texts = {
    en: ['The bridge connects automatically in the background. This panel is only for diagnostics.', 'Waiting for the background bridge…', 'The background bridge has not responded. Restart Premiere Pro after installing the extension, then refresh the status.', 'Reconnect', 'Refresh status', 'You can close this panel. The background bridge continues running without a visible window.', 'Before reconnecting, check Premiere and the export queue. An interrupted operation may have completed; do not repeat it without checking.', 'Open this diagnostics panel inside Premiere Pro.'],
    zh_CN: ['桥接会在后台自动连接；此面板仅用于排查连接问题。', '正在等待后台桥接…', '后台桥接未响应。安装扩展后请重启 Premiere Pro，再刷新状态。', '重新连接', '刷新状态', '可以关闭此面板，后台桥接仍会运行，不占用可见窗口。', '重新连接前，请检查 Premiere 和导出队列。中断的操作可能已完成，确认前不要重复操作。', '请在 Premiere Pro 中打开此诊断面板。'],
    zh_HK: ['橋接會在背景自動連線；此面板僅用於排查連線問題。', '正在等待背景橋接…', '背景橋接未回應。安裝擴充功能後請重新啟動 Premiere Pro，再重新整理狀態。', '重新連線', '重新整理狀態', '可以關閉此面板，背景橋接仍會執行，不佔用可見視窗。', '重新連線前，請檢查 Premiere 和匯出佇列。中斷的操作可能已完成，確認前不要重複操作。', '請在 Premiere Pro 中開啟此診斷面板。'],
    de_DE: ['Die Brücke verbindet sich automatisch im Hintergrund. Dieses Bedienfeld dient nur der Diagnose.', 'Warten auf die Hintergrundbrücke…', 'Die Hintergrundbrücke antwortet nicht. Starten Sie Premiere Pro nach der Installation der Erweiterung neu und aktualisieren Sie den Status.', 'Neu verbinden', 'Status aktualisieren', 'Sie können dieses Bedienfeld schließen. Die Hintergrundbrücke läuft ohne sichtbares Fenster weiter.', 'Prüfen Sie vor dem erneuten Verbinden Premiere und die Exportwarteschlange. Ein unterbrochener Vorgang kann abgeschlossen sein; wiederholen Sie ihn nicht ungeprüft.', 'Öffnen Sie dieses Diagnosebedienfeld in Premiere Pro.'],
    es_ES: ['El puente se conecta automáticamente en segundo plano. Este panel es solo para diagnóstico.', 'Esperando al puente en segundo plano…', 'El puente en segundo plano no responde. Reinicia Premiere Pro tras instalar la extensión y actualiza el estado.', 'Reconectar', 'Actualizar estado', 'Puedes cerrar este panel. El puente sigue funcionando en segundo plano sin una ventana visible.', 'Antes de reconectar, comprueba Premiere y la cola de exportación. Una operación interrumpida puede haber finalizado; no la repitas sin comprobarlo.', 'Abre este panel de diagnóstico dentro de Premiere Pro.'],
    ja_JP: ['ブリッジはバックグラウンドで自動接続します。このパネルは診断専用です。', 'バックグラウンドブリッジを待機中…', 'バックグラウンドブリッジが応答しません。拡張機能のインストール後に Premiere Pro を再起動し、状態を更新してください。', '再接続', '状態を更新', 'このパネルは閉じても構いません。バックグラウンドブリッジはウィンドウを表示せずに動作を続けます。', '再接続する前に Premiere と書き出しキューを確認してください。中断した操作が完了している場合があります。確認せずに繰り返さないでください。', 'Premiere Pro 内でこの診断パネルを開いてください。'],
    ko_KR: ['브리지가 백그라운드에서 자동으로 연결됩니다. 이 패널은 진단 전용입니다.', '백그라운드 브리지 대기 중…', '백그라운드 브리지가 응답하지 않습니다. 확장 기능 설치 후 Premiere Pro를 다시 시작하고 상태를 새로 고치세요.', '다시 연결', '상태 새로 고침', '이 패널을 닫아도 됩니다. 백그라운드 브리지는 창을 표시하지 않고 계속 실행됩니다.', '다시 연결하기 전에 Premiere와 내보내기 대기열을 확인하세요. 중단된 작업이 완료되었을 수 있으므로 확인 없이 반복하지 마세요.', 'Premiere Pro 안에서 이 진단 패널을 여세요.'],
    pt_PT: ['A ponte liga-se automaticamente em segundo plano. Este painel serve apenas para diagnóstico.', 'À espera da ponte em segundo plano…', 'A ponte em segundo plano não respondeu. Reinicie o Premiere Pro após instalar a extensão e atualize o estado.', 'Voltar a ligar', 'Atualizar estado', 'Pode fechar este painel. A ponte continua a funcionar em segundo plano sem uma janela visível.', 'Antes de voltar a ligar, verifique o Premiere e a fila de exportação. Uma operação interrompida pode ter terminado; não a repita sem verificar.', 'Abra este painel de diagnóstico no Premiere Pro.']
  };
  var language = (navigator.language || 'en').replace('-', '_');
  try { language = JSON.parse(window.__adobe_cep__.getHostEnvironment()).appUILocale || language; } catch (_) {}
  if (/^zh/i.test(language)) language = /TW|HK|Hant/i.test(language) ? 'zh_HK' : 'zh_CN';
  if (!texts[language]) {
    var prefix = language.split(/[_-]/)[0];
    language = Object.keys(texts).filter(function (name) { return name.split('_')[0] === prefix; })[0] || 'en';
  }
  function t(key) { return texts[language][keys.indexOf(key)] || key; }
  document.documentElement.lang = language.replace('_', '-');
  ['description', 'reconnect', 'refresh', 'footer', 'recovery'].forEach(function (key) { document.getElementById(key).textContent = t(key); });
  var connection = document.getElementById('connection');
  var reconnect = document.getElementById('reconnect');
  var refresh = document.getElementById('refresh');
  var recovery = document.getElementById('recovery');
  var parameter = document.getElementById('parameter');
  var cs = null, closed = false, available = false, busy = false, retryTimer = null;
  var retryDelays = [200, 600, 1500, 3000];
  function display(key) { connection.textContent = t(key); connection.dataset.state = key; }
  function dispatch(type) {
    if (!cs || closed) return false;
    try {
      var event = new CSEvent(type, 'APPLICATION', 'PPRO', diagnosticsId);
      event.data = JSON.stringify({ protocol: 1 });
      cs.dispatchEvent(event);
      return true;
    } catch (_) { return false; }
  }
  function stopRetry() { clearTimeout(retryTimer); retryTimer = null; }
  function requestStatus() {
    stopRetry();
    var attempt = 0, received = false;
    available = false;
    reconnect.disabled = true;
    // A fresh status or later push cancels this bounded sequence. Never reconnect here.
    function request() {
      if (closed || available || received) return;
      dispatch(eventNames.request);
      if (available) { received = true; return; }
      if (attempt < retryDelays.length) retryTimer = setTimeout(request, retryDelays[attempt++]);
      else { display('unavailable'); retryTimer = null; }
    }
    request();
  }
  function onStatus(event) {
    if (closed || !event || event.extensionId !== backgroundId || event.appId !== 'PPRO' || (event.scope && event.scope !== 'APPLICATION')) return;
    var data;
    try {
      // CEP delivers valid JSON as an object; older/mocked transports may use strings.
      var raw = typeof event.data === 'string' ? event.data : JSON.stringify(event.data);
      if (typeof raw !== 'string' || raw.length > 16384) return;
      data = JSON.parse(raw);
    } catch (_) { return; }
    if (!data || typeof data !== 'object' || Array.isArray(data)) return;
    if (!data || data.protocol !== 1 || data.kind !== 'status' || typeof data.state !== 'string' || !/^[a-zA-Z][a-zA-Z0-9]{0,39}$/.test(data.state) ||
        typeof data.text !== 'string' || data.text.length > 2000 || typeof data.connected !== 'boolean' || typeof data.busy !== 'boolean' ||
        typeof data.locked !== 'boolean' || typeof data.parameterText !== 'string' || data.parameterText.length > 1000 ||
        typeof data.version !== 'string' || data.version.length > 40) return;
    available = true;
    busy = data.busy;
    stopRetry();
    connection.textContent = data.text || t('starting');
    connection.dataset.state = data.state;
    reconnect.disabled = busy;
    recovery.hidden = !data.locked;
    parameter.textContent = data.parameterText;
    parameter.hidden = !data.parameterText;
  }
  refresh.addEventListener('click', function () {
    if (!cs || closed) return;
    requestStatus();
  });
  reconnect.addEventListener('click', function () {
    if (!available || busy || closed || reconnect.disabled) return;
    // A deliberate user click is the only path to a recovery request.
    reconnect.disabled = true;
    dispatch(eventNames.reconnect);
    requestStatus();
  });
  window.addEventListener('unload', function () {
    closed = true;
    stopRetry();
    if (cs) { try { cs.removeEventListener(eventNames.status, onStatus); } catch (_) {} }
  });
  display('starting');
  try {
    if (!window.__adobe_cep__) throw new Error('CEP_REQUIRED');
    cs = new CSInterface();
    if (cs.getHostEnvironment().appId !== 'PPRO') throw new Error('PREMIERE_REQUIRED');
    cs.addEventListener(eventNames.status, onStatus);
    refresh.disabled = false;
    // This fallback is only reached after the user explicitly opens diagnostics.
    try { cs.requestOpenExtension(backgroundId, ''); } catch (_) {}
    requestStatus();
  } catch (_) {
    cs = null;
    display('runtimeError');
    reconnect.disabled = true;
    refresh.disabled = true;
  }
}());
