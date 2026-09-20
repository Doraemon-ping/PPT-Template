# -*- coding: utf-8 -*-
"""SQLite 连接工厂：连接生命周期、迁移用的 PRAGMA 开关、整库备份。

**为什么要 ``rename_compat``**：基础库的迁移都是"改成同名新表"（改名 → 建新表 → 搬数据 →
删旧表）。现在项目侧的表会真外键指向 ``tools``/``fixtures``/``gauges``/``machines``，
改名那一步默认会把子表里的 ``REFERENCES tools(id)`` 一起改写成
``REFERENCES tools_pre_foreign_keys(id)``，删掉旧表后子表的外键就指到不存在的表。
``legacy_alter_table=ON`` 关掉这个改写（改名只改名）。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Database:
    """指向一个 SQLite 文件的连接工厂。

    各域引擎都拿着同一个 ``connect`` 可调用对象（``AssetStore`` / ``TypedLibrary`` 等），
    所以这里暴露的 ``connect`` 必须能当普通函数直接调用并用作上下文管理器。
    """

    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        """一次连接 + 一次事务：正常退出提交，抛异常回滚，最后一定关连接。"""
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def rename_compat(self, db):
        """让 ``ALTER TABLE ... RENAME`` 只改名，不改写别的表里指向它的外键。"""
        previous = int(db.execute("PRAGMA legacy_alter_table").fetchone()[0])
        db.execute("PRAGMA legacy_alter_table=ON")
        try:
            yield
        finally:
            db.execute(f"PRAGMA legacy_alter_table={1 if previous else 0}")

    def backup(self, name: str, backup_dir: Path) -> Path | None:
        """把整库复制一份到 ``backup_dir/name``；同名备份已存在或库还不存在就跳过。

        用 SQLite 自己的在线备份 API，不是文件拷贝：即使有并发连接也不会拷出半截库。
        """
        backup_dir = Path(backup_dir)
        target = backup_dir / name
        if not self.path.is_file() or target.exists():
            return None
        backup_dir.mkdir(parents=True, exist_ok=True)
        source, sink = sqlite3.connect(self.path), sqlite3.connect(target)
        try:
            source.backup(sink)
        finally:
            sink.close()
            source.close()
        return target

    @staticmethod
    def table_exists(db, name: str) -> bool:
        """这张表在不在（迁移判据用，比 ``SELECT`` 试探更省事也更安全）。"""
        return db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone() is not None
