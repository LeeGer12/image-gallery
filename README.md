# Image Gallery

面向室内设计公司的本地图库管理软件，支持局域网多用户共享浏览、标签管理和批量操作。

## 功能特性

- **文件夹索引**：添加本地文件夹，自动扫描入库，图片原地不动
- **缩略图浏览**：异步生成缩略图，网格展示，支持 JPG/PNG/WEBP/GIF/BMP/TIFF/HEIF/RAW
- **大图预览**：双击缩略图打开预览窗口，左右翻页，另存为
- **属性面板**：选中图片显示文件信息、尺寸、EXIF 元数据
- **中文搜索**：按文件名、项目类型、风格名模糊匹配
- **相册管理**：创建相册、批量添加图片、按相册浏览
- **二级分类**：项目类型 → 风格，侧边栏树形浏览，拖拽快速分类
- **导入模式**：选中图片按项目/类型/风格自动复制到 STORAGE_ROOT 目录
- **多用户共享**：基于 PostgreSQL，局域网内多客户端同时访问

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
python main.py
```

## 使用方法

1. 点击工具栏 **添加文件夹**，选择含图片的目录
2. 程序自动扫描并生成缩略图，左侧边栏显示文件夹
3. 点击缩略图查看属性，双击打开大图预览
4. 搜索框输入关键词搜索图片
5. 拖拽图片到侧边栏分类节点可快速分类，右键可添加到相册、导入到库
6. 侧边栏按二级分类树（项目类型→风格）或相册浏览，双击节点可重命名
7. 导入后可右键侧边栏删除索引（已导入图片保留）

## 项目结构

```
image-gallery/
├── core/              # 业务逻辑
│   ├── models.py      # ORM 模型（Folder, Image, Tag, Album）
│   ├── database.py    # 引擎、会话、全文搜索
│   ├── queries.py     # 共享查询（分类去重、键解析、标签格式化）
│   ├── scanner.py     # 文件夹扫描 Worker
│   ├── thumbnailer.py # 缩略图生成 Worker
│   ├── album_worker.py  # 相册 CRUD + 分类 + 索引删除 Worker
│   └── import_worker.py # 导入 Worker（复制文件+更新DB）
├── ui/                # 界面层
│   ├── main_window.py    # 主窗口三栏布局
│   ├── thumbnail_grid.py # 缩略图网格（多种过滤+右键菜单）
│   ├── property_panel.py # 属性面板
│   ├── image_viewer.py   # 大图预览（翻页、另存为）
│   ├── album_dialog.py   # 创建/编辑相册对话框
│   ├── batch_meta_dialog.py # 批量设置项目类型/风格
│   ├── import_dialog.py  # 导入对话框（含进度条）
│   └── thread_utils.py   # QThread 生命周期工具
├── utils/             # 工具函数
│   └── image_utils.py    # 格式判断、元数据读取、缩略图生成
├── assets/            # 静态资源
├── main.py            # 入口
├── config.py          # 全局配置
└── requirements.txt
```
