"""把线上那条项目的「项目信息」整份拆出来看：表结构 + 每一列的值 + 附件 + 兜底字段。

用法：
    python tools/show_project_info_row.py            # 默认看线上库（只读）
    python tools/show_project_info_row.py --all       # 连空列也一起列出来
    python tools/show_project_info_row.py --json      # 额外打印该行原始 JSON（便于对照）
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
from app.machining_project import SETTINGS_ATTACHMENTS, SETTINGS_FIELDS  # noqa: E402

LIVE = BASE / "data" / "machining_dfm"
SEED = BASE / "app" / "resources" / "machining_dfm_seed"


def cell(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        text = value.replace("\n", "\\n")
        return text if text == "" else f"{text!r}"
    return repr(value)


def is_blank(value) -> bool:
    return value in (None, "", 0, 0.0, "{}")


def pr_signature(rows) -> str:
    """工序数组的紧凑指纹：工序名/mc + 每行刀具的 (刀号, vf, n, d)，便于一眼看出改在哪。"""
    if not isinstance(rows, list):
        return str(rows)
    parts = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        tools = [f"{tool.get('id')}:{tool.get('vf')}/{tool.get('n')}/{tool.get('d')}"
                 for tool in (row.get("tl") or []) if isinstance(tool, dict)]
        parts.append(f"[{row.get('nm')}|mc{row.get('mc')}|" + " ".join(tools) + "]")
    return " ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="空列也列出来")
    parser.add_argument("--json", action="store_true", help="额外打印原始行 JSON")
    parser.add_argument("--versions", type=int, default=0, metavar="N",
                        help="打印最近 N 个版本各自改了什么（对比上一版）")
    parser.add_argument("--root", default=str(LIVE))
    args = parser.parse_args()
    root = Path(args.root)
    db_path = root / "machining_dfm.sqlite3"

    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        ddl = db.execute("SELECT sql FROM sqlite_master WHERE name='project_settings'").fetchone()
        rows = db.execute("SELECT * FROM project_settings").fetchall()
        project = db.execute("SELECT id,name,revision,length(state_json) AS n FROM projects").fetchone()
        revisions = db.execute("SELECT COUNT(*) AS n FROM revisions WHERE project_id=?",
                               (project["id"],)).fetchone()["n"]
        assets = {row["id"]: dict(row) for row in
                  db.execute("SELECT id,kind,name,size,path FROM assets")}
        archive = db.execute("SELECT length(state_json) AS n FROM projects_legacy_v1 LIMIT 1").fetchone()
    finally:
        db.close()

    print("=" * 78)
    print("project_settings 表结构（1b 未改动，这是 1a 项目信息落表时建的）")
    print("=" * 78)
    print(ddl["sql"] + ";")
    print()

    if not rows:
        print("（表里没有行）")
        return 0
    print(f"表里 {len(rows)} 行"
          + ("（一个项目一行）" if len(rows) == 1 else "")
          + f" · 列数 {len(rows[0].keys())}")
    print()

    for index, row in enumerate(rows):
        data = dict(row)
        print("=" * 78)
        print(f"第 {index + 1} 行：project_id = {data['project_id']}"
              f"（= projects.id，{'对得上' if data['project_id'] == project['id'] else '对不上！'}）")
        print("=" * 78)
        print(f"  项目名称       = {project['name']}")
        print(f"  当前版本       = v{project['revision']}（历史快照 {revisions} 条）")
        print(f"  state_json     = {project['n']} 字节（只剩 is/pr/vh；G 已搬进本表）")
        if archive:
            print(f"  迁移前归档     = {archive['n']} 字节（projects_legacy_v1）")
        print()

        print("  —— 建模列（页面上的输入项，一行一列）")
        blank = 0
        for field in SETTINGS_FIELDS:
            value = data.get(field.column)
            if is_blank(value) and not args.all:
                blank += 1
                continue
            unit = f" {field.unit}" if getattr(field, "unit", "") else ""
            shown = value
            if field.kind == "choice":
                labels = dict(getattr(field, "choice_labels", ()) or ())
                shown = f"{value!r}（{labels.get(value, '?')}）"
            print(f"    {field.column:<18} = {cell(shown):<34} ← G.{field.key:<9} {field.label}{unit}")
        if blank:
            print(f"    （另有 {blank} 列是空/默认值，加 --all 可看全）")
        print()

        print("  —— 图片列（存的是附件 id，不是 data URL）")
        for spec in SETTINGS_ATTACHMENTS:
            asset_id = data.get(spec.column)
            if asset_id and asset_id in assets:
                info = assets[asset_id]
                print(f"    {spec.column:<20} = {asset_id}  ← G.{spec.legacy_key:<9} "
                      f"{info['kind']} · {info['size']} 字节 · {info['name']}")
            else:
                print(f"    {spec.column:<20} = {cell(asset_id):<34} ← G.{spec.legacy_key:<9} （没传图）")
        print()

        extra = data.get("extra_json") or "{}"
        try:
            parsed_extra = json.loads(extra)
        except ValueError:
            parsed_extra = {"<解析失败>": extra}
        print(f"  —— 兜底列 extra_json（建模之外的键，一个都不丢）：{len(parsed_extra)} 个键")
        for key, value in parsed_extra.items():
            print(f"    {key:<18} = {cell(value)[:60]}")
        print()

        print("  —— 记账列")
        for key in ("created", "updated"):
            print(f"    {key:<18} = {cell(data.get(key))}")
        print()

    # 反证：整行还原成读模型 G，键必须与页面一致
    store = MachiningDFMStore(root, SEED)
    record = store.get(project["id"])
    general = record["state"].get("G") or {}
    print("=" * 78)
    print(f"整行还原出来的读模型 G：{len(general)} 个键（页面就读这份）")
    print("=" * 78)
    modeled = {field.key for field in SETTINGS_FIELDS}
    for key in sorted(general):
        value = general[key]
        tag = "字段" if key in modeled else ("图片" if key in {s.legacy_key for s in SETTINGS_ATTACHMENTS}
                                            else "派生/兼容")
        short = cell(value)
        if len(short) > 60:
            short = short[:57] + "..."
        print(f"    {key:<10} [{tag}] = {short}")

    if args.versions:
        print("=" * 78)
        print(f"最近 {args.versions} 个版本改了什么（口径 1：每次保存都留一版）")
        print("=" * 78)
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            history = db.execute(
                "SELECT revision,name,state_json,created FROM revisions WHERE project_id=? "
                "ORDER BY revision DESC LIMIT ?",
                (project["id"], args.versions + 1),
            ).fetchall()
        finally:
            db.close()
        for index in range(len(history) - 1):
            newer, older = history[index], history[index + 1]
            new_state, old_state = json.loads(newer["state_json"]), json.loads(older["state_json"])
            changes = []
            for key in sorted(set(new_state) | set(old_state)):
                before, after = old_state.get(key), new_state.get(key)
                if before == after:
                    continue
                if key == "G":
                    for gkey in sorted(set(before or {}) | set(after or {})):
                        if (before or {}).get(gkey) != (after or {}).get(gkey):
                            changes.append(f"G.{gkey}: {cell((before or {}).get(gkey))[:24]} → "
                                           f"{cell((after or {}).get(gkey))[:24]}")
                elif key == "pr":
                    changes.append(f"工序：{pr_signature(before)} → {pr_signature(after)}")
                else:
                    changes.append(f"{key}: {len(before) if isinstance(before, list) else before} → "
                                   f"{len(after) if isinstance(after, list) else after}")
            print(f"  v{newer['revision']}  {newer['created']}  "
                  f"{'、'.join(changes) if changes else '整份内容与上一版相同（只是又点了保存）'}")
        print()

    if args.json:
        print()
        print("原始行 JSON：")
        print(json.dumps(dict(rows[0]), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
