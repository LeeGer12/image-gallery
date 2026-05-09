# Image Gallery - 项目规范

## 项目定位
面向室内设计公司的本地图库管理软件，支持局域网多用户共享，管理规模五万张以上。

## 技术栈
- GUI: PySide6 (LGPL, 商业闭源免费)
- 数据库: PostgreSQL (局域网共享)
- ORM: SQLAlchemy 2.0
- 图片处理: Pillow, rawpy, pillow-heif
- 数据库驱动: psycopg2-binary

## 目录约定
```
core/           # 业务逻辑层（数据库、扫描、缩略图、导入导出）
  models.py     # ORM 模型（Folder, Image, Tag, Album）
  database.py   # 引擎、会话、全文搜索初始化
  queries.py    # 共享查询（分类去重、分类键解析、标签格式化）
  scanner.py    # 文件夹扫描 Worker
  thumbnailer.py # 缩略图生成 Worker
  album_worker.py # 相册 CRUD + 分类 + 索引删除 Worker
  import_worker.py # 导入 Worker（复制文件+更新DB）
ui/             # UI 层（窗口、面板、对话框）
  main_window.py    # 主窗口三栏布局
  thumbnail_grid.py # 缩略图网格（支持多种过滤+右键菜单）
  property_panel.py # 属性面板
  image_viewer.py   # 大图预览（翻页、另存为）
  album_dialog.py   # 创建/编辑相册对话框
  batch_meta_dialog.py # 批量设置项目类型/风格对话框
  import_dialog.py  # 导入对话框（含进度条）
  thread_utils.py   # QThread 生命周期工具（stop_thread）
utils/          # 工具函数（图片处理、EXIF、文件操作）
  image_utils.py    # 格式判断、元数据读取、缩略图生成
assets/         # 静态资源（图标、QSS 样式表）
```

## 命名规范
- 文件/目录: 全小写，下划线分隔
- 类名: PascalCase
- 函数/变量: snake_case
- 常量: UPPER_SNAKE_CASE
- Qt 信号: 以 `_signal` 结尾

## 代码纪律
- 所有数据库 IO 必须在 QThread 中执行，禁止在主线程阻塞
- 图片路径统一使用 Path 对象，禁止硬编码路径分隔符
- 缩略图缓存路径必须基于 storage_root 配置，不可写死
- 数据库连接字符串从环境变量或配置文件读取，禁止硬编码密码
- 所有用户可见字符串使用中文

## 环境变量
数据库连接通过环境变量配置，不硬编码到代码：
- `IG_DB_HOST` — 数据库服务器地址（默认 localhost）
- `IG_DB_PORT` — 端口（默认 5432）
- `IG_DB_NAME` — 数据库名（默认 imagegallery）
- `IG_DB_USER` — 用户名
- `IG_DB_PASSWORD` — 密码

## 当前状态
- Phase 1 骨架已完成：目录结构、数据库模型、主窗口三栏布局
- Phase 2 核心浏览链路已完成：文件夹扫描、缩略图生成、网格浏览、属性面板、全文搜索
- Phase 3 功能已完成：相册管理、二级项目分类(类型→风格)、导入模式、属性面板增强、storage_path回退
- Phase 3 优化已完成：二级分类体系、索引文件夹删除、拖拽分类、节点重命名
- 代码审查已完成（2026-05-08）：提取 thread_utils/queries 工具模块，修复 N+1 查询、批量操作、线程安全
- 运行环境已就绪：Python 3.12.10、PostgreSQL、依赖包安装完成，数据库表已初始化
- `python main.py` 可正常启动

## 分类体系
二级结构：项目类型(project_type) → 风格(style_name)
- 侧边栏以二级树展示，点击各级节点过滤对应图片
- 导入路径：`STORAGE_ROOT/{项目名}/{项目类型}/{风格名}/`（项目名仅用于文件夹路径，不参与分类）
- 拖拽缩略图到侧边栏分类节点可快速分类

## 验证规则
- 改完代码必须能运行 `python main.py` 启动无报错
- 新增功能必须有对应的手动验证步骤
