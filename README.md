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

### 2. 配置数据库

在内网一台电脑上安装 PostgreSQL，创建数据库：

```sql
CREATE DATABASE imagegallery;
CREATE USER gallery WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE imagegallery TO gallery;

-- PostgreSQL 15+ 需要额外授权 public schema
GRANT ALL PRIVILEGES ON SCHEMA public TO gallery;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO gallery;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO gallery;
```

### 3. 配置环境变量

```bash
set IG_DB_HOST=192.168.1.100
set IG_DB_PORT=5432
set IG_DB_NAME=imagegallery
set IG_DB_USER=gallery
set IG_DB_PASSWORD=your_password
```

### 4. 运行

```bash
py main.py
```

## 文档

- [CLAUDE.md](CLAUDE.md) — Claude 项目规范
- [docs/DECISIONS.md](docs/DECISIONS.md) — 关键决策记录
- [docs/PLAN_TEMPLATE.md](docs/PLAN_TEMPLATE.md) — 计划模板
