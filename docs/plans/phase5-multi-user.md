# Phase 5: 多用户局域网共享

**状态**: 待开发
**预计范围**: 17 个步骤，涉及 13 个文件（3 个新建 + 10 个修改）

---

## Context

Image Gallery 项目 Phase 1-4 已完成，单用户功能齐全。但公司多人需要在同一局域网共享图库，当前代码完全是单用户架构——没有用户概念、没有登录、没有权限、没有操作归属。需要加入多用户支持。

**需求范围**：
- 两种角色：管理员（全部操作）/ 普通用户（不能删除文件夹索引、不能删除记录、不能管理用户）
- 免密码登录：启动时从用户列表中选择自己的用户名
- 操作归属：记录谁导入了图片、谁创建了相册（仅数据库审计，无 UI 查看）
- 网络共享路径：STORAGE_ROOT 支持 UNC 路径（`//server/share`）

**深挖确认的需求**：
- 首次启动：用户为空时显示注册界面，第一个用户自动成为 admin
- 删除行为：管理员删除图片记录时，仅删数据库记录，保留磁盘文件
- 并发冲突：乐观锁 + 弹窗提示"数据已被 XXX 修改，是否覆盖？"
- admin 之间：admin 不能降级其他 admin（防止误操作）
- 用户自助：普通用户可修改自己的显示名，不能改用户名
- 登录界面：即使只有一个用户也始终显示选择界面

---

## 实现步骤

### 5A: 数据库模型 + 迁移

**1. `core/models.py` — 新增 User 和 OperationLog 模型**

新增 `User` 表：
- `id`, `username`(唯一), `display_name`, `role`("admin"/"normal"), `is_active`, `created_at`
- 无密码字段（需求：选用户名即可登录）

新增 `OperationLog` 表：
- `id`, `user_id`(FK→users), `action`, `target_desc`, `created_at`
- 追加式日志，仅记录不展示

现有模型增加外键：
- `Image.imported_by` → `users.id`（nullable, ON DELETE SET NULL）
- `Album.created_by` → `users.id`（nullable, ON DELETE SET NULL）

Image 表增加乐观锁字段：
- `version: Mapped[int] = mapped_column(Integer, default=1)` — 用于并发冲突检测

**2. `core/database.py` — 迁移语句**

在 `_migrate_columns()` 中追加（用现有的 `ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS` 模式）：
- 创建 `users` 表
- 创建 `operation_log` 表
- `images` 表添加 `imported_by` 列
- `images` 表添加 `version` 列（默认 1）
- `albums` 表添加 `created_by` 列
- **不自动创建 admin** — 由首次启动的注册界面处理

### 5B: 用户会话管理

**3. 新建 `core/session.py` — 进程级内存单例**

```python
_current_user: dict | None = None

def set_current_user(user_id, username, role)
def get_current_user() -> dict | None
def get_current_user_id() -> int | None
def is_admin() -> bool
def clear_session()
```

不用 QSettings：无密码需持久化，每次启动都要选用户。

### 5C: 登录与注册对话框

**4. 新建 `ui/login_dialog.py`**

- 模态 QDialog，启动时始终显示（即使只有一个用户）
- 用 `run_query` 异步检查 users 表是否为空
  - **空** → 进入注册模式：输入用户名 + 显示名，第一个用户自动成为 admin
  - **非空** → 进入选择模式：QListWidget 显示用户名，双击或点确认登录
- 登录/注册后调用 `set_current_user()`
- 关闭对话框 = 退出程序

**5. `main.py` — 插入登录流程**

在 `init_db()` 之后、`MainWindow` 之前插入：
```python
login = LoginDialog()
if login.exec() != QDialog.Accepted:
    sys.exit(0)
```

### 5D: 存储路径配置化

**6. `config.py` — STORAGE_ROOT 改为环境变量**

```python
STORAGE_ROOT = Path(os.environ.get("IG_STORAGE_ROOT", "G:/ImageGalleryStorage"))
```

已有 `import os`，直接加。UNC 路径由 `pathlib.Path` 原生支持，其他代码无需改。

### 5E: Worker 传递 user_id

**7. `core/import_worker.py`**

- `__init__` 新增 `user_id=None` 参数
- `run()` 中设置 `image.imported_by = self._user_id`
- 导入完成后写 `OperationLog`

**8. `core/scanner.py`**

- `__init__` 新增 `user_id=None` 参数
- 扫描完成后写 `OperationLog`（扫描本身不归属用户，只记录操作）

**9. `core/album_worker.py`**

- `__init__` 新增 `user_id=None` 参数
- `_create()` 中设置 `album.created_by = self._user_id`
- 操作完成后写 `OperationLog`

**10. `ui/main_window.py` — 所有 Worker 调用点传入 user_id**

- `_start_scan()`: `ScanWorker(folder_id, user_id=get_current_user_id())`
- `_run_album_worker()`: `AlbumWorker(operation, user_id=get_current_user_id(), **kwargs)`
- 导入流程：`ImportDialog` 透传 `user_id` 给 `ImportWorker`
- 删除/重命名等操作：在回调中写 `OperationLog`

### 5F: 角色权限控制

**11. `ui/main_window.py` — 管理员专属 UI**

- `_apply_role_permissions()` 方法：根据 `is_admin()` 控制
  - 工具栏"添加文件夹"按钮可见性
  - 状态栏显示当前用户（`当前用户: XXX（管理员/普通用户）`）
  - 新增"用户管理"按钮（仅管理员可见）

**12. `ui/thumbnail_grid.py` — 右键菜单权限**

- `_show_context_menu()` 中：`is_admin()` 才显示"删除记录"
- `keyPressEvent` 中：`is_admin()` 才响应 Delete 键

**13. 文件夹右键菜单权限**

- `_on_folder_context_menu()` 中：`is_admin()` 才显示"删除索引"

### 5G: 属性面板显示操作者

**14. `ui/property_panel.py`**

- 新增"导入者:"行，显示 `imported_by_name`
- `main_window.py` 的查询回调中关联 User 表获取用户名

### 5H: 用户管理对话框

**15. 新建 `ui/user_manage_dialog.py`（管理员专属）**

- 查看用户列表（用户名、显示名、角色、状态）
- 新增用户（用户名 + 显示名 + 角色选择）
- 停用/启用用户（软删除，不实际删除记录）
- **admin 不能降级其他 admin**（UI 上禁用角色下拉框或显示提示）
- 通过 `run_query` 异步操作数据库

### 5I: 用户自助修改显示名

**16. `ui/main_window.py` — 状态栏入口**

- 普通用户可在状态栏点击自己的名字，弹出简单对话框修改显示名
- 只能改 `display_name`，不能改 `username` 和 `role`
- 修改后通过 `run_query` 更新数据库和 `session` 单例

### 5J: 并发冲突检测

**17. 乐观锁机制**

- `Image` 模型新增 `version` 字段（整数，默认 1）
- 编辑图片分类时：查询时记录当前 version，保存时 `UPDATE ... WHERE id=? AND version=?`
- 如果 affected rows = 0（version 已被别人改过），弹窗提示"数据已被 XXX 修改，是否覆盖？"
- 用户选择"覆盖"：强制保存（更新 version+1）
- 用户选择"取消"：丢弃本次编辑

---

## 关键文件清单

| 文件 | 改动类型 |
|------|----------|
| `core/models.py` | 新增 User、OperationLog 模型；Image/Album 加 FK；Image 加 version |
| `core/database.py` | `_migrate_columns()` 追加迁移语句 |
| `core/session.py` | **新建** — 用户会话单例 |
| `config.py` | STORAGE_ROOT 改为环境变量 |
| `main.py` | 插入登录对话框 |
| `ui/login_dialog.py` | **新建** — 登录/注册二合一 |
| `ui/main_window.py` | 传 user_id 给 Worker、角色权限、状态栏用户、用户管理入口、显示名修改 |
| `ui/thumbnail_grid.py` | 右键菜单/快捷键权限控制 |
| `ui/property_panel.py` | 显示导入者 |
| `ui/user_manage_dialog.py` | **新建** — 管理员用户管理 |
| `core/import_worker.py` | 接受 user_id，记录操作日志 |
| `core/scanner.py` | 接受 user_id，记录操作日志 |
| `core/album_worker.py` | 接受 user_id，记录操作日志 |

## 实现顺序

1. 5A（模型+迁移）→ 5B（session）→ 5D（config）— 基础层，无 UI 变化
2. 5C（登录/注册对话框）— 第一个可见变化
3. 5F（角色权限）— 管理员/普通用户 UI 区分
4. 5E（Worker 传递 user_id）— 操作归属
5. 5G（属性面板）→ 5I（显示名修改）→ 5J（并发冲突）→ 5H（用户管理）— 完善功能

## 验证步骤

1. `py main.py` 启动 → 应显示注册界面（首次）或用户选择界面
2. 注册第一个用户 → 自动成为 admin → 状态栏显示"管理员"
3. 管理员可：添加文件夹、删除索引、删除记录（仅删记录不删文件）、管理用户
4. 创建普通用户 → 重新登录选择该用户
5. 普通用户不可：添加文件夹、删除索引、删除记录（这些按钮/菜单项不显示）
6. 普通用户可：浏览、搜索、导入、编辑分类、创建相册、修改自己的显示名
7. 导入图片后 → 属性面板显示"导入者: XXX"
8. 两个浏览器窗口同时编辑同一张图 → 后保存者看到冲突提示
9. 设置 `IG_STORAGE_ROOT` 环境变量为 UNC 路径 → 导入功能正常

---

## 关键架构决策

**Q1: 用户会话怎么存？**
A: 进程级内存单例（`core/session.py`）。无密码需持久化，每次启动都要选用户，最简方案。

**Q2: Worker 怎么获取 user_id？**
A: 构造函数参数。调用方在创建 Worker 时传入 `get_current_user_id()`，显式传递，不依赖全局变量。

**Q3: 登录流程怎么插？**
A: `main.py` 中 `init_db()` 之后、`MainWindow` 之前插入模态对话框。首次启动进入注册模式，后续进入选择模式。

**Q4: 管理员专属 UI 怎么控制？**
A: 在使用点导入 `is_admin()`（菜单构建、按钮可见性），不通过构造函数传角色。

**Q5: 数据库迁移策略？**
A: 扩展 `_migrate_columns()`，用 `CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`，幂等安全。不自动创建 admin，由注册界面处理。

**Q6: 用户被删除怎么办？**
A: 软删除（`is_active = False`），外键 `ON DELETE SET NULL` 兜底，历史记录保留。

**Q7: 并发编辑怎么处理？**
A: 乐观锁（`version` 字段）+ 保存时检查 version，冲突时弹窗让用户决定是否覆盖。

**Q8: admin 之间权限怎么管？**
A: admin 不能降级其他 admin。UI 上禁用其他 admin 的角色修改控件。
