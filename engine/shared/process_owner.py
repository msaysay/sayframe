"""Windows Job Object keeps FFmpeg children tied to the server lifetime."""
import ctypes,os
from ctypes import wintypes

class ProcessOwner:
    def __init__(self):
        self.handle=None;self.closed=False
        if os.name!='nt':return
        class Basic(ctypes.Structure):
            _fields_=[('processTime',ctypes.c_longlong),('jobTime',ctypes.c_longlong),('flags',wintypes.DWORD),('minWorking',ctypes.c_size_t),('maxWorking',ctypes.c_size_t),('active',wintypes.DWORD),('affinity',ctypes.c_size_t),('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_=[(n,ctypes.c_ulonglong) for n in ('readCount','writeCount','otherCount','readBytes','writeBytes','otherBytes')]
        class Extended(ctypes.Structure):
            _fields_=[('basic',Basic),('io',IO),('processMemory',ctypes.c_size_t),('jobMemory',ctypes.c_size_t),('peakProcess',ctypes.c_size_t),('peakJob',ctypes.c_size_t)]
        self.api=ctypes.WinDLL('kernel32',use_last_error=True)
        self.api.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR];self.api.CreateJobObjectW.restype=wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD];self.api.SetInformationJobObject.restype=wintypes.BOOL
        self.api.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE];self.api.AssignProcessToJobObject.restype=wintypes.BOOL
        self.api.CloseHandle.argtypes=[wintypes.HANDLE];self.api.CloseHandle.restype=wintypes.BOOL
        handle=self.api.CreateJobObjectW(None,None)
        if not handle:raise ctypes.WinError(ctypes.get_last_error())
        info=Extended();info.basic.flags=0x2000
        if not self.api.SetInformationJobObject(handle,9,ctypes.byref(info),ctypes.sizeof(info)):
            self.api.CloseHandle(handle);raise ctypes.WinError(ctypes.get_last_error())
        self.handle=handle
    def attach(self,process):
        if self.handle and not self.api.AssignProcessToJobObject(self.handle,int(process._handle)):
            error=ctypes.get_last_error()
            # Very short frame extractions can finish between Popen and Job
            # Object attachment. They cannot escape the server lifetime after
            # exit; still reject an attachment failure for any live process.
            if process.poll() is not None:return
            raise ctypes.WinError(error)
    def close(self):
        self.closed=True
        if self.handle:self.api.CloseHandle(self.handle);self.handle=None
    def __del__(self):self.close()
