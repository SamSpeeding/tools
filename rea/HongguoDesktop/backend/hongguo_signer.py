"""Run the installer-supplied signer locally; never start the Windows app."""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time


class LocalSigner:
    def __init__(self, app_dir: Path, java: str | None = None, timeout: float = 90):
        self.app_dir = Path(app_dir).resolve()
        self.java = java or self.find_java()
        self.timeout = timeout
        self.token = secrets.token_urlsafe(32)
        self.process = None
        self.log = None
        self.successful = False

    @staticmethod
    def find_java():
        candidates = [os.environ.get("JAVA_HOME", "") + "/bin/java",
                      "/opt/homebrew/opt/openjdk/bin/java",
                      "/usr/local/opt/openjdk/bin/java", shutil.which("java")]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return candidate
        raise RuntimeError("未找到 Java；请安装 Java 17+，或用 --java 指定 java 可执行文件。")

    def __enter__(self):
        sign_dir = self.app_dir / "sign"
        required = [sign_dir / "unidbg-sign.jar"] + [
            self.app_dir / "capture/fq_oversea" / name for name in
            ("libmetasec_ml.so", "libc++_shared.so", "ms_16777218.bin")]
        for path in required:
            if not path.is_file():
                raise RuntimeError(f"缺少签名器文件：{path}")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        log_dir = Path(os.environ.get("HG_DATA_DIR", str(Path(__file__).resolve().parent))) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / f"signer-{os.getpid()}.log"
        self.log = self.log_path.open("w", encoding="utf-8")
        env = dict(os.environ, HG_SIGN_TOKEN=self.token, BIND_HOST="127.0.0.1")
        # Avoid inherited JVM options changing the selected application's launch.
        for key in ("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"):
            env.pop(key, None)
        command = [self.java, "-Xmx1024m", "-XX:+ExitOnOutOfMemoryError",
                   "--add-opens", "java.base/java.lang=ALL-UNNAMED", "-cp",
                   "unidbg-sign.jar", "com.hongguo.sign.FqTrace", "serve", str(port)]
        try:
            self.process = subprocess.Popen(command, cwd=sign_dir, env=env,
                                            stdout=self.log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError(f"签名器启动失败，日志：{self.log_path}")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                        return self
                except OSError:
                    time.sleep(0.25)
            raise RuntimeError(f"签名器启动超时，日志：{self.log_path}")
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log:
            self.log.close()

    def mark_success(self):
        self.successful = True

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        if self.log is None:
            return
        if exc_type is None and self.successful:
            try:
                self.log_path.unlink(missing_ok=True)
            except OSError as exc:
                print(f"提示：未能清理签名器日志 {self.log_path}：{exc}", file=sys.stderr)
        else:
            print(f"签名器日志已保留：{self.log_path}", file=sys.stderr)
