"""Per-service logs and request identifiers; no business dependencies."""
import logging
import time
import uuid
from collections import deque
from logging.handlers import RotatingFileHandler
from fastapi.responses import JSONResponse, FileResponse
from ..settings import DATA_DIR


def install(app, name):
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
    def tail(lines: int = 200):
        with path.open(encoding='utf-8', errors='replace') as stream:
            return {'file': str(path), 'lines': list(deque(stream, maxlen=max(1, min(lines, 2000))))}

    @app.get('/api/logs/download')
    def download():
        return FileResponse(path, filename=name + '-server.log')

    return path
