# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec —— HPDC DFM 报告自动生成器（Windows x64, onedir 绿色版）。

构建（在项目根目录执行，使用装有 PyInstaller 的 Python）：
    python -m PyInstaller packaging/dfm_standalone.spec --noconfirm --clean
产物：packaging/build_dist/HPDC_DFM_Generator/
随后运行 packaging/build_win64.ps1 组装正式发布目录（补 templates/data/说明文档）。
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# 本 spec 位于 packaging/ 下，所有路径一律基于项目根绝对化
SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
sys.path.insert(0, str(ROOT))

APP_NAME = "HPDC_DFM_Generator"

hiddenimports = collect_submodules("app")
# uvicorn 运行时按字符串自动加载的模块
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
]

datas = []
# app 包内的数据文件（report/ppt/schemas/*.yaml、decks/*.yaml、assets/logo.png）
datas += collect_data_files("app")
# 前端页面 / 静态资源
datas += [(str(ROOT / "static"), "static")]
# 真实 PPT 预览脚本（live-preview 依赖 PowerShell + PowerPoint COM）：
# 一次性回退导出 + 常驻 worker，后者避免每次预览重新启动 PowerPoint。
datas += [
    (str(ROOT / "tools" / "export_slide_preview.ps1"), "tools"),
    (str(ROOT / "tools" / "preview_worker.ps1"), "tools"),
    (str(ROOT / "tools" / "check_preview_environment.ps1"), "tools"),
]
# python-pptx 自带 default 模板（Presentation() 无参创建时需要）
datas += collect_data_files("pptx")

a = Analysis(
    [str(ROOT / "app" / "standalone.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "numpy",
        "matplotlib",
        "scipy",
        "pandas",
        "tkinter",
        "IPython",
        "jupyter",
        "pytest",
        "notebook",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
