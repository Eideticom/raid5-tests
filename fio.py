# SPDX-License-Identifier: GPL-2.0
# Copyright (c) 2022, Eidetic Communications Inc.

import json
import psutil
import subprocess as sp

class FIO:
    _SIZE = 4<<30

    def __init__(self, path, cpu=False, executable="fio", **kargs):
        self.args = {
            "filename": path,
            "name": "md_test",
            "blocksize": 1 << 20,
            "runtime": 15,
            "size": self._SIZE,
            "numjobs": 16,
            "fallocate": "none",
            "time_based": 1,
            "ramp_time": 10,
            "group_reporting": 1,
            "direct": 1,
            "ioengine": "libaio",
            "iodepth": 8,
            "offset_increment": self._SIZE,
            "output-format": "json",
        }
        self.cpu = cpu
        self.args.update(kargs)
        self.executable = executable

    def gen_options(self):
        return [f"--{key}={val}" for key, val in self.args.items()]

    def run(self, **kargs):
        self.cpu = kargs.pop('cpu', self.cpu)
        self.args.update(kargs)
        fio_opts = self.gen_options()

        try:
            run_cmd = [self.executable] + fio_opts
            test_data = {"cmd" : run_cmd}

            if self.cpu:
                psutil.cpu_times_percent()

            run_result = sp.check_output(run_cmd, encoding="utf-8",
                                         stderr=sp.PIPE)

            if self.cpu:
                test_data["cpu"] = psutil.cpu_times_percent()

            test_data["result"] = json.loads(run_result)
        except sp.CalledProcessError as err:
            test_data["err"] = {
                "stdout": err.stdout.split("\n"),
                "stderr": err.stderr.split("\n"),
                "ret": err.returncode,
            }

        return test_data
