/* 统一解析服务端错误响应：优先展示 JSON 里的 detail，其次退回响应文本，
 * 并附带 HTTP 状态码与 X-Request-Id（便于和服务端 data/logs/server.log 对应）。
 */
(function (global) {
  'use strict';

  function dfmReadError(status, text, requestId) {
    var detail = '';
    var body = (text || '').trim();
    if (body) {
      try {
        var parsed = JSON.parse(body);
        if (parsed && typeof parsed.detail === 'string') {
          detail = parsed.detail;
        } else if (parsed && parsed.detail) {
          detail = JSON.stringify(parsed.detail);
        } else if (parsed && parsed.error) {
          detail = String(parsed.error);
        }
      } catch (e) {
        // 非 JSON（例如未捕获异常时的纯文本 500）——直接截取正文
        detail = body.length > 300 ? body.slice(0, 300) + '…' : body;
      }
    }
    var parts = [detail || '请求失败'];
    parts.push('HTTP ' + status);
    if (requestId) { parts.push('请求号 ' + requestId); }
    return parts.join(' · ');
  }

  global.dfmReadError = dfmReadError;
})(typeof window !== 'undefined' ? window : this);
