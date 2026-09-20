"""项目级业务数据（阶段 2a：问题清单 ``project_issues``）。

与 1b 的工序表同一个套路（行级读写、逻辑删除、旧读模型精确还原），
额外遵守**外键口径**：凡是"指向别的表里的行"的列一律是真外键：

* ``project_id`` → ``projects(id)``
* ``process_id`` → ``project_processes(id)``（**可空**：项目级问题不挂具体工序）
* ``before_photo_id`` / ``after_photo_id`` → ``assets(id)``

顺带修掉旧结构的两个真缺陷：

1. 旧 ``is[].pr`` 存的是**工序名字**——工序一改名，这条问题就"指向不存在"。
   落表后以 ``process_id`` 外键为准，读模型里的 ``pr`` 由外键**现算当前名字**；
   同时把迁移当时的名字存进 ``process_name_snapshot``，工序被逻辑删除后照样显示得出来。
2. 旧 ``bI/aI`` 存整张图的 data URL（跟着 ``state_json`` 一起膨胀），
   落表后进附件库，列里只存附件 id。

启用同样是显式的：``app_settings.project_business_version >= 2``
（或环境变量 ``MACHINING_PROJECT_BUSINESS=2``）。版本 1 只开工序表。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import HTTPException

from ..db.library import AttachmentSpec, LibraryField
from ..db.rows import (
    ProjectRows,
    asset_value,
    clean_json_object,
)
from ..db.tables import ISSUE_TABLE, PROCESS_TABLE

#: 阶段 2 的版本号：``app_settings.project_business_version`` ≥ 2 才算"问题清单已落表"
ISSUE_VERSION = 2

#: 旧读模型里"看得见"的键（compose 不多不少输出这些，顺序与线上 state_json 一致）
LEGACY_ISSUE_KEYS = ("tp", "pr", "ds", "fx", "cr", "st", "bI", "aI")

#: 状态取值（页面上的下拉：进行中 / 已完成）
ISSUE_STATUSES = ("进行中", "已完成")

#: 问题类型字典（页面上是自由文本，这里只作为建议值，不做约束）
ISSUE_TYPES = ("尺寸", "外观", "结构", "工艺", "其他")

ISSUE_FIELDS: tuple[LibraryField, ...] = (
    LibraryField("tp", "issue_type", "text", "", "问题类型", limit=60),
    LibraryField("ds", "description", "text", "", "问题描述", limit=2000),
    LibraryField("fx", "fix_plan", "text", "", "修改方案", limit=2000),
    LibraryField("cr", "customer_reply", "text", "", "客户回复", limit=2000),
    LibraryField("st", "status", "choice", "进行中", "状态", choices=ISSUE_STATUSES),
    LibraryField("prName", "process_name_snapshot", "text", "", "工序名快照", limit=120),
)

ISSUE_ATTACHMENTS: tuple[AttachmentSpec, ...] = (
    AttachmentSpec("before", "issue_photo", "before_photo_id", "bI", value_keys=("bI",)),
    AttachmentSpec("after", "issue_photo", "after_photo_id", "aI", value_keys=("aI",)),
)


class ProjectIssues(ProjectRows):
    """``project_issues``：一个问题一行（表标签给报错用）。"""

    table = ISSUE_TABLE
    table_label = "问题清单"
    parent_column = "process_id"
    parent_table = PROCESS_TABLE
    parent_nullable = True
    #: 页面上问题清单是一张平表（不按工序分组），所以序号在**整个项目**里排
    order_scope = "project"
    fields = ISSUE_FIELDS
    attachments = ISSUE_ATTACHMENTS
    #: 兜底列：旧数据里将来出现的、登记表没覆盖的键整份留着，一个都不丢
    json_columns = {"extra": "extra_json"}
    default_json_cleaner = staticmethod(clean_json_object)
    #: 阶段 3b：问题清单的每次改动都进变更流水
    change_entity = "issue"
    title_keys = ("tp", "ds")


# ---------------- 读模型：表行 → 旧 is[] ----------------

def compose_issues(
    rows: list[dict[str, Any]],
    *,
    process_names: dict[str, str] | None = None,
    asset_store=None,
    inline_assets: bool = False,
) -> list[dict[str, Any]]:
    """把表行还原成旧 ``is[]``（键顺序与线上一致：tp, pr, ds, fx, cr, st, bI, aI）。

    ``pr`` 取**当前工序名**（外键 → 工序表）；工序为空或已找不到时用 ``process_name_snapshot``。

    **逻辑删除的行不进读模型**（与 1b 的 ``compose_processes`` 同一口径）：页面上点"删除"，
    这一条就该从 DFM 报告里消失；行本身还在表里，回收站能恢复。
    """
    names = process_names or {}
    result: list[dict[str, Any]] = []
    for row in rows:
        if row.get("deleted_at"):
            continue
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        process_id = str(row.get("process_id") or "")
        process_name = names.get(process_id) or str(row.get("prName") or "")
        item: dict[str, Any] = {
            "tp": str(row.get("tp") or ""),
            "pr": process_name,
            "ds": str(row.get("ds") or ""),
            "fx": str(row.get("fx") or ""),
            "cr": str(row.get("cr") or ""),
            "st": str(row.get("st") or "进行中"),
            "bI": asset_value(asset_store, row.get("before_photo_id"), inline_assets),
            "aI": asset_value(asset_store, row.get("after_photo_id"), inline_assets),
        }
        for key, value in extra.items():
            item.setdefault(str(key), value)
        result.append(item)
    return result


def legacy_issues(
    issues: "ProjectIssues | None",
    project_id: str,
    *,
    process_rows: list[dict[str, Any]] | None = None,
    asset_store=None,
    inline_assets: bool = False,
) -> list[dict[str, Any]] | None:
    """从表读出旧 ``is[]``；这个项目**表里一行都没有**时返回 ``None``（调用方回退 state_json）。

    注意判空用的是 ``include_deleted=True``：全删光的时候读模型应该是空数组，
    绝不能回退到 ``state_json.is`` 把删掉的又显示出来。
    """
    if issues is None:
        return None
    if not issues.rows(project_id, include_deleted=True):
        return None
    names = {str(row["id"]): str(row.get("nm") or "") for row in (process_rows or [])}
    return compose_issues(
        issues.list_typed(project_id, include_deleted=True),
        process_names=names,
        asset_store=asset_store,
        inline_assets=inline_assets,
    )


# ---------------- 反向：旧 is[] → 表行（迁移用） ----------------

def split_issues(
    state: dict[str, Any],
    *,
    process_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """把旧 ``is[]`` 拆成行载荷，并报告工序名能不能对上。

    返回 ``(载荷列表, 报告)``；报告里的 ``missing`` / ``ambiguous`` 是"没敢猜"的条数，
    这些行会**留空 process_id**、只存名字快照（绝不按名字瞎指）。
    """
    processes = process_rows or []
    by_name: dict[str, list[str]] = {}
    for row in processes:
        by_name.setdefault(str(row.get("nm") or ""), []).append(str(row["id"]))

    report: dict[str, Any] = {"issues": 0, "linked": 0, "missing": 0, "ambiguous": 0,
                              "missing_names": [], "ambiguous_names": []}
    payloads: list[dict[str, Any]] = []
    for index, issue in enumerate(state.get("is") or []):
        if not isinstance(issue, dict):
            continue
        name = str(issue.get("pr") or "")
        candidates = by_name.get(name) or []
        process_id = candidates[0] if len(candidates) == 1 else ""
        if not name:
            pass
        elif len(candidates) == 1:
            report["linked"] += 1
        elif not candidates:
            report["missing"] += 1
            if name not in report["missing_names"]:
                report["missing_names"].append(name)
        else:
            report["ambiguous"] += 1
            if name not in report["ambiguous_names"]:
                report["ambiguous_names"].append(name)
        payload: dict[str, Any] = {"sid": f"i{index + 1}"}
        for field in ISSUE_FIELDS:
            if field.key == "prName":
                payload[field.key] = name
                continue
            # 旧行里没有的键、或者值是 null 的键，都不写进载荷（写进去等于"填了个空"，
            # 取值枚举字段会因此被判非法）；落库时用字段默认值补。
            value = issue.get(field.key)
            if value is not None:
                payload[field.key] = value
        known = {field.key for field in ISSUE_FIELDS} | set(LEGACY_ISSUE_KEYS)
        extra = {key: value for key, value in issue.items() if key not in known}
        payload["extra"] = extra
        payloads.append({
            "sid": payload["sid"],
            "payload": payload,
            "process_id": process_id,
            "attachments": {
                ISSUE_ATTACHMENTS[0].column: issue.get(ISSUE_ATTACHMENTS[0].legacy_key),
                ISSUE_ATTACHMENTS[1].column: issue.get(ISSUE_ATTACHMENTS[1].legacy_key),
            },
        })
        report["issues"] += 1
    return payloads, report


def apply_issue_split(
    issues: "ProjectIssues",
    project_id: str,
    state: dict[str, Any],
    *,
    process_rows: list[dict[str, Any]] | None = None,
    db=None,
) -> dict[str, Any]:
    """把旧 ``is[]`` 灌进表（迁移用；调用方负责备份与归档）。**幂等**：已有行就跳过。"""
    existing = issues.count(project_id, include_deleted=True)
    payloads, report = split_issues(state, process_rows=process_rows)
    if existing:
        report["skipped"] = True
        report["existing_rows"] = existing
        return report
    for item in payloads:
        body = dict(item["payload"])
        if item["process_id"]:
            body["process_id"] = item["process_id"]
        issues.create(project_id, body, attachments=item["attachments"], db=db)
    report["skipped"] = False
    report["existing_rows"] = 0
    return report
