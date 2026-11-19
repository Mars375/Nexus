"""A Windows job object around a run's process tree (spec 2026-11-13, §4.2). Windows only.

An anonymous job, its handle not inheritable (no process of the run can open or hold it), whose
only limit is `KILL_ON_JOB_CLOSE`: no breakaway, and if the server dies the system closes the
handle and kills what is left. The process starts suspended and is resumed only once in the job;
any error before that kills it (fail closed). `ctypes` only; imported lazily under Windows.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import subprocess
import threading
import time

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

CREATE_SUSPENDED, TH32CS_SNAPTHREAD = 0x00000004, 0x00000004
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, POLL = 0x00002000, 0.05  # POLL: seconds between job reads
EXTENDED_LIMIT_INFORMATION, BASIC_ACCOUNTING_INFORMATION = 9, 1  # JOBOBJECTINFOCLASS
PROCESS_TERMINATE, PROCESS_SET_QUOTA, THREAD_SUSPEND_RESUME = 0x0001, 0x0100, 0x0002
INVALID_HANDLE_VALUE, RESUME_FAILED = ctypes.c_void_p(-1).value, 0xFFFFFFFF
_I64, _SIZE, _DW, _H, _P = ctypes.c_int64, ctypes.c_size_t, wt.DWORD, wt.HANDLE, ctypes.c_void_p


def _fields(names: str, kind) -> list:
    return [(name, kind) for name in names.split()]


class _BasicLimit(ctypes.Structure):
    _fields_ = [*_fields("PerProcessUserTimeLimit PerJobUserTimeLimit", _I64), ("LimitFlags", _DW),
                *_fields("MinimumWorkingSetSize MaximumWorkingSetSize", _SIZE),
                ("ActiveProcessLimit", _DW), ("Affinity", _SIZE),
                *_fields("PriorityClass SchedulingClass", _DW)]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimit),
                *_fields("ReadOps WriteOps OtherOps ReadBytes WriteBytes OtherBytes",
                         ctypes.c_uint64),  # IO_COUNTERS
                *_fields("ProcessMemoryLimit JobMemoryLimit PeakProcessMemoryUsed "
                         "PeakJobMemoryUsed", _SIZE)]


class _Accounting(ctypes.Structure):
    _fields_ = [*_fields("TotalUserTime TotalKernelTime ThisPeriodTotalUserTime "
                         "ThisPeriodTotalKernelTime", _I64),
                *_fields("TotalPageFaultCount TotalProcesses ActiveProcesses "
                         "TotalTerminatedProcesses", _DW)]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [*_fields("dwSize cntUsage th32ThreadID th32OwnerProcessID", _DW),
                *_fields("tpBasePri tpDeltaPri", wt.LONG), ("dwFlags", _DW)]


for _name, _result, _args in (
    ("CreateJobObjectW", _H, [_P, wt.LPCWSTR]),
    ("SetInformationJobObject", wt.BOOL, [_H, ctypes.c_int, _P, _DW]),
    ("QueryInformationJobObject", wt.BOOL, [_H, ctypes.c_int, _P, _DW, _P]),
    ("OpenProcess", _H, [_DW, wt.BOOL, _DW]),
    ("AssignProcessToJobObject", wt.BOOL, [_H, _H]),
    ("CreateToolhelp32Snapshot", _H, [_DW, _DW]),
    ("Thread32First", wt.BOOL, [_H, _P]),
    ("Thread32Next", wt.BOOL, [_H, _P]),
    ("OpenThread", _H, [_DW, wt.BOOL, _DW]),
    ("ResumeThread", _DW, [_H]),
    ("TerminateJobObject", wt.BOOL, [_H, wt.UINT]),
    ("CloseHandle", wt.BOOL, [_H]),
):
    getattr(_k32, _name).restype = _result
    getattr(_k32, _name).argtypes = _args


class Job:
    """The handle of a run's job, kept on the `Popen` as `nexus_job`. Closed once, under the lock,
    only after a confirmed stop (a closed handle value may be reused by the system)."""

    def __init__(self, handle: int) -> None:
        self.handle: int | None = handle
        self.lock = threading.Lock()


def _check(ok: object, what: str) -> None:
    if not ok:
        error = ctypes.WinError(ctypes.get_last_error())
        raise OSError(error.errno, f"{what} : {error.strerror}")


def _close(handle: int) -> None:
    _k32.CloseHandle(handle)


def _create_job() -> int:
    job = _k32.CreateJobObjectW(None, None)  # anonymous; NULL attributes: not inheritable
    _check(job, "CreateJobObjectW")
    info = _ExtendedLimit()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE  # no breakaway
    try:
        _check(_k32.SetInformationJobObject(job, EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
                                            ctypes.sizeof(info)), "SetInformationJobObject")
    except OSError:
        _close(job)
        raise
    return job


def _assign(job: int, pid: int) -> None:
    # By pid, not `Popen._handle` (private): no reuse of the pid while `Popen` holds its handle.
    process = _k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
    _check(process, "OpenProcess")
    try:
        _check(_k32.AssignProcessToJobObject(job, process), "AssignProcessToJobObject")
    finally:
        _close(process)


def _resume(pid: int) -> None:
    """Resume the threads of `pid` (a snapshot: `subprocess` closes the thread handle it got)."""
    snapshot = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    _check(snapshot and snapshot != INVALID_HANDLE_VALUE, "CreateToolhelp32Snapshot")
    resumed = 0
    try:
        entry = _ThreadEntry()
        entry.dwSize = ctypes.sizeof(entry)
        more = _k32.Thread32First(snapshot, ctypes.byref(entry))
        while more:
            if entry.th32OwnerProcessID == pid:
                thread = _k32.OpenThread(THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                _check(thread, "OpenThread")
                try:
                    _check(_k32.ResumeThread(thread) != RESUME_FAILED, "ResumeThread")
                finally:
                    _close(thread)
                resumed += 1
            more = _k32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        _close(snapshot)
    if resumed == 0:
        raise OSError("aucun fil à reprendre")


def _active_processes(job: int) -> int:
    info = _Accounting()
    _check(_k32.QueryInformationJobObject(job, BASIC_ACCOUNTING_INFORMATION, ctypes.byref(info),
                                          ctypes.sizeof(info), None), "QueryInformationJobObject")
    return info.ActiveProcesses


def _abandon(process: subprocess.Popen) -> None:
    """Kill a process that never ran outside the job (still suspended), and close its pipes."""
    try:
        process.kill()  # TerminateProcess
        process.wait(5.0)
    except (OSError, subprocess.TimeoutExpired):
        pass
    for pipe in filter(None, (process.stdin, process.stdout, process.stderr)):
        pipe.close()


def spawn(argv: list[str], *, creationflags: int = 0, **options) -> subprocess.Popen:
    """`subprocess.Popen` in a new job; on any error, raises with nothing left running."""
    job = _create_job()
    process = None
    try:
        process = subprocess.Popen(argv, creationflags=creationflags | CREATE_SUSPENDED, **options)
        _assign(job, process.pid)
        _resume(process.pid)
    except BaseException:
        if process is not None:
            _abandon(process)
        _close(job)
        raise
    process.nexus_job = Job(job)  # type: ignore[attr-defined]
    return process


def stop(process: subprocess.Popen, job: Job, timeout: float) -> bool:
    """True once the job is terminated, empty and the process reaped. Never raises: an error is
    an unconfirmed stop (False), and the handle stays open."""
    deadline = time.monotonic() + timeout
    if not job.lock.acquire(timeout=timeout):
        return False
    try:
        if job.handle is not None:
            _check(_k32.TerminateJobObject(job.handle, 1), "TerminateJobObject")
            while _active_processes(job.handle) > 0:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(POLL)
        process.wait(timeout=max(0.0, deadline - time.monotonic()))
        if job.handle is not None:
            _close(job.handle)
            job.handle = None
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        job.lock.release()
