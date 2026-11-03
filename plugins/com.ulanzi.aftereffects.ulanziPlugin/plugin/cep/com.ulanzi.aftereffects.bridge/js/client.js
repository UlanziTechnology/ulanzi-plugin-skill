(function () {
  "use strict";

  var PORT = 39731;
  var PROTOCOL = "ulanzi-aftereffects-v1";
  var TOKEN = "ulanzi-aftereffects-local-bridge-v1";
  var EXTENSION_VERSION = "1.0.0";
  var RECONNECT_MIN = 500;
  var RECONNECT_MAX = 5000;
  var csInterface = new CSInterface();
  var socket = null;
  var reconnectTimer = null;
  var reconnectDelay = RECONNECT_MIN;
  var executionQueue = Promise.resolve();

  function hostVersion() {
    try {
      return csInterface.getHostEnvironment().appVersion || "unknown";
    } catch (error) {
      return "unknown";
    }
  }

  function loadExtendScript(done) {
    var root = csInterface.getSystemPath(SystemPath.EXTENSION).replace(/\\/g, "/");
    var jsxPath = root + "/jsx/ulanzi-ae.jsx";
    var escaped = jsxPath.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    csInterface.evalScript('$.evalFile("' + escaped + '")', function () {
      done();
    });
  }

  function connect() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
    try {
      socket = new WebSocket("ws://127.0.0.1:" + PORT);
    } catch (error) {
      scheduleReconnect();
      return;
    }

    socket.onopen = function () {
      reconnectDelay = RECONNECT_MIN;
      socket.send(JSON.stringify({
        type: "hello",
        protocol: PROTOCOL,
        token: TOKEN,
        extensionVersion: EXTENSION_VERSION,
        hostVersion: hostVersion()
      }));
    };

    socket.onmessage = function (event) {
      var message;
      try {
        message = JSON.parse(event.data);
      } catch (error) {
        return;
      }
      if (message.type === "request" && message.requestId) {
        executionQueue = executionQueue.catch(function () {}).then(function () {
          return executeRequest(message);
        });
      }
    };

    socket.onclose = function () {
      socket = null;
      scheduleReconnect();
    };

    socket.onerror = function () {};
  }

  function executeRequest(message) {
    return new Promise(function (resolve) {
      var encoded = encodeURIComponent(JSON.stringify({ command: message.command, payload: message.payload || {} }))
        .replace(/'/g, "%27");
      csInterface.evalScript("UlanziAE.dispatchEncoded('" + encoded + "')", function (rawResult) {
        var result;
        try {
          if (!rawResult || rawResult === "EvalScript error.") throw new Error("evalScript failed");
          result = JSON.parse(rawResult);
        } catch (error) {
          result = {
            ok: false,
            errorCode: "EVAL_SCRIPT_FAILED",
            messageKey: "status.communication_failed",
            data: { reason: error.message }
          };
        }
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "response", requestId: message.requestId, result: result }));
        }
        resolve();
      });
    });
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(function () {
      reconnectTimer = null;
      connect();
    }, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 1.6, RECONNECT_MAX);
  }

  window.addEventListener("load", function () {
    loadExtendScript(connect);
  });
})();
