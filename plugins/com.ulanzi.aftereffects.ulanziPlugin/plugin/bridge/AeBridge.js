import { EventEmitter } from "node:events";
import { WebSocket, WebSocketServer } from "ws";
import AfterEffectsExtensionInstaller from "./AfterEffectsExtensionInstaller.js";
import { BRIDGE_PORT, BRIDGE_PROTOCOL, BRIDGE_TOKEN, MAX_MESSAGE_BYTES, REQUEST_TIMEOUT_MS, failure } from "./protocol.js";

export default class AeBridge extends EventEmitter {
  constructor(options = {}) {
    super();
    this.port = typeof options.port === "number" ? options.port : BRIDGE_PORT;
    this.host = "127.0.0.1";
    this.protocol = options.protocol || BRIDGE_PROTOCOL;
    this.token = options.token || BRIDGE_TOKEN;
    this.timeoutMs = options.timeoutMs || REQUEST_TIMEOUT_MS;
    this.installer = options.installer || new AfterEffectsExtensionInstaller(options.installerOptions);
    this.server = null;
    this.client = null;
    this.pending = new Map();
    this.sequence = 0;
    this.queue = Promise.resolve();
    this.heartbeat = null;
    this.status = { code: "STARTING", statusKey: "status.bridge_starting", severity: "info" };
  }

  async start() {
    await this.startServer();
    try {
      const install = await this.installer.install();
      if (!install.debugModeEnabled) {
        this.setStatus("DEBUG_MODE_REQUIRED", "status.debug_mode_required", "error", install);
      } else if (install.status === "Installed" || install.status === "Updated") {
        this.setStatus("RESTART_REQUIRED", "status.restart_after_effects", "warn", install);
      } else {
        this.setStatus("WAITING_FOR_AE", "status.waiting_for_after_effects", "warn", install);
      }
    } catch (error) {
      this.setStatus("INSTALL_FAILED", "status.install_failed", "error", { reason: error.message });
    }
  }

  startServer() {
    return new Promise((resolve, reject) => {
      const server = new WebSocketServer({ host: this.host, port: this.port, maxPayload: MAX_MESSAGE_BYTES });
      this.server = server;
      const onError = (error) => {
        server.off("listening", onListening);
        this.setStatus("PORT_IN_USE", "status.bridge_port_in_use", "error", { reason: error.message });
        reject(error);
      };
      const onListening = () => {
        server.off("error", onError);
        server.on("error", (error) => this.emit("bridgeError", error));
        this.startHeartbeat();
        resolve();
      };
      server.once("error", onError);
      server.once("listening", onListening);
      server.on("connection", (socket, request) => this.onConnection(socket, request));
    });
  }

  onConnection(socket, request) {
    const remote = request.socket.remoteAddress || "";
    if (!["127.0.0.1", "::1", "::ffff:127.0.0.1"].includes(remote)) {
      socket.close(1008, "loopback only");
      return;
    }
    socket.isAlive = true;
    socket.authenticated = false;
    const handshakeTimer = setTimeout(() => {
      if (!socket.authenticated) socket.close(1008, "handshake timeout");
    }, 2500);
    socket.on("pong", () => { socket.isAlive = true; });
    socket.on("message", (raw) => this.onMessage(socket, raw, handshakeTimer));
    socket.on("close", () => {
      clearTimeout(handshakeTimer);
      if (this.client === socket) {
        this.client = null;
        this.rejectPending("AE_DISCONNECTED", "status.communication_failed");
        this.setStatus("DISCONNECTED", "status.ae_disconnected", "warn");
      }
    });
    socket.on("error", () => {});
  }

  onMessage(socket, raw, handshakeTimer) {
    let message;
    try {
      message = JSON.parse(raw.toString());
    } catch {
      socket.close(1003, "invalid json");
      return;
    }
    if (!socket.authenticated) {
      if (message.type !== "hello" || message.protocol !== this.protocol || message.token !== this.token) {
        socket.close(1008, "invalid handshake");
        return;
      }
      clearTimeout(handshakeTimer);
      if (this.client && this.client !== socket) this.client.close(1012, "replaced");
      socket.authenticated = true;
      this.client = socket;
      socket.send(JSON.stringify({ type: "helloAck", protocol: this.protocol }));
      this.setStatus("CONNECTED", "status.ae_connected", "success", { hostVersion: message.hostVersion, extensionVersion: message.extensionVersion });
      return;
    }
    if (message.type === "response" && message.requestId) {
      const pending = this.pending.get(message.requestId);
      if (!pending) return;
      clearTimeout(pending.timer);
      this.pending.delete(message.requestId);
      pending.resolve(message.result || failure("INVALID_RESPONSE", "status.communication_failed"));
    }
  }

  request(command, payload = {}, meta = {}) {
    const task = () => this.sendRequest(command, payload, meta);
    const next = this.queue.catch(() => {}).then(task);
    this.queue = next;
    return next;
  }

  sendRequest(command, payload, meta) {
    if (!this.client || this.client.readyState !== WebSocket.OPEN || !this.client.authenticated) {
      return Promise.resolve(failure("AE_NOT_CONNECTED", "status.ae_not_connected"));
    }
    const requestId = `${Date.now().toString(36)}-${(++this.sequence).toString(36)}`;
    const message = { type: "request", requestId, command, payload, meta };
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.pending.delete(requestId);
        resolve(failure("AE_TIMEOUT", "status.communication_timeout"));
      }, this.timeoutMs);
      this.pending.set(requestId, { resolve, timer });
      try {
        this.client.send(JSON.stringify(message));
      } catch (error) {
        clearTimeout(timer);
        this.pending.delete(requestId);
        resolve(failure("SEND_FAILED", "status.communication_failed", { reason: error.message }));
      }
    });
  }

  startHeartbeat() {
    if (this.heartbeat) clearInterval(this.heartbeat);
    this.heartbeat = setInterval(() => {
      for (const socket of this.server.clients) {
        if (socket.isAlive === false) {
          socket.terminate();
          continue;
        }
        socket.isAlive = false;
        socket.ping();
      }
    }, 3000);
  }

  rejectPending(errorCode, messageKey) {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.resolve(failure(errorCode, messageKey));
    }
    this.pending.clear();
  }

  setStatus(code, statusKey, severity, detail = {}) {
    this.status = { code, statusKey, severity, detail };
    this.emit("status", this.status);
  }

  async stop() {
    if (this.heartbeat) clearInterval(this.heartbeat);
    this.heartbeat = null;
    this.rejectPending("BRIDGE_STOPPED", "status.communication_failed");
    if (this.client) this.client.close(1001, "bridge stopped");
    this.client = null;
    if (this.server) {
      const server = this.server;
      this.server = null;
      await new Promise((resolve) => server.close(resolve));
    }
  }
}
