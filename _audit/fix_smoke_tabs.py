# -*- coding: utf-8 -*-
"""把冒烟脚本里的"页签序号"从 PR.length+N 改成固定序号。

老布局：si = PR.length+1，于是 问题清单=PR.length+1、版本履历=+2、
        工艺设置=+3、设备库=+4、刀具库=+5、夹具库=+6、检具库=+7。
新布局（legacy_app.js 里 SI=4）：0 项目信息 / 1 工序 / 2 夹具选型 / 3 检具选型 /
        4 问题清单 / 5 版本履历 / 6 工艺设置 / 7 设备库 / 8 刀具库 / 9 夹具库 / 10 检具库。

映射（按每个调用点的**用途**，不是机械按数字）：
    PR.length+3 → 6   工艺设置
    PR.length+4 → 7   设备库
    PR.length+5 → 8   刀具库
    PR.length+6 → 9   夹具库
    PR.length+7 → 10  检具库
    PR.length+2 → 2   "选型页"（老脚本用这个序号只是为了让选型下拉被 render 出来，
                      新布局里选型有自己的页签，直接指 2）
"""
import io
import re

PATH = 'tools/smoke_machining_page.mjs'
with io.open(PATH, encoding='utf-8') as handle:
    text = handle.read()

REPLACEMENTS = ()

before = text
MAPPING = {'2': '2', '3': '6', '4': '7', '5': '8', '6': '9', '7': '10'}


def swap(match: 're.Match') -> str:
    number = match.group('n')
    assert number in MAPPING, f'没见过的页签序号 +{number}'
    return match.group('head') + MAPPING[number]


# curTab=PR.length+N （写在被 run() 执行的字符串里）与页签表里的 'PR.length+N'
text = re.sub(r"(?P<head>curTab=)PR\.length\+(?P<n>\d)", swap, text)
text = re.sub(r"'(?P<head>)PR\.length\+(?P<n>\d)'", lambda m: "'" + MAPPING[m.group('n')] + "'", text)

text = text.replace(
    '// legacy_app 的页签基准：si = PR.length + 1（render() 内的局部变量）',
    '// 页签序号现在是**固定的**（legacy_app.js 里 SI=4）：0 项目信息 / 1 工序 / 2 夹具选型 /\n'
    '// 3 检具选型 / 4 问题清单 / 5 版本履历 / 6 工艺设置 / 7 设备库 / 8 刀具库 / 9 夹具库 / 10 检具库')
text = text.replace(
    "run('curTab=PR.length+6;render();');\nawait new Promise(resolve => setTimeout(resolve, 300));\nconst firstFixtureId",
    "run('curTab=9;render();');\nawait new Promise(resolve => setTimeout(resolve, 300));\nconst firstFixtureId")

left = [m.group(0) for m in re.finditer(r'PR\.length\s*\+\s*\d', text)]
print('剩下的 PR.length+N 引用：', left if left else '无')
with io.open(PATH, 'w', encoding='utf-8', newline='\n') as handle:
    handle.write(text)
print('替换完成，改动 %d 处字符' % (len(before) - len(text)))
