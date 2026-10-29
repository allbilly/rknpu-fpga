"""POSIX command ownership for serial offline qualification runners.

One child session is owned through completion, timeout and interruption. No
resource limits are imposed. Normal return also rejects lingering descendants
through the returned cleanup metadata; a successful leader is insufficient.
"""
from dataclasses import dataclass
import math
import os
from pathlib import Path
import signal
import subprocess
import threading
import time


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    timed_out: bool
    pid: int
    live_before_cleanup: tuple[int, ...]
    live_after_cleanup: tuple[int, ...]


def live_group(pgid):
    result=[]
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            fields=(proc/'stat').read_text().rsplit(')',1)[1].split()
            if int(fields[2])==pgid and fields[0] not in ('Z','X'):
                result.append(int(proc.name))
        except (OSError,ValueError,IndexError):
            pass
    return tuple(sorted(result))


def _stop(child):
    for sig,grace in ((signal.SIGTERM,2.0),(signal.SIGKILL,2.0)):
        if not live_group(child.pid):
            break
        try:
            os.killpg(child.pid,sig)
        except ProcessLookupError:
            pass
        end=time.monotonic()+grace
        while live_group(child.pid) and time.monotonic()<end:
            time.sleep(.01)
    child.wait(timeout=2)
    return live_group(child.pid)


def run_owned(argv, *, timeout, cwd=None, stdout=None, stderr=subprocess.STDOUT,
              stdin=subprocess.DEVNULL, env=None):
    """Run a command; preserve and report all owned-session cleanup outcomes.

    Call on the main thread. SIGTERM/INT/HUP become exceptions only while a
    command is owned; previous handlers and signal masks are restored. Timeout
    is a result, and every other exception is re-raised after group cleanup.
    """
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Owned command signal supervision requires the main thread')
    if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or timeout<=0:
        raise ValueError('Command timeout must be finite and positive')
    watched={signal.SIGINT,signal.SIGTERM,signal.SIGHUP}
    handlers={s:signal.getsignal(s) for s in watched}
    pending_signal=None
    interruptible=False
    def interrupted(signum,frame):
        nonlocal pending_signal
        pending_signal=signum
        # Another Python thread can receive the process signal while this
        # main thread masks it. Defer until Popen has returned the owned PID.
        if interruptible:
            raise InterruptedError('Owned command interrupted by signal '+str(signum))
    child=None;timed_out=False;before=();after=();error=None
    # Block before installing any handler, and keep restoration around the
    # entire installation/spawn/unblock sequence as well as the wait itself.
    previous=signal.pthread_sigmask(signal.SIG_BLOCK,watched)
    try:
        for s in watched:
            signal.signal(s,interrupted)
        child=subprocess.Popen(argv,cwd=cwd,stdin=stdin,stdout=stdout,stderr=stderr,
            env=env,start_new_session=True,
            preexec_fn=lambda:signal.pthread_sigmask(signal.SIG_SETMASK,previous))
        interruptible=True
        signal.pthread_sigmask(signal.SIG_SETMASK,previous)
        if pending_signal is not None:
            raise InterruptedError('Owned command interrupted by signal '+str(pending_signal))
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out=True
        before=live_group(child.pid)
    except BaseException as exc:
        error=exc
        raise
    finally:
        interruptible=False
        signal.pthread_sigmask(signal.SIG_BLOCK,watched)
        try:
            if child is not None:
                if error is not None:
                    before=live_group(child.pid)
                after=_stop(child)
                details={'pid':child.pid,'pgid':child.pid,'live_before_cleanup':list(before),
                         'live_after_cleanup':list(after)}
                if error is not None:
                    error.owned_process_cleanup=details
                if after:
                    raise RuntimeError('Owned command descendants survived cleanup: '+repr(details))
        finally:
            for s,handler in handlers.items():
                signal.signal(s,handler)
            signal.pthread_sigmask(signal.SIG_SETMASK,previous)
    if pending_signal is not None:
        exc=InterruptedError('Owned command interrupted by signal '+str(pending_signal))
        exc.owned_process_cleanup={'pid':child.pid,'pgid':child.pid,
            'live_before_cleanup':list(before),'live_after_cleanup':list(after)}
        raise exc
    return CommandResult(child.returncode,timed_out,child.pid,before,after)
