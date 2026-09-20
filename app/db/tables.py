# -*- coding: utf-8 -*-
"""数据库表名登记表（模式级标识，集中一处）。

**为什么要有这个文件**：表名会同时出现在三处——建表 DDL、外键声明、迁移脚本。更麻烦的是
**跨域外键**：问题清单的 ``process_id`` 指向工序表、变更流水的六个 ``*_row_id`` 指向工序/
刀具行/问题/选型/履历。如果让 ``issue`` 去 ``import`` 工序模块拿表名，两个**本是平级的
业务域**之间就产生了代码依赖；选型与变更流水同理，越加越多就织成一张网。

把表名放进 ``db/`` 这一层（"谁都可以依赖，我不依赖任何人"），各业务域**各自向下读同一份
登记表**，彼此不产生任何 import。跨域关系因此是**声明的**（谁能外键指到谁，一眼可查），
而不是**隐式**的模块依赖。
"""

# ---------------- 共享表（db/schema.py 建） ----------------
PROJECTS_TABLE = "projects"
ASSETS_TABLE = "assets"
APP_SETTINGS_TABLE = "app_settings"
AUTH_SETTINGS_TABLE = "auth_settings"

# ---------------- 基础库（domains/ 各自建） ----------------
MACHINES_TABLE = "machines"
TOOLS_TABLE = "tools"
TOOL_GROUPS_TABLE = "tool_groups"
TOOL_CATEGORIES_TABLE = "tool_categories"
FIXTURES_TABLE = "fixtures"
FIXTURE_CENTERS_TABLE = "fixture_centers"
GAUGES_TABLE = "gauges"
GAUGE_CATEGORIES_TABLE = "gauge_categories"

# ---------------- 项目级业务表（domains/ 各自建） ----------------
SETTINGS_TABLE = "project_settings"
PROCESS_TABLE = "project_processes"
PROCESS_TOOL_TABLE = "project_process_tools"
ISSUE_TABLE = "project_issues"
FIXTURE_TABLE = "project_fixtures"
GAUGE_TABLE = "project_gauges"
HISTORY_TABLE = "project_versions"
CHANGES_TABLE = "project_changes"

#: 已废弃的多态选型表：不再读写，只当迁移来源（见 ``domains/selection.py``）
LEGACY_SELECTION_TABLE = "project_selections"
