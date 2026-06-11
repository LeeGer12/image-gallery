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
  models.py       # ORM 模型（Folder, Image, Tag, Album, User, OperationLog）
  database.py     # 引擎、会话、全文搜索、迁移初始化、rebuild_engine
  settings.py     # settings.json 读写（局域网连接配置）
  queries.py      # 共享查询（分类去重、分类键解析、标签格式化）
  query_worker.py # 通用 QueryWorker + run_query 便捷函数 + abort_query
  scanner.py      # 文件夹扫描 Worker
  thumbnailer.py  # 缩略图生成 Worker
  album_worker.py # 相册 CRUD + 分类 + 索引删除 Worker
  import_worker.py # 导入 Worker（复制文件+更新DB）
  zip_worker.py   # 打包下载 Worker（保留分类目录结构）
  session.py      # 进程级用户会话单例（set_current_user / is_admin）
  auth.py         # 密码哈希与验证（PBKDF2-SHA256）
ui/             # UI 层（窗口、面板、对话框）
  main_window.py      # 主窗口三栏布局
  thumbnail_grid.py   # 缩略图网格（纯图片方格、无限滚动、懒加载、右键菜单）
  accordion_sidebar.py # 折叠面板侧边栏（CollapsibleSection + AccordionSidebar）
  property_panel.py   # 属性面板
  image_viewer.py     # 大图预览（翻页、另存为）
  album_dialog.py     # 创建/编辑相册对话框
  batch_meta_dialog.py # 批量设置项目类型/风格对话框
  import_dialog.py    # 导入对话框（含进度条）
  thread_utils.py     # QThread 生命周期工具（stop_thread）
  login_dialog.py     # 登录/注册对话框（免密码选用户，admin 需密码）
  user_manage_dialog.py # 用户管理对话框（增删用户、停用启用、admin 密码验证）
  password_dialog.py  # 密码输入对话框（登录验证 + 敏感操作验证）
  setup_wizard.py     # 首次启动配置向导（输入服务器 IP → 测试连接）
utils/          # 工具函数（图片处理、EXIF、文件操作）
  image_utils.py    # 格式判断、元数据读取、缩略图生成
assets/         # 静态资源
  style.qss       # 全局 QSS 样式表（轻量工具风）
```

## 命名规范
- 文件/目录: 全小写，下划线分隔
- 类名: PascalCase
- 函数/变量: snake_case
- 常量: UPPER_SNAKE_CASE
- Qt 信号: snake_case，描述事件含义（如 `result_ready`、`image_selected`）

## 代码纪律
- 所有数据库 IO 必须在 QThread 中执行，禁止在主线程阻塞
- 图片路径统一使用 Path 对象，禁止硬编码路径分隔符
- 缩略图缓存路径必须基于 storage_root 配置，不可写死
- 数据库连接字符串从 settings.json 或环境变量读取（局域网模式账号密码写死在 config.py）
- 所有用户可见字符串使用中文

## 配置方式
局域网模式：首次启动弹出配置向导，输入中枢电脑 IP 即可。配置保存在 `~/.image_gallery/settings.json`。
本地开发模式：settings.json 为空时，从环境变量读取数据库配置：
- `IG_DB_HOST` — 数据库服务器地址（默认 localhost）
- `IG_DB_PORT` — 端口（默认 5432）
- `IG_DB_NAME` — 数据库名（默认 imagegallery）
- `IG_DB_USER` — 用户名
- `IG_DB_PASSWORD` — 密码
- `IG_STORAGE_ROOT` — 图片存储根目录（默认 G:/ImageGalleryStorage，支持 UNC 路径）

## 当前状态
- Phase 1 骨架已完成：目录结构、数据库模型、主窗口三栏布局
- Phase 2 核心浏览链路已完成：文件夹扫描、缩略图生成、网格浏览、属性面板、全文搜索
- Phase 3 功能已完成：相册管理、二级项目分类(类型→风格)、导入模式、属性面板增强、storage_path回退
- Phase 3 优化已完成：二级分类体系、索引文件夹删除、拖拽分类、节点重命名
- Phase 4 UI 打磨已完成：纯图片缩略图网格、QueryWorker 异步 DB、无限滚动、折叠面板侧边栏、快捷键+右键菜单、打包下载、全局 QSS
- 代码审查已完成（2026-05-08）：提取 thread_utils/queries 工具模块，修复 N+1 查询、批量操作、线程安全
- Bug 修复已完成（2026-05-15）：闪退（并发查询竞态）、侧边栏操作失败（Worker 信号交叉污染 + 线程泄漏）
- 功能测试全部通过（2026-05-28）：15 项测试清单全部完成（代码审查+数据库验证），详见 tests/TEST_RECORD.md
- Phase 5 代码已完成（2026-05-29）：用户模型、登录/注册、角色权限、操作日志、乐观锁、用户管理、管理员密码（PBKDF2-SHA256）
- Phase 5 测试全部通过（2026-06-11）：63/63 项通过，详见 tests/TEST_PHASE5.md
- Phase 6 代码已完成（2026-06-11）：局域网连接配置向导、settings.json 配置持久化、rebuild_engine、中枢电脑配置指南
- 测试数据：数据库中 20 张图片已分配分类数据（Office/Hotel/Restaurant × Modern/Chinese/Luxury）
- 运行环境已就绪：Python 3.12.3、PostgreSQL、依赖包安装完成，数据库表已初始化
- `py main.py` 可正常启动

## 分类体系
二级结构：项目类型(project_type) → 风格(style_name)
- 侧边栏以二级树展示，点击各级节点过滤对应图片
- 导入路径：`STORAGE_ROOT/{项目名}/{项目类型}/{风格名}/`（项目名仅用于文件夹路径，不参与分类）
- 拖拽缩略图到侧边栏分类节点可快速分类

## 验证规则
- 改完代码必须能运行 `py main.py` 启动无报错（使用 Python Launcher）
- 新增功能必须有对应的手动验证步骤

## 线程安全规则
- 停止 Worker 前必须先断开其所有信号，防止旧 Worker 的信号回调污染新 Worker
- abort_query 中需处理 C++ 对象已被 deleteLater 销毁的情况（try/except RuntimeError）
- abort 未启动的线程后需手动 deleteLater，防止线程/Worker 对象泄漏
