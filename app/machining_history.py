"""机加 DFM · 阶段 3a：版本履历落表（``project_versions``）。

## 这一张表解决什么

旧的"版本"有两套互不相干的东西：

| | 旧形态 | 谁在写 | 页面在哪看 |
| --- | --- | --- | --- |
| **保存版本** | ``revisions`` 表（每次保存一行全量快照，线上 60 行 / 约 3.9 MB） | 每次保存（含每个行级写入点） | 「版本」弹窗：列版本号、时间，可"恢复此版本" |
| **版本履历** | ``projects.state_json.vh[]``（``{dt,ver,ds,by}`` 四键一行） | 页面手填 4 个格子 + `addVH` + `delVH` + `verRec` 自动追加 | 「版本履历」卡片 + PPT 导出表 |

两套东西都落进 ``project_versions`` 一张表，用 ``kind`` 分开：

* ``kind='save'``：一次保存一行，``revision`` = 当时的项目版本号，``state_json`` = 那份全量快照。
  它提供 ``GET /versions`` 与 ``?revision=N`` 还原（对外字段与旧 ``revisions`` 完全一致）。
* ``kind='history'``：页面上"版本履历"里的一行（手填的 + 自动追加的），
  ``revision`` 固定为 **0**（哨兵：它不是保存版本），四列 ``ver/dt/ds/by`` 就是旧四键。

## 口径与约束

* **关联列全是真外键**：``project_id`` → ``projects(id)``；本表没有别的关联列。
* **不允许永久删除**（口径 2）：``delVH`` 变成逻辑删除 + 回收站恢复；
* **不无中生有**（口径 5）：履历行只认旧四键，旧行里多出来的键进 ``extra_json`` 兜底列，
  读模型按原样补在四键之后——不猜、不补、不改值；
* **保存版本必须有快照**：``CHECK (kind='history' OR state_json <> '{}')``，
  避免出现"空版本"这种凭空捏造的历史。

## 读模型：``vh[]`` 逐字节不变

``compose_history()`` 只输出 ``LEGACY_HISTORY_KEYS``（``dt,ver,ds,by``，顺序与 ``addVH()`` 的插入
顺序一致），逻辑删除的行不进读模型；表里一行都没有（没迁移的项目）→ 返回 ``None``，
读模型回退 ``projects.state_json.vh``（与 ``pr``/``is`` 同一套"表里有数据才是权威"的规则）。
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from fastapi import HTTPException

from .machining_library import LibraryField
from .machining_process import _ProjectRows, _stamp, clean_json_object

#: 表名
HISTORY_TABLE = "project_versions"

#: 阶段 3a 的能力级别：``app_settings.project_business_version`` ≥ 4 才算"版本履历已落表"
HISTORY_VERSION = 4

KIND_SAVE = "save"
KIND_HISTORY = "history"
HISTORY_KINDS = (KIND_SAVE, KIND_HISTORY)

#: 旧读模型里"看得见"的键（顺序 = 页面上 addVH()/verRec() 的插入顺序）
LEGACY_HISTORY_KEYS = ("dt", "ver", "ds", "by")

#: 履历行的四个键（缺键补空串，与旧渲染 `String(v.ds||'')` 的观感一致）
HISTORY_KEYS = LEGACY_HISTORY_KEYS

#: 履历行里允许的最大文本长度（旧页面是自由文本，给个上限防爆）
HISTORY_LIMITS = {"dt": 32, "ver": 40, "ds": 4000, "by": 64}

HISTORY_FIELDS: tuple[LibraryField, ...] = (
    LibraryField("kind", "kind", "choice", KIND_HISTORY, "类型",
                 choices=HISTORY_KINDS,
                 choice_labels=((KIND_SAVE, "保存版本"), (KIND_HISTORY, "版本履历"))),
    # 0 = 履历行（不是保存版本）；保存版本必须 >0，两条 CHECK 一起把语义钉死
    LibraryField("revision", "revision", "int", 0, "保存版本号", maximum=10 ** 9),
    LibraryField("ver", "ver", "text", "", "版本号", limit=HISTORY_LIMITS["ver"]),
    LibraryField("dt", "dt", "text", "", "日期", limit=HISTORY_LIMITS["dt"]),
    LibraryField("ds", "ds", "text", "", "变更内容", limit=HISTORY_LIMITS["ds"]),
    LibraryField("by", "by", "text", "", "变更人", limit=HISTORY_LIMITS["by"]),
    LibraryField("name", "name", "text", "", "项目名", limit=120),
)

#: 两个 JSON 兜底列：保存版本的全量快照 + 履历行里"登记表没覆盖的键"
HISTORY_JSON_COLUMNS = {"state": "state_json", "extra": "extra_json"}

HISTORY_CHECKS = (
    f"kind IN ('{KIND_SAVE}','{KIND_HISTORY}')",
    f"kind='{KIND_HISTORY}' OR revision > 0",
    f"kind='{KIND_SAVE}' OR revision = 0",
    # 两条对称的"快照"约束：保存版本必须有快照（不许凭空造一个空版本），
    # 履历行必须没有快照（履历不是版本，混着存会让"这一行到底代表什么"说不清）。
    f"kind='{KIND_HISTORY}' OR state_json <> '{{}}'",
    f"kind='{KIND_SAVE}' OR state_json = '{{}}'",
)

#: 列表/读模型用得到的列。**不含 state_json**：保存版本的快照一行 66 KB，
#: 列 60 行会把每次读模型都拖成"解析 4 MB JSON"（线上实测过的教训）。
LIGHT_COLUMNS = (
    "id", "project_id", "kind", "revision", "ver", "dt", "ds", "by", "name", "extra_json",
    "sort_order", "deleted_at", "deleted_by", "deleted_reason", "created", "updated",
)


class ProjectVersions(_ProjectRows):
    """``project_versions``：一行 = 一个保存版本（``kind='save'``）或一行版本履历（``kind='history'``）。"""

    table = HISTORY_TABLE
    table_label = "版本履历"
    parent_column = ""
    #: 版本列表是一张平表，序号在整个项目里排（页面上的顺序就是显示顺序）
    order_scope = "project"
    fields = HISTORY_FIELDS
    json_columns = HISTORY_JSON_COLUMNS
    #: 快照与兜底键都是**任意 JSON 对象**，不走 ``clean_count`` 那套计数校验
    default_json_cleaner = staticmethod(clean_json_object)
    check_sql = HISTORY_CHECKS
    #: 阶段 3b：页面履历行的每次改动都进变更流水（保存版本是系统写的，不记流水）
    change_entity = "history"
    title_keys = ("ver", "dt")

    # ---------------- 轻量读取（不碰 state_json） ----------------

    def _light_rows(self, project_id: str, *, kind: str | None = None,
                    include_deleted: bool = True, order: str = "sort_order, id") -> list[Any]:
        sql = f"SELECT {','.join(LIGHT_COLUMNS)} FROM {self.table} WHERE project_id=?"
        params: list[Any] = [project_id]
        if kind is not None:
            sql += " AND kind=?"
            params.append(kind)
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        sql += f" ORDER BY {order}"
        with self.assets.session(db=None) as conn:
            return conn.execute(sql, tuple(params)).fetchall()

    def save_rows(self, project_id: str, *, include_deleted: bool = False) -> list[Any]:
        """保存版本（``kind='save'``），按版本号倒序 —— ``GET /versions`` 用。"""
        return self._light_rows(project_id, kind=KIND_SAVE, include_deleted=include_deleted,
                                order="revision DESC, id")

    def history_rows(self, project_id: str, *, include_deleted: bool = True) -> list[Any]:
        """版本履历行（``kind='history'``），按页面顺序 —— 读模型与 ``/history`` 用。"""
        return self._light_rows(project_id, kind=KIND_HISTORY, include_deleted=include_deleted)

    def find_save(self, project_id: str, revision: int, *, db=None) -> Any:
        """某一版（含完整快照）—— ``?revision=N`` 还原用，一次只取一行。"""
        with self.assets.session(db) as conn:
            return conn.execute(
                f"SELECT * FROM {self.table} WHERE project_id=? AND kind=? AND revision=?",
                (project_id, KIND_SAVE, int(revision)),
            ).fetchone()

    def find_save_by_id(self, project_id: str, record_id: str) -> Any:
        with self.assets.session(db=None) as conn:
            return conn.execute(
                f"SELECT {','.join(LIGHT_COLUMNS)} FROM {self.table} "
                "WHERE project_id=? AND kind=? AND id=?",
                (project_id, KIND_SAVE, record_id),
            ).fetchone()

    def has_history_rows(self, project_id: str) -> bool:
        """这个项目在表里有没有**履历行**（含逻辑删除的）。

        为什么按履历行判定、而不是"表里有没有行"：开关一打开，应用每次保存都会写保存版本，
        所以"有行"根本不代表"履历已经迁过"。履历行才是 ``vh[]`` 的权威信号。
        """
        with self.assets.session(db=None) as conn:
            return conn.execute(
                f"SELECT 1 FROM {self.table} WHERE project_id=? AND kind=? LIMIT 1",
                (project_id, KIND_HISTORY),
            ).fetchone() is not None

    def reorder_history(self, project_id: str, record_ids: Sequence[str], *, db=None) -> None:
        """重排履历行：**只动 ``kind='history'`` 的行**。

        不能用引擎的通用 ``reorder()``：它会把整个项目的行重排一遍，连保存版本的
        ``sort_order``（那里存的是版本号）一起打乱。
        """
        wanted = [str(item) for item in record_ids]
        known = {row["id"] for row in self.history_rows(project_id)}
        unknown = [item for item in wanted if item not in known]
        if unknown:
            raise HTTPException(422, f"这些版本履历不属于该项目：{'、'.join(unknown[:5])}")
        rest = [item for item in _ordered_ids(self.history_rows(project_id)) if item not in wanted]
        with self.assets.session(db) as conn:
            for order, record_id in enumerate([*wanted, *rest]):
                conn.execute(
                    f"UPDATE {self.table} SET sort_order=?,updated=? WHERE id=?",
                    (order, _stamp(), record_id),
                )
        self._note_change("reorder", label=f"版本履历排序调整（{len(wanted)} 行）",
                          extra={"ids": wanted[:20]})


# ---------------- 读模型：表行 → 旧 vh[] ----------------

def light_view(row: Any) -> dict[str, Any]:
    """轻量行 → 普通 dict（只含 ``LIGHT_COLUMNS`` 那几列，``extra_json`` 解析成 ``extra``）。"""
    record = {column: row[column] for column in LIGHT_COLUMNS}
    raw = record.pop("extra_json", "{}")
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        parsed = {}
    record["extra"] = parsed if isinstance(parsed, dict) else {}
    return record


def _ordered_ids(rows: Sequence[Any]) -> list[str]:
    """按页面上看到的顺序取 id（``sort_order, id``）。"""
    return [str(row["id"]) for row in rows]


def compose_history(rows: Sequence[Any]) -> list[dict[str, Any]]:
    """把履历行还原成旧 ``vh[]``（键顺序 ``dt,ver,ds,by``，多出来的键按原样补在后面）。

    **逻辑删除的行不进读模型**（与 ``compose_processes`` / ``compose_issues`` 同一口径）：
    页面上点了删除，这行就该从报告里消失；行还在表里，回收站能恢复。
    """
    result: list[dict[str, Any]] = []
    for row in rows:
        record = light_view(row) if not isinstance(row, dict) else row
        if record.get("deleted_at"):
            continue
        item: dict[str, Any] = {
            key: str(record.get(key) or "") for key in LEGACY_HISTORY_KEYS
        }
        extra = record.get("extra")
        if isinstance(extra, dict):
            # 旧行里登记表没覆盖的键：原样补在后面，一个都不丢、也不改
            for key, value in extra.items():
                if key not in item:
                    item[key] = value
        result.append(item)
    return result


def legacy_history(versions: "ProjectVersions | None", project_id: str) -> list[dict[str, Any]] | None:
    """读模型里的 ``vh[]``；**表里没有履历行**时返回 ``None``（回退 ``state_json.vh``）。

    注意判定的不是"表里有没有行"：开关打开后保存版本立刻就有一堆行，但它们跟 ``vh[]`` 无关。
    """
    if versions is None or not versions.has_history_rows(project_id):
        return None
    return compose_history(versions.history_rows(project_id))


# ---------------- 接口用的清单 ----------------

def version_listing(versions: ProjectVersions, project_id: str) -> list[dict[str, Any]]:
    """``GET /versions`` 的返回：与旧 ``revisions`` 的字段一致（多一个 ``id``）。"""
    return [
        {
            "id": row["id"],
            "revision": int(row["revision"]),
            "name": str(row["name"] or ""),
            "created": str(row["created"] or ""),
        }
        for row in versions.save_rows(project_id)
    ]


def _history_item(row: Any, index: int) -> dict[str, Any]:
    record = light_view(row)
    return {
        "id": record["id"],
        "index": index,
        **{key: str(record.get(key) or "") for key in LEGACY_HISTORY_KEYS},
        # 履历行不是保存版本：对外不给哨兵值，直接给 None
        "revision": None,
        "extra": record.get("extra") if isinstance(record.get("extra"), dict) else {},
        "deleted_at": record.get("deleted_at"),
        "deleted_by": str(record.get("deleted_by") or ""),
        "deleted_reason": str(record.get("deleted_reason") or ""),
        "created": str(record.get("created") or ""),
        "updated": str(record.get("updated") or ""),
    }


def history_listing(
    versions: ProjectVersions, project_id: str, *, enabled: bool = True, recycle: bool = False
) -> dict[str, Any]:
    """版本履历清单：``recycle=False`` 给在用的行，``True`` 给回收站。"""
    rows = versions.history_rows(project_id)
    live = [row for row in rows if not row["deleted_at"]]
    deleted = [row for row in rows if row["deleted_at"]]
    source = deleted if recycle else live
    return {
        "table": HISTORY_TABLE,
        "enabled": enabled,
        "kind": KIND_HISTORY,
        "keys": list(LEGACY_HISTORY_KEYS),
        "materialized": True,
        "count": len(source),
        "live_count": len(live),
        "recycle_count": len(deleted),
        "history": [_history_item(row, index) for index, row in enumerate(source)],
    }


def virtual_history_listing(state: dict[str, Any], project_id: str, *, enabled: bool = True,
                            recycle: bool = False) -> dict[str, Any]:
    """表里还没有履历行时，先按 ``state_json.vh`` 给一份**只读的"影子清单"**。

    为什么需要：开关打开之后（或迁移工具还没跑之前），老项目的履历还在 ``state_json.vh`` 里。
    这时候：
    * 读模型照旧读它（``legacy_history`` 返回 ``None`` → 回退），页面上看到的和改造前一模一样；
    * 页面要改其中一行时，服务端会拿这份清单里的 **id 就地补建行**（见 ``_ensure_history_rows``），
      id 就是这里发的 ``<项目 id>-h<下标>``，所以页面拿到的 id 和补建出来的行是同一个，
      不会出现"刚看到就说这一行不在了"。

    这个函数**只读**，不碰数据库。
    """
    rows = (state or {}).get("vh") or []
    items = compose_history(rows) if isinstance(rows, list) else []
    return {
        "table": HISTORY_TABLE,
        "enabled": enabled,
        "kind": KIND_HISTORY,
        "keys": list(LEGACY_HISTORY_KEYS),
        # 影子清单：还没落表（页面照样能看能改，第一次写就补建成真行）
        "materialized": False,
        "count": 0 if recycle else len(items),
        "live_count": len(items),
        "recycle_count": 0,
        "history": [] if recycle else [
            {
                "id": f"{project_id}-h{index}",
                "index": index,
                **{key: str(item.get(key) or "") for key in LEGACY_HISTORY_KEYS},
                "revision": None,
                "extra": {key: value for key, value in item.items()
                          if key not in LEGACY_HISTORY_KEYS},
                "deleted_at": None, "deleted_by": "", "deleted_reason": "",
                "created": "", "updated": "",
            }
            for index, item in enumerate(items)
        ],
    }


# ---------------- 写入：旧四键 → 行 ----------------

def history_payload(payload: dict[str, Any], *, current: dict[str, Any] | None = None,
                    strict: bool = True) -> dict[str, Any]:
    """页面提交 → 行载荷：只认 ``dt/ver/ds/by``，别的键进 ``extra_json`` 兜底。

    ``strict=False``（迁移用）连键名都不校验：旧数据里出现的怪键也照存，不中断迁移。
    """
    if not isinstance(payload, dict):
        raise HTTPException(422, "版本履历必须是 JSON 对象")
    values: dict[str, Any] = {}
    extra = dict(current.get("extra") or {}) if current else {}
    for key, value in payload.items():
        if key in HISTORY_KEYS:
            limit = HISTORY_LIMITS[key]
            text = "" if value is None else str(value)
            if len(text) > limit:
                if strict:
                    raise HTTPException(422, f"{key} 最长 {limit} 个字符")
                text = text[:limit]
            values[key] = text
            continue
        if key in {"id", "index", "revision", "kind", "created", "updated", "deleted_at",
                   "deleted_by", "deleted_reason", "extra"}:
            continue  # 服务端管的列：页面提交了也不认
        extra[key] = value  # 兜底列：不丢用户数据（口径 5：不无中生有，也不丢）
    if extra:
        values["extra"] = extra
    return values


def new_history_values(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """新增一行的默认载荷：四个键齐全（与 ``addVH()`` 的默认值一致）。"""
    values = {key: "" for key in HISTORY_KEYS}
    values.update(history_payload(payload or {}))
    return values


# ---------------- 迁移：旧数组 → 行载荷 ----------------

def split_history_rows(rows: Sequence[Any], *, project_id: str = "") -> list[dict[str, Any]]:
    """``state_json.vh[]`` → 行载荷（``order`` = 旧数组下标，保证顺序不变）。

    **非对象元素直接报错**（不静默丢数据）：旧读模型会把原样的值输出到页面上，
    这里吞掉它就等于悄悄改数据。让它响，交给人工决定。
    """
    result: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise HTTPException(
                422,
                f"版本履历第 {index + 1} 条不是对象（{type(row).__name__}），"
                "迁移不会替你丢掉它，请先人工确认这一条",
            )
        values = history_payload(row, strict=False)
        values["kind"] = KIND_HISTORY
        values["revision"] = 0
        values["order"] = index
        if project_id:
            # 稳定 id：同一份数据重复迁移会得到同一行（幂等）
            values["id"] = f"{project_id}-h{index}"
        result.append(values)
    return result


def save_row_values(project_id: str, revision: int, name: str, state: dict[str, Any],
                    *, created: str = "") -> dict[str, Any]:
    """一次保存 → ``kind='save'`` 行载荷（快照原样给 dict，落库时按同一套紧凑格式序列化）。"""
    payload: dict[str, Any] = {
        "id": f"{project_id}-v{int(revision)}",   # 稳定 id：重复迁移不会插出第二行
        "kind": KIND_SAVE,
        "revision": int(revision),
        "name": str(name or ""),
        "state": state,
    }
    if created:
        payload["created"] = created
    return payload


def save_row_id(project_id: str, revision: int) -> str:
    """保存版本的稳定 id（``<项目 id>-v<版本号>``；迁移与变更流水都按这个规则对得上）。"""
    return f"{project_id}-v{int(revision)}"


def insert_save_row(db, project_id: str, revision: int, name: str, state_json: str,
                    created: str) -> None:
    """在**已有写事务**里落一个保存版本（``_write_snapshot`` 用，与 ``revisions`` 影子副本同一次提交）。

    ``state_json`` 是已经序列化好的紧凑 JSON（与 ``revisions.state_json`` 同一份字节），
    所以保存版本在两张表里**逐字节一致**，回滚时不会对不上。
    """
    db.execute(
        f"INSERT OR REPLACE INTO {HISTORY_TABLE}"
        "(id,project_id,sort_order,kind,revision,ver,dt,ds,by,name,state_json,extra_json,"
        "deleted_at,deleted_by,deleted_reason,created,updated) "
        "VALUES(?,?,?,?,?,'','','','',?,?,'{}',NULL,'','',?,?)",
        (save_row_id(project_id, revision), project_id, int(revision), KIND_SAVE, int(revision),
         str(name or ""), state_json, created, created),
    )


def delete_save_row(db, project_id: str, revision: int) -> None:
    """把某一版从保存版本里撤掉（**只在迁移失败回滚时用**，平时版本永不删）。"""
    db.execute(
        f"DELETE FROM {HISTORY_TABLE} WHERE project_id=? AND kind=? AND revision=?",
        (project_id, KIND_SAVE, int(revision)),
    )


def json_text(payload: Any) -> str:
    """紧凑 JSON（与项目快照同一套序列化规则：``ensure_ascii=False`` + 无空格分隔符）。"""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


# ---------------- 迁移：revisions + state_json.vh → 行 ----------------

def history_preflight(projects: Sequence[dict[str, Any]]) -> list[str]:
    """迁移前体检（**写任何数据之前**跑）：把"会丢数据"的旧形态全部挡在门外。

    ``projects`` 每项：``{id, name, state_json, revisions}``。返回问题清单（空 = 可以迁）。
    """
    problems: list[str] = []
    for project in projects:
        label = f"项目「{project.get('name') or project.get('id')}」"
        try:
            state = json.loads(project.get("state_json") or "{}")
        except ValueError as error:
            problems.append(f"{label}：state_json 不是合法 JSON（{error}）")
            continue
        raw = state.get("vh")
        if raw is None:
            continue
        if not isinstance(raw, list):
            problems.append(f"{label}：state_json.vh 不是数组（{type(raw).__name__}）"
                            "，迁移不会替你猜它该怎么拆")
            continue
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                problems.append(f"{label}：version 履历第 {index + 1} 条不是对象"
                                f"（{type(item).__name__}），迁移不会替你丢掉它")
        for row in project.get("revisions") or []:
            try:
                json.loads(row["state_json"] or "{}")
            except (ValueError, TypeError) as error:
                problems.append(f"{label}：第 {row['revision']} 版的快照不是合法 JSON（{error}）")
    return problems


def apply_history_split(
    versions: "ProjectVersions",
    project_id: str,
    state: dict[str, Any] | None,
    *,
    revisions: Sequence[Any] = (),
) -> dict[str, Any]:
    """把一个项目的旧版本数据灌进 ``project_versions``（幂等：表里已有行就跳过）。

    两类输入：
    * ``revisions``：旧 ``revisions`` 表的行（``revision``/``name``/``state_json``/``created``）
      → ``kind='save'``，``state_json`` **原样搬**（逐字节一致，回滚能对上）；
    * ``state['vh']``：页面上的版本履历 → ``kind='history'``，下标就是顺序。

    返回报告（供迁移工具打印）：``{"saved", "history", "skipped", "existing_rows", "extras"}``。
    """
    report: dict[str, Any] = {"saved": 0, "history": 0, "skipped": False, "existing_rows": 0,
                              "extras": 0}
    rows = (state or {}).get("vh") or []
    known = {int(row["revision"]) for row in versions.save_rows(project_id, include_deleted=True)}
    missing = [row for row in revisions if int(row["revision"]) not in known]
    # 幂等：履历行已经建过、或这次也没什么可建的，就跳过（保存版本用稳定 id 覆盖写，重复跑不会多行）
    if versions.has_history_rows(project_id) or (not missing and not rows):
        report["skipped"] = True
        report["existing_rows"] = len(versions.save_rows(project_id, include_deleted=True)) + \
            len(versions.history_rows(project_id))
        return report

    if missing:
        with versions.assets.session(db=None) as conn:
            for row in missing:
                # 快照**原样搬**：不 json.loads 再 dumps，改一个字节都可能让回滚对不上
                insert_save_row(
                    conn, project_id, int(row["revision"]), str(row["name"] or ""),
                    str(row["state_json"]), str(row["created"] or ""),
                )
                report["saved"] += 1

    for values in split_history_rows(rows, project_id=project_id):
        order = int(values.pop("order"))
        record_id = str(values.pop("id"))
        if values.get("extra"):
            report["extras"] += 1
        versions.create(project_id, values, order=order, record_id=record_id)
        report["history"] += 1
    return report
