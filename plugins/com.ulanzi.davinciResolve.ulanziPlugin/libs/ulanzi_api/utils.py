import json
import platform
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional


class UlanziUtils:
    def parse_json(self, json_string: Any) -> Any:
        if isinstance(json_string, (dict, list)):
            return json_string
        if isinstance(json_string, bytes):
            json_string = json_string.decode("utf-8")
        if not isinstance(json_string, str):
            return False
        try:
            return json.loads(json_string)
        except (TypeError, ValueError):
            return False

    parseJson = parse_json

    def join_timestamp(self) -> dict:
        return {"_t": int(time.time() * 1000)}

    joinTimestamp = join_timestamp

    def adapt_language(self, ln: Optional[str]) -> str:
        user_language = ln or "en"
        if user_language.startswith("zh"):
            user_language = "zh_CN" if "CN" in user_language.upper() else "zh_HK"
        elif user_language.startswith("en"):
            user_language = "en"
        elif "-" in user_language:
            user_language = user_language.replace("-", "_")
        return user_language

    adaptLanguage = adapt_language

    def get_plugin_path(self, current_file_path: Optional[str] = None) -> str:
        raw_path = current_file_path or (sys.argv[0] if sys.argv else "")
        if not raw_path:
            return ""

        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path

        cursor = path if path.is_dir() else path.parent
        for candidate in (cursor, *cursor.parents):
            if candidate.name.endswith("ulanziPlugin"):
                return str(candidate)
        return ""

    getPluginPath = get_plugin_path

    def get_system_type(self) -> str:
        return "windows" if platform.system().lower().startswith("win") else "mac"

    getSystemType = get_system_type

    def get_property(
        self, obj: Any, dot_separated_keys: str, default_value: Any = None
    ) -> Any:
        if not isinstance(dot_separated_keys, str):
            return None

        keys = []
        for part in dot_separated_keys.split("."):
            match = re.match(r"^([^\[]+)\[(\d+)\]$", part)
            if match:
                keys.append(match.group(1))
                keys.append(int(match.group(2)))
            else:
                keys.append(part)

        current = obj
        for key in keys:
            try:
                if isinstance(current, dict):
                    current = current[key]
                elif isinstance(current, (list, tuple)) and isinstance(key, int):
                    current = current[key]
                else:
                    current = getattr(current, key)
            except (KeyError, IndexError, TypeError, AttributeError):
                return default_value
        return current

    getProperty = get_property

    def get_prop(
        self, jsn: Any, path: str, default_value: Any = None, sep: str = "."
    ) -> Any:
        current = jsn
        for key in path.split(sep):
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default_value
        return current

    getProp = get_prop

    def debounce(self, fn: Callable, wait: int = 150) -> Callable:
        timer: Optional[threading.Timer] = None
        lock = threading.Lock()

        def wrapper(*args: Any, **kwargs: Any) -> None:
            nonlocal timer
            with lock:
                if timer:
                    timer.cancel()
                timer = threading.Timer(wait / 1000, fn, args=args, kwargs=kwargs)
                timer.daemon = True
                timer.start()

        return wrapper

    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y/%m/%d %H:%M:%S")

    def log(self, *msg: Any) -> None:
        print(f"[{self._timestamp()}]", *msg)

    def warn(self, *msg: Any) -> None:
        print(f"[{self._timestamp()}]", *msg)

    def error(self, *msg: Any) -> None:
        print(f"[{self._timestamp()}]", *msg)


Utils = UlanziUtils()
