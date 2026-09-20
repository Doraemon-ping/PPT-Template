# -*- coding: utf-8 -*-
"""共享表的结构定义与各基础库的"结构版本号"。

这里只有**共享表**（项目、后台配置、账号、以及两张只作为迁移来源的旧载荷壳表）；
各业务表由对应的 ``app/domains/`` 模块自己声明 DDL（见 ``app/db/rows.py`` 的 ``ddl()``）。

结构版本号全部存在 ``app_settings`` 里，是**幂等迁移的开关**：迁移只看"版本号到没到"，
不看数据长什么样，所以同一段迁移重复跑一万遍结果都一样。
"""

#: 基础库的结构版本号（设备 / 刀具 / 夹具 / 检具各自一个键）
MACHINE_SCHEMA_VERSION = 2
TOOL_SCHEMA_VERSION = 3
FIXTURE_SCHEMA_VERSION = 2
GAUGE_SCHEMA_VERSION = 2
#: 项目业务数据：项目信息（G 的建模字段）已搬进 project_settings 表
PROJECT_SCHEMA_VERSION = 1

#: 旧读模型里"归基础库共享"的键（``mdb`` 设备 / ``tdb`` 刀具 / ``fdb`` 夹具 / ``idb`` 检具）。
#: 这四个键一旦出现在 ``projects.state_json`` 里，说明库数据还没从项目里解耦出来。
LIBRARY_KEYS = ("mdb", "tdb", "fdb", "idb")

#: 项目**自带**的三份业务数组（= 旧读模型减去 :data:`LIBRARY_KEYS`）：
#: ``pr`` 工序、``is`` 问题清单、``vh`` 版本履历。它们随项目走，不共享。
PROJECT_ARRAYS = ("pr", "is", "vh")

#: 旧载荷表：只在首次建库/迁移时作为数据来源，迁完就归档成 ``*_legacy_v1``。
LEGACY_LIBRARY_TABLES = {"fdb": "fixtures", "idb": "gauges"}

#: 旧 ``revisions`` 表（整份快照一版一行）。**只在"版本履历还没落表"时才建**：
#: 阶段 3a 之后保存版本进了 ``project_versions``，``revisions`` 就只剩"影子副本"这一个作用，
#: 而影子副本只在还能回滚到旧路径（开关 < 4）时才有意义。开关到 4 之后表不建、行不写，
#: 库里每种数据只有一份（口径 6：哪一级落表了，那一级的影子副本就停写）。
LEGACY_REVISIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS revisions(
    project_id TEXT NOT NULL, revision INTEGER NOT NULL, name TEXT NOT NULL,
    state_json TEXT NOT NULL, created TEXT NOT NULL,
    PRIMARY KEY(project_id, revision),
    FOREIGN KEY(project_id) REFERENCES projects(id)
);
"""

#: 共享表 DDL（幂等，每次开库都执行一遍）
SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(
    id TEXT PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL,
    state_json TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0
);
-- 设备库的旧壳 ``equipment``（id/sort_order/payload_json/updated）**不再创建**：
-- 设备已经类型化进 ``machines``，那张表只剩 288 KB 没人读的重复数据（含内联图片），
-- 2026-09-18 已随旧副本一起清掉。老库（``library_schema_version`` 还没到 2）里如果还有它，
-- ``migrate_machine_library()`` 照旧会读它当搬迁来源（见那里的 ``table_exists`` 判断）。
CREATE TABLE IF NOT EXISTS fixtures(
    id TEXT PRIMARY KEY, sort_order INTEGER NOT NULL,
    payload_json TEXT NOT NULL, updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gauges(
    id TEXT PRIMARY KEY, sort_order INTEGER NOT NULL,
    payload_json TEXT NOT NULL, updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_settings(
    role TEXT PRIMARY KEY, salt TEXT NOT NULL, password_hash TEXT NOT NULL,
    iterations INTEGER NOT NULL, updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_settings(
    key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_machining_dfm_projects_archived_updated
    ON projects(archived, updated DESC);
"""
