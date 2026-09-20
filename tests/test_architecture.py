# -*- coding: utf-8 -*-
"""分层架构守卫：把"依赖只能向下、域之间不许互引"钉成可执行的测试。

重构定下的分层与依赖方向（严格向下，不设例外）::

    api  →  services  →  domains  →  db  →  core
    （app/main.py 与 app/machining_dfm.py 是最外层：组合根与兼容转发层，可引任意层）

本文件只**读源码做静态分析**，不导入被测模块 —— 这样即使某天有人写出循环导入，
这些断言照样能跑出结论，而不是先被 ImportError 拦住。
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator

import pytest

APP = Path(__file__).resolve().parent.parent / "app"

#: 分层顺序：下标越小越底层。依赖只允许从高层指向低层。
LAYERS = ("core", "db", "domains", "services", "api")
RANK = {name: index for index, name in enumerate(LAYERS)}

#: 最外层模块：允许引用任意层
OUTERMOST = {"main", "machining_dfm"}


def _module_name(path: Path) -> str:
    """``app/domains/process.py`` → ``domains.process``。"""
    parts = list(path.relative_to(APP).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _app_modules() -> Iterator[tuple[str, Path]]:
    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield _module_name(path), path


def _resolved_imports(path: Path, module: str) -> list[tuple[str, int]]:
    """把一条 import 解析成"app 内的目标模块"，返回 ``(目标, 行号)``。

    相对导入按当前模块所在的包解析；标准库与第三方一律忽略。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = module.split(".")[:-1]
                up = node.level - 1
                base = base[: len(base) - up] if up else base
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            if target == "app":
                found.append(("", node.lineno))
            elif target.startswith("app."):
                found.append((target[4:], node.lineno))
            elif target.split(".")[0] in LAYERS:
                found.append((target, node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app":
                    found.append(("", node.lineno))
                elif alias.name.startswith("app."):
                    found.append((alias.name[4:], node.lineno))
    return found


def _layer(module: str) -> str | None:
    head = module.split(".")[0]
    if head in RANK:
        return head
    return None


def _violations() -> list[str]:
    """收集所有违反分层方向的 import。"""
    problems: list[str] = []
    for module, path in _app_modules():
        if module.split(".")[0] in OUTERMOST:
            continue
        source_layer = _layer(module)
        for target, line in _resolved_imports(path, module):
            if not target:
                continue
            target_layer = _layer(target)
            if target_layer is None:
                problems.append(
                    f"{path.name}:{line} {module} 导入了非分层模块 app.{target}")
                continue
            if source_layer is None:
                continue
            if target_layer == source_layer:
                continue
            if RANK[target_layer] > RANK[source_layer]:
                problems.append(
                    f"{path.name}:{line} {module}[{source_layer}] 反向依赖 "
                    f"app.{target}[{target_layer}]（只能向下："
                    f"{' → '.join(LAYERS)}）")
    return problems


def test_dependencies_only_point_downwards():
    """依赖方向严格向下：core ← db ← domains ← services ← api。"""
    problems = _violations()
    assert not problems, "发现反向/越层依赖：\n" + "\n".join(problems)


def test_domains_never_import_each_other():
    """业务域之间**零互引**：跨域编排只允许发生在 app/services/。

    这是"职责清晰、边界规范"的核心一条：两个域要是互相 import，改一个域就得动另一个域，
    边界就名存实亡了。共享的底座（表名、行 CRUD、工具函数）都在 app/db/ 与 app/core/。
    """
    problems: list[str] = []
    for module, path in _app_modules():
        if _layer(module) != "domains":
            continue
        mine = module.split(".")[-1]
        for target, line in _resolved_imports(path, module):
            if _layer(target) != "domains" or not target.startswith("domains."):
                continue
            peer = target.split(".")[1]
            if peer != mine:
                problems.append(f"{path.name}:{line} 域 {mine} 导入了兄弟域 {peer}")
    assert not problems, "业务域之间出现互相依赖：\n" + "\n".join(problems)


def test_only_composition_root_and_shim_touch_the_old_flat_module():
    """实现模块不许反过来导入兼容转发层 ``app.machining_dfm``。

    那个模块只为兼容 ``tools/`` 与老测试而存在；实现代码一旦依赖它，
    就绕过了分层（它自己引用全部分层），等于把依赖方向反过来。
    """
    problems: list[str] = []
    for module, path in _app_modules():
        if module.split(".")[0] in OUTERMOST:
            continue
        for target, line in _resolved_imports(path, module):
            if target == "machining_dfm":
                problems.append(f"{path.name}:{line} {module} 导入了兼容转发层")
    assert not problems, "有实现模块依赖兼容转发层：\n" + "\n".join(problems)


def test_core_and_db_stay_free_of_business_layers():
    """``core``（配置/工具/安全）与 ``db``（连接/DDL/行 CRUD）**不含业务规则**。"""
    problems: list[str] = []
    for module, path in _app_modules():
        if _layer(module) not in {"core", "db"}:
            continue
        for target, line in _resolved_imports(path, module):
            if _layer(target) in {"domains", "services", "api"}:
                problems.append(f"{path.name}:{line} {module} 依赖了业务层 app.{target}")
    assert not problems, "底座层混进了业务依赖：\n" + "\n".join(problems)


def test_every_routers_module_exposes_register():
    """``app/api/routers/`` 下每个路由模块都只通过 ``register()`` 挂载。

    统一入口才好一眼看全"有哪些接口"：清单在 ``app/api/routers/__init__.py``。
    """
    routers = APP / "api" / "routers"
    assert routers.is_dir(), "缺少 app/api/routers 包"
    missing: list[str] = []
    for path in sorted(routers.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        if not any(isinstance(node, ast.FunctionDef) and node.name == "register"
                   for node in tree.body):
            missing.append(path.name)
    assert not missing, f"这些路由模块没有 register()：{missing}"


def test_layers_exist_as_packages():
    """分层包齐备（少一个都说明结构没落地）。"""
    for name in LAYERS:
        package = APP / name
        assert package.is_dir(), f"缺少分层包 app/{name}/"
        assert (package / "__init__.py").is_file(), f"app/{name}/ 缺少 __init__.py（中文说明）"


def test_app_entrypoints_are_importable_targets():
    """标准入口 ``app.main:create_app`` 与兼容入口都存在。"""
    assert (APP / "main.py").is_file(), "缺少 app/main.py（FastAPI 标准入口）"
    assert (APP / "machining_dfm.py").is_file(), "缺少兼容转发层 app/machining_dfm.py"
    source = (APP / "main.py").read_text(encoding="utf-8")
    assert "def create_app(" in source, "app/main.py 必须提供 create_app()"
    assert "app = create_app()" in source, "app/main.py 必须暴露 ASGI 入口 app"


@pytest.mark.parametrize("module", ["app.main", "app.machining_dfm",
                                    "app.services.machining", "app.services.store"])
def test_entrypoint_modules_actually_import(module):
    """入口与转发层能真导入（挡住改名漏改、循环导入这类问题）。"""
    import importlib

    assert importlib.import_module(module) is not None
