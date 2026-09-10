# -*- coding: utf-8 -*-
"""打包成独立 exe（PyInstaller 冻结态）时的启动入口。

app/main.py 的 ``if __name__ == "__main__": run()`` 分支只在直接以模块方式运行时
触发；冻结成 exe 后入口是本文件，负责：
  1) 探测空闲端口（默认 8000，被占用则顺延），避免与其它程序冲突；
  2) 短暂延时后自动打开浏览器；
  3) 把服务日志同时写入 exe 旁 data/server.log，便于排查；
  4) 以进程内方式启动 uvicorn（不能 reload / 不能按字符串导入）。

开发模式下无需使用本文件，直接 ``uvicorn app.main:app --reload`` 即可。
"""
import logging
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path


def _pick_port(preferred: int = 8000) -> int:
    env_port = os.environ.get("DFM_PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass
    for port in range(preferred, preferred + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    return preferred


def _open_browser(url: str, delay: float = 1.4) -> None:
    def _do() -> None:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    timer = threading.Timer(delay, _do)
    timer.daemon = True
    timer.start()


def _setup_file_log(data_dir: Path) -> None:
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(data_dir / "server.log", encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            logger = logging.getLogger(name)
            logger.addHandler(handler)
    except Exception:  # noqa: BLE001
        pass


def _lan_ips():
    """收集本机非回环 IPv4 地址，用于提示局域网访问地址。"""
    ips = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except Exception:  # noqa: BLE001
        pass
    return sorted(ips)


def main() -> None:
    # 提前收集函数体内惰性 import 的模块：保证 PyInstaller 全量打包
    # （collect_submodules('app') 已兜底，这里再显式引入关键链以防万一）。
    import app.main  # noqa: F401
    import app.report.ppt.template_engine  # noqa: F401
    import app.report.ppt.deck  # noqa: F401
    import app.report.ppt.openxml.shape_binding  # noqa: F401
    import app.report.ppt.openxml.slide_repeater  # noqa: F401
    import app.report.ppt.openxml.slide_importer  # noqa: F401
    import app.report.ppt.openxml.package_editor  # noqa: F401
    import app.report.ppt.openxml.image_binding  # noqa: F401
    import app.report.ppt.openxml.visual_binding  # noqa: F401
    import app.report.ppt.openxml.shape_inventory  # noqa: F401
    import app.report.ppt.openxml.placeholder_scanner  # noqa: F401
    import app.report.ppt.openxml.table_pagination  # noqa: F401
    import app.report.ppt.openxml.text_binding  # noqa: F401
    import app.report.ppt.scheme_service  # noqa: F401
    import app.report.ppt.template_registry  # noqa: F401

    import uvicorn

    from app.main import DATA_DIR

    _setup_file_log(DATA_DIR)

    app_obj = app.main.app
    # 默认监听 0.0.0.0（本机 + 局域网均可访问）；如需只限本机，设环境变量 DFM_HOST=127.0.0.1
    host = os.environ.get("DFM_HOST", "0.0.0.0")
    port = _pick_port()
    local_url = f"http://127.0.0.1:{port}"
    print(f"[DFM] 服务启动中")
    print(f"[DFM] 本机访问:   {local_url}")
    if host != "127.0.0.1":
        for ip in _lan_ips():
            print(f"[DFM] 局域网访问: http://{ip}:{port}   (同一网络的其他电脑浏览器打开)")
    if not os.environ.get("DFM_NO_BROWSER"):
        _open_browser(local_url)

    config = uvicorn.Config(
        app_obj,
        host=host,
        port=port,
        log_level=os.environ.get("DFM_LOG_LEVEL", "info"),
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        print("[DFM] 服务已退出")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"[DFM] 启动失败: {exc}", file=sys.stderr)
        try:
            from app.main import DATA_DIR

            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(DATA_DIR / "startup-error.log", "w", encoding="utf-8") as fp:
                import traceback

                traceback.print_exc(file=fp)
        except Exception:  # noqa: BLE001
            pass
        raise
