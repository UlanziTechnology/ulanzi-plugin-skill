import secrets
from pathlib import Path
from typing import Optional, Union

from .utils import Utils


class RandomPort:
    def __init__(self, min_port: int = 49152, max_port: int = 65535) -> None:
        if min_port > max_port:
            raise ValueError("min_port must be less than or equal to max_port")
        self.min_port = min_port
        self.max_port = max_port
        self.random_port: Optional[int] = None

    def get_port(self, plugin_path: Optional[Union[str, Path]] = None) -> int:
        self.random_port = self.generate_random_port(self.min_port, self.max_port)
        self.write_port(plugin_path)
        return self.random_port

    getPort = get_port

    def generate_random_port(
        self, min_port: int = 49152, max_port: int = 65535
    ) -> int:
        if min_port > max_port:
            raise ValueError("min_port must be less than or equal to max_port")
        return min_port + secrets.randbelow(max_port - min_port + 1)

    generateRandomPort = generate_random_port

    def write_port(self, plugin_path: Optional[Union[str, Path]] = None) -> Path:
        if self.random_port is None:
            raise RuntimeError("Call get_port() before write_port().")

        root = Path(plugin_path or Utils.get_plugin_path() or Path.cwd())
        root.mkdir(parents=True, exist_ok=True)
        file_path = root / "ws-port.js"
        file_path.write_text(f"window.__port = {self.random_port};", encoding="utf-8")
        return file_path

    writePort = write_port
