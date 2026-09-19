"""统计前端业务写入点与页签结构，给重构方案的"改造面"提供依据。"""

from __future__ import annotations

import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
src = io.open("static/machining_dfm/legacy_app.js", encoding="utf-8").read()

print("=== 触发保存 save() 的位置数 ===")
print("  save() 调用点:", len(re.findall(r"(?<![\w.])save\(\)", src)))
print("  sve()  调用点:", len(re.findall(r"(?<![\w.])sve\(\)", src)))
print("  render() 调用点:", len(re.findall(r"(?<![\w.])render\(\)", src)))
print("  scheduleSave 引用:", len(re.findall(r"scheduleSave", src)))

print("\n=== 会直接改业务数据的内联处理器（onchange/onclick 里赋值）===")
handlers = re.findall(r'on(?:change|click|input)="([^"]{0,200})"', src)
mutating = [h for h in handlers if re.search(r"(G|PR|IS|VH|tl)\w*\[[^\]]*\]\s*=|\.push\(|\.splice\(", h)]
print("  内联处理器总数:", len(handlers), "其中直接改数据的:", len(mutating))
for item in mutating[:10]:
    print("   -", item[:120])

print("\n=== 报价/成本相关函数 ===")
for name in sorted(set(re.findall(r"function (\w*(?:Quote|Cost|Price|Insp|Fix)\w*)", src))):
    print("  -", name)

print("\n=== 页签渲染函数 ===")
for name in re.findall(r"function (b[A-Z]\w*)\(\)", src):
    print("  -", name)

print("\n=== 业务实体在界面上的位置（关键函数）===")
for name in ("bProcess", "bIssues", "bVersion", "bSettings", "bSetup"):
    match = re.search(rf"function {name}\(\)", src)
    if match:
        snippet = src[match.start():match.start() + 420].replace("\n", " ")
        print(f"\n  {name}: …{snippet[:380]}…")
