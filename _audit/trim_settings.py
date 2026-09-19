# -*- coding: utf-8 -*-
"""把 legacy_app.js 里 bSettings() 的"工序管理 + 选型表 + 检具选择"三块摘掉。

这三块已经搬成顶层页签：
  工序管理     → bProcessTable()（页签 1「工序」）
  fixQuoteTable → bFixtureSelect()（页签 2「夹具选型」）
  inspQuoteTable + 检具选择 → bGaugeSelect()（页签 3「检具选型」）

按行号做，因为这几行都是几百到上千字符的长表达式，没法用一个字面量匹配。
每一条边界都先断言内容对得上，对不上就整个脚本不写文件（宁可失败也不半改）。
"""
import io

PATH = 'static/machining_dfm/legacy_app.js'
with io.open(PATH, encoding='utf-8') as handle:
    lines = handle.read().split('\n')


def expect(number: int, needle: str) -> None:
    text = lines[number - 1]
    assert needle in text, f'第 {number} 行对不上：期望包含 {needle!r}，实际 {text[:100]!r}'


expect(600, 'function bSettings(){')
expect(601, 'if(!checkPwd())return;')
expect(602, 'var _bL=')
expect(603, '工艺设置 / Settings')
expect(606, '工序管理 / Process Management')
expect(617, '+ 添加工序</button></div></div></div>')
expect(618, 'bCostTable()+inspQuoteTable()+fixQuoteTable()')
expect(618, '检具选择 / Inspection Fixtures')
expect(619, '数据保存与导出 / Save & Export')
assert '_bO' not in '\n'.join(lines[617:618]) or True  # 只作提示，真正的检查在下面

out = (
    lines[:601]                 # 1..601：函数头
    + lines[602:605]            # 603..605：标题 + 两句说明
    + ['    bCostTable()+']     # 618 只留成本表（选型已各自成页）
    + lines[618:]               # 619.. 之后照旧
)

text = '\n'.join(out)
# 这两个变量现在只该在 bGaugeSelect() 里定义一次（老 bSettings 里那份要被摘掉）
for gone in ('var _bO=', 'var _fO=', 'var _bL='):
    assert text.count(gone) == 1, f'{gone} 出现 {text.count(gone)} 次（应该只剩 bGaugeSelect 里那一份）'
with io.open(PATH, 'w', encoding='utf-8', newline='\n') as handle:
    handle.write(text)
print('OK：摘掉 %d 行，文件现在 %d 行' % (len(lines) - len(out), len(out)))
