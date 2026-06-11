# Image Gallery

面向室内设计公司的本地图库管理软件，支持局域网多用户共享浏览、标签管理和批量操作。

## 技术栈

- GUI: PySide6
- 数据库: PostgreSQL + SQLAlchemy 2.0
- 图片处理: Pillow, rawpy, pillow-heif

## 快速开始

### 1. 安装依赖

需要 Python 3.11+：

```bash
pip install -r requirements.txt
```

### 2. 配置中枢电脑（只需一次）

找一台闲置电脑作为图库服务器，按 [docs/HUB_SETUP.md](docs/HUB_SETUP.md) 操作：

1. 安装 PostgreSQL（密码设为 `ImageGallery2026`）
2. 创建 `gallery` 用户和 `imagegallery` 数据库
3. 创建 `ImageGalleryStorage` 共享文件夹
4. 设置固定 IP（如 `192.168.1.100`）
5. 防火墙放行 5432 端口

### 3. 运行

```bash
py main.py
```

首次启动会弹出配置向导，输入中枢电脑的 IP 地址即可连接。以后再启动自动连接。

## 功能

- **图片浏览**：缩略图网格、无限滚动、大图预览、翻页
- **二级分类**：项目类型 → 风格，拖拽分类
- **相册管理**：创建相册、添加图片
- **导入管理**：复制文件到指定目录结构
- **全文搜索**：文件名、分类、EXIF 全文检索
- **多用户**：管理员/普通用户角色、操作归属、乐观锁并发控制
- **批量操作**：打包下载（保留目录结构）、批量设置分类

## 文档

- [CLAUDE.md](CLAUDE.md) — 项目规范（给 AI 看）
- [docs/HUB_SETUP.md](docs/HUB_SETUP.md) — 中枢电脑配置指南（给人看）
- [docs/DECISIONS.md](docs/DECISIONS.md) — 关键决策记录
- [docs/PLAN_TEMPLATE.md](docs/PLAN_TEMPLATE.md) — 计划模板
- [tests/TEST_RECORD.md](tests/TEST_RECORD.md) — Phase 1-4 测试记录
- [tests/TEST_PHASE5.md](tests/TEST_PHASE5.md) — Phase 5 测试记录
