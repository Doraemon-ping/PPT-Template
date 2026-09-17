"""启动「通用 PPT 模板工作台」独立进程。

用法：
    python run_service.py                          # 默认 127.0.0.1:8003
    python run_service.py --host 0.0.0.0           # 局域网可访问
    python run_service.py --port 8013 --reload     # 开发模式热重载

环境变量：WORKBENCH_HOST / WORKBENCH_PORT / DFM_APP_ROOT（数据根目录，默认项目根）
数据目录：<DFM_APP_ROOT>/data/ppt_workbench/（模板、方案、草稿、预览缓存）
数据源连接：config/ppt-connections.json（可复制 config/ppt-connections.example.json）
"""
import argparse
import os

import uvicorn

DEFAULT_HOST = os.environ.get('WORKBENCH_HOST', '127.0.0.1')
DEFAULT_PORT = int(os.environ.get('WORKBENCH_PORT', '8003'))


def main() -> int:
    parser = argparse.ArgumentParser(description='通用 PPT 模板工作台')
    parser.add_argument('--host', default=DEFAULT_HOST)
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--reload', action='store_true', help='开发模式热重载')
    parser.add_argument('--log-level', default=os.environ.get('WORKBENCH_LOG_LEVEL', 'info'))
    args = parser.parse_args()
    uvicorn.run('app.services.workbench:app', host=args.host, port=args.port,
                reload=args.reload, log_level=args.log_level)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())