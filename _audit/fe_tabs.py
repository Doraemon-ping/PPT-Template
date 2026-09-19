# -*- coding: utf-8 -*-
"""看清前端页签与页面构建函数（改造前先对准现状）。"""
import re

SRC = open('static/machining_dfm/legacy_app.js', encoding='utf-8').read()

print('== 页签按钮 ==')
for m in re.finditer(r'ondblclick|onclick="sw\(([^"]{0,24})\)">([^<]{1,28})<', SRC):
    if m.group(1) is None:
        continue
    print('   sw(%-14s) %s' % (m.group(1), m.group(2)))

print('\n== si / 页签下标算法 ==')
for m in re.finditer(r'.{0,120}\bsi\s*=.{0,160}', SRC):
    print('   ' + ' '.join(m.group(0).split()))

print('\n== 页面构建函数（bXxx）==')
print('   ' + ', '.join(sorted(set(re.findall(r'function (b[A-Z][A-Za-z]*)\(', SRC)))))

print('\n== 选型报价在哪一页（fixQuoteTable / inspQuoteTable 被谁调用）==')
for name in ('fixQuoteTable', 'inspQuoteTable'):
    for m in re.finditer(r'.{0,80}' + name + r'\s*\(.{0,80}', SRC):
        print('   ' + ' '.join(m.group(0).split())[:190])

print('\n== 工序页里的设备选择 ==')
for m in re.finditer(r'.{0,60}(机器|设备)[^;]{0,120}', SRC):
    text = ' '.join(m.group(0).split())
    if 'mid' in text or 'MDB' in text or '设备' in text:
        print('   ' + text[:190])
