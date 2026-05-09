from PySide6.QtCore import QThread, QObject


def run_worker_in_thread(worker: QObject, parent: QObject,
                         started_slot=None, finished_slot=None,
                         error_slot=None, custom_signals: dict | None = None) -> QThread:
    """将 Worker 挂到新 QThread 并启动，返回 QThread 引用。"""
    thread = QThread(parent)
    worker.moveToThread(thread)

    if started_slot:
        worker.finished.connect(started_slot)
    if error_slot:
        worker.error.connect(error_slot)
    if custom_signals:
        for signal, slot in custom_signals.items():
            signal.connect(slot)

    thread.started.connect(worker.run)
    thread.start()
    return thread


def stop_thread(thread: QThread | None, timeout: int = 3000):
    """安全停止 QThread：quit + wait，引用由调用方负责置 None。"""
    if thread and thread.isRunning():
        thread.quit()
        thread.wait(timeout)
