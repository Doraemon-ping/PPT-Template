# -*- coding: utf-8 -*-
"""选型报价现在挂在哪个页面里？工序页面长什么样？"""
import re

SRC = open('static/machining_dfm/legacy_app.js', encoding='utf-8').read()


def owner(fragment: str) -> str:
    """返回包含这段代码的最内层 function 名。"""
    index = SRC.find(fragment)
    if index < 0:
        return '(找不到)'
    best = '(顶层)'
    for match in re.finditer(r'function\s+([A-Za-z_$][\w$]*)\s*\(', SRC):
        start = match.start()
        if start > index:
            break
        # 粗略找这个函数的结束：下一个同级 function 之前
        nxt = SRC.find('\nfunction ', match.end())
        end = len(SRC) if nxt < 0 else nxt
        if start <= index < end:
            best = match.group(1)
    return best


for fragment in ('inspQuoteTable()', 'fixQuoteTable()', 'bCostTable()', 'id="mainPanels"'):
    print('%-24s 所属函数: %s' % (fragment, owner(fragment)))

print('\n== bSetup / bProcess / bSettings 的开头 200 字 ==')
for name in ('bSetup', 'bProcess', 'bSettings', 'bFlow', 'bSummary'):
    match = re.search(r'function\s+' + name + r'\([^)]*\)\s*\{', SRC)
    if match:
        print('\n--- %s ---' % name)
        print(' '.join(SRC[match.start():match.start() + 420].split()))

print('\n== 工序页签是怎么来的（标题 = PR[p].nm）==')
match = re.search(r'.{0,200}PR\[p\]\.nm.{0,200}', SRC)
if match:
    print(' '.join(match.group(0).split()))

print('\n== 每道工序的页面构建入口 ==')
for match in re.finditer(r'curTab===(p\+1|pi\+1)[^;]{0,200}', SRC):
    print('   ' + ' '.join(match.group(0).split())[:200])
