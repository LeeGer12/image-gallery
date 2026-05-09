import json
import logging

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.database import SessionLocal
from core.models import Album, Folder, Image
from core.queries import get_distinct_classifications, parse_classify_key
from core.scanner import ScanWorker
from ui.image_viewer import ImageViewerDialog
from ui.property_panel import PropertyPanel
from ui.thumbnail_grid import ThumbnailGrid
from ui.thread_utils import stop_thread
from sqlalchemy import func, select

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Gallery")
        self.setMinimumSize(1200, 700)

        self._scan_thread: QThread | None = None
        self._scan_worker: ScanWorker | None = None

        self._setup_toolbar()
        self._setup_central_widget()
        self._setup_statusbar()
        self._load_sidebar_folders()

    def _setup_toolbar(self):
        toolbar = QToolBar()
        self.addToolBar(toolbar)

        btn_add = QPushButton("添加文件夹")
        btn_add.clicked.connect(self._on_add_folder)
        toolbar.addWidget(btn_add)

        btn_new_album = QPushButton("新建相册")
        btn_new_album.clicked.connect(self._on_create_album)
        toolbar.addWidget(btn_new_album)

        toolbar.addSeparator()

        toolbar.addWidget(QLabel(" 搜索: "))
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("输入关键词...")
        self._search_input.setMaximumWidth(250)
        self._search_input.returnPressed.connect(self._on_search)
        toolbar.addWidget(self._search_input)

        btn_search = QPushButton("搜索")
        btn_search.clicked.connect(self._on_search)
        toolbar.addWidget(btn_search)

    def _setup_central_widget(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # 左侧边栏
        self.sidebar = self._create_sidebar()
        splitter.addWidget(self.sidebar)

        # 中间缩略图网格
        self.thumbnail_grid = ThumbnailGrid()
        self.thumbnail_grid.image_selected.connect(self._on_image_selected)
        self.thumbnail_grid.image_double_clicked.connect(self._on_image_double_clicked)
        self.thumbnail_grid.context_action.connect(self._on_context_action)
        splitter.addWidget(self.thumbnail_grid)

        # 右侧属性面板
        self.property_panel = PropertyPanel()
        splitter.addWidget(self.property_panel)

        splitter.setSizes([200, 800, 250])

    def _create_sidebar(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.itemClicked.connect(self._on_sidebar_clicked)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_sidebar_context_menu)
        self._tree.setEditTriggers(QTreeWidget.EditTrigger.DoubleClicked)
        self._tree.itemChanged.connect(self._on_sidebar_item_changed)
        self._tree.setAcceptDrops(True)
        self._tree.setDropIndicatorShown(True)
        self._tree.dragEnterEvent = self._on_tree_drag_enter
        self._tree.dragMoveEvent = self._on_tree_drag_move
        self._tree.dropEvent = self._on_tree_drop

        layout.addWidget(self._tree)
        return widget

    def _setup_statusbar(self):
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._statusbar.showMessage("就绪")

    def _load_sidebar_folders(self):
        """从数据库加载侧边栏节点"""
        self._tree.blockSignals(True)
        self._tree.clear()

        root = QTreeWidgetItem(self._tree, ["全部图片"])
        root.setData(0, Qt.ItemDataRole.UserRole, "all")

        # 索引文件夹
        folders_node = QTreeWidgetItem(root, ["索引文件夹"])
        folders_node.setData(0, Qt.ItemDataRole.UserRole, "folders_root")

        db = SessionLocal()
        try:
            folders = db.execute(select(Folder)).scalars().all()
            for folder in folders:
                item = QTreeWidgetItem(folders_node, [folder.path])
                item.setData(0, Qt.ItemDataRole.UserRole, f"folder:{folder.id}")

            # 导入库
            imported_node = QTreeWidgetItem(root, ["导入库"])
            imported_node.setData(0, Qt.ItemDataRole.UserRole, "imported")

            # 项目分类（二级树：项目类型 → 风格）
            projects_node = QTreeWidgetItem(root, ["项目分类"])
            projects_node.setData(0, Qt.ItemDataRole.UserRole, "projects_root")

            combos = get_distinct_classifications(db)

            # 构建嵌套 dict: {ptype: set(sname)}
            tree: dict[str, set[str]] = {}
            for ptype, sname in combos:
                ptype = ptype or ""
                sname = sname or ""
                tree.setdefault(ptype, set())
                if sname:
                    tree[ptype].add(sname)

            for ptype, snames in tree.items():
                type_item = QTreeWidgetItem(projects_node, [ptype])
                type_item.setData(0, Qt.ItemDataRole.UserRole, f"ptype:{ptype}")
                type_item.setFlags(type_item.flags() | Qt.ItemFlag.ItemIsEditable)
                for sname in snames:
                    style_item = QTreeWidgetItem(type_item, [sname])
                    style_item.setData(
                        0, Qt.ItemDataRole.UserRole,
                        f"style:{ptype}|{sname}",
                    )
                    style_item.setFlags(style_item.flags() | Qt.ItemFlag.ItemIsEditable)

            # 相册
            albums_node = QTreeWidgetItem(root, ["相册"])
            albums_node.setData(0, Qt.ItemDataRole.UserRole, "albums_root")
            albums = db.execute(select(Album)).scalars().all()
            for album in albums:
                item = QTreeWidgetItem(albums_node, [album.name])
                item.setData(0, Qt.ItemDataRole.UserRole, f"album:{album.id}")

            # 标签（占位）
            tags_node = QTreeWidgetItem(root, ["标签"])
            tags_node.setData(0, Qt.ItemDataRole.UserRole, "tags_root")
        finally:
            db.close()

        self._tree.blockSignals(False)
        self._tree.expandAll()

    def _on_sidebar_clicked(self, item: QTreeWidgetItem, column: int):
        """侧边栏节点点击"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is None:
            return

        # 分类根节点仅展开/折叠，不加载图片
        if data in ("folders_root", "projects_root", "albums_root", "tags_root"):
            return

        db = SessionLocal()
        try:
            if data == "all":
                self.thumbnail_grid.load_images(db, folder_id=None)
                total = db.query(func.count(Image.id)).scalar() or 0
                self._statusbar.showMessage(f"显示全部图片 (共{total}张)")
            elif data.startswith("folder:"):
                folder_id = int(data.split(":")[1])
                self.thumbnail_grid.load_images(db, folder_id=folder_id)
                folder = db.get(Folder, folder_id)
                if folder:
                    count = db.query(func.count(Image.id)).filter(
                        Image.folder_id == folder_id
                    ).scalar() or 0
                    self._statusbar.showMessage(
                        f"显示文件夹: {folder.path} ({count}张)"
                    )
            elif data == "imported":
                self.thumbnail_grid.load_images(db, imported_only=True)
                count = db.query(func.count(Image.id)).filter(
                    Image.imported == True
                ).scalar() or 0
                self._statusbar.showMessage(f"显示导入库图片 (共{count}张)")
            elif data.startswith("style:"):
                ptype, sname = parse_classify_key(data)
                self.thumbnail_grid.load_images(
                    db, project_type=ptype, style_name=sname,
                )
                count = db.query(func.count(Image.id)).filter(
                    Image.project_type == ptype,
                    Image.style_name == sname,
                ).scalar() or 0
                label = f"{ptype} / {sname}"
                self._statusbar.showMessage(f"{label} ({count}张)")
            elif data.startswith("ptype:"):
                ptype = data[len("ptype:"):]
                self.thumbnail_grid.load_images(
                    db, project_type=ptype,
                )
                count = db.query(func.count(Image.id)).filter(
                    Image.project_type == ptype,
                ).scalar() or 0
                self._statusbar.showMessage(f"{ptype} ({count}张)")
            elif data.startswith("album:"):
                album_id = int(data[len("album:"):])
                self.thumbnail_grid.load_images(db, album_id=album_id)
                album = db.get(Album, album_id)
                name = album.name if album else "未知"
                count = len(album.images) if album else 0
                self._statusbar.showMessage(f"相册: {name} ({count}张)")
        finally:
            db.close()

    def _on_sidebar_item_changed(self, item: QTreeWidgetItem, column: int):
        """侧边栏节点重命名"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        new_name = item.text(0).strip()
        if not new_name:
            return

        # 解析节点类型和旧值
        if data.startswith("ptype:"):
            old_ptype = data[len("ptype:"):]
            if new_name == old_ptype:
                return
            db = SessionLocal()
            try:
                count = db.query(func.count(Image.id)).filter(
                    Image.project_type == old_ptype
                ).scalar() or 0
                reply = QMessageBox.question(
                    self, "确认重命名",
                    f"将 {count} 张图片的项目类型从「{old_ptype}」改为「{new_name}」",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    db.query(Image).filter(
                        Image.project_type == old_ptype
                    ).update({Image.project_type: new_name})
                    db.commit()
                    self._statusbar.showMessage(f"已重命名: {old_ptype} → {new_name}")
                    self._load_sidebar_folders()
                else:
                    # 用户取消，恢复原名
                    self._load_sidebar_folders()
            finally:
                db.close()
        elif data.startswith("style:"):
            ptype, old_sname = data[len("style:"):].split("|", 1)
            if new_name == old_sname:
                return
            db = SessionLocal()
            try:
                count = db.query(func.count(Image.id)).filter(
                    Image.project_type == ptype,
                    Image.style_name == old_sname,
                ).scalar() or 0
                reply = QMessageBox.question(
                    self, "确认重命名",
                    f"将 {count} 张图片的风格从「{old_sname}」改为「{new_name}」",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    db.query(Image).filter(
                        Image.project_type == ptype,
                        Image.style_name == old_sname,
                    ).update({Image.style_name: new_name})
                    db.commit()
                    self._statusbar.showMessage(f"已重命名: {old_sname} → {new_name}")
                    self._load_sidebar_folders()
                else:
                    # 用户取消，恢复原名
                    self._load_sidebar_folders()
            finally:
                db.close()

    def _on_tree_drag_enter(self, event):
        """接受来自缩略图的拖拽"""
        if event.mimeData().hasFormat("application/x-image-ids"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def _on_tree_drag_move(self, event):
        """拖拽过程中高亮目标节点"""
        if event.mimeData().hasFormat("application/x-image-ids"):
            item = self._tree.itemAt(event.position().toPoint())
            if item:
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if data and (data.startswith("ptype:") or data.startswith("style:")):
                    event.acceptProposedAction()
                    self._tree.setCurrentItem(item)
                    return
            event.ignore()
        else:
            event.ignore()

    def _on_tree_drop(self, event):
        """处理拖拽放下"""
        if not event.mimeData().hasFormat("application/x-image-ids"):
            event.ignore()
            return

        item = self._tree.itemAt(event.position().toPoint())
        if not item:
            event.ignore()
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            event.ignore()
            return

        # 解析目标分类
        project_type = ""
        style_name = ""
        if data.startswith("style:"):
            ptype, sname = data[len("style:"):].split("|", 1)
            project_type = ptype
            style_name = sname
        elif data.startswith("ptype:"):
            project_type = data[len("ptype:"):]
        else:
            event.ignore()
            return

        # 解析图片 ID
        try:
            raw = event.mimeData().data("application/x-image-ids").data()
            image_ids = json.loads(raw)
        except Exception:
            event.ignore()
            return

        if not image_ids:
            event.ignore()
            return

        # 执行分类
        self._run_album_worker(
            "quick_classify",
            image_ids=image_ids,
            project_type=project_type,
            style_name=style_name,
        )

        event.acceptProposedAction()
        self._statusbar.showMessage(
            f"已将 {len(image_ids)} 张图片分类到: {project_type}"
            + (f" / {style_name}" if style_name else "")
        )

    def _on_add_folder(self):
        """添加文件夹"""
        folder_str = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if not folder_str:
            return

        from pathlib import Path

        folder_path = Path(folder_str)

        db = SessionLocal()
        try:
            existing = db.execute(
                select(Folder).where(Folder.path == str(folder_path))
            ).scalar_one_or_none()
            if existing:
                self._statusbar.showMessage(f"文件夹已存在: {folder_path}")
                return

            folder = Folder(path=str(folder_path))
            db.add(folder)
            db.commit()
            db.refresh(folder)
            folder_id = folder.id
        finally:
            db.close()

        self._start_scan(folder_id, str(folder_path))

    def _start_scan(self, folder_id: int, folder_path: str):
        """启动后台扫描"""
        self._statusbar.showMessage(f"正在扫描: {folder_path} ...")

        self._scan_thread = QThread()
        self._scan_worker = ScanWorker(folder_id)
        self._scan_worker.moveToThread(self._scan_thread)

        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.error.connect(self._on_scan_error)

        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_thread.start()

    def _on_scan_progress(self, current: int, total: int):
        self._statusbar.showMessage(f"扫描中: {current}/{total}")

    def _on_scan_finished(self):
        self._statusbar.showMessage("扫描完成")
        self._cleanup_scan_thread()
        self._load_sidebar_folders()

        db = SessionLocal()
        try:
            self.thumbnail_grid.load_images(db, folder_id=None)
        finally:
            db.close()

    def _on_scan_error(self, msg: str):
        self._statusbar.showMessage(f"扫描出错: {msg}")
        self._cleanup_scan_thread()

    def _cleanup_scan_thread(self):
        stop_thread(self._scan_thread)
        self._scan_thread = None
        self._scan_worker = None

    def _on_image_selected(self, image_id: int):
        """图片选中，更新属性面板"""
        db = SessionLocal()
        try:
            self.property_panel.show_image(image_id, db)
        finally:
            db.close()

    def _on_image_double_clicked(self, image_id: int):
        """双击图片，打开大图预览"""
        image_ids = self.thumbnail_grid.get_all_image_ids()
        if not image_ids:
            return
        try:
            current_index = image_ids.index(image_id)
        except ValueError:
            current_index = 0

        viewer = ImageViewerDialog(image_ids, current_index, self)
        viewer.exec()

    def _on_search(self):
        """搜索图片：ILIKE 中文子串匹配 + 全文搜索补充"""
        keyword = self._search_input.text().strip()
        if not keyword:
            return

        from sqlalchemy import or_, text

        db = SessionLocal()
        try:
            terms = keyword.split()
            conditions = []
            for term in terms:
                pattern = f"%{term}%"
                conditions.append(Image.file_name.ilike(pattern))
                conditions.append(Image.project_type.ilike(pattern))
                conditions.append(Image.style_name.ilike(pattern))

            stmt = (
                select(Image)
                .where(or_(*conditions))
                .order_by(Image.id.desc())
                .limit(200)
            )
            results = db.execute(stmt).scalars().all()

            if not results and len(terms) == 1:
                tsquery = " & ".join(terms)
                try:
                    stmt_fts = (
                        select(Image)
                        .where(text("search_vector @@ to_tsquery('simple', :q)"))
                        .order_by(text("ts_rank(search_vector, to_tsquery('simple', :q)) DESC"))
                        .params(q=tsquery)
                        .limit(200)
                    )
                    results = db.execute(stmt_fts).scalars().all()
                except Exception:
                    pass

            self.thumbnail_grid.clear()
            for img in results:
                self.thumbnail_grid.add_image_item(img)

            self._statusbar.showMessage(f"搜索 \"{keyword}\": 找到 {len(results)} 张图片")
        except Exception as e:
            logger.error("搜索出错: %s", e)
            self._statusbar.showMessage(f"搜索出错: {e}")
        finally:
            db.close()

    def _on_sidebar_context_menu(self, pos):
        """侧边栏右键菜单"""
        item = self._tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or not data.startswith("folder:"):
            return

        menu = QMenu(self)
        action = menu.addAction("删除索引")
        triggered = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if triggered == action:
            folder_id = int(data.split(":")[1])
            self._on_delete_folder(folder_id)

    def _on_delete_folder(self, folder_id: int):
        """删除索引文件夹"""
        reply = QMessageBox.question(
            self, "确认删除索引",
            "将删除该文件夹的索引记录和未导入的图片记录。\n"
            "已导入的图片会保留（可在导入库中查看）。\n"
            "原文件不会被删除。\n\n确定继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._run_album_worker("delete_folder", folder_id=folder_id)

    def _on_context_action(self, action: str, image_ids: list):
        """右键菜单动作分发"""
        if action == "new_album":
            self._on_create_album_for_images(image_ids)
        elif action.startswith("add_to_album:"):
            album_id = int(action.split(":")[1])
            self._on_add_to_album(album_id, image_ids)
        elif action == "set_metadata":
            self._on_set_metadata(image_ids)
        elif action == "import":
            self._on_import_images(image_ids)

    def _on_create_album(self):
        """工具栏新建相册"""
        from ui.album_dialog import AlbumDialog
        dialog = AlbumDialog(self)
        if dialog.exec() != AlbumDialog.DialogCode.Accepted:
            return
        name, description = dialog.get_data()
        self._run_album_worker("create", name=name, description=description)

    def _on_create_album_for_images(self, image_ids: list):
        """新建相册并添加选中图片"""
        from ui.album_dialog import AlbumDialog
        dialog = AlbumDialog(self)
        if dialog.exec() != AlbumDialog.DialogCode.Accepted:
            return
        name, description = dialog.get_data()
        self._run_album_worker("create", name=name, description=description,
                               image_ids=image_ids)

    def _on_add_to_album(self, album_id: int, image_ids: list):
        """添加图片到指定相册"""
        self._run_album_worker("add_images", album_id=album_id,
                               image_ids=image_ids)

    def _on_set_metadata(self, image_ids: list):
        """批量设置项目类型/风格"""
        from ui.batch_meta_dialog import BatchMetaDialog
        dialog = BatchMetaDialog(image_ids, self)
        if dialog.exec() != BatchMetaDialog.DialogCode.Accepted:
            return
        project_type, style_name, only_empty = dialog.get_data()
        if not project_type and not style_name:
            return
        self._run_album_worker("update_metadata", image_ids=image_ids,
                               project_type=project_type,
                               style_name=style_name, only_empty=only_empty)

    def _on_import_images(self, image_ids: list):
        """导入图片到库"""
        from ui.import_dialog import ImportDialog
        dialog = ImportDialog(image_ids, self)
        dialog.import_finished.connect(self._on_import_finished)
        dialog.exec()

    def _on_import_finished(self):
        """导入完成回调"""
        self._load_sidebar_folders()
        db = SessionLocal()
        try:
            self.thumbnail_grid.load_images(db, imported_only=True)
        finally:
            db.close()
        self._statusbar.showMessage("导入完成")

    def _run_album_worker(self, operation: str, **kwargs):
        """运行 AlbumWorker"""
        from core.album_worker import AlbumWorker

        if hasattr(self, '_album_thread') and self._album_thread:
            stop_thread(self._album_thread)
            self._album_thread = None
            self._album_worker = None

        self._album_thread = QThread()
        self._album_worker = AlbumWorker(operation, **kwargs)
        self._album_worker.moveToThread(self._album_thread)

        self._album_worker.finished.connect(self._on_album_worker_finished)
        self._album_worker.error.connect(self._on_album_worker_error)
        self._album_worker.albums_changed.connect(self._load_sidebar_folders)

        self._album_thread.started.connect(self._album_worker.run)
        self._album_thread.start()

    def _on_album_worker_finished(self):
        self._statusbar.showMessage("操作完成")
        self._cleanup_album_thread()

    def _on_album_worker_error(self, msg: str):
        self._statusbar.showMessage(f"操作失败: {msg}")
        self._cleanup_album_thread()

    def _cleanup_album_thread(self):
        if hasattr(self, '_album_thread'):
            stop_thread(self._album_thread)
            self._album_thread = None
            self._album_worker = None

    def _refresh_sidebar(self):
        """刷新侧边栏"""
        self._load_sidebar_folders()
