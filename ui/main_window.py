import json
import logging

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from core.models import Album, Folder, Image
from core.queries import get_distinct_classifications, parse_classify_key
from core.query_worker import abort_query, run_query
from core.scanner import ScanWorker
from core.session import get_current_user, get_current_user_id, is_admin
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
        self._pending_sidebar_query = (None, None)
        self._pending_search_query = (None, None)
        self._pending_detail_query = (None, None)
        self._detail_query_seq = 0  # 查询序列号，防止旧回调覆盖新数据

        self._setup_toolbar()
        self._setup_central_widget()
        self._setup_statusbar()
        self._load_sidebar_folders()

    def _setup_toolbar(self):
        toolbar = QToolBar()
        self.addToolBar(toolbar)

        self._btn_add = QPushButton("添加文件夹")
        self._btn_add.clicked.connect(self._on_add_folder)
        self._act_add = toolbar.addWidget(self._btn_add)

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

        toolbar.addSeparator()

        toolbar.addWidget(QLabel(" 缩略图: "))
        self._size_group = QButtonGroup(self)
        for size_key, label in [("small", "小"), ("medium", "中"), ("large", "大")]:
            btn = QRadioButton(label)
            btn.setProperty("size_key", size_key)
            self._size_group.addButton(btn)
            toolbar.addWidget(btn)
            if size_key == "medium":
                btn.setChecked(True)
        self._size_group.buttonClicked.connect(self._on_thumb_size_changed)

        toolbar.addSeparator()

        self._btn_zip = QPushButton("打包下载")
        self._btn_zip.setEnabled(False)
        self._btn_zip.clicked.connect(self._on_zip_download)
        toolbar.addWidget(self._btn_zip)

        toolbar.addSeparator()

        self._btn_users = QPushButton("用户管理")
        self._btn_users.clicked.connect(self._on_user_manage)
        self._act_users = toolbar.addWidget(self._btn_users)

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
        self.thumbnail_grid.load_finished.connect(self._on_thumb_load_finished)
        self.thumbnail_grid.selection_changed.connect(self._on_selection_changed)
        splitter.addWidget(self.thumbnail_grid)

        # 右侧属性面板
        self.property_panel = PropertyPanel()
        splitter.addWidget(self.property_panel)

        splitter.setSizes([200, 800, 250])

    def _on_thumb_size_changed(self, button):
        """缩略图尺寸切换"""
        size_key = button.property("size_key")
        if size_key:
            self.thumbnail_grid.set_thumb_size(size_key)

    def _on_thumb_load_finished(self, count: int, desc: str):
        """缩略图加载完成，更新状态栏"""
        if count > 0:
            self._statusbar.showMessage(f"{desc} (共{count}张)")
        else:
            self._statusbar.showMessage(f"{desc} (无图片)")

    def _on_selection_changed(self, count: int):
        """选中图片数量变化"""
        self._btn_zip.setEnabled(count > 0)

    def _on_zip_download(self):
        """打包下载选中图片"""
        image_ids = self.thumbnail_grid.get_selected_image_ids()
        if not image_ids:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存打包文件", "images.zip", "Zip 文件 (*.zip)"
        )
        if not file_path:
            return

        from core.zip_worker import ZipWorker
        from ui.thread_utils import stop_thread

        self._zip_thread = QThread()
        self._zip_worker = ZipWorker(image_ids, file_path)
        self._zip_worker.moveToThread(self._zip_thread)

        self._zip_worker.progress.connect(self._on_zip_progress)
        self._zip_worker.finished.connect(self._on_zip_finished)
        self._zip_worker.error.connect(self._on_zip_error)

        self._zip_thread.started.connect(self._zip_worker.run)
        self._zip_thread.start()
        self._btn_zip.setEnabled(False)
        self._statusbar.showMessage("正在打包...")

    def _on_zip_progress(self, current: int, total: int):
        self._statusbar.showMessage(f"打包中: {current}/{total}")

    def _on_zip_finished(self, path: str):
        self._statusbar.showMessage(f"打包完成: {path}")
        self._btn_zip.setEnabled(True)
        self._cleanup_zip_thread()

    def _on_zip_error(self, msg: str):
        self._statusbar.showMessage(f"打包出错: {msg}")
        self._btn_zip.setEnabled(True)
        self._cleanup_zip_thread()

    def _cleanup_zip_thread(self):
        if hasattr(self, "_zip_thread") and self._zip_thread:
            from ui.thread_utils import stop_thread
            stop_thread(self._zip_thread)
            self._zip_thread = None
            self._zip_worker = None

    def _create_sidebar(self) -> QWidget:
        from ui.accordion_sidebar import AccordionSidebar

        self._sidebar_accordion = AccordionSidebar()

        # 全部图片
        self._btn_all = QPushButton("查看全部图片")
        self._btn_all.clicked.connect(self._on_show_all)
        self._sidebar_accordion.add_section("全部图片", self._btn_all)

        # 索引文件夹
        self._folders_list = QListWidget()
        self._folders_list.itemClicked.connect(self._on_folder_clicked)
        self._folders_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._folders_list.customContextMenuRequested.connect(self._on_folder_context_menu)
        self._folders_section = self._sidebar_accordion.add_section("索引文件夹", self._folders_list)

        # 导入库
        self._btn_imported = QPushButton("查看已导入图片")
        self._btn_imported.clicked.connect(self._on_show_imported)
        self._sidebar_accordion.add_section("导入库", self._btn_imported)

        # 项目分类（保留 QTreeWidget 支持拖拽和重命名）
        self._classification_tree = QTreeWidget()
        self._classification_tree.setHeaderHidden(True)
        self._classification_tree.itemClicked.connect(self._on_classification_clicked)
        self._classification_tree.setEditTriggers(QTreeWidget.EditTrigger.DoubleClicked)
        self._classification_tree.itemChanged.connect(self._on_sidebar_item_changed)
        self._classification_tree.setAcceptDrops(True)
        self._classification_tree.setDropIndicatorShown(True)
        self._classification_tree.dragEnterEvent = self._on_tree_drag_enter
        self._classification_tree.dragMoveEvent = self._on_tree_drag_move
        self._classification_tree.dropEvent = self._on_tree_drop
        self._sidebar_accordion.add_section("项目分类", self._classification_tree)

        # 相册
        self._albums_list = QListWidget()
        self._albums_list.itemClicked.connect(self._on_album_clicked)
        self._sidebar_accordion.add_section("相册", self._albums_list)

        return self._sidebar_accordion

    def _setup_statusbar(self):
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._statusbar.showMessage("就绪")

        # 当前用户显示
        user = get_current_user()
        if user:
            role_text = "管理员" if user["role"] == "admin" else "普通用户"
            display = user.get("display_name") or user["username"]
            self._user_label = QLabel(f"  {user['username']} ({role_text}:{display})  ")
            self._user_label.setStyleSheet("padding: 0 8px;")
            self._user_label.mousePressEvent = self._on_user_label_clicked
            self._statusbar.addPermanentWidget(self._user_label)

        # 应用角色权限
        self._apply_role_permissions()

    def _apply_role_permissions(self):
        """根据当前用户角色控制 UI 元素可见性"""
        admin = is_admin()
        self._act_add.setVisible(admin)
        self._act_users.setVisible(admin)

    def _on_user_label_clicked(self, event):
        """点击状态栏用户名，修改显示名"""
        user = get_current_user()
        if not user:
            return
        from PySide6.QtWidgets import QInputDialog
        current_display = user.get("display_name") or user["username"]
        new_name, ok = QInputDialog.getText(
            self, "修改显示名", "显示名称:", text=current_display
        )
        if ok and new_name.strip():
            def update_name(db):
                from core.models import User
                u = db.get(User, user["id"])
                if u:
                    u.display_name = new_name.strip()
                    db.commit()
                    return True
                return False

            def on_done(result):
                if result:
                    from core.session import set_current_user
                    set_current_user(user["id"], user["username"], user["role"], new_name.strip())
                    role_text = "管理员" if user["role"] == "admin" else "普通用户"
                    self._user_label.setText(f"  {user['username']} ({role_text}:{new_name.strip()})  ")

            run_query(self, update_name, on_result=on_done)

    def _on_user_manage(self):
        """打开用户管理对话框"""
        from ui.user_manage_dialog import UserManageDialog
        dialog = UserManageDialog(self)
        dialog.exec()

    def _load_sidebar_folders(self):
        """从数据库加载侧边栏各区块内容（异步）"""
        worker, thread = self._pending_sidebar_query
        abort_query(thread, worker)
        worker, thread = run_query(self, self._query_sidebar_data, on_result=self._on_sidebar_data_loaded)
        self._pending_sidebar_query = (worker, thread)

    def _query_sidebar_data(self, db):
        """查询侧边栏数据（后台线程）"""
        folders = db.execute(select(Folder)).scalars().all()
        combos = get_distinct_classifications(db)
        albums = db.execute(select(Album)).scalars().all()
        return (folders, combos, albums)

    def _on_sidebar_data_loaded(self, data):
        """侧边栏数据加载完成（主线程更新 UI）"""
        folders, combos, albums = data

        # 索引文件夹
        self._folders_list.clear()
        for folder in folders:
            item = QListWidgetItem(folder.path)
            item.setData(Qt.ItemDataRole.UserRole, f"folder:{folder.id}")
            self._folders_list.addItem(item)

        # 项目分类（二级树）
        self._classification_tree.blockSignals(True)
        self._classification_tree.clear()
        tree: dict[str, set[str]] = {}
        for ptype, sname in combos:
            ptype = ptype or ""
            sname = sname or ""
            tree.setdefault(ptype, set())
            if sname:
                tree[ptype].add(sname)
        for ptype, snames in tree.items():
            type_item = QTreeWidgetItem(self._classification_tree, [ptype])
            type_item.setData(0, Qt.ItemDataRole.UserRole, f"ptype:{ptype}")
            type_item.setFlags(type_item.flags() | Qt.ItemFlag.ItemIsEditable)
            for sname in snames:
                style_item = QTreeWidgetItem(type_item, [sname])
                style_item.setData(
                    0, Qt.ItemDataRole.UserRole,
                    f"style:{ptype}|{sname}",
                )
                style_item.setFlags(style_item.flags() | Qt.ItemFlag.ItemIsEditable)
        self._classification_tree.blockSignals(False)
        self._classification_tree.expandAll()

        # 相册
        self._albums_list.clear()
        for album in albums:
            item = QListWidgetItem(album.name)
            item.setData(Qt.ItemDataRole.UserRole, f"album:{album.id}")
            self._albums_list.addItem(item)

    def _on_show_all(self):
        """查看全部图片"""
        self.thumbnail_grid.load_images()
        self._statusbar.showMessage("加载全部图片...")

    def _on_folder_clicked(self, item: QListWidgetItem):
        """索引文件夹点击"""
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or not data.startswith("folder:"):
            return
        folder_id = int(data.split(":")[1])
        self.thumbnail_grid.load_images(folder_id=folder_id)
        self._statusbar.showMessage("加载文件夹...")

    def _on_show_imported(self):
        """查看已导入图片"""
        self.thumbnail_grid.load_images(imported_only=True)
        self._statusbar.showMessage("加载导入库...")

    def _on_classification_clicked(self, item: QTreeWidgetItem, column: int):
        """项目分类树点击"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        if data.startswith("style:"):
            ptype, sname = parse_classify_key(data)
            self.thumbnail_grid.load_images(project_type=ptype, style_name=sname)
            self._statusbar.showMessage(f"加载 {ptype} / {sname}...")
        elif data.startswith("ptype:"):
            ptype = data[len("ptype:"):]
            self.thumbnail_grid.load_images(project_type=ptype)
            self._statusbar.showMessage(f"加载 {ptype}...")

    def _on_album_clicked(self, item: QListWidgetItem):
        """相册点击"""
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or not data.startswith("album:"):
            return
        album_id = int(data[len("album:"):])
        self.thumbnail_grid.load_images(album_id=album_id)
        self._statusbar.showMessage("加载相册...")

    def _on_sidebar_item_changed(self, item: QTreeWidgetItem, column: int):
        """侧边栏节点重命名"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        new_name = item.text(0).strip()
        if not new_name:
            return

        if data.startswith("ptype:"):
            old_ptype = data[len("ptype:"):]
            if new_name == old_ptype:
                return
            reply = QMessageBox.question(
                self, "确认重命名",
                f"将项目类型从「{old_ptype}」改为「{new_name}」",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._run_rename_query("ptype", old_ptype, new_name)
            else:
                self._load_sidebar_folders()
        elif data.startswith("style:"):
            ptype, old_sname = data[len("style:"):].split("|", 1)
            if new_name == old_sname:
                return
            reply = QMessageBox.question(
                self, "确认重命名",
                f"将风格从「{old_sname}」改为「{new_name}」",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._run_rename_query("style", old_sname, new_name, ptype)
            else:
                self._load_sidebar_folders()

    def _run_rename_query(self, rename_type: str, old_name: str, new_name: str, ptype: str = ""):
        """异步执行重命名"""
        def do_rename(db):
            if rename_type == "ptype":
                db.query(Image).filter(
                    Image.project_type == old_name
                ).update({Image.project_type: new_name})
            else:
                db.query(Image).filter(
                    Image.project_type == ptype,
                    Image.style_name == old_name,
                ).update({Image.style_name: new_name})
            db.commit()

        def on_done():
            self._statusbar.showMessage(f"已重命名: {old_name} → {new_name}")
            self._load_sidebar_folders()

        run_query(self, do_rename, on_finished=on_done)

    def _on_tree_drag_enter(self, event):
        """接受来自缩略图的拖拽"""
        if event.mimeData().hasFormat("application/x-image-ids"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def _on_tree_drag_move(self, event):
        """拖拽过程中高亮目标节点"""
        if event.mimeData().hasFormat("application/x-image-ids"):
            item = self._classification_tree.itemAt(event.position().toPoint())
            if item:
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if data and (data.startswith("ptype:") or data.startswith("style:")):
                    event.acceptProposedAction()
                    self._classification_tree.setCurrentItem(item)
                    return
            event.ignore()
        else:
            event.ignore()

    def _on_tree_drop(self, event):
        """处理拖拽放下"""
        if not event.mimeData().hasFormat("application/x-image-ids"):
            event.ignore()
            return

        item = self._classification_tree.itemAt(event.position().toPoint())
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
        folder_path = str(Path(folder_str))

        def check_and_add(db):
            existing = db.execute(
                select(Folder).where(Folder.path == folder_path)
            ).scalar_one_or_none()
            if existing:
                return None
            folder = Folder(path=folder_path)
            db.add(folder)
            db.commit()
            db.refresh(folder)
            return folder.id

        def on_result(folder_id):
            if folder_id is None:
                self._statusbar.showMessage(f"文件夹已存在: {folder_path}")
            else:
                self._start_scan(folder_id, folder_path)

        run_query(self, check_and_add, on_result=on_result)

    def _start_scan(self, folder_id: int, folder_path: str):
        """启动后台扫描"""
        self._statusbar.showMessage(f"正在扫描: {folder_path} ...")

        self._scan_thread = QThread()
        self._scan_worker = ScanWorker(folder_id, user_id=get_current_user_id())
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
        self.thumbnail_grid.load_images()

    def _on_scan_error(self, msg: str):
        self._statusbar.showMessage(f"扫描出错: {msg}")
        self._cleanup_scan_thread()

    def _cleanup_scan_thread(self):
        stop_thread(self._scan_thread)
        self._scan_thread = None
        self._scan_worker = None

    def _on_image_selected(self, image_id: int):
        """图片选中，更新属性面板（异步）"""
        # 取消旧查询
        worker, thread = self._pending_detail_query
        abort_query(thread, worker)

        # 递增序列号，确保只有最新回调执行
        self._detail_query_seq += 1
        current_seq = self._detail_query_seq

        def on_result(data):
            # 只有序列号匹配时才更新 UI
            if current_seq == self._detail_query_seq:
                self.property_panel.show_image_from_data(data)

        worker, thread = run_query(self, self._query_image_detail, image_id=image_id,
                  on_result=on_result)
        self._pending_detail_query = (worker, thread)

    def _query_image_detail(self, db, image_id: int):
        """查询图片详情（后台线程）"""
        from core.models import User
        image = db.get(Image, image_id)
        if not image:
            return None
        imported_by_name = "未知"
        if image.imported_by:
            user = db.get(User, image.imported_by)
            if user:
                imported_by_name = user.display_name or user.username
        return {
            "file_name": image.file_name,
            "file_path": image.file_path,
            "file_size": image.file_size,
            "width": image.width,
            "height": image.height,
            "format": image.format,
            "color_space": image.color_space,
            "created_at": image.created_at,
            "modified_at": image.modified_at,
            "exif_json": image.exif_json,
            "project_type": image.project_type,
            "style_name": image.style_name,
            "imported": image.imported,
            "imported_by_name": imported_by_name,
            "storage_path": image.storage_path,
            "thumb_path": image.thumb_path,
        }

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
        """搜索图片（异步）"""
        keyword = self._search_input.text().strip()
        if not keyword:
            return
        self._statusbar.showMessage(f"搜索 \"{keyword}\" ...")
        worker, thread = self._pending_search_query
        abort_query(thread, worker)
        worker, thread = run_query(self, self._query_search, keyword=keyword,
                  on_result=lambda results: self._on_search_results(keyword, results))
        self._pending_search_query = (worker, thread)

    def _query_search(self, db, keyword: str) -> list:
        """搜索查询（后台线程）"""
        from sqlalchemy import or_, text

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

        return results

    def _on_search_results(self, keyword: str, results: list):
        """搜索结果回调（主线程）"""
        self.thumbnail_grid.add_images_from_search(results)
        self._statusbar.showMessage(f"搜索 \"{keyword}\": 找到 {len(results)} 张图片")

    def _on_folder_context_menu(self, pos):
        """索引文件夹右键菜单"""
        item = self._folders_list.itemAt(pos)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or not data.startswith("folder:"):
            return

        menu = QMenu(self)
        if is_admin():
            action = menu.addAction("删除索引")
            triggered = menu.exec(self._folders_list.viewport().mapToGlobal(pos))
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
        elif action == "copy_path":
            self._on_copy_paths(image_ids)
        elif action == "open_in_explorer":
            self._on_open_in_explorer(image_ids)
        elif action == "delete_records":
            self._on_delete_records(image_ids)

    def _on_copy_paths(self, image_ids: list):
        """复制选中图片的文件路径到剪贴板"""
        def query_paths(db):
            images = db.query(Image.file_path).filter(Image.id.in_(image_ids)).all()
            return [img.file_path for img in images]

        def on_result(paths):
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText("\n".join(paths))
            self._statusbar.showMessage(f"已复制 {len(paths)} 个文件路径到剪贴板")

        run_query(self, query_paths, on_result=on_result)

    def _on_open_in_explorer(self, image_ids: list):
        """在资源管理器中打开第一个选中图片所在目录"""
        def query_path(db):
            img = db.query(Image.file_path).filter(Image.id == image_ids[0]).scalar()
            return img

        def on_result(file_path):
            if file_path:
                import subprocess
                subprocess.Popen(f'explorer /select,"{file_path}"')

        run_query(self, query_path, on_result=on_result)

    def _on_delete_records(self, image_ids: list):
        """从数据库删除选中图片记录（不删原文件）"""
        reply = QMessageBox.question(
            self, "确认删除",
            f"将从数据库中删除 {len(image_ids)} 条图片记录。\n"
            "原文件不会被删除。\n\n确定继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def delete_records(db):
            from core.models import OperationLog
            count = db.query(Image).filter(Image.id.in_(image_ids)).delete(synchronize_session=False)
            uid = get_current_user_id()
            if uid:
                log = OperationLog(user_id=uid, action="delete_records",
                                   target_desc=f"删除 {count} 条图片记录")
                db.add(log)
            db.commit()
            return count

        def on_done():
            self._statusbar.showMessage("已删除记录")
            self._load_sidebar_folders()
            self.thumbnail_grid.load_images()

        run_query(self, delete_records, on_finished=on_done)

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
        # 先查询当前 version，用于乐观锁
        def query_versions(db):
            imgs = db.query(Image.id, Image.version).filter(Image.id.in_(image_ids)).all()
            return {img.id: img.version for img in imgs}

        def on_versions(versions):
            self._run_album_worker("update_metadata", image_ids=image_ids,
                                   project_type=project_type,
                                   style_name=style_name, only_empty=only_empty,
                                   expected_versions=versions)

        run_query(self, query_versions, on_result=on_versions)

    def _on_import_images(self, image_ids: list):
        """导入图片到库"""
        from ui.import_dialog import ImportDialog
        dialog = ImportDialog(image_ids, self, user_id=get_current_user_id())
        dialog.import_finished.connect(self._on_import_finished)
        dialog.exec()

    def _on_import_finished(self):
        """导入完成回调"""
        self._load_sidebar_folders()
        self.thumbnail_grid.load_images(imported_only=True)
        self._statusbar.showMessage("导入完成")

    def _run_album_worker(self, operation: str, **kwargs):
        """运行 AlbumWorker"""
        from core.album_worker import AlbumWorker

        if hasattr(self, '_album_thread') and self._album_thread:
            stop_thread(self._album_thread)
            self._album_thread = None
            self._album_worker = None

        self._last_album_op = (operation, kwargs)

        self._album_thread = QThread()
        self._album_worker = AlbumWorker(operation, user_id=get_current_user_id(), **kwargs)
        self._album_worker.moveToThread(self._album_thread)

        self._album_worker.finished.connect(self._on_album_worker_finished)
        self._album_worker.error.connect(self._on_album_worker_error)
        self._album_worker.albums_changed.connect(self._load_sidebar_folders)
        self._album_worker.conflict_images.connect(self._on_conflict_images)

        self._album_thread.started.connect(self._album_worker.run)
        self._album_thread.start()

    def _on_album_worker_finished(self):
        self._statusbar.showMessage("操作完成")
        self._cleanup_album_thread()

    def _on_album_worker_error(self, msg: str):
        self._statusbar.showMessage(f"操作失败: {msg}")
        self._cleanup_album_thread()

    def _on_conflict_images(self, conflict_ids: list):
        """处理乐观锁冲突"""
        reply = QMessageBox.question(
            self, "数据冲突",
            f"有 {len(conflict_ids)} 张图片已被其他用户修改。\n是否强制覆盖？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            if hasattr(self, '_last_album_op'):
                operation, kwargs = self._last_album_op
                kwargs["force"] = True
                self._run_album_worker(operation, **kwargs)

    def _cleanup_album_thread(self):
        if hasattr(self, '_album_thread'):
            stop_thread(self._album_thread)
            self._album_thread = None
            self._album_worker = None

    def _refresh_sidebar(self):
        """刷新侧边栏"""
        self._load_sidebar_folders()
