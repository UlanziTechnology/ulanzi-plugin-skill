/* CEP browser code: only the allowlisted dispatcher is callable, never arbitrary JSX. */
(function () {
  'use strict';
  var texts = {
    en: ['Control Premiere from Ulanzi Studio.', 'Reconnect', 'Connected', 'Connecting…', 'Waiting for Ulanzi Studio…', 'Start the Ulanzi plugin to create the local pairing file.', 'Result unknown. Check Premiere, then reconnect. Never repeat an export without checking the queue.', 'A Premiere request is still running. Wait before reconnecting.', 'Background bridge initialization failed. Check the CEP installation, save your project and restart Premiere Pro.', 'Local connection failed.', 'The bridge connects automatically in the background; no visible panel is required. Changes are made only after a device action.'],
    zh_CN: ['通过 Ulanzi Studio 控制 Premiere。', '重新连接', '已连接', '正在连接…', '等待 Ulanzi Studio…', '请先启动 Ulanzi 插件，生成本机配对文件。', '执行结果未知。请检查 Premiere 后再重连；重新导出前请检查队列。', 'Premiere 请求尚未结束，请稍后再重连。', '后台桥接初始化失败。请检查 CEP 安装，保存项目并重启 Premiere Pro。', '本机连接失败。', '桥接会在后台自动连接，无需保持可见面板。仅在设备操作后修改工程。'],
    zh_HK: ['透過 Ulanzi Studio 控制 Premiere。', '重新連線', '已連線', '正在連線…', '等待 Ulanzi Studio…', '請先啟動 Ulanzi 插件，產生本機配對檔案。', '執行結果未知。請檢查 Premiere 後再連線；重新匯出前請檢查佇列。', 'Premiere 請求尚未結束，請稍後再連線。', '背景橋接初始化失敗。請檢查 CEP 安裝，儲存專案並重新啟動 Premiere Pro。', '本機連線失敗。', '橋接會在背景自動連線，無需保持可見面板。僅在裝置操作後修改專案。'],
    de_DE: ['Premiere mit Ulanzi Studio steuern.', 'Neu verbinden', 'Verbunden', 'Verbindung wird hergestellt…', 'Warten auf Ulanzi Studio…', 'Starten Sie das Ulanzi-Plugin, um die lokale Kopplungsdatei zu erstellen.', 'Ergebnis unbekannt. Prüfen Sie Premiere und verbinden Sie neu. Vor erneutem Export die Warteschlange prüfen.', 'Eine Premiere-Anfrage läuft noch. Warten Sie vor der erneuten Verbindung.', 'Die Hintergrundbrücke konnte nicht initialisiert werden. Prüfen Sie die CEP-Installation, speichern Sie Ihr Projekt und starten Sie Premiere Pro neu.', 'Lokale Verbindung fehlgeschlagen.', 'Die Brücke verbindet sich automatisch im Hintergrund; ein sichtbares Bedienfeld ist nicht nötig. Änderungen erfolgen nur nach einer Geräteaktion.'],
    es_ES: ['Controla Premiere desde Ulanzi Studio.', 'Reconectar', 'Conectado', 'Conectando…', 'Esperando a Ulanzi Studio…', 'Inicia el complemento Ulanzi para crear el archivo de emparejamiento local.', 'Resultado desconocido. Comprueba Premiere y reconecta. Revisa la cola antes de repetir una exportación.', 'Una solicitud de Premiere sigue en curso. Espera antes de reconectar.', 'No se pudo inicializar el puente en segundo plano. Comprueba la instalación CEP, guarda el proyecto y reinicia Premiere Pro.', 'Error de conexión local.', 'El puente se conecta automáticamente en segundo plano; no requiere un panel visible. Los cambios solo ocurren tras una acción del dispositivo.'],
    ja_JP: ['Ulanzi Studio から Premiere を操作します。', '再接続', '接続済み', '接続中…', 'Ulanzi Studio を待機中…', 'Ulanzi プラグインを起動し、ローカルのペアリングファイルを作成してください。', '結果が不明です。Premiere を確認して再接続してください。再書き出し前にキューを確認してください。', 'Premiere の処理が続いています。完了後に再接続してください。', 'バックグラウンドブリッジの初期化に失敗しました。CEP のインストールを確認し、プロジェクトを保存して Premiere Pro を再起動してください。', 'ローカル接続に失敗しました。', 'ブリッジはバックグラウンドで自動接続し、パネルの表示は不要です。デバイス操作時のみ変更されます。'],
    ko_KR: ['Ulanzi Studio에서 Premiere를 제어합니다.', '다시 연결', '연결됨', '연결 중…', 'Ulanzi Studio 대기 중…', 'Ulanzi 플러그인을 시작하여 로컬 페어링 파일을 만드세요.', '결과를 알 수 없습니다. Premiere를 확인하고 다시 연결하세요. 내보내기를 반복하기 전에 대기열을 확인하세요.', 'Premiere 요청이 진행 중입니다. 완료 후 다시 연결하세요.', '백그라운드 브리지를 초기화하지 못했습니다. CEP 설치를 확인하고 프로젝트를 저장한 후 Premiere Pro를 다시 시작하세요.', '로컬 연결에 실패했습니다.', '브리지가 백그라운드에서 자동으로 연결되므로 패널을 표시할 필요가 없습니다. 장치 동작 후에만 변경됩니다.'],
    pt_PT: ['Controle o Premiere a partir do Ulanzi Studio.', 'Voltar a ligar', 'Ligado', 'A ligar…', 'À espera do Ulanzi Studio…', 'Inicie o plugin Ulanzi para criar o ficheiro de emparelhamento local.', 'Resultado desconhecido. Verifique o Premiere e volte a ligar. Verifique a fila antes de repetir a exportação.', 'Um pedido do Premiere ainda está em curso. Aguarde antes de voltar a ligar.', 'Não foi possível inicializar a ponte em segundo plano. Verifique a instalação CEP, guarde o projeto e reinicie o Premiere Pro.', 'Falha na ligação local.', 'A ponte liga-se automaticamente em segundo plano; não é necessário um painel visível. As alterações só ocorrem após uma ação do dispositivo.']
  };
  var keys = ['description', 'reconnect', 'connected', 'connecting', 'waiting', 'pairing', 'locked', 'busy', 'runtimeError', 'connectionError', 'footer'];
  var lang = (navigator.language || 'en').replace('-', '_');
  try { lang = JSON.parse(window.__adobe_cep__.getHostEnvironment()).appUILocale || lang; } catch (_) {}
  if (/^zh/i.test(lang)) lang = /TW|HK|Hant/i.test(lang) ? 'zh_HK' : 'zh_CN';
  if (!texts[lang]) {
    var prefix = lang.split(/[_-]/)[0];
    lang = Object.keys(texts).filter(function (name) { return name.split('_')[0] === prefix; })[0] || 'en';
  }
  function t(key) { return texts[lang][keys.indexOf(key)] || key; }
  document.documentElement.lang = lang.replace('_', '-');
  ['description', 'reconnect', 'footer'].forEach(function (key) { document.getElementById(key).textContent = t(key); });
  var statusEl = document.getElementById('connection');
  var reconnectEl = document.getElementById('reconnect');
  var parameterEl = document.getElementById('parameter');
  var socket = null, retryTimer = null, pairingTimer = null, displayTimer = null, backoff = 500;
  var poisoned = false, busy = false, closing = false, runtimeReady = false, paired = false, cs, fs, os, path;
  var backgroundId = 'com.ulanzi.premierepro.bridge';
  var diagnosticsId = backgroundId + '.diagnostics';
  var statusRequestEvent = backgroundId + '.statusRequest';
  var statusEvent = backgroundId + '.status';
  var reconnectRequestEvent = backgroundId + '.reconnectRequest';
  var allowed = ['capabilities', 'exportPresets', 'exportInfo', 'queueExport', 'directExport', 'timelineJog', 'trimControl', 'timelineZoom', 'parameterDial'];
  function publishStatus() {
    if (!cs || closing) return;
    try {
      // CEP events contain display state only, never the pairing token or project data.
      var event = new CSEvent(statusEvent, 'APPLICATION', 'PPRO', backgroundId);
      event.data = JSON.stringify({
        protocol: 1, kind: 'status', state: statusEl.dataset.state || 'waiting',
        text: statusEl.textContent, connected: paired && !poisoned,
        busy: busy, locked: poisoned,
        parameterText: parameterEl.hidden ? '' : parameterEl.textContent, version: '0.1.1'
      });
      cs.dispatchEvent(event);
    } catch (_) { /* A closed diagnostics panel must never interrupt the bridge. */ }
  }
  function status(key) { statusEl.textContent = t(key); statusEl.dataset.state = key; publishStatus(); }
  function validDiagnosticEvent(event) {
    if (!event || event.extensionId !== diagnosticsId || event.appId !== 'PPRO' || (event.scope && event.scope !== 'APPLICATION')) return false;
    try {
      // CEP can decode JSON event payloads natively. Accept both transport forms.
      var raw = typeof event.data === 'string' ? event.data : JSON.stringify(event.data);
      if (typeof raw !== 'string' || raw.length > 256) return false;
      var data = JSON.parse(raw);
      return !!data && typeof data === 'object' && !Array.isArray(data) && data.protocol === 1;
    } catch (_) { return false; }
  }
  function onStatusRequest(event) { if (validDiagnosticEvent(event)) publishStatus(); }
  function onReconnectRequest(event) { if (validDiagnosticEvent(event)) manualReconnect(); }
  function retry() {
    if (closing || poisoned || busy) return;
    clearTimeout(retryTimer);
    retryTimer = setTimeout(connect, backoff);
    backoff = Math.min(backoff * 2, 10000);
  }
  function send(peer, message) { if (peer === socket && peer.readyState === WebSocket.OPEN) peer.send(JSON.stringify(message)); }
  function disconnect() {
    clearTimeout(retryTimer); clearTimeout(pairingTimer);
    var previous = socket; socket = null; paired = false;
    if (previous) previous.close(1000, 'Bridge reconnect');
  }
  function scriptFor(request) {
    // Encode data as a string literal; quotes, backslashes, and Unicode separators cannot escape into code.
    var json = JSON.stringify(request);
    return '$._ulanziPremiere.dispatch(' + JSON.stringify(json).replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029') + ')';
  }
  function execute(peer, message) {
    if (busy || poisoned) { send(peer, { type: 'response', id: message.id, ok: false, error: { code: 'CEP_BUSY', message: 'An earlier host request is still running.' } }); return; }
    if (typeof message.id !== 'string' || message.id.length > 100 || allowed.indexOf(message.action) < 0 || !message.settings || typeof message.settings !== 'object' || !message.payload || typeof message.payload !== 'object') {
      send(peer, { type: 'response', id: message.id, ok: false, error: { code: 'INVALID_REQUEST', message: 'Invalid bridge request.' } }); return;
    }
    busy = true;
    reconnectEl.disabled = true;
    publishStatus();
    var request = { id: message.id, action: message.action, settings: message.settings, payload: message.payload };
    cs.evalScript(scriptFor(request), function (response) {
      busy = false;
      reconnectEl.disabled = false;
      var parsed;
      try { parsed = JSON.parse(response); if (!parsed || typeof parsed.ok !== 'boolean') throw new Error(); }
      catch (_) { parsed = { ok: false, error: { code: 'HOST_RESPONSE_INVALID', message: 'Host response could not be decoded. Check Premiere before repeating the action.' } }; poisoned = true; status('locked'); }
      if (poisoned) status('locked');
      else if (paired && statusEl.dataset.state === 'busy') status('connected');
      else publishStatus();
      if (peer !== socket || poisoned && peer.readyState !== WebSocket.OPEN) return;
      send(peer, { type: 'response', id: message.id, ok: parsed.ok, result: parsed.result, error: parsed.error });
      if (poisoned) peer.close(4008, 'Manual recovery required');
    });
  }
  function connect() {
    if (closing || poisoned || busy || !runtimeReady || socket) return;
    clearTimeout(retryTimer);
    var pairing;
    try {
      var pairingPath = path.join(os.homedir(), '.ulanzi-premiere', 'bridge.json');
      var stat = fs.lstatSync(pairingPath);
      if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 4096) throw new Error('PAIRING_INVALID');
      pairing = JSON.parse(fs.readFileSync(pairingPath, 'utf8'));
      if (!Number.isInteger(pairing.port) || pairing.port < 1 || pairing.port > 65535 || !/^[a-f0-9]{64}$/.test(pairing.token || '')) throw new Error('PAIRING_INVALID');
    } catch (_) { status('pairing'); retry(); return; }
    status('connecting');
    var peer = new WebSocket('ws://127.0.0.1:' + pairing.port);
    socket = peer;
    pairingTimer = setTimeout(function () { if (peer === socket) peer.close(4001, 'Pairing timeout'); }, 5000);
    peer.onopen = function () {
      var env = cs.getHostEnvironment();
      send(peer, { type: 'hello', protocol: 1, host: env.appId, appVersion: env.appVersion, token: pairing.token });
      pairing.token = '';
    };
    peer.onmessage = function (event) {
      if (peer !== socket || typeof event.data !== 'string' || event.data.length > 65536) return;
      var message;
      try { message = JSON.parse(event.data); } catch (_) { return; }
      if (message.type === 'ready' && message.protocol === 1) { clearTimeout(pairingTimer); paired = true; backoff = 500; status('connected'); }
      else if (message.type === 'request') execute(peer, message);
      else if (message.type === 'fatal') { poisoned = true; status('locked'); }
      else if (message.type === 'parameterStatus') {
        clearTimeout(displayTimer);
        parameterEl.textContent = String(message.name || message.parameter || '').slice(0, 100) + (message.value == null ? '' : ': ' + String(message.value).slice(0, 60));
        parameterEl.hidden = false;
        publishStatus();
        displayTimer = setTimeout(function () { parameterEl.hidden = true; publishStatus(); }, 2200);
      }
    };
    peer.onerror = function () { if (!poisoned) status('waiting'); };
    peer.onclose = function (event) {
      if (peer !== socket) return;
      clearTimeout(pairingTimer); socket = null; paired = false;
      if (event.code === 4008 || busy) poisoned = true;
      if (poisoned) status('locked');
      else { status(event.code === 4001 || event.code === 4009 ? 'connectionError' : 'waiting'); retry(); }
    };
  }
  function manualReconnect() {
    if (!runtimeReady) { status('runtimeError'); return; }
    if (busy) { status('busy'); return; }
    poisoned = false; backoff = 500; disconnect(); connect();
  }
  reconnectEl.addEventListener('click', manualReconnect);
  window.addEventListener('unload', function () {
    closing = true; disconnect(); clearTimeout(displayTimer);
    if (cs) {
      cs.removeEventListener(statusRequestEvent, onStatusRequest);
      cs.removeEventListener(reconnectRequestEvent, onReconnectRequest);
    }
  });
  try {
    if (!window.__adobe_cep__) throw new Error('CEP_REQUIRED');
    cs = new CSInterface();
    if (cs.getHostEnvironment().appId !== 'PPRO') throw new Error('PREMIERE_REQUIRED');
    cs.addEventListener(statusRequestEvent, onStatusRequest);
    cs.addEventListener(reconnectRequestEvent, onReconnectRequest);
    var nodeRequire = window.cep_node && window.cep_node.require ? window.cep_node.require : require;
    fs = nodeRequire('fs'); os = nodeRequire('os'); path = nodeRequire('path');
    runtimeReady = true;
    connect();
  } catch (_) { status('runtimeError'); reconnectEl.disabled = true; }
}());
