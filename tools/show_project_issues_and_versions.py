"""把项目里剩下的三块业务数据拆出来看：问题清单 is[]、版本履历 vh[]、选型报价（G 里的数组）。

线上这三块**还没落表**（阶段 2/3 待做），本工具分三部分：
1. 现在的样子：逐行逐列打印线上真实数据（含「引用的工序名能不能对上」这类现存缺陷）；
2. 落表后长什么样：按 docs/MACHINING_BUSINESS_REFACTOR.md 的设计给出建表列与旧键映射；
3. 顺带把自动快照 revisions 的实际情况（条数/体积）列出来，跟人工维护的 vh[] 对照。

用法：
    python tools/show_project_issues_and_versions.py
    python tools/show_project_issues_and_versions.py --json     # 额外打印原始 JSON
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

from app.machining_dfm import MachiningDFMStore  # noqa: E402

LIVE = BASE / "data" / "machining_dfm"
SEED = BASE / "app" / "resources" / "machining_dfm_seed"

ISSUE_KEYS = (
    ("tp", "issue_type", "问题类型", "text"),
    ("pr", "process_id", "工序（现在存的是工序名字）", "FK → project_processes.id"),
    ("ds", "description", "问题描述", "text"),
    ("fx", "fix_plan", "修改方案", "text"),
    ("cr", "customer_reply", "客户回复", "text"),
    ("st", "status", "状态", "text 进行中/已完成"),
    ("bI", "before_photo_id", "优化前图片", "FK → assets.id"),
    ("aI", "after_photo_id", "优化后图片", "FK → assets.id"),
)
VERSION_KEYS = (
    ("dt", "event_date", "日期", "text（input type=date）"),
    ("ver", "label", "版本号", "text 如 V1.0"),
    ("ds", "note", "变更内容", "text"),
    ("by", "author", "变更人", "text"),
)
SELECTION_KEYS = ("fixQ", "fixQC", "insp", "inspQ")


def cell(value, limit: int = 70) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        text = repr(value.replace("\n", "\\n"))
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    store = MachiningDFMStore(LIVE, SEED)
    db = sqlite3.connect(f"file:{LIVE / 'machining_dfm.sqlite3'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        project = db.execute("SELECT id,name,revision FROM projects").fetchone()
        revisions = db.execute(
            "SELECT revision,created,length(state_json) AS n FROM revisions WHERE project_id=? "
            "ORDER BY revision DESC",
            (project["id"],),
        ).fetchall()
    finally:
        db.close()

    state = store.get(project["id"])["state"]
    issues = state.get("is") or []
    versions = state.get("vh") or []
    general = state.get("G") or {}
    processes = state.get("pr") or []
    process_names = [str(row.get("nm") or "") for row in processes]

    print("=" * 96)
    print(f"项目：{project['name']}（v{project['revision']}）")
    print("=" * 96)
    print(f"state_json 里剩下的三块：is[] {len(issues)} 行 · vh[] {len(versions)} 行 · "
          f"选型报价 4 个数组")
    print()

    # ---------------- 1) 问题清单 ----------------
    print("=" * 96)
    print(f"一、问题清单 is[]：{len(issues)} 行 → 将来落 project_issues")
    print("=" * 96)
    if not issues:
        print("  （这个项目还没有问题记录）")
    for index, issue in enumerate(issues):
        print(f"—— 第 {index + 1} 行（页面排序第 {index + 1} 条）")
        for key, column, label, note in ISSUE_KEYS:
            value = issue.get(key)
            extra = ""
            if key == "pr":
                hit = process_names.index(value) if value in process_names else -1
                if hit >= 0:
                    extra = f"  ← 能在工序里对上第 {hit + 1} 道（按名字对，工序改名就对不上）"
                else:
                    extra = "  ← 没有任何工序叫这个名字（现在会显示成空引用）"
            print(f"   {key:<4} → {column:<18} = {cell(value):<24} {label}（{note}）{extra}")
        print()
    print("   现存的缺陷（这次重构顺手修掉）：")
    print("   · pr 存的是工序名字：工序改名后这条问题就指向不存在——落表时改成")
    print("     process_id 外键；同时把旧名字存进 name_snapshot，历史行照样说得清。")
    print("   · bI/aI 现在存的是整张图的 data URL（会随 state_json 一起膨胀），")
    print("     落表后进 assets 附件库，列里只存附件 id。")
    print()

    # ---------------- 2) 版本履历 ----------------
    print("=" * 96)
    print(f"二、版本履历 vh[]：{len(versions)} 行（人工维护的那张表）→ 将来落 project_versions")
    print("=" * 96)
    if not versions:
        print("  （现在是空的：页面上的「+ 新增版本记录」还没点过，所以一行都没有）")
    for index, version in enumerate(versions):
        print(f"—— 第 {index + 1} 行")
        for key, column, label, note in VERSION_KEYS:
            print(f"   {key:<4} → {column:<12} = {cell(version.get(key)):<24} {label}（{note}）")
        print()
    print("   页面上这张表的四个输入框：日期 / 版本号 / 变更内容 / 变更人，")
    print("   加上「+ 新增版本记录」和逐行删除。")
    print("   注意区分两套版本：")
    print(f"   · 人工维护的版本履历 vh[]    = {len(versions)} 行（你手填的，业务版本）")
    print(f"   · 系统自动留的快照 revisions = {len(revisions)} 条（每次保存一条，数据版本）")
    print("   重构后合并成一张 project_versions：手填的记 kind=manual（可勾选同时存快照），")
    print("   自动的记 kind=auto（has_snapshot=1），再加一张 project_changes 记")
    print("   这个版本比上个版本改了哪些字段。")
    print()
    print("   自动快照现状（revisions）：")
    total = sum(row["n"] for row in revisions)
    smallest = min(row["n"] for row in revisions)
    largest = max(row["n"] for row in revisions)
    print(f"     共 {len(revisions)} 条，合计 {total / 1024:.1f} KB，"
          f"单条 {smallest} ~ {largest} 字节")
    print(f"     最新一条：v{revisions[0]['revision']} @ {revisions[0]['created']}"
          f"（{revisions[0]['n']} 字节）")
    print(f"     最早一条：v{revisions[-1]['revision']} @ {revisions[-1]['created']}"
          f"（{revisions[-1]['n']} 字节）")
    print()

    # ---------------- 3) 选型报价 ----------------
    print("=" * 96)
    print("三、夹具 / 检具选型报价（还在 project_settings.extra_json 里，第一阶段没动）")
    print("=" * 96)
    for key in SELECTION_KEYS:
        print(f"   {key:<6} = {cell(general.get(key), 90)}")
    print()
    print("   这四个是按「类别下标」对齐的数组——夹具库加一行、检具类别顺序一变，")
    print("   整列就会错位（这正是要落 project_selections 的原因：变成行 + id 外键 + 价格快照）。")
    print()

    if args.json:
        print("原始 JSON：")
        payload = {"is": issues, "vh": versions}
        payload.update({key: general.get(key) for key in SELECTION_KEYS})
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
