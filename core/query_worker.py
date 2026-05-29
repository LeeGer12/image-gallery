import logging

from PySide6.QtCore import QObject, QThread, Signal

from core.database import SessionLocal

logger = logging.getLogger(__name__)


class _MainThreadBridge(QObject):
    """主线程信号桥：接收工作线程的信号，转发为直接调用，确保回调在主线程执行。"""

    _sig_result = Signal(object)
    _sig_error = Signal(str)

    def __init__(self, on_result=None, on_error=None):
        super().__init__()
        if on_result:
            self._sig_result.connect(on_result)
        if on_error:
            self._sig_error.connect(on_error)


class QueryWorker(QObject):
    """通用后台查询 Worker，在 QThread 中执行 DB 操作。"""

    result_ready = Signal(object)
    error = Signal(str)
    finished = Signal()

    def __init__(self, query_func, *args, **kwargs):
        super().__init__()
        self._query_func = query_func
        self._args = args
        self._kwargs = kwargs
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            self.finished.emit()
            return
        db = SessionLocal()
        try:
            result = self._query_func(db, *self._args, **self._kwargs)
            if not self._cancelled:
                self.result_ready.emit(result)
            self.finished.emit()
        except Exception as e:
            if not self._cancelled:
                logger.error("QueryWorker error: %s", e)
                self.error.emit(str(e))
            self.finished.emit()
        finally:
            db.close()


def run_query(parent, query_func, on_result=None, on_error=None, on_finished=None,
              *args, **kwargs):
    """便捷函数：创建 QueryWorker + QThread，自动管理生命周期。

    Args:
        parent: 父对象（用于线程生命周期管理）
        query_func: 查询函数，签名 func(db, *args, **kwargs) -> Any
        on_result: 结果回调 on_result(result)
        on_error: 错误回调 on_error(msg)
        on_finished: 完成回调（无论成功失败都会调用）
    """
    thread = QThread(parent)
    worker = QueryWorker(query_func, *args, **kwargs)
    worker.moveToThread(thread)

    # 通过主线程 QObject 的信号中转，确保回调在主线程执行
    bridge = _MainThreadBridge(on_result, on_error)
    bridge.setParent(parent)  # bridge 在主线程，parent 也在主线程
    worker.result_ready.connect(bridge._sig_result)
    worker.error.connect(bridge._sig_error)

    # cleanup 在 thread.finished 时执行
    def cleanup():
        bridge.deleteLater()
        worker.deleteLater()
        thread.deleteLater()

    thread.finished.connect(cleanup)

    if on_finished:
        worker.finished.connect(on_finished)
    # worker.finished 触发 thread.quit，thread 退出后触发 cleanup
    worker.finished.connect(thread.quit)

    thread.started.connect(worker.run)
    thread.start()
    return worker, thread


def abort_query(thread: QThread | None, worker: QueryWorker | None):
    """中止正在运行的查询（异步，不阻塞主线程）"""
    if not thread and not worker:
        return
    try:
        if worker:
            worker.cancel()
        if thread:
            if thread.isRunning():
                thread.quit()
                # 不调用 thread.wait()，避免阻塞主线程
                # 由 cleanup 闭包负责 deleteLater
            else:
                # 线程未启动或已结束时，手动清理
                if worker:
                    worker.deleteLater()
                thread.deleteLater()
    except RuntimeError:
        # C++ 对象已被 cleanup 闭包的 deleteLater() 销毁
        pass
