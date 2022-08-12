import os
import signal
import subprocess as sp
import threading
import time

class Funccount:
    def _sleep_and_run(self):
        time.sleep(self.sleep)

        cmd = [self.executable, self.funcs]

        self.proc = sp.Popen(cmd, stdout=sp.PIPE, stderr=sp.PIPE, text=True,
                             start_new_session=True)

    def __init__(self, funcs, executable='funccount', sleep=0):
        self.funcs = funcs
        self.executable = executable
        self.sleep = sleep

    def start(self):
        self.thr = threading.Thread(target=self._sleep_and_run)
        self.thr.start()

    def stop(self):
        self.thr.join()

        pgid = os.getpgid(self.proc.pid)
        os.killpg(pgid, signal.SIGINT)

        while self.proc.poll() is None:
            time.sleep(0.1)

        out, err = self.proc.communicate()
        if err:
            raise RuntimeError(f'funccount failed:\n\n{err}')

        res = {}
        for line in out.split('\n'):
            line = line.strip().split()
            if len(line) > 0 and line[0] in self.funcs:
                res[line[0]] = int(line[1])

        return res
