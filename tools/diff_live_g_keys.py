"""对比迁移前后 G 的键集合：只许"值一样"，不允许悄悄多出来一堆非契约键。"""

from __future__ import annotations

import io
import json
import sys

sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.machining_dfm import MachiningDFMStore  # noqa: E402

store = MachiningDFMStore("data/machining_dfm", "app/resources/machining_dfm_seed")
project_id = store.list()[0]["id"]
with store.connect() as db:
    archived = json.loads(
        db.execute("SELECT state_json FROM projects_legacy_v1 WHERE id=?", (project_id,)).fetchone()[0]
    )
    raw = json.loads(db.execute("SELECT state_json FROM projects WHERE id=?", (project_id,)).fetchone()[0])
    version = db.execute("SELECT value_json FROM app_settings WHERE key='project_schema_version'").fetchone()

now = store.get(project_id)["state"]

before_keys = set(archived["G"])
after_keys = set(now["G"])
print("迁移前 G 键数:", len(before_keys), "| 迁移后 G 键数:", len(after_keys))
print("迁移后新增键:", sorted(after_keys - before_keys))
print("迁移后丢失键:", sorted(before_keys - after_keys))
print("schema 版本键:", version[0] if version else None)
print("state_json 顶层键:", sorted(raw))

changed = []
for key in sorted(before_keys & after_keys):
    if archived["G"][key] != now["G"][key]:
        changed.append((key, str(archived["G"][key])[:40], str(now["G"][key])[:40]))
print("\n值发生变化的键:", len(changed))
for key, old, new in changed:
    print(f"  {key}: {old!r} -> {new!r}")

print("\n键值与归档一致:", not (before_keys - after_keys) )
