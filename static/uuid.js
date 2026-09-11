/* 兼容非安全上下文的 UUID 生成器。
 *
 * 背景：crypto.randomUUID() 只在安全上下文（HTTPS 或 localhost/127.0.0.1）可用；
 * 通过局域网 IP + http（如 http://10.3.74.70:8001）访问时该函数不存在，
 * 会抛 “crypto.randomUUID is not a function” 导致表单加载失败。
 * crypto.getRandomValues 在非安全上下文仍可用，故优先用它生成 RFC4122 v4，
 * 仅在完全没有 crypto 时才退回 Math.random。
 */
(function (global) {
  'use strict';

  function fallbackUuid() {
    var bytes = new Uint8Array(16);
    var c = global.crypto;
    if (c && typeof c.getRandomValues === 'function') {
      c.getRandomValues(bytes);
    } else {
      for (var i = 0; i < 16; i++) { bytes[i] = Math.floor(Math.random() * 256); }
    }
    bytes[6] = (bytes[6] & 0x0f) | 0x40;  // version 4
    bytes[8] = (bytes[8] & 0x3f) | 0x80;  // variant 10xx
    var hex = [];
    for (var j = 0; j < 16; j++) { hex.push((bytes[j] + 0x100).toString(16).slice(1)); }
    return hex.slice(0, 4).join('') + '-' + hex.slice(4, 6).join('') + '-' +
           hex.slice(6, 8).join('') + '-' + hex.slice(8, 10).join('') + '-' +
           hex.slice(10, 16).join('');
  }

  function dfmUuid() {
    var c = global.crypto;
    if (c && typeof c.randomUUID === 'function') {
      try { return c.randomUUID(); } catch (e) { /* 退回到 fallback */ }
    }
    return fallbackUuid();
  }

  global.dfmUuid = dfmUuid;
  // 兜底：若页面/第三方脚本仍直接调用 crypto.randomUUID，也能工作
  if (global.crypto && typeof global.crypto.randomUUID !== 'function') {
    try { global.crypto.randomUUID = dfmUuid; } catch (e) { /* 只读属性时忽略 */ }
  }
})(typeof window !== 'undefined' ? window : this);
