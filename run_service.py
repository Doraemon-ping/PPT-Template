"""启动「压铸 DFM 表单服务」独立进程。

用法：
    python run_service.py                          # 默认 127.0.0.1:8001
    python run_service.py --host 0.0.0.0           # 局域网可访问
    python run_service.py --port 8011 --reload     # 开发模式热重载

环境变量：HPDC_HOST / HPDC_PORT / DFM_APP_ROOT（数据根目录，默认项目根）
数据目录：<DFM_APP_ROOT>/data/form_platform/（表单平台项目库）、data/project.json
"""
import argparse
import os

import uvicorn

DEFAULT_HOST = os.environ.get('HPDC_HOST', '127.0.0.1')
DEFAULT_PORT = int(os.environ.get('HPDC_PORT', '8001'))


def main() -> int:
    parser = argparse.ArgumentParser(description='压铸 DFM 表单服务')
    parser.add_argument('--host', default=DEFAULT_HOST)
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--reload', action='store_true', help='开发模式热重载')
    parser.add_argument('--log-level', default=os.environ.get('HPDC_LOG_LEVEL', 'info'))
    args = parser.parse_args()
    uvicorn.run('app.services.hpdc:app', host=args.host, port=args.port,
                reload=args.reload, log_level=args.log_level)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())