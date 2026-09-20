"""按服务隔离的日志与请求标识；不含任何业务依赖。

日志落在 ``<DATA_DIR>/<服务名>/logs/server.log``（滚动切分），并对外提供
``/api/logs/tail`` 与 ``/api/logs/download`` 两个只读接口，可选带鉴权钩子。
"""
import logging
import time
import uuid
from collections import deque
from logging.handlers import RotatingFileHandler
from typing import Callable

from fastapi import Header
from fastapi.responses import JSONResponse, FileResponse

from ..core.config import DATA_DIR


def install(app, name, guard: Callable[[str | None], None] | None = None):
    """挂上请求日志与两个日志读取接口。

    ``guard`` 给"日志要鉴权"的服务用：收到 ``Authorization`` 头后自行决定放不放行（不通过就抛）。
    不传就维持原样（日志接口谁都能读，只适合纯内网的老服务）。
    """
    path = DATA_DIR / name / 'logs' / 'server.log'
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('dfm.service.' + name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(path, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger.addHandler(handler)

    @app.middleware('http')
    async def log_requests(request, call_next):
        request_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.exception('未处理异常 %s %s [%s]', request.method, request.url.path, request_id)
            response = JSONResponse({'detail': f'服务器内部错误：{exc}', 'request_id': request_id}, status_code=500)
        response.headers['X-Request-Id'] = request_id
        logger.info('%s %s -> %s %.0fms [%s]', request.method, request.url.path,
                    response.status_code, (time.perf_counter()-started)*1000, request_id)
        return response

    @app.get('/api/logs/tail')
    def tail(lines: int = 200, authorization: str | None = Header(None)):
        if guard is not None:
            guard(authorization)
        with path.open(encoding='utf-8', errors='replace') as stream:
            return {'file': str(path), 'lines': list(deque(stream, maxlen=max(1, min(lines, 2000))))}

    @app.get('/api/logs/download')
    def download(authorization: str | None = Header(None)):
        if guard is not None:
            guard(authorization)
        return FileResponse(path, filename=name + '-server.log')

    return path
