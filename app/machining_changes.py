"""机加 DFM · 阶段 3b：变更流水落表（``project_changes``）。

## 这一张表解决什么

落表之后，"项目里的数据变了"这句话需要有地方说清楚：**谁、什么时候、被哪一次保存带走、
改的是哪一行、改成了什么**。保存版本（3a 的 ``kind='save'``）只留全量快照——
快照能"还原"，但人看不出"第 47 版到底改了什么"（只能拿两版 diff）。

``project_changes`` 一行 = 一次改动里的一个实体：

| 列 | 说明 |
| --- | --- |
| ``entity`` | 被改的是什么：``project`` 整份保存 / ``settings`` 项目信息 / ``process`` 工序 / ``tool`` 工序刀具行 / ``issue`` 问题清单 / ``selection`` 选型格子 / ``history`` 版本履历行 |
| ``action`` | 干了什么：``create`` / ``update`` / ``delete``（逻辑删除）/ ``restore`` / ``reorder`` / ``photo`` / ``save``（整份保存） |
| ``label`` | **给人看的一句话**："工序 OP10 改名"、"刀具 T01：转速 3000→3500"、"删除问题：尺寸超差（客户撤销）" |
| ``version_id`` | 这次改动被哪一次保存带走（真外键 → ``project_versions.id``，就是那次保存的 ``kind='save'`` 行） |
| ``extra_json`` | 兜底明细（字段级 old/new、槽位、原因、被删行的 id 清单……） |
| 4 + 1 个 ``*_row_id`` | 被改的那一行（真外键，按实体分列） |

## 关联列：多态引用怎么用真外键表达

"被改的行"天然是多态的（可能是工序行、刀具行、问题行、选型行）。**没有**用
"``entity_id`` 一列 + 类型列"的做法——SQLite 的外键只能指一张表，那样只能软引用，
与"有关联的数据结构全部使用真外键"的口径冲突。这里用**分列**：

```text
process_row_id   → project_processes(id)   ON DELETE SET NULL
tool_row_id      → project_process_tools(id) ON DELETE SET NULL
issue_row_id     → project_issues(id)      ON DELETE SET NULL
fixture_row_id   → project_fixtures(id)    ON DELETE SET NULL   （夹具选型的格子）
gauge_row_id     → project_gauges(id)      ON DELETE SET NULL   （检具选型的格子）
selection_row_id → project_selections(id)  ON DELETE SET NULL   （老的多态表，只给历史行指路）
history_row_id   → project_versions(id)    ON DELETE SET NULL
version_id       → project_versions(id)    ON DELETE SET NULL
project_id       → projects(id)            NO ACTION
```

**选型为什么还是"一个实体 + 三个列"**：``entity`` 的白名单是 ``CHECK`` 约束，
往里面加实体名要重建整张流水表（SQLite 改不了 CHECK），而"夹具选型/检具选型"
本来就是同一件事的两种表——所以它们共用 ``entity='selection'``，
用 **``fixture_row_id`` / ``gauge_row_id`` 分列指向各自那张表**（写入时按草稿里的
``extra.kind`` 选列），``extra_json`` 里也留一份 ``kind``。
``selection_row_id`` 留给"迁移前就写下的历史流水行"，新行不再写它。

``CHECK`` 保证"**最多挂一个、而且必须与实体对应**"：``entity='process'`` 就只能挂
``process_row_id``（``settings``/``project`` 五个列全空）。写成"最多一个 + 必须对应"而不是
"恰好一个"，是因为这五列都是 ``ON DELETE SET NULL``：目标行被物理删掉时列会被置空，
那种状态（行还在、被改的那一行已经没了）必须仍然是合法行——`label` 里写着是谁。
于是 ``PRAGMA foreign_key_check`` 能把这张表一起查干净，而"哪一行被改了"能按实体建索引查。

``ON DELETE SET NULL`` 不丢信息：外键置空时 ``label`` 里仍然写着"当时改的是谁、改成什么"
（与工序刀具行价格快照同一条思路）。我们本来也不物理删除业务行（口径 2），这一手是保险。

## 只记一次：流水与保存版本同生共死

行级写入（引擎 ``_ProjectRows``）**不直接写这张表**，而是把一个"草稿"交给 store；
store 在 ``_bump_project`` 的写事务里（已经拿到新版本号、也写好了 ``kind='save'`` 行）
才把草稿落库并挂上 ``version_id``。所以：

* 一次改动 → 恰好一条流水，且一定指得到那一次的保存版本；
* 事务失败/乐观锁 409 → 这次改动没有流水，也不会留下半条；
* 迁移工具直接在表上搬数据（绕开 store），**不会**凭空产生流水（口径 5：不无中生有）。

## 只读

这张表是**追加型**日志：3b 不提供写接口（前端也没有写入点），
``deleted_at``/``deleted_by``/``deleted_reason`` 三列跟着引擎的规矩一起建出来，
留给阶段 4 的"隐藏某条/回收站"用。
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from .machining_library import LibraryField
from .machining_process import ForeignKey, _ProjectRows, _stamp, clean_json_object

#: 表名
CHANGES_TABLE = "project_changes"

#: 阶段 3b 的能力级别：``app_settings.project_business_version`` ≥ 5 才算"变更流水已落表"
CHANGES_VERSION = 5

#: 实体
ENTITY_PROJECT = "project"
ENTITY_SETTINGS = "settings"
ENTITY_PROCESS = "process"
ENTITY_TOOL = "tool"
ENTITY_ISSUE = "issue"
ENTITY_SELECTION = "selection"
ENTITY_HISTORY = "history"
CHANGE_ENTITIES = (
    ENTITY_PROJECT, ENTITY_SETTINGS, ENTITY_PROCESS, ENTITY_TOOL,
    ENTITY_ISSUE, ENTITY_SELECTION, ENTITY_HISTORY,
)

#: 实体 → 它挂哪个外键列（``settings``/``project`` 不挂行）
ENTITY_COLUMNS = {
    ENTITY_PROCESS: "process_row_id",
    ENTITY_TOOL: "tool_row_id",
    ENTITY_ISSUE: "issue_row_id",
    ENTITY_SELECTION: "selection_row_id",
    ENTITY_HISTORY: "history_row_id",
}

#: 实体的中文名（清单与文档里用）
ENTITY_LABELS = {
    ENTITY_PROJECT: "项目",
    ENTITY_SETTINGS: "项目信息",
    ENTITY_PROCESS: "工序",
    ENTITY_TOOL: "工序刀具行",
    ENTITY_ISSUE: "问题清单",
    ENTITY_SELECTION: "选型报价",
    ENTITY_HISTORY: "版本履历",
}

#: 动作
ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_DELETE = "delete"
ACTION_RESTORE = "restore"
ACTION_REORDER = "reorder"
ACTION_PHOTO = "photo"
ACTION_SAVE = "save"
CHANGE_ACTIONS = (
    ACTION_CREATE, ACTION_UPDATE, ACTION_DELETE,
    ACTION_RESTORE, ACTION_REORDER, ACTION_PHOTO, ACTION_SAVE,
)

ACTION_LABELS = {
    ACTION_CREATE: "新增",
    ACTION_UPDATE: "修改",
    ACTION_DELETE: "删除",
    ACTION_RESTORE: "恢复",
    ACTION_REORDER: "排序调整",
    ACTION_PHOTO: "图片",
    ACTION_SAVE: "保存",
}

#: ``label`` 最多留多少字（人看的一句话，不塞整段描述）
LABEL_LIMIT = 400

CHANGES_FIELDS: tuple[LibraryField, ...] = (
    LibraryField("entity", "entity", "choice", ENTITY_PROCESS, "实体",
                 choices=CHANGE_ENTITIES,
                 choice_labels=tuple((item, ENTITY_LABELS[item]) for item in CHANGE_ENTITIES)),
    LibraryField("action", "action", "choice", ACTION_UPDATE, "动作",
                 choices=CHANGE_ACTIONS,
                 choice_labels=tuple((item, ACTION_LABELS[item]) for item in CHANGE_ACTIONS)),
    LibraryField("label", "label", "text", "", "说明", limit=LABEL_LIMIT),
)

#: 兜底明细（字段级 old/new、槽位、原因、被删行清单……）
CHANGES_JSON_COLUMNS = {"extra": "extra_json"}

#: 五列"被改的行" + 一次保存的版本行，全是真外键；删目标行时置空（label 里还写着是谁）。
#: ``selection_row_id`` **不在其中**：它指向的是已经废弃的多态表 ``project_selections``，
#: 新库连那张表都不建（写它等于写一个指不到的表）。老库上这一列还在、外键也还在，
#: 只用来给历史流水行指路；新行一律不写它，改由下面两列分列指向夹具/检具表。
CHANGES_FOREIGN_KEYS = (
    ForeignKey("version_id", "project_versions", on_delete="SET NULL"),
    ForeignKey("process_row_id", "project_processes", on_delete="SET NULL"),
    ForeignKey("tool_row_id", "project_process_tools", on_delete="SET NULL"),
    ForeignKey("issue_row_id", "project_issues", on_delete="SET NULL"),
    ForeignKey("fixture_row_id", "project_fixtures", on_delete="SET NULL"),
    ForeignKey("gauge_row_id", "project_gauges", on_delete="SET NULL"),
    ForeignKey("history_row_id", "project_versions", on_delete="SET NULL"),
)

#: 老库遗留列：新库里只留一个**可空**列（没有外键），历史流水行仍读得到当时挂的是哪一行
CHANGES_EXTRA_COLUMNS = ("selection_row_id TEXT",)

#: 选型的两种表各自挂哪一列（写入时按草稿 ``extra.kind`` 选）
SELECTION_KIND_COLUMNS = {"fixture": "fixture_row_id", "gauge": "gauge_row_id"}

#: 老库补列用：这几列是后加的，老库上要用 ``ALTER TABLE ADD COLUMN`` 补（可空 + REFERENCES）
LATE_COLUMNS = (
    "fixture_row_id TEXT REFERENCES project_fixtures(id) ON DELETE SET NULL",
    "gauge_row_id TEXT REFERENCES project_gauges(id) ON DELETE SET NULL",
)

#: 五个"被改的行"列全空
_ALL_ROWS_NULL = " AND ".join(f"{column} IS NULL" for column in ENTITY_COLUMNS.values())


#: ``entity``/``action`` 白名单 + "被改的行"怎么挂
#:
#: **为什么不是"恰好一列非空"**：五个行外键都是 ``ON DELETE SET NULL``（设计里定的口径），
#: 目标行被物理删掉时列会被置空——那时候 ``entity='process'`` 却一个列都不挂是**正常状态**，
#: 要是写成"必须有一列非空"，置空这一步会被 CHECK 拦住，SQLite 直接报
#: ``IntegrityError: CHECK constraint failed``（写这版时踩过，测试里那一条就是回归点）。
#: 所以拆成三条更准的约束：
#:
#: 1. 最多挂一列（五列里至少四列是空的）；
#: 2. 挂上的那一列必须正好是 ``entity`` 对应的列（``entity='process'`` 不许挂刀具行）；
#: 3. ``project``/``settings`` 是整项目改动，一列都不许挂。
#:
#: "写入时必须挂上"由写入方保证（``insert_drafts`` 在有 ``record_id`` 时一定填），
#: 单测里逐条断言了每种实体的流水都挂着对应的行。
CHANGES_CHECKS = (
    "entity IN (" + ",".join(f"'{item}'" for item in CHANGE_ENTITIES) + ")",
    "action IN (" + ",".join(f"'{item}'" for item in CHANGE_ACTIONS) + ")",
    "(" + " + ".join(f"({column} IS NULL)" for column in ENTITY_COLUMNS.values()) + ") >= 4",
    *tuple(f"({column} IS NULL OR entity='{entity}')"
           for entity, column in ENTITY_COLUMNS.items()),
    "(" + "entity NOT IN ('%s','%s') OR " % (ENTITY_PROJECT, ENTITY_SETTINGS)
    + _ALL_ROWS_NULL + ")",
)

#: 清单里要报的列（不取 ``extra_json`` 之外的 JSON 明细时也能用）
LIST_COLUMNS = (
    "id", "project_id", "version_id", "sort_order", "entity", "action", "label",
    "process_row_id", "tool_row_id", "issue_row_id", "selection_row_id",
    "fixture_row_id", "gauge_row_id", "history_row_id",
    "extra_json", "deleted_at", "deleted_by", "deleted_reason", "created", "updated",
)


class ProjectChanges(_ProjectRows):
    """``project_changes``：一行 = 一次改动里的一个实体（追加型日志）。"""

    table = CHANGES_TABLE
    table_label = "变更流水"
    parent_column = ""
    #: 平表：序号在整个项目里排（显示顺序 = 发生顺序）
    order_scope = "project"
    fields = CHANGES_FIELDS
    json_columns = CHANGES_JSON_COLUMNS
    default_json_cleaner = staticmethod(clean_json_object)
    foreign_keys = CHANGES_FOREIGN_KEYS
    extra_columns = CHANGES_EXTRA_COLUMNS
    check_sql = CHANGES_CHECKS
    #: 这张表自己不进变更流水（否则记一笔变一条，没完没了）
    change_entity = ""

    # ---------------- 表结构（含老库补列） ----------------

    def schema(self, db) -> None:
        """建表 + 索引；老库还要补上"后来才加的列"。"""
        db.executescript(self.ddl())
        self.ensure_late_columns(db)
        db.executescript(self.index_ddl())

    def ensure_late_columns(self, db) -> list[str]:
        """老库补列：``ALTER TABLE ADD COLUMN`` 只加**可空 + 有默认 NULL** 的列，不动既有数据。

        这里加的是 ``fixture_row_id``/``gauge_row_id``（选型拆表后才有）。
        SQLite 允许带 ``REFERENCES`` 的 ``ADD COLUMN``，前提是默认值是 NULL —— 正好满足。
        """
        existing = {row[1] for row in db.execute(f"PRAGMA table_info({self.table})")}
        added: list[str] = []
        for definition in LATE_COLUMNS:
            column = definition.split()[0]
            if column not in existing:
                db.execute(f"ALTER TABLE {self.table} ADD COLUMN {definition}")
                added.append(column)
        return added

    # ---------------- 写入 ----------------

    def next_order(self, db, project_id: str) -> int:
        row = db.execute(
            f"SELECT COALESCE(MAX(sort_order), -1) AS top FROM {self.table} WHERE project_id=?",
            (project_id,),
        ).fetchone()
        return int(row["top"]) + 1

    def insert_drafts(self, db, project_id: str, drafts: Sequence[dict[str, Any]],
                      *, version_id: str | None = None, created: str | None = None) -> list[str]:
        """把一次改动的草稿落库（**调用方要已经在事务里**，与保存版本同一次提交）。

        草稿形如 ``{"entity": "process", "action": "update", "label": "...",
        "record_id": "...", "extra": {...}}``；``entity`` 不认识的行**不插**（宁可少记，
        也不插一条挂不上外键的烂行）。
        """
        stamp = created or _stamp()
        order = self.next_order(db, project_id)
        written: list[str] = []
        for draft in drafts:
            entity = str(draft.get("entity") or "")
            action = str(draft.get("action") or "")
            if entity not in CHANGE_ENTITIES or action not in CHANGE_ACTIONS:
                continue
            record_id = str(draft.get("record_id") or "").strip()
            body = {
                "id": f"{project_id}-c{order}-{len(written)}",
                "project_id": project_id,
                "version_id": version_id,
                "sort_order": order,
                "entity": entity,
                "action": action,
                "label": str(draft.get("label") or "")[:LABEL_LIMIT],
                "extra_json": json.dumps(draft.get("extra") or {}, ensure_ascii=False,
                                         separators=(",", ":")),
                "deleted_at": None,
                "deleted_by": "",
                "deleted_reason": "",
                "created": stamp,
                "updated": stamp,
            }
            for name, column in ENTITY_COLUMNS.items():
                # 选型**不走** selection_row_id（它指的老表在新库里根本不存在）：
                # 那一列留给历史行，新行的行外键由下面的"按 kind 分列"负责
                keep = name == entity and record_id and name != ENTITY_SELECTION
                body[column] = record_id if keep else None
            # 选型的行外键**分列**（夹具/检具各一张表），按草稿里的 kind 落列；
            # 认不出 kind 就不挂（宁可少挂，也不写一个指错表的 id）
            for column in SELECTION_KIND_COLUMNS.values():
                body[column] = None
            if entity == ENTITY_SELECTION and record_id:
                kind = str((draft.get("extra") or {}).get("kind") or "")
                column = SELECTION_KIND_COLUMNS.get(kind)
                if column:
                    body[column] = record_id
            order += 1
            columns = list(body)
            db.execute(
                f"INSERT INTO {self.table}("
                + ",".join(columns) + ") VALUES(" + ",".join("?" * len(columns)) + ")",
                (*body.values(),),
            )
            written.append(body["id"])
        return written

    # ---------------- 读取 ----------------

    def listing(self, project_id: str, *, limit: int = 200, entity: str = "",
                action: str = "", recycle: bool = False) -> dict[str, Any]:
        """项目变更流水（新的在前），带那次保存的版本号（一次查询，不 N+1）。"""
        sql = (
            f"SELECT c.{', c.'.join(LIST_COLUMNS)}, v.revision AS version_revision, "
            "v.name AS version_name FROM project_changes c "
            "LEFT JOIN project_versions v ON v.id = c.version_id "
            "WHERE c.project_id=?"
        )
        params: list[Any] = [project_id]
        sql += " AND c.deleted_at IS NOT NULL" if recycle else " AND c.deleted_at IS NULL"
        if entity:
            sql += " AND c.entity=?"
            params.append(entity)
        if action:
            sql += " AND c.action=?"
            params.append(action)
        sql += " ORDER BY c.sort_order DESC, c.id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self._connect() as db:
            rows = db.execute(sql, tuple(params)).fetchall()
        changes = [self.change_view(row) for row in rows]
        return {
            "table": CHANGES_TABLE,
            "entities": list(CHANGE_ENTITIES),
            "actions": list(CHANGE_ACTIONS),
            "entity_labels": dict(ENTITY_LABELS),
            "action_labels": dict(ACTION_LABELS),
            "count": len(changes),
            "limit": max(1, min(int(limit), 1000)),
            "recycle": bool(recycle),
            "changes": changes,
        }

    def change_view(self, row: Any) -> dict[str, Any]:
        """一行 → 清单里的一份（``extra_json`` 解析成 ``extra``，带上版本号与目标行）。"""
        record = {column: row[column] for column in LIST_COLUMNS}
        raw = record.pop("extra_json", "{}")
        try:
            parsed = json.loads(raw or "{}")
        except (TypeError, ValueError):
            parsed = {}
        record["extra"] = parsed if isinstance(parsed, dict) else {}
        try:
            record["version_revision"] = row["version_revision"]
            record["version_name"] = row["version_name"]
        except (IndexError, KeyError):
            record.setdefault("version_revision", None)
            record.setdefault("version_name", "")
        record.pop("project_id", None)
        return record
