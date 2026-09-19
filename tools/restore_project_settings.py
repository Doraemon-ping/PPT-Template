"""把项目信息按迁移归档（projects_legacy_v1）还原回表。

起因：整份 PUT 的语义是"没提交的字段回默认值、没提交的图片清空"，
如果只想改两个字段却用了 PUT，其余字段会被重置。本工具用迁移前归档的那份 G
（图片还是 data URL）重新灌一遍，逐键比对确认还原干净。

用法：
    python tools/restore_project_settings.py            # 干跑，只看差异
    python tools/restore_project_settings.py --apply    # 真还原
"""

from __future__ import annotations

import io
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.machining_dfm import MachiningDFMStore  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "machining_dfm"
SEED = ROOT / "app" / "resources" / "machining_dfm_seed"
IMAGE_KEYS = ("pI", "pf", "bInspImg", "fInspImg")

apply_changes = "--apply" in sys.argv
prune_extra = "--prune-extra" in sys.argv
store = MachiningDFMStore(DATA, SEED)

with store.connect() as db:
    projects = db.execute("SELECT id, name, revision FROM projects ORDER BY created").fetchall()
    archive = {
        row["id"]: json.loads(row["state_json"])["G"]
        for row in db.execute("SELECT id, state_json FROM projects_legacy_v1")
    }

def view(typed: dict) -> dict:
    """把 extra_json 摊平、把四个图片槽的类型化键映射回旧键，好和归档的 G 逐键对齐。"""
    merged = {key: value for key, value in typed.items() if key not in ("extra", "fields")}
    merged.update(typed.get("extra") or {})
    merged["_extra"] = typed.get("extra") or {}
    for legacy, slot in (("pI", "product_url"), ("pf", "product2_url"),
                         ("bInspImg", "blank_insp_url"), ("fInspImg", "final_insp_url")):
        merged[legacy] = typed.get(slot)
    return merged


print(f"项目 {len(projects)} 个，归档 {len(archive)} 份")
for project in projects:
    pid = project["id"]
    if pid not in archive:
        print(f"  跳过 {project['name']}：没有迁移归档")
        continue
    current = view(store.settings.typed(pid))
    wanted = archive[pid]
    print(f"\n项目 {project['name']}（v{project['revision']}）")
    diffs = []
    for key, value in wanted.items():
        have = current.get(key)
        if key in IMAGE_KEYS:
            # 归档里是 data URL，表里是附件地址：只比"有没有图"
            if bool(have) != bool(value):
                diffs.append((key, "有图" if value else "无图", "有图" if have else "无图"))
            continue
        if isinstance(have, float) and isinstance(value, (int, float)):
            if abs(have - float(value)) > 1e-9:
                diffs.append((key, value, have))
            continue
        if str(have) != str(value):
            diffs.append((key, value, have))
    if not diffs:
        print("  √ 与归档一致，无需还原")
        if prune_extra:
            stale = sorted(set(current.get("_extra") or {}) - set(wanted))
            if not stale:
                print("  √ extra_json 没有多余键")
            elif not apply_changes:
                print(f"  extra_json 多余键（干跑未删）：{stale}")
            else:
                payload = dict(store.settings.extra(store.settings.find(pid)))
                for key in stale:
                    payload.pop(key, None)
                with store.connect() as db:
                    db.execute(
                        f"UPDATE {store.settings.table} SET extra_json=? WHERE project_id=?",
                        (json.dumps(payload, ensure_ascii=False, separators=(",", ":")), pid),
                    )
                print(f"  已从 extra_json 删掉多余键：{stale}")
        continue
    for key, old, now in diffs:
        print(f"  差异 {key}: 归档 {old!r} → 现在 {now!r}")
    if not apply_changes:
        print("  （干跑，未改动；加 --apply 才写回去）")
        continue
    backup = store.backup_dir / "pre-project-settings-restore.sqlite3"
    if not backup.exists():
        store.backup_dir.mkdir(parents=True, exist_ok=True)
        import sqlite3

        source = sqlite3.connect(DATA / "machining_dfm.sqlite3")
        target = sqlite3.connect(backup)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        print(f"  已备份 {backup}")
    store.settings.apply_state(pid, {"G": wanted}, lenient=True)
    again = view(store.settings.typed(pid))
    left = []
    for key, value in wanted.items():
        have = again.get(key)
        if key in IMAGE_KEYS:
            if bool(have) != bool(value):
                left.append(key)
            continue
        if isinstance(have, float) and isinstance(value, (int, float)):
            if abs(have - float(value)) > 1e-9:
                left.append(key)
            continue
        if str(have) != str(value):
            left.append(key)
    print(f"  还原完成，剩余差异 {len(left)} 项：{left if left else '无'}")
    print(f"  版本 → v{store.get(pid)['revision']}")

print("\n" + ("已写回。" if apply_changes else "干跑结束（没动数据）。"))
