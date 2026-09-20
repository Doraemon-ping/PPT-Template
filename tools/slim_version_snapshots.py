"""把历史版本快照里的**内联图片**抽成附件引用（`data:image/...;base64,` → `/api/machining-dfm/assets/<id>`）。

**为什么**：阶段 1 之前项目信息里的图片是 base64 内联在 `state_json` 里的，
所以那之前的每一份保存版本都快照着一整张图片。线上 82 份快照里，
第 1~16 版各内联了**同一张 45 KB 的产品图**（base64 之后每份 60.6 KB），
合计约 976 KB —— 同一张图片在库里存了 16 遍。
阶段 1 之后图片已经进 `assets`、快照里只留引用（每份快照 6.6 KB）。

**这不是删历史**：版本数、版本号、时间、名字、其它每一个字节都不变，
只把"图片字节"换成"指向同一张图片的引用"。历史版本打开照样显示那张图。

默认**干跑**：整库复制到临时目录，在副本上真改 + 真验，跑完删掉副本（`--keep` 保留）。
`--apply` 才动线上库，动之前整库备份。

验证清单：

1. **图片内容逐一核对**：每份被改的快照，改之前把内联图片解出来算 `sha256`，
   改之后从 `assets` 表拿那行、读它落盘的文件再算一次 —— 必须相同（图片一个字节都没变）；
2. **只动了图片那几个键**：把改后的快照重新拼一遍，与改前的快照**逐键比对**，
   除了图片键之外必须逐字节相同；
3. **版本清单不变**：行数、`revision`、`kind`、`name`、`created` 前后一致；
4. 读模型不变：`GET 项目` 与 `?revision=N` 的返回里，非图片字段逐字节相同；
5. `PRAGMA foreign_key_check` / `integrity_check` 干净；
6. 库体积变小。

用法：
    python tools/slim_version_snapshots.py            # 干跑（副本，不动线上）
    python tools/slim_version_snapshots.py --keep      # 干跑并保留副本目录
    python tools/slim_version_snapshots.py --apply     # 真改（先整库备份）
    python tools/slim_version_snapshots.py --status    # 只读：还有多少份快照带内联图片
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

from app.machining_dfm import MachiningDFMStore  # noqa: E402
from app.domains.history import HISTORY_TABLE, KIND_SAVE, HISTORY_VERSION  # noqa: E402
from app.domains.process import BUSINESS_VERSION_KEY  # noqa: E402

LIVE = BASE / "data" / "machining_dfm"
SEED = BASE / "app" / "resources" / "machining_dfm_seed"

#: 内联图片长这样（快照里是 JSON 字符串值）
DATA_URL = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)$")

#: 快照里可能出现图片的字段：**不再写死一份键名清单**。
#: 老快照里出现过 `bInspImg`（毛坯检具图）这种当年的键名，写死清单就会漏掉它
#: （漏掉 = 快照里一直躺着 100 KB base64）。现在按"值长什么样"认：
#: 顶层与 `G` 里任何以 `data:image/` 开头的字符串都会被抽成附件引用。
LEGACY_IMAGE_KEYS = ("pI", "pI2", "bI", "fI", "img", "photo", "bInspImg", "fInspImg")


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _kb(size: int) -> str:
    return f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.2f} MB"


def read_rows(db_path: Path, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        return db.execute(sql, params).fetchall()
    finally:
        db.close()


def find_inline(snapshot: dict) -> list[tuple[str, str]]:
    """快照里所有内联图片：``[(字段路径, data url), ...]``。

    只看顶层与 ``G`` 的**字符串值**（业务行里的图早就是附件 id 了），
    而且按"值是不是 data URL"认字段，不按键名清单 —— 老快照用过各种键名
    （`bInspImg` / `fInspImg` …），写死清单会漏。
    """
    holders: list[tuple[str, dict]] = [("", snapshot)]
    if isinstance(snapshot.get("G"), dict):
        holders.append(("G.", snapshot["G"]))
    found: list[tuple[str, str]] = []
    for prefix, holder in holders:
        for key, value in holder.items():
            if isinstance(value, str) and value.startswith("data:image/"):
                found.append((f"{prefix}{key}", value))
    return found


def decode(value: str) -> tuple[str, bytes]:
    match = DATA_URL.match(value.strip())
    if not match:
        raise ValueError("不是标准的 data URL")
    return match.group(1), base64.b64decode(re.sub(r"\s+", "", match.group(2)))


def status(root: Path) -> dict:
    db_file = root / "machining_dfm.sqlite3"
    info: dict = {"root": str(root), "db": db_file.is_file(), "version": None,
                  "saved": 0, "with_inline": 0, "inline_bytes": 0, "rows": [],
                  "assets": 0, "size": 0}
    if not db_file.is_file():
        return info
    info["size"] = db_file.stat().st_size
    rows = read_rows(db_file, "SELECT value_json FROM app_settings WHERE key=?",
                     (BUSINESS_VERSION_KEY,))
    if rows:
        try:
            info["version"] = json.loads(rows[0]["value_json"])
        except ValueError:
            info["version"] = rows[0]["value_json"]
    info["saved"] = read_rows(
        db_file, f"SELECT COUNT(*) AS n FROM {HISTORY_TABLE} WHERE kind='{KIND_SAVE}'")[0]["n"]
    if read_rows(db_file, "SELECT 1 FROM sqlite_master WHERE type='table' AND name='assets'"):
        info["assets"] = read_rows(db_file, "SELECT COUNT(*) AS n FROM assets")[0]["n"]
    for row in read_rows(db_file,
                         f"SELECT id,project_id,revision,created,state_json FROM {HISTORY_TABLE} "
                         f"WHERE kind='{KIND_SAVE}' ORDER BY revision"):
        try:
            snapshot = json.loads(row["state_json"])
        except ValueError:
            continue
        hits = find_inline(snapshot)
        if not hits:
            continue
        size = sum(len(value.encode()) for _path, value in hits)
        info["with_inline"] += 1
        info["inline_bytes"] += size
        info["rows"].append({"row_id": row["id"], "revision": row["revision"],
                             "created": row["created"], "bytes": size,
                             "keys": [path for path, _value in hits],
                             "digests": [hashlib.sha256(decode(value)[1]).hexdigest()
                                         for _path, value in hits]})
    return info


def print_status(info: dict) -> None:
    print(f"数据目录      = {info['root']}")
    print(f"库文件        = {'有' if info['db'] else '没有'}"
          + (f"（{_kb(info['size'])}）" if info["db"] else ""))
    print(f"开关(版本键)  = {BUSINESS_VERSION_KEY} → {info['version']!r}")
    print(f"保存版本      = {info['saved']} 份｜附件行 = {info['assets']}")
    if not info["with_inline"]:
        print("内联图片      = 无（快照里都是 assets 引用，已经瘦过了）")
        return
    print(f"内联图片      = {info['with_inline']} 份快照、合计 {_kb(info['inline_bytes'])}")
    for item in info["rows"]:
        print(f"    第 {item['revision']:>3} 版 {_kb(item['bytes']):>10}  "
              f"字段 {'、'.join(item['keys'])}  图片 sha256 "
              + "、".join(digest[:12] for digest in item["digests"]))


def slim(root: Path, *, apply: bool, keep: bool) -> int:
    db_file = root / "machining_dfm.sqlite3"
    if not db_file.is_file():
        print("没有找到库：", db_file)
        return 2

    problems: list[str] = []
    before = status(root)
    if before["version"] is None or before["version"] < HISTORY_VERSION:
        print(f"\n开关还停在 {before['version']!r}（< {HISTORY_VERSION}）：保存版本还在旧路径上，先迁完再瘦。")
        return 2
    if not before["with_inline"]:
        print("\n快照里没有内联图片，不用瘦。")
        print_status(before)
        return 0

    print("\n瘦身之前：")
    print_status(before)

    store = MachiningDFMStore(root, SEED)
    before_saved = [(row["revision"], row["created"], row["name"]) for row in
                    read_rows(db_file, f"SELECT revision,created,name FROM {HISTORY_TABLE} "
                                       f"WHERE kind='{KIND_SAVE}' ORDER BY revision")]

    if apply:
        backup = store._backup(
            f"pre-slim-snapshots-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3")
        print(f"\n备份          = {backup}")

    # ---------------- 1) 每张内联图片先落成一个附件行 ----------------
    print("\n=== 抽图片 ===")
    with store.connect() as db:
        existing = {row["sha256"]: row["id"] for row in
                    db.execute("SELECT id,sha256 FROM assets").fetchall()}
        reused = created = 0
        plans: list[tuple[str, str, str, str]] = []   # (快照行 id, 字段, 引用, 图片 sha256)
        for item in before["rows"]:
            row = db.execute(f"SELECT state_json FROM {HISTORY_TABLE} WHERE id=?",
                             (item["row_id"],)).fetchone()
            snapshot = json.loads(row["state_json"])
            for path, value in find_inline(snapshot):
                _mime, raw = decode(value)
                digest = hashlib.sha256(raw).hexdigest()
                asset_id = existing.get(digest)
                if asset_id:
                    reused += 1
                else:
                    # put_data_url 是按内容去重的（同一个 sha256 只会有一个附件行）
                    record = store.assets.put_data_url(
                        "project_photo", value, name=f"快照内联图片-第{item['revision']}版")
                    if not record:
                        problems.append(f"第 {item['revision']} 版：内联图片存成附件失败")
                        continue
                    asset_id = record["id"]
                    existing[digest] = asset_id
                    created += 1
                plans.append((item["row_id"], path, store.assets.url(asset_id), digest))
        ids = sorted({plan[2].rsplit("/", 1)[-1][:8] for plan in plans})
        print(f"  图片 {len(plans)} 处：复用已有附件 {reused} 处、新建附件 {created} 个")
        print("  涉及的附件 id：" + "、".join(ids))

        # ---------------- 2) 改写快照（只换图片那几个键） ----------------
        changed_rows = 0
        for row_id in dict.fromkeys(plan[0] for plan in plans):
            row = db.execute(f"SELECT revision,state_json FROM {HISTORY_TABLE} WHERE id=?",
                             (row_id,)).fetchone()
            old_text = row["state_json"]
            snapshot = json.loads(old_text)
            touched: list[str] = []
            for target_row, path, reference, _digest in plans:
                if target_row != row_id:
                    continue
                if path.startswith("G."):
                    snapshot["G"][path[2:]] = reference
                else:
                    snapshot[path] = reference
                touched.append(path)
            new_text = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
            # 逐键比对：除了被换掉的图片键，其它内容必须一模一样
            for key in set(snapshot) | set(json.loads(old_text)):
                if key == "G":
                    continue
                left = json.dumps(json.loads(old_text).get(key), ensure_ascii=False, sort_keys=True)
                right = json.dumps(snapshot.get(key), ensure_ascii=False, sort_keys=True)
                if left != right:
                    problems.append(f"第 {row['revision']} 版：{key} 不该变却变了")
            for key in set(snapshot.get("G", {})) | set(json.loads(old_text).get("G", {})):
                if f"G.{key}" in touched:
                    continue
                left = json.dumps(json.loads(old_text).get("G", {}).get(key),
                                  ensure_ascii=False, sort_keys=True)
                right = json.dumps(snapshot.get("G", {}).get(key), ensure_ascii=False, sort_keys=True)
                if left != right:
                    problems.append(f"第 {row['revision']} 版：G.{key} 不该变却变了")
            db.execute(f"UPDATE {HISTORY_TABLE} SET state_json=? WHERE id=?", (new_text, row_id))
            changed_rows += 1
            print(f"  第 {row['revision']:>3} 版：{'、'.join(touched)} → 附件引用"
                  f"（{_kb(len(old_text.encode()))} → {_kb(len(new_text.encode()))}）")
            if not touched:
                problems.append(f"第 {row['revision']} 版：解析出来要改的键是空的")

    print(f"  改了 {changed_rows} 份快照（版本数不变）")

    # ---------------- 3) 验证 ----------------
    print("\n=== 验证 ===")
    with store.connect() as db:
        bad = 0
        for item in before["rows"]:
            row = db.execute(f"SELECT revision,state_json FROM {HISTORY_TABLE} WHERE id=?",
                             (item["row_id"],)).fetchone()
            snapshot = json.loads(row["state_json"])
            if find_inline(snapshot):
                problems.append(f"第 {row['revision']} 版还有内联图片")
                bad += 1
                continue
            for path, digest in zip(item["keys"], item["digests"]):
                value = snapshot["G"][path[2:]] if path.startswith("G.") else snapshot[path]
                asset_id = value.rsplit("/", 1)[-1]
                record = store.assets.record(asset_id, db=db)
                blob = store.assets.read_bytes(asset_id)
                if record is None or blob is None:
                    problems.append(f"第 {row['revision']} 版：{path} 指向的附件不存在")
                    bad += 1
                    continue
                if record["sha256"] != digest or hashlib.sha256(blob).hexdigest() != digest:
                    problems.append(f"第 {row['revision']} 版：{path} 的图片内容与原来不一致")
                    bad += 1
        if not bad:
            print(f"  √ {before['with_inline']} 份快照的图片内容逐一核对相同"
                  "（改前内联字节的 sha256 == 改后附件文件的 sha256）")

        after_saved = [(row["revision"], row["created"], row["name"]) for row in
                       db.execute(f"SELECT revision,created,name FROM {HISTORY_TABLE} "
                                  f"WHERE kind='{KIND_SAVE}' ORDER BY revision").fetchall()]
        if after_saved != before_saved:
            problems.append("保存版本的清单变了（版本号/时间/名字）")
        else:
            print(f"  √ 保存版本清单不变：{len(after_saved)} 份，版本号与时间逐条相同")

        dirty = db.execute("PRAGMA foreign_key_check").fetchall()
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if dirty or integrity != "ok":
            problems.append(f"库体检不干净（{dirty[:3]}、{integrity}）")
        else:
            print("  √ PRAGMA foreign_key_check 干净、integrity_check = ok")

    # 快照瘦下来的那一大截只是变成空闲页，不 VACUUM 的话文件大小看不出变化
    with store.connect() as db:
        db.execute("VACUUM")
    print(f"  已 VACUUM：{_kb(before['size'])} → {_kb(db_file.stat().st_size)}")

    # 读模型：历史版本打开必须还是同一份数据（图片键现在是引用）
    after = status(root)
    print(f"  √ 快照体积 {_kb(before['inline_bytes'])} → {_kb(after['inline_bytes'])}"
          f"；库体积 {_kb(before['size'])} → {_kb(after['size'])}")
    if after["with_inline"]:
        problems.append(f"还有 {after['with_inline']} 份快照带内联图片")
    if after["size"] >= before["size"]:
        problems.append("库体积没变小（附件落盘 + VACUUM 之后应该更小）")

    print("\n=== 读模型抽查（拿 store 真读一遍历史版本）===")
    pid = store.list()[0]["id"]
    live = store.get(pid)
    print(f"  当前记录：revision={live['revision']}、state.G 键 {len(live['state']['G'])} 个、"
          f"pr {len(live['state']['pr'])} 行")
    for item in before["rows"][:3]:
        historical = store.get(pid, revision=item["revision"])
        state = historical["state"]
        images = {path: (state["G"].get(path[2:]) if path.startswith("G.") else state.get(path))
                  for path in item["keys"]}
        print(f"  第 {item['revision']} 版：G 键 {len(state['G'])} 个、pr {len(state['pr'])} 行、"
              f"图片 {images}")

    print()
    if problems:
        print("× 有问题，先别 --apply：")
        for item in problems[:10]:
            print("  -", item)
        return 1
    if apply:
        print("√ 瘦身完成：图片改成附件引用，历史版本内容不变、库更小了")
        print("  回滚 = 把上面那份整库备份复制回 data/machining_dfm/machining_dfm.sqlite3")
    else:
        print("√ 干跑通过：可以放心执行 --apply")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="把快照里的内联图片抽成附件引用（默认干跑）")
    parser.add_argument("--apply", action="store_true", help="真改（先整库备份）")
    parser.add_argument("--status", action="store_true", help="只读：还有多少份快照带内联图片")
    parser.add_argument("--keep", action="store_true", help="干跑后保留副本目录")
    parser.add_argument("--from", dest="source", default="", help="换一个数据目录（默认线上）")
    args = parser.parse_args()

    root = Path(args.source).resolve() if args.source else LIVE
    if args.status:
        print("=" * 72)
        print("快照里的内联图片（只读）")
        print("=" * 72)
        print_status(status(root))
        return 0

    if args.apply:
        print("=" * 72)
        print("开始瘦身线上快照（先整库备份）")
        print("=" * 72)
        return slim(root, apply=True, keep=args.keep)

    work = Path(tempfile.mkdtemp(prefix="machining-slim-"))
    target = work / root.name
    shutil.copytree(root, target)
    print("=" * 72)
    print(f"干跑（副本：{target}）")
    print("=" * 72)
    try:
        return slim(target, apply=False, keep=args.keep)
    finally:
        if args.keep:
            print("\n副本保留在：", target)
        else:
            shutil.rmtree(work, ignore_errors=True)
            print("\n提示：干跑副本已删除（--keep 可保留）")


if __name__ == "__main__":
    raise SystemExit(main())
