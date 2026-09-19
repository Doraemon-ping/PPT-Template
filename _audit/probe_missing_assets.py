# -*- coding: utf-8 -*-
"""查：老快照里引用的 7 个附件 id 还能不能找回来（磁盘文件 / 各份整库备份）。"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "data" / "machining_dfm"
DB = LIVE / "machining_dfm.sqlite3"

MISSING = [
    "6b9f6df42b9e4dfe804590392fa67fa6",
    "18992028902247a9937792c70800b544",
    "1199ce56d35b4dc89897280804698b6f",
    "f1f723b5146549fe9d0c595928143ebb",
    "b615c97dcad14e8197d40c906b6ff9d8",
    "35e713887eaa449bb43efed57418ccd2",
    "c9505b1ce5304845ad57a42e03791e9f",
]


def assets_table(db_file: Path) -> dict[str, tuple]:
    db = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    try:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='assets'").fetchone():
            return {}
        return {row[0]: row for row in db.execute("SELECT id, path, size, sha256 FROM assets")}
    finally:
        db.close()


def snapshot_hits(db_file: Path) -> dict[str, list[int]]:
    db = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    try:
        rows = db.execute("SELECT revision, state_json FROM project_versions").fetchall()
    finally:
        db.close()
    hits: dict[str, list[int]] = {}
    for revision, text in rows:
        for found in set(re.findall(r"/assets/([0-9a-zA-Z_-]{8,64})", text or "")):
            if found in MISSING:
                hits.setdefault(found, []).append(revision)
    return hits


def inline_bytes(db_file: Path) -> dict[str, int]:
    """老快照里还留着内联 base64 的（能直接救回来）。"""
    db = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    try:
        rows = db.execute("SELECT revision, state_json FROM project_versions").fetchall()
    finally:
        db.close()
    found: dict[str, int] = {}
    for revision, text in rows:
        if "data:image" in (text or ""):
            found[str(revision)] = len(text)
    return found


print("线上库 assets 行 =", len(assets_table(DB)))
disk = LIVE / "assets"
print("磁盘附件文件     =", len([p for p in disk.rglob('*') if p.is_file()]) if disk.is_dir() else "没有目录")
for aid in MISSING:
    hits = list(disk.rglob(f"*{aid}*")) if disk.is_dir() else []
    print(f"  磁盘找 {aid[:12]}… → {[str(p.relative_to(disk)) for p in hits] or '没有'}")

print()
print("各份备份里有没有这些 id：")
backups = sorted((LIVE / "backups").glob("*.sqlite3"))
for backup in backups:
    table = assets_table(backup)
    have = [aid for aid in MISSING if aid in table]
    hits = snapshot_hits(backup)
    print(f"  {backup.name:<52} assets {len(table):>3} 行｜命中 {len(have)} 个"
          f"｜备份里引用这些 id 的快照 {sum(len(v) for v in hits.values())} 处")
    for aid in have:
        print(f"      √ {aid} → {table[aid][1]}（{table[aid][2]} 字节）")
    inline = inline_bytes(backup)
    if inline:
        print(f"      备份里还有内联图片的快照：{inline}")

print()
now = snapshot_hits(DB)
print("线上库当前引用这些 id 的地方：")
for aid, revisions in now.items():
    print(f"  {aid[:12]}… → 第 {revisions} 版")
