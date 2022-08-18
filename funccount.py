import os
import re
import shutil
import signal
import subprocess as sp
import threading
import time

class FunccountInvalidFunctionError(Exception):
    pass

class FunccountNotStartedError(Exception):
    pass

class Funccount:
    def _sleep_and_run(self):
        self.event.wait(self.sleep)

        self.lock.acquire()
        if not self.joined:
            # Do not start funccount tool if stop() has already been called,
            # otherwise we end up with a zombie thread
            self.proc = sp.Popen(self.cmd, stdout=sp.PIPE, stderr=sp.PIPE,
                                 text=True, start_new_session=True)
        self.lock.release()

    def __init__(self, funcs, executable='funccount', sleep=0):
        if not shutil.which(executable):
            raise FileNotFoundError(executable)

        with open('/sys/kernel/debug/tracing/available_filter_functions') as f:
            avail_funcs = f.read().splitlines()

        for func in funcs.split():
            r = re.compile(func.replace('*', '.*'))
            if any(r.match(line) for line in avail_funcs):
                continue
            raise FunccountInvalidFunctionError(f'Function/Regex not available for tracing: {func}')

        self.funcs = funcs
        self.cmd = [executable, funcs]
        self.sleep = sleep
        self.lock = threading.Lock()
        self.event = threading.Event()
        self.joined = False

    def start(self):
        self.thr = threading.Thread(target=self._sleep_and_run)
        self.thr.start()

    def stop(self):
        self.lock.acquire()
        self.thr.join(timeout=0.1)

        if self.thr.is_alive():
            self.joined = True
            self.event.set()
            self.lock.release()
            raise FunccountNotStartedError('funccount.stop() called during sleep phase. Decrease "sleep" and try again.')

        self.lock.release()

        pgid = os.getpgid(self.proc.pid)
        os.killpg(pgid, signal.SIGINT)

        try:
            out, err = self.proc.communicate(timeout=1)
        except sp.TimeoutExpired:
            self.proc.kill()
            out, err = self.proc.communicate()

        if self.proc.returncode:
            raise sp.CalledProcessError(cmd=self.cmd,
                                        returncode=self.proc.returncode,
                                        output=out,
                                        stderr=err)

        res = {}
        for line in out.split('\n'):
            line = line.strip().split()
            if len(line) > 0 and line[0] in self.funcs:
                res[line[0]] = int(line[1])

        return res
