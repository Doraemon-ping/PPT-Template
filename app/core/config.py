# -*- coding: utf-8 -*-
"""部署路径与环境变量配置（全项目唯一的路径来源）。

只负责"文件放在哪"，不含任何业务逻辑；各层的存储与业务规则由各自模块自己负责。

路径口径：

* ``BASE_DIR``：代码/资源所在的项目根（打包后是解包目录），只读资源都从这里找；
* ``APP_ROOT``：可写数据根，默认等于 ``BASE_DIR``，打包后是 exe 同级目录；
  可用环境变量 ``DFM_APP_ROOT`` 覆盖（测试与探针靠它把数据写到临时目录）；
* ``DATA_DIR``：``<APP_ROOT>/data``，机加库落在 ``DATA_DIR/machining_dfm/``；
* ``STATIC_DIR``：``<BASE_DIR>/static``，前端静态资源。
"""
import os
import sys
from pathlib import Path

#: 项目根：app/core/config.py → 上溯三层
BASE_DIR = Path(__file__).resolve().parent.parent.parent

#: 可写数据根：打包运行时取 exe 同级目录，否则就是项目根
APP_ROOT = Path(
    os.environ.get('DFM_APP_ROOT')
    or (Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else BASE_DIR)
)

#: 数据目录（其下按服务隔离：data/machining_dfm 等）
DATA_DIR = APP_ROOT / 'data'

#: 前端静态资源目录
STATIC_DIR = BASE_DIR / 'static'

#: 机加种子数据目录（首次建库时灌入设备/刀具/夹具/检具与类别字典）
SEED_DIR = BASE_DIR / 'app' / 'resources' / 'machining_dfm_seed'
