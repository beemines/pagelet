"""Modern Windows Recycle Bin only; never fall back to permanent deletion."""
from pathlib import Path
import os
import site
import sys
import threading

_loaded=False
_load_lock=threading.Lock()


def recycle_file(path):
    global _loaded
    if os.name!='nt' or sys.getwindowsversion().major<10:
        raise OSError('需要 Windows 10 或更新版本的回收站支持。')
    with _load_lock:
        if not _loaded:
            site.addsitedir(str(Path(__file__).resolve().parent/'vendor'))
            _loaded=True
    import pythoncom
    from win32com.shell import shell, shellcon
    from win32com.server.exception import COMException
    from send2trash.win.IFileOperationProgressSink import FileOperationProgressSink

    class RecycleOnlySink(FileOperationProgressSink):
        def PreDeleteItem(self, flags, item):
            if not flags & shellcon.TSF_DELETE_RECYCLE_IF_POSSIBLE:
                raise COMException(desc='该位置不支持回收站，操作已取消。', scode=-2147467259)
            return 0

    pythoncom.CoInitialize()
    try:
        operation=pythoncom.CoCreateInstance(shell.CLSID_FileOperation,None,pythoncom.CLSCTX_ALL,shell.IID_IFileOperation)
        operation.SetOperationFlags(shellcon.FOF_NOCONFIRMATION|shellcon.FOF_NOERRORUI|shellcon.FOF_SILENT|
                                    shellcon.FOFX_EARLYFAILURE|0x20000000|0x00080000)
        implementation=RecycleOnlySink()
        sink=pythoncom.WrapObject(implementation,shell.IID_IFileOperationProgressSink)
        item=shell.SHCreateItemFromParsingName(str(path),None,shell.IID_IShellItem)
        operation.DeleteItem(item,sink)
        result=operation.PerformOperations()
        if result or operation.GetAnyOperationsAborted():
            raise OSError('无法移入回收站，操作已取消。')
    finally:
        pythoncom.CoUninitialize()
