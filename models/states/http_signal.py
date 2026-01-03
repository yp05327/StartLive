from PySide6.QtCore import QObject, Signal


class HttpSignalEmitter(QObject):
    startLive = Signal()
    stopLive = Signal()
    startLogin = Signal()
    logout = Signal()
    setTitle = Signal(str)
    setArea = Signal(str, str)
    exception = Signal(object)  # Signal(Exception)
