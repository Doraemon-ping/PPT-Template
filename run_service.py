"""启动「机加 DFM 表单服务」独立进程。

用法：
    python run_service.py                          # 默认 127.0.0.1:8002
    python run_service.py --host 0.0.0.0           # 局域网可访问
    python run_service.py --port 8012 --reload     # 开发模式热重载

环境变量：MACHINING_HOST / MACHINING_PORT / DFM_APP_ROOT（数据目录根，默认项目根）
数据目录：<DFM_APP_ROOT>/data/machining_dfm/
"""
import argparse
import os

import uvicorn

DEFAULT_HOST = os.environ.get('MACHINING_HOST', '127.0.0.1')
DEFAULT_PORT = int(os.environ.get('MACHINING_PORT', '8002'))


def main() -> int:
    parser = argparse.ArgumentParser(description='机加 DFM 表单服务')
    parser.add_argument('--host', default=DEFAULT_HOST)
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--reload', action='store_true', help='开发模式热重载')
    parser.add_argument('--log-level', default=os.environ.get('MACHINING_LOG_LEVEL', 'info'))
    args = parser.parse_args()
    uvicorn.run('app.services.machining:app', host=args.host, port=args.port,
                reload=args.reload, log_level=args.log_level)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
