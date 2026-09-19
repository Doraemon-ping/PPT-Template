"""检查机加页面的样式是否齐全：host.js 用到的 class 必须在 app.css ∪ host.css 里有定义。

背景：`host.css`（顶部项目条、后台配置对话框、库计数等）在分支拆分时丢了，
`index.html` 还挂着 `<link>`，浏览器一直拿 404，页面顶部/弹窗等于没样式。
"""

from __future__ import annotations

import io
import os
import re
import sys

# 控制台是 GBK 时 ✓/✗ 会抛 UnicodeEncodeError（脚本本身没问题，只是打印编码），
# 与 check_process_wiring.py 一样把 stdout 固定成 UTF-8，任何控制台都能跑完并给出退出码。
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

STATIC = "static/machining_dfm"
problems: list[str] = []


def read(name: str) -> str:
    with io.open(os.path.join(STATIC, name), encoding="utf-8") as handle:
        return handle.read()


html = read("index.html")
css = read("app.css") + "\n" + read("host.css")
js = read("host.js")

# 1. index.html 引用的样式表都要真实存在（别再出现 404 的 host.css）
for href in re.findall(r'<link[^>]+href="([^"]+)"', html):
    path = href.split("?")[0]
    target = os.path.join("static", path.split("/static/", 1)[-1]) if "/static/" in path else path.lstrip("/")
    exists = os.path.exists(target)
    print(("  ✓ " if exists else "  ✗ ") + f"样式表存在：{path}")
    if not exists:
        problems.append(f"{path} 不存在（页面会 404）")

# 2. host.js 用到的 class 必须被某张样式表覆盖
used = sorted({name for group in re.findall(r'class="([^"]+)"', js) for name in group.split()})
missing = [name for name in used if ("." + name) not in css]
print(("  ✓ " if not missing else "  ✗ ") + "host.js 的 class 都有样式：" + ", ".join(used))
if missing:
    problems.append("缺少样式定义：" + ", ".join(missing))

# 3. 版本号要统一（缓存版本混用会让浏览器拿旧文件）
versions = set(re.findall(r"\?v=([\w.-]+)", html))
print(("  ✓ " if len(versions) == 1 else "  ✗ ") + "静态资源版本号统一：" + ", ".join(sorted(versions)))
if len(versions) != 1:
    problems.append("版本号不统一：" + ", ".join(sorted(versions)))

print("发现问题:\n - " + "\n - ".join(problems) if problems else "全部检查通过 ✓")
sys.exit(1 if problems else 0)
