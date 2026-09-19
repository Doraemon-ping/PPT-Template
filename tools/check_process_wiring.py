"""核对 1b + 2a + 2b + 3a + 3b 改造：写入点该行级保存的行级保存、该服务端记录的服务端记录。

为什么需要这个检查：数据落表后，页面上任何一个"直接改内存"的写入点如果漏掉，
表现就是"界面上改了、表里没变"或者"下次整份保存把表里的新值覆盖回去"，
而且不报错、不冒烟，只有用久了才发现。这里把它变成一条可重复跑的检查。

覆盖：
* 阶段 1b：``PR[]`` / 刀具行（``tl[]``）的写入点；
* 阶段 2a：问题清单 ``IS[]`` 的写入点（含工序外键与两张图片）；
* 阶段 2b：选型报价 ``G.fixQ/fixQC/insp/inspQ`` 的写入点（按"类别 + 格子下标"）；
* 阶段 3a：版本履历 ``VH[]`` 的写入点（四个格子 + 新增/删除 + 客户版本切换自动追加）；
* 阶段 3b：变更流水**只由服务端记录**——页面上一个写入点都不该有（前端只读不写，
  流水是行级写入的副产物；界面留到阶段 4 回收站一起做）。

用法：python tools/check_process_wiring.py
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from process_wiring import (  # noqa: E402
    EXEMPT,
    HISTORY_EXEMPT,
    HISTORY_WRITE_POINTS,
    ISSUE_EXEMPT,
    ISSUE_WRITE_POINTS,
    SELECTION_EXEMPT,
    SELECTION_WRITE_POINTS,
    STATIC_SNIPPETS,
    WRITE_POINTS,
)

STATIC = ROOT / "static" / "machining_dfm"

#: 会改工序/刀具行的写法：PR[...]= / PR.push / PR.splice / tl[...]= / tl.push …
MUTATION = re.compile(
    r"(PR\s*\[\s*[^\]]+\s*\]\s*(?:\.[A-Za-z_$][\w$]*|\[[^\]]+\])?\s*=(?!=))"
    r"|(PR\.push\s*\()|(PR\.splice\s*\()",
)

#: 会改问题清单的写法：IS[...]= / IS.push / IS.splice / IS[...].xxx=
ISSUE_MUTATION = re.compile(
    r"(IS\s*\[\s*[^\]]+\s*\]\s*(?:\.[A-Za-z_$][\w$]*|\[[^\]]+\])?\s*=(?!=))"
    r"|(IS\.push\s*\()|(IS\.splice\s*\()",
)

#: 会改选型报价的写法：G.fixQ[...]= / G.fixQC[...]= / G.insp[...]= / G.inspQ[...]=
SELECTION_MUTATION = re.compile(
    r"G\.(?:fixQ|fixQC|insp|inspQ)\s*\[\s*[^\]]+\s*\]\s*=(?!=)"
    r"|G\.(?:fixQ|fixQC|insp|inspQ)\s*=",
)

#: 会改版本履历的写法：VH[...]= / VH[...].xxx= / VH= / VH.push / VH.splice
HISTORY_MUTATION = re.compile(
    r"(VH\s*\[\s*[^\]]+\s*\]\s*(?:\.[A-Za-z_$][\w$]*|\[[^\]]+\])?\s*=(?!=))"
    r"|(VH\s*=(?!=))|(VH\.push\s*\()|(VH\.splice\s*\()",
)

#: 前端**写**变更流水的任何写法：POST/PATCH/PUT/DELETE 到 /changes
CHANGES_WRITE = re.compile(
    r"method\s*:\s*['\"](?:POST|PATCH|PUT|DELETE)['\"][^}]*?/changes"
    r"|/changes[^}]*?method\s*:\s*['\"](?:POST|PATCH|PUT|DELETE)['\"]",
    re.S,
)

#: 3b：服务端的行级写入点必须逐个记流水（引擎里这六种动作各有一处，缺一个就是漏记）
SERVER_NOTE_ACTIONS = ("create", "update", "delete", "restore", "reorder", "photo")

#: 3b：五张业务表都要声明自己的"实体名"（少了哪张，那张表的改动就进不了流水）
CHANGE_ENTITIES = (
    ('machining_process.py', 'change_entity = "process"'),
    ('machining_process.py', 'change_entity = "tool"'),
    ('machining_issue.py', 'change_entity = "issue"'),
    ('machining_selection.py', 'change_entity = "selection"'),
    ('machining_history.py', 'change_entity = "history"'),
)


def check_points(points, label: str, problems: list[str], legacy: str) -> None:
    print(f"=== {label}：每个写入点：行级保存 + 旧路径 ===")
    for name, gateway, fallback in points:
        has_gateway = gateway in legacy
        has_fallback = fallback in legacy
        print(f"  {'√' if has_gateway else '×'} {name}"
              f"｜行级保存{'有' if has_gateway else '缺'}"
              f"｜旧路径{'有' if has_fallback else '缺'}")
        if not has_gateway:
            problems.append(f"{name}：没有走行级保存")
        if not has_fallback:
            problems.append(f"{name}：旧路径被删了（开关关着时页面会坏）")
    print()


def scan(lines, pattern, exempt, gateway_tokens, label: str, problems: list[str]) -> None:
    print(f"=== 扫描：{label}还有没有漏掉的写入点 ===")
    missed: list[tuple[int, str]] = []
    for number, line in enumerate(lines, start=1):
        if any(token in line for token in gateway_tokens):
            continue
        if not pattern.search(line):
            continue
        if any(token in line for token in (item[0] for item in exempt)):
            continue
        missed.append((number, line.strip()))
    if missed:
        for number, text in missed:
            print(f"  × 第 {number} 行未接管：{text[:160]}")
            problems.append(f"第 {number} 行有未接管的{label}写入：{text[:80]}")
    else:
        print(f"  √ 没有漏掉的写入点（其余赋值都在豁免清单里）")
    print()


def main() -> int:
    legacy = (STATIC / "legacy_app.js").read_text(encoding="utf-8")
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    module = (STATIC / "process_page.js").read_text(encoding="utf-8")
    issue_module = (STATIC / "issue_page.js").read_text(encoding="utf-8")
    selection_module = (STATIC / "selection_page.js").read_text(encoding="utf-8")
    history_module = (STATIC / "history_page.js").read_text(encoding="utf-8")
    host = (STATIC / "host.js").read_text(encoding="utf-8")
    lines = legacy.splitlines()
    problems: list[str] = []

    check_points(WRITE_POINTS, "1) 工序/刀具行（1b）", problems, legacy)
    check_points(ISSUE_WRITE_POINTS, "2) 问题清单（2a）", problems, legacy)
    check_points(SELECTION_WRITE_POINTS, "3) 选型报价（2b）", problems, legacy)
    check_points(HISTORY_WRITE_POINTS, "4) 版本履历（3a）", problems, legacy)

    scan(lines, MUTATION, EXEMPT, ("ppOn()", "ProcessPage."), "工序", problems)
    scan(lines, ISSUE_MUTATION, ISSUE_EXEMPT, ("ipOn()", "IssuePage."), "问题清单", problems)
    scan(lines, SELECTION_MUTATION, SELECTION_EXEMPT, ("spOn()", "SelectionPage."),
         "选型报价", problems)
    scan(lines, HISTORY_MUTATION, HISTORY_EXEMPT, ("hpOn()", "HistoryPage."),
         "版本履历", problems)

    print("=== 3) 页面装配 ===")
    for label, snippet in STATIC_SNIPPETS:
        if label.startswith("index"):
            target = index
        elif "issue_page" in label:
            target = issue_module
        elif "selection_page" in label:
            target = selection_module
        elif "history_page" in label:
            target = history_module
        elif "process_page" in label:
            target = module
        elif "host.js" in label:
            target = host
        else:
            target = legacy
        hit = snippet in target
        print(f"  {'√' if hit else '×'} {label}")
        if not hit:
            problems.append(f"{label}：缺少 {snippet[:60]}")

    print("\n=== 4) 模块自身要点 ===")
    checks = (
        ("工序：读行列表拿行 id", "'/projects/'+encodeURIComponent(pid)+'/processes'" in module),
        ("工序：行级 PATCH 刀具行", "'/tools/'+encodeURIComponent(row.id)" in module),
        ("工序：图片走附件接口", "'/photo'" in module and "method:'PUT'" in module),
        ("工序：刀号 id→code 换名", "TOOL_KEY_ALIAS={id:'code'}" in module),
        ("工序：刀柄/配件写快照", "hld_id" in module and "acc_price" in module),
        ("工序：列表长度不一致就刷新不瞎写", "工序列表已变化，正在刷新" in module),
        ("工序：删除有二次确认", "confirm(" in module),
        ("工序：至少留一道工序/一把刀", "至少保留一道工序" in module and "至少保留一把刀" in module),
        ("问题：读行列表拿行 id", "'/projects/'+encodeURIComponent(pid)+'/issues'" in issue_module),
        ("问题：行级 PATCH 一行", "'/issues/'\n        +encodeURIComponent(row.id)" in issue_module),
        ("问题：工序下拉换成外键写 process_id", "process_id:processId" in issue_module),
        ("问题：工序序号对不上就刷新不瞎写", "工序列表已变化，正在刷新" in issue_module),
        ("问题：图片走附件接口（两个槽）", "PHOTO_SLOTS={bI:'before',aI:'after'}" in issue_module),
        ("问题：删除/恢复走逻辑删除接口", "'/restore'" in issue_module and "removeIssue" in issue_module),
        ("选型：读一次格子列表再写（下标不缓存）", "KIND_PATH[kind]" in selection_module),
        ("选型：按 (哪一类, 格子) 定位，不碰行 id",
         "'/'+encodeURIComponent(slot)" in selection_module and "KIND_PATH" in selection_module),
        ("选型：两类各一套路径（/fixtures、/gauges）",
         "KIND_PATH={fixture:'fixtures',gauge:'gauges'}" in selection_module),
        ("选型：选型写 legacy_key（服务端负责绑库）", "json:{legacy_key:text}" in selection_module),
        ("选型：清空走 DELETE（行保留）", "method:'DELETE'" in selection_module),
        ("选型：是否报价单独 PATCH 一个格子", "json:{quoted:on?1:0}" in selection_module),
        ("选型：格子不在就刷新不瞎写", "这一格已经不在了" in selection_module),
        ("履历：读行列表拿行 id", "'/projects/'+encodeURIComponent(pid)+'/history'" in history_module),
        ("履历：行级 PATCH 一行", "'/history/'\n        +encodeURIComponent(found.row.id)" in history_module),
        ("履历：只认四个格子", "const FIELDS=['dt','ver','ds','by'];" in history_module),
        ("履历：新增一行走 POST", "{method:'POST',json:fields||{}}" in history_module),
        ("履历：删除走逻辑删除接口", "'/history/'\n        +encodeURIComponent(found.row.id)+'?reason='" in history_module),
        ("履历：下标越界就刷新不瞎写", "这一行已经不在了" in history_module),
    )
    for label, ok in checks:
        print(f"  {'√' if ok else '×'} {label}")
        if not ok:
            problems.append(f"模块：{label} 缺失")

    print("\n=== 5) 变更流水：只由服务端记录（3b）===")
    # 5.1 前端一个写入点都不许有（流水是行级写入的副产物，页面只读不写）
    for page in sorted(STATIC.iterdir()):
        if page.suffix not in (".js", ".html"):
            continue
        text = page.read_text(encoding="utf-8")
        hit = CHANGES_WRITE.search(text)
        print(f"  {'√' if not hit else '×'} {page.name}：{'没有写流水的代码' if not hit else '竟然在写流水'}")
        if hit:
            problems.append(f"{page.name} 里有写变更流水的代码：{hit.group(0)[:60]}")
    # 5.2 服务端：引擎里六种动作都记、五张表都自报了实体名
    process_source = (ROOT / "app" / "machining_process.py").read_text(encoding="utf-8")
    for action in SERVER_NOTE_ACTIONS:
        ok = f'_note_change("{action}"' in process_source
        print(f"  {'√' if ok else '×'} 引擎：{action} 记流水（_note_change(\"{action}\")）")
        if not ok:
            problems.append(f"引擎里 {action} 没有记流水")
    for filename, snippet in CHANGE_ENTITIES:
        source = (ROOT / "app" / filename).read_text(encoding="utf-8")
        ok = snippet in source
        print(f"  {'√' if ok else '×'} {filename}：{snippet}")
        if not ok:
            problems.append(f"{filename} 里缺少 {snippet}")
    routes = (ROOT / "app" / "machining_dfm.py").read_text(encoding="utf-8")
    ok = 'def list_project_changes' in routes and "/changes\")" in routes
    print(f"  {'√' if ok else '×'} 服务端提供只读清单 GET /projects/{'{project_id}'}/changes")
    if not ok:
        problems.append("缺少变更流水只读接口")
    for snippet, why in (
        ("_changes_guard()", "没开关时给 409 而不是 500"),
        ("self.change_table = ProjectChanges(", "变更流水表对象接上了"),
        ('"changes_table": self.changes_enabled', "记录里带 changes_table 标志（页面能判断）"),
        ("self._flush_changes(", "流水落库（与保存版本同一事务）"),
        ("def _quiet_changes(", "系统搬数据时静音（不无中生有记流水）"),
    ):
        ok = snippet in routes
        print(f"  {'√' if ok else '×'} 接线：{why}")
        if not ok:
            problems.append(f"接线缺失：{why}")
    print("  （流水的界面留到阶段 4 回收站一起做：这一阶段只有服务端记录 + 只读接口）")

    print()
    if problems:
        print("× 发现问题：")
        for item in problems:
            print("  -", item)
        return 1
    print("√ 前端接管完整：工序、问题清单、选型报价与版本履历的每个写入点都走行级保存，"
          "且旧路径仍在；变更流水由服务端在每个行级写入点记录，前端一个写入点都没有")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
