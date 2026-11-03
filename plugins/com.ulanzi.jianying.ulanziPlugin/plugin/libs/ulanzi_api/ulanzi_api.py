import json
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from .constants import Events, SocketErrors
from .utils import Utils

Callback = Callable[[Any], None]


class UlanziApi:
    def __init__(self) -> None:
        self.key = ""
        self.uuid = ""
        self.actionid = ""
        self.address = "127.0.0.1"
        self.port: Union[int, str] = 3906
        self.language = "en"
        self.localization: Optional[Dict[str, Any]] = None
        self.websocket: Any = None
        self._listeners: Dict[str, List[Callback]] = {}
        self._thread: Optional[threading.Thread] = None
        self._is_main = False

    def connect(
        self,
        uuid: str,
        port: Union[int, str] = 3906,
        address: str = "127.0.0.1",
        language: str = "en",
        argv: Optional[List[str]] = None,
        threaded: bool = True,
        daemon: bool = False,
        **run_forever_kwargs: Any,
    ) -> "UlanziApi":
        args = list(sys.argv[1:4] if argv is None else argv[:3])
        argv_address = args[0] if len(args) > 0 else None
        argv_port = args[1] if len(args) > 1 else None
        argv_language = args[2] if len(args) > 2 else None

        self.address = argv_address or address
        self.port = argv_port or port
        self.language = Utils.adapt_language(argv_language or language)
        self.uuid = uuid
        self._is_main = len(uuid.split(".")) == 4

        if self.websocket:
            self.close()

        try:
            import websocket
        except ImportError as exc:
            raise RuntimeError(
                "websocket-client is required. Install with "
                "`pip install websocket-client`."
            ) from exc

        url = f"ws://{self.address}:{self.port}"
        self.websocket = websocket.WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        if threaded:
            self._thread = threading.Thread(
                target=self.websocket.run_forever,
                kwargs=run_forever_kwargs,
                daemon=daemon,
            )
            self._thread.start()
        else:
            self.websocket.run_forever(**run_forever_kwargs)
        return self

    def close(self) -> None:
        if self.websocket:
            close = getattr(self.websocket, "close", None)
            if callable(close):
                close()
        self.websocket = None

    def wait(self, timeout: Optional[float] = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def on(self, event: Union[str, Events], fn: Callback) -> "UlanziApi":
        if not callable(fn):
            raise ValueError(f"A callback function is required for {event}.")
        event_name = self._event_value(event)
        self._listeners.setdefault(event_name, []).append(fn)
        return self

    def off(self, event: Union[str, Events], fn: Optional[Callback] = None) -> "UlanziApi":
        event_name = self._event_value(event)
        if fn is None:
            self._listeners.pop(event_name, None)
            return self
        callbacks = self._listeners.get(event_name, [])
        self._listeners[event_name] = [callback for callback in callbacks if callback != fn]
        return self

    def emit(self, event: Union[str, Events], data: Any = None) -> "UlanziApi":
        for callback in list(self._listeners.get(self._event_value(event), [])):
            callback(data)
        return self

    def localize_ui(self) -> None:
        if self.localization is not None:
            return
        try:
            file_path = Path(Utils.get_plugin_path()) / f"{self.language}.json"
            data = json.loads(file_path.read_text(encoding="utf-8"))
            self.localization = data.get("Localization")
        except (OSError, ValueError, TypeError):
            Utils.warn(f"[ULANZIDECK] No FILE found to localize {self.language}")

    localizeUI = localize_ui

    def t(self, key: str) -> str:
        if self.localization and key in self.localization:
            return self.localization[key]
        return key

    def encode_context(self, jsn: Dict[str, Any]) -> str:
        return f"{jsn.get('uuid', '')}___{jsn.get('key', '')}___{jsn.get('actionid', '')}"

    encodeContext = encode_context

    def decode_context(self, context: str) -> Dict[str, str]:
        uuid, key, actionid = (context.split("___") + ["", "", ""])[:3]
        return {"uuid": uuid, "key": key, "actionid": actionid}

    decodeContext = decode_context

    def send(
        self, cmd: Union[str, Events], params: Optional[Dict[str, Any]] = None
    ) -> bool:
        payload = {
            "cmd": self._event_value(cmd),
            "uuid": self.uuid,
            "key": self.key,
            "actionid": self.actionid,
        }
        if params:
            payload.update(params)

        if not self._websocket_is_open():
            return False

        self.websocket.send(json.dumps(payload, ensure_ascii=False))
        return True

    def send_param_from_plugin(
        self, settings: Dict[str, Any], context: Optional[str] = None
    ) -> bool:
        ctx = self.decode_context(context) if context else {}
        return self.send(
            Events.PARAMFROMPLUGIN,
            {
                "uuid": ctx.get("uuid", self.uuid),
                "key": ctx.get("key", self.key),
                "actionid": ctx.get("actionid", self.actionid),
                "param": settings,
            },
        )

    sendParamFromPlugin = send_param_from_plugin

    def open_url(
        self,
        url: str,
        local: bool = False,
        param: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return self.send(
            Events.OPENURL,
            {"url": url, "local": bool(local), "param": param if param else None},
        )

    openUrl = open_url

    def open_view(
        self,
        url: str,
        width: int = 200,
        height: int = 200,
        x: Optional[int] = None,
        y: Optional[int] = None,
        param: Optional[Dict[str, Any]] = None,
    ) -> bool:
        payload: Dict[str, Any] = {"url": url, "width": width, "height": height}
        if x is not None:
            payload["x"] = x
        if y is not None:
            payload["y"] = y
        if param is not None:
            payload["param"] = param
        return self.send(Events.OPENVIEW, payload)

    openView = open_view

    def toast(self, msg: str) -> bool:
        return self.send(Events.TOAST, {"msg": msg})

    def hotkey(self, key: str) -> bool:
        return self.send(Events.HOTKEY, {"keylist": key})

    def log_message(self, msg: str, level: str = "info") -> bool:
        return self.send(Events.LOGMESSAGE, {"message": msg, "level": level or "info"})

    logMessage = log_message

    def send_to_property_inspector(
        self, settings: Dict[str, Any], context: Optional[str] = None
    ) -> bool:
        ctx = self.decode_context(context) if context else {}
        payload: Dict[str, Any] = {"payload": settings}
        payload.update(ctx)
        return self.send(Events.SENDTOPROPERTYINSPECTOR, payload)

    sendToPropertyInspector = send_to_property_inspector

    def send_to_plugin(self, settings: Dict[str, Any]) -> bool:
        return self.send(
            Events.SENDTOPLUGIN,
            {
                "uuid": self.uuid,
                "key": self.key,
                "actionid": self.actionid,
                "payload": settings,
            },
        )

    sendToPlugin = send_to_plugin

    def show_alert(self, context: Optional[str] = None) -> bool:
        return self._send_context_event(Events.SHOWALERT, context)

    showAlert = show_alert

    def get_settings(self, context: Optional[str] = None) -> bool:
        return self._send_context_event(Events.GETSETTINGS, context)

    getSettings = get_settings

    def set_settings(
        self, settings: Dict[str, Any], context: Optional[str] = None
    ) -> bool:
        return self._send_context_event(
            Events.SETSETTINGS, context, {"settings": settings}
        )

    setSettings = set_settings

    def get_global_settings(self, context: Optional[str] = None) -> bool:
        return self._send_context_event(Events.GETGLOBALSETTINGS, context)

    getGlobalSettings = get_global_settings

    def set_global_settings(
        self, settings: Dict[str, Any], context: Optional[str] = None
    ) -> bool:
        return self._send_context_event(
            Events.SETGLOBALSETTINGS, context, {"settings": settings}
        )

    setGlobalSettings = set_global_settings

    def select_file_dialog(self, file_filter: Optional[str] = None) -> bool:
        payload: Dict[str, Any] = {"type": "file"}
        if file_filter is not None:
            payload["filter"] = file_filter
        return self.send(Events.SELECTDIALOG, payload)

    selectFileDialog = select_file_dialog

    def select_folder_dialog(self) -> bool:
        return self.send(Events.SELECTDIALOG, {"type": "folder"})

    selectFolderDialog = select_folder_dialog

    def set_state(self, context: str, state: int) -> bool:
        """Set the active state for an action instance."""
        return self._send_param_context_event(
            Events.SETSTATE, context, {"state": state}
        )

    setState = set_state

    def set_image(self, context: str, options: Dict[str, Any]) -> bool:
        """Set runtime images using the protocol's isDefault/icons/clear fields."""
        return self._send_param_context_event(
            Events.SETIMAGE, context, dict(options or {})
        )

    setImage = set_image

    def set_title(self, context: str, text: str) -> bool:
        """Set the title for an action instance."""
        return self._send_param_context_event(
            Events.SETTITLE, context, {"text": text}
        )

    setTitle = set_title

    def set_feedback_layout(self, context: str, layout: str) -> bool:
        """Set a built-in encoder layout such as $UA1."""
        return self._send_context_event(
            Events.SETFEEDBACKLAYOUT, context, {"layout": layout}
        )

    setFeedbackLayout = set_feedback_layout

    def set_feedback(self, context: str, layout: Dict[str, Any]) -> bool:
        """Update elements in the current encoder feedback layout."""
        return self._send_context_event(
            Events.SETFEEDBACK, context, {"layout": layout}
        )

    setFeedback = set_feedback

    def set_state_icon(
        self, context: str, state: int, text: Optional[str] = None
    ) -> bool:
        return self._set_icon(context, {"type": 0, "state": state}, text)

    setStateIcon = set_state_icon

    def set_base_data_icon(
        self, context: str, data: str, text: Optional[str] = None
    ) -> bool:
        return self._set_icon(context, {"type": 1, "data": data}, text)

    setBaseDataIcon = set_base_data_icon

    def set_path_icon(
        self, context: str, path: str, text: Optional[str] = None
    ) -> bool:
        return self._set_icon(context, {"type": 2, "path": path}, text)

    setPathIcon = set_path_icon

    def set_gif_data_icon(
        self, context: str, gifdata: str, text: Optional[str] = None
    ) -> bool:
        return self._set_icon(context, {"type": 3, "gifdata": gifdata}, text)

    setGifDataIcon = set_gif_data_icon

    def set_gif_path_icon(
        self, context: str, gifpath: str, text: Optional[str] = None
    ) -> bool:
        return self._set_icon(context, {"type": 4, "gifpath": gifpath}, text)

    setGifPathIcon = set_gif_path_icon

    def on_connected(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.CONNECTED, fn)

    onConnected = on_connected

    def on_close(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.CLOSE, fn)

    onClose = on_close

    def on_error(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.ERROR, fn)

    onError = on_error

    def on_add(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.ADD, fn)

    onAdd = on_add

    def on_param_from_app(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.PARAMFROMAPP, fn)

    onParamFromApp = on_param_from_app

    def on_param_from_plugin(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.PARAMFROMPLUGIN, fn)

    onParamFromPlugin = on_param_from_plugin

    def on_run(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.RUN, fn)

    onRun = on_run

    def on_set_active(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.SETACTIVE, fn)

    onSetActive = on_set_active

    def on_clear(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.CLEAR, fn)

    onClear = on_clear

    def on_selectdialog(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.SELECTDIALOG, fn)

    onSelectdialog = on_selectdialog

    def on_did_receive_settings(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.DIDRECEIVESETTINGS, fn)

    onDidReceiveSettings = on_did_receive_settings

    def on_did_receive_global_settings(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.DIDRECEIVEGLOBALSETTINGS, fn)

    onDidReceiveGlobalSettings = on_did_receive_global_settings

    def on_send_to_property_inspector(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.SENDTOPROPERTYINSPECTOR, fn)

    onSendToPropertyInspector = on_send_to_property_inspector

    def on_send_to_plugin(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.SENDTOPLUGIN, fn)

    onSendToPlugin = on_send_to_plugin

    def on_key_down(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.KEYDOWN, fn)

    onKeyDown = on_key_down

    def on_key_up(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.KEYUP, fn)

    onKeyUp = on_key_up

    def on_dial_down(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.DIALEDOWN, fn)

    onDialDown = on_dial_down

    def on_dial_up(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.DIALEUP, fn)

    onDialUp = on_dial_up

    def on_dial_rotate(self, fn: Callback) -> "UlanziApi":
        return self.on(Events.DIALROTATE, fn)

    onDialRotate = on_dial_rotate

    def on_dial_rotate_left(self, fn: Callback) -> "UlanziApi":
        return self._on_dial_rotate_value("left", fn)

    onDialRotateLeft = on_dial_rotate_left

    def on_dial_rotate_right(self, fn: Callback) -> "UlanziApi":
        return self._on_dial_rotate_value("right", fn)

    onDialRotateRight = on_dial_rotate_right

    def on_dial_rotate_hold_left(self, fn: Callback) -> "UlanziApi":
        return self._on_dial_rotate_value("hold-left", fn)

    onDialRotateHoldLeft = on_dial_rotate_hold_left

    def on_dial_rotate_hold_right(self, fn: Callback) -> "UlanziApi":
        return self._on_dial_rotate_value("hold-right", fn)

    onDialRotateHoldRight = on_dial_rotate_hold_right

    def _on_open(self, ws: Any) -> None:
        Utils.log(f"[ULANZIDECK] MAIN WEBSOCKET OPEN: {self.uuid}")
        ws.send(
            json.dumps(
                {"code": 0, "cmd": Events.CONNECTED.value, "uuid": self.uuid},
                ensure_ascii=False,
            )
        )
        self.emit(Events.CONNECTED, {})

    def _on_error(self, ws: Any, error: Any) -> None:
        message = f"[ULANZIDECK] MAIN WEBSOCKET ERROR: {error}, {SocketErrors['DEFAULT']}"
        Utils.warn(message)
        self.emit(Events.ERROR, message)

    def _on_close(
        self,
        ws: Any,
        close_status_code: Optional[int] = None,
        close_msg: Optional[str] = None,
    ) -> None:
        Utils.warn(
            f"[ULANZIDECK] MAIN WEBSOCKET CLOSED: {self.uuid}, "
            f"{close_status_code or ''} {close_msg or SocketErrors['DEFAULT']}"
        )
        self.emit(Events.CLOSE, None)

    def _on_message(self, ws: Any, message: Any) -> None:
        self._handle_message(message)

    def _handle_message(self, message: Any) -> None:
        data = Utils.parse_json(message)
        if not data or not isinstance(data, dict):
            return
        if "code" in data and data.get("cmdType") != "REQUEST":
            return

        if not self.key and data.get("uuid") == self.uuid and data.get("key"):
            self.key = data["key"]
        if not self.actionid and data.get("uuid") == self.uuid and data.get("actionid"):
            self.actionid = data["actionid"]

        if self._is_main:
            self.send(data.get("cmd", ""), {"code": 0, **data})

        if data.get("cmd") == Events.CLEAR.value:
            param = data.get("param")
            if isinstance(param, list):
                for item in param:
                    if isinstance(item, dict):
                        item["context"] = self.encode_context(item)
        else:
            data["context"] = self.encode_context(data)

        self.emit(data.get("cmd", ""), data)

    def _send_context_event(
        self,
        event: Events,
        context: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        ctx = self.decode_context(context) if context else {}
        payload = {
            "uuid": ctx.get("uuid", self.uuid),
            "key": ctx.get("key", self.key),
            "actionid": ctx.get("actionid", self.actionid),
        }
        if extra:
            payload.update(extra)
        return self.send(event, payload)

    def _send_param_context_event(
        self,
        event: Events,
        context: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        payload: Dict[str, Any] = self.decode_context(context)
        if extra:
            payload.update(extra)
        return self.send(event, {"param": payload})

    def _set_icon(
        self, context: str, icon_payload: Dict[str, Any], text: Optional[str]
    ) -> bool:
        ctx = self.decode_context(context)
        state_item = {
            **ctx,
            **icon_payload,
            "textData": text or "",
            "showtext": bool(text),
        }
        return self.send(Events.STATE, {"param": {"statelist": [state_item]}})

    def _on_dial_rotate_value(self, rotate_event: str, fn: Callback) -> "UlanziApi":
        if not callable(fn):
            raise ValueError("A callback function is required for dialrotate.")

        def wrapper(jsn: Dict[str, Any]) -> None:
            if jsn.get("rotateEvent") == rotate_event:
                fn(jsn)

        return self.on(Events.DIALROTATE, wrapper)

    def _websocket_is_open(self) -> bool:
        if not self.websocket:
            return False
        if getattr(self.websocket, "connected", False):
            return True
        sock = getattr(self.websocket, "sock", None)
        return bool(getattr(sock, "connected", False))

    def _event_value(self, event: Union[str, Events]) -> str:
        return event.value if isinstance(event, Events) else str(event)
