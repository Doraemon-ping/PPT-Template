# -*- coding: utf-8 -*-
"""找出某个 .py 里"用了但没定义/没 import"的全局名字。

重构期间把 3655 行的单文件拆成 20 多个模块时，靠它一次抓全猜漏的 import
（比"跑一次报一个 NameError、再跑一次再报一个"快得多）。

判据：AST 里所有 ``Name`` 的 Load，减去
  * 内置名字与解释器提供的模块级 dunder（``__file__`` / ``__name__`` / …）
  * 模块级定义的任何名字（import / 赋值 / def / class）
  * 类体与函数体里绑定的局部名字（参数、赋值、for、with、except、comprehension）
  * 属性名与全局声明
这样剩下的就是真正需要 import 的符号。

用法：``python tools_audit/check_undefined_names.py app/services/store.py``
"""
import ast
import builtins
import pathlib
import sys

#: 解释器自动注入的模块级名字，不是"没 import"
INTERPRETER_NAMES = frozenset({
    "__file__", "__name__", "__doc__", "__package__", "__spec__",
    "__loader__", "__builtins__", "__debug__", "__dict__", "__path__",
})


def bound_names(node: ast.AST) -> set[str]:
    """这个作用域里被绑定的名字。"""
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            names.add(child.id)
        elif isinstance(child, ast.arg):
            names.add(child.arg)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(child.name)
        elif isinstance(child, ast.ExceptHandler) and child.name:
            names.add(child.name)
        elif isinstance(child, (ast.Import, ast.ImportFrom)):
            for alias in child.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(child, ast.Global):
            names.update(child.names)
    return names


def main(path: str) -> int:
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"), path)
    local = bound_names(tree) | set(dir(builtins)) | INTERPRETER_NAMES
    used: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.setdefault(node.id, node.lineno)
    missing = {name: line for name, line in used.items() if name not in local}
    for name, line in sorted(missing.items(), key=lambda item: item[1]):
        print(f"{line:6}  {name}")
    print(f"--- 共 {len(missing)} 个未定义名字")
    return 1 if missing else 0


if __name__ == "__main__":
    # 不传文件就扫整个 app/（退出码非 0 表示有问题，方便串进脚本）
    if len(sys.argv) > 1:
        raise SystemExit(main(sys.argv[1]))
    root = pathlib.Path("app")
    files = sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    bad = 0
    for file in files:
        tree = ast.parse(file.read_text(encoding="utf-8"), str(file))
        local = bound_names(tree) | set(dir(builtins)) | INTERPRETER_NAMES
        used = {n.id for n in ast.walk(tree)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        missing = sorted(used - local)
        if missing:
            print(f"{file}: {', '.join(missing)}")
            bad += 1
    print(f"--- 扫了 {len(files)} 个模块，{bad} 个有未定义名字")
    raise SystemExit(1 if bad else 0)
