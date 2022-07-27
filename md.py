#!/usr/bin/env python3

import argparse
import os
import pathlib
import re
import subprocess
import sys
import time

class _EnvironmentArgMixin:
    _is_mutex_grp = False
    _env_found = None

    def to_bool(self, x):
        if isinstance(x, bool):
            return x
        if isinstance(x, str):
            x = x.lower()
            if x.startswith("y") or x.startswith("t") or x == "1":
                return True
            if x.startswith("n") or x.startswith("f") or x == "0":
                return False
        return False

    def add_argument(self, *args, **kwargs):
        action_type = kwargs.get("action", None)
        action = super().add_argument(*args, **kwargs)

        if action_type == "help":
            return action

        env = action.dest.upper()
        if self._is_mutex_grp and os.environ.get(env, None):
            if self._env_found is not None:
                print(f"environment variable {env} not allowed with variable {self._env_found}",
                      file=sys.stderr)
                sys.exit(2)
            self._env_found = env

        envval = os.environ.get(env, action.default)
        if action_type in ("store_true", "store_false"):
            envval = self.to_bool(envval)
        nargs = kwargs.get("nargs", None)
        if ((nargs in ("+", "*") or isinstance(nargs, int)) and
            isinstance(envval, str)):
            envval = envval.split()
            if action.type:
                envval = [action.type(x) for x in envval]
        if envval != "":
            action.default = envval

        return action

    def _mixin_group(self, grp):
        orig_typ = type(grp)
        grp.__class__ = type("_Env" + orig_typ.__name__,
                             (_EnvironmentArgMixin, orig_typ), {})
        return grp

    def add_argument_group(self, *args, **kwargs):
        grp = super().add_argument_group(*args, **kwargs)
        return self._mixin_group(grp)

    def add_mutually_exclusive_group(self, *args, **kwargs):
        grp = super().add_mutually_exclusive_group(*args, **kwargs)
        grp._is_mutex_grp = True
        return self._mixin_group(grp)

class _EnvironmentArgumentParser(_EnvironmentArgMixin,
                                 argparse.ArgumentParser):
    class _CustomHelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
        def _get_help_string(self, action):
            help = super()._get_help_string(action)
            if action.dest != 'help':
                help += ' [env: {}]'.format(action.dest.upper())
            return help

    def __init__(self, *, formatter_class=_CustomHelpFormatter,
                 **kwargs):
        super().__init__(formatter_class=formatter_class, **kwargs)

class MDArgumentParser(_EnvironmentArgumentParser):
    _UNITS = {"B": 1,
              "K": 1 << 10,
              "M": 1 << 20,
              "G": 1 << 30,
              "T": 1 << 40,
    }

    @classmethod
    def _suffix_parse(cls, val):
        m = re.match(r'^(\d+)([KMGTB]?)B?$', val.upper())
        if m:
            number, unit = m.groups()
            return int(number) * cls._UNITS[unit]
        raise TypeError("Not a valid size")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        grp = self.add_argument_group("MD Array Options")
        grp.add_argument("-l", "--level", type=int, default=5,
                         help="raid level")
        grp.add_argument("-c", "--chunk-size", default=64 << 10,
                         type=self._suffix_parse,
                         help="md chunk size")

        grp.add_argument("-d", "--disks", type=int, default=3,
                         help="number of disks to create")
        grp.add_argument("--disk-type", choices=["ram", "dev", "loopback"],
                         help="type of block device to use in testing, default uses either ramdisk or specified devs if present")
        grp.add_argument("--devs", nargs="+",
                         help="specific disks to use")

        grp.add_argument("--no-assume-clean", dest="assume-clean",
                         action="store_false",
                         help="don't sync after creating the array")
        grp.add_argument("--assume-clean", action="store_true", default=True)
        grp.add_argument("--force", action="store_true",
                         help="force mdadm creation")
        grp.add_argument("--zero-first", action="store_true",
                         help="don't prompt to start the array")
        grp.add_argument("--run", action="store_true",
                         help="don't prompt to start the array")
        grp.add_argument("--policy", default="resync",
                         help="consistency policy")
        grp.add_argument("--quiet", action="store_true",
                         help="be quiet")
        grp.add_argument("--thread-cnt", default=4, type=int,
                         help="group thread count for array")
        grp.add_argument("--cache-size", default=8192, type=int,
                         help="cache size")
        grp.add_argument("--size", type=self._suffix_parse,
                         help="size used from each disk")
        grp.add_argument("--mdadm", help="mdadm executable to use")

        self.md_grp = grp

class MDInvalidArgumentError(Exception):
    pass

class MDInstance:
    # Overestimate the maximum superblock size to ensure enough of the
    # constituent disks get zeroed. 5MB seems like a high bar.
    MAX_SUPERBLOCK_SZ = 5 << 20

    @classmethod
    def create_from_parsed_args(cls, args):
        return cls(level=args.level,
                   devs=args.devs,
                   ndisks=args.disks,
                   disk_type=args.disk_type,
                   size=args.size,
                   chunk_size=args.chunk_size,
                   assume_clean=args.assume_clean,
                   force=args.force,
                   run=args.run or args.zero_first,
                   policy=args.policy,
                   quiet=args.quiet,
                   thread_cnt=args.thread_cnt,
                   cache_size=args.cache_size,
                   mdadm=args.mdadm)

    @classmethod
    def create_from_args(cls, args=None):
        md_parser = MDArgumentParser()
        args = md_parser.parse_args(args)
        return cls.create_from_parsed_args(args)

    def __init__(self, md="md0", level=5, devs=None, ndisks=None,
                 disk_type=None, size=None, chunk_size=64 << 10,
                 assume_clean=True, force=True, run=False, policy="resync",
                 quiet=False, thread_cnt=4, cache_size=8192, mdadm=None):
        self.md_dev = f"/dev/{md}"
        self._sysfs = pathlib.Path("/sys/block") / md / "md"

        self.level = level
        self.ndisks = ndisks
        self.size = size
        self.chunk_size = chunk_size
        self.assume_clean = assume_clean
        self.force = force
        self.run = run
        self.policy = policy
        self.quiet = quiet
        self.thread_cnt = thread_cnt
        self.cache_size = cache_size
        self._size_to_zero = None
        self.mdadm = mdadm or "mdadm"

        if (devs is None and disk_type == 'dev') or ndisks == 0:
            raise MDInvalidArgumentError("No disks specified for an array")

        if disk_type is None:
            self.disk_type = "dev" if devs else "ram"
        else:
            self.disk_type = disk_type

        self.special_devs = []
        self.extra_devs = []
        self.disk_size = size

        if self.disk_type == 'ram':
            if devs:
                raise MDInvalidArgumentError("Must not specify both devs and ram_disks")
            subprocess.check_call(["modprobe", "brd", "rd_size=131072"])
            self.devs = [f"/dev/ram{i}" for i in range(ndisks)]
        elif self.disk_type == 'loopback':
            if devs:
                raise MDInvalidArgumentError("Must not specify both disks and loop_disks")
            if size is None:
                raise MDInvalidArgumentError("Must specify size with loop_disks")
            self.devs = None
            self.size = None
        elif self.disk_type == "dev":
            if len(devs) < ndisks:
                raise MDInvalidArgumentError(f"Must specify at least {ndisks} devs")

            self.extra_devs = devs[ndisks:]
            self.devs = devs[:ndisks]
        else:
            raise MDInvalidArgumentError(f"Unknown disk_type: {disk_type}")

    def open_direct(self):
        return os.open(self.md_dev, os.O_RDWR|os.O_DIRECT)

    def wait(self):
        subprocess.call([self.mdadm, "--wait", self.md_dev, "--quiet"],
                        stderr=subprocess.DEVNULL)

    def stop(self):
        subprocess.call([self.mdadm, "--stop", self.md_dev, "--quiet"],
                        stderr=subprocess.DEVNULL)
        while pathlib.Path(self.md_dev).exists():
            time.sleep(0.01)

    def _create_loop_disk(self, i, size):
        dev = f"/dev/loop{i}"
        backing = f"/var/tmp/lodisk{i}"
        subprocess.call(["losetup", "-d", dev], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
        open(backing, "w").close()
        os.truncate(backing, size)
        subprocess.check_call(["losetup", dev, backing])
        return dev

    def _create_loop_disks(self, count, size):
        ret = []

        for i in range(count):
            dev = self._create_loop_disk(i, size)
            ret.append(dev)

        return ret

    def _stop_and_create_disks(self):
        self.wait()
        self.stop()

        if self.disk_type == 'loopback' and self.devs is None:
            self.devs = self._create_loop_disks(self.ndisks, self.disk_size)

    def setup(self):
        self._stop_and_create_disks()

        mdadm_args = [self.mdadm, "--create", self.md_dev,
                      "--level", str(self.level),
                      "--chunk", str(self.chunk_size >> 10),
                      "--raid-devices", str(len(self.devs)),
                      "--consistency-policy", self.policy]

        if self.policy == "bitmap":
            mdadm_args.append("--bitmap=internal")
        if self.policy == "journal":
            mdadm_args += ["--write-journal", self.get_special_disk()]
        if self.assume_clean:
            mdadm_args.append("--assume-clean")
        if self.force:
            mdadm_args.append("--force")
        if self.run:
            mdadm_args.append("--run")
        if self.quiet:
            mdadm_args.append("--quiet")
        if self.size is not None:
            mdadm_args += ["--size", str(self.size >> 10)]

        subprocess.check_call(mdadm_args + self.devs)

        if self.thread_cnt is not None:
            (self._sysfs / "group_thread_cnt").write_text(str(self.thread_cnt))
        if self.cache_size is not None and self.cache_size > 0:
            (self._sysfs / "stripe_cache_size").write_text(str(self.cache_size))

    def get_level(self):
        return (self._sysfs / "level").read_text().strip()

    def get_num_disks(self):
        return int((self._sysfs / "raid_disks").read_text().strip())

    def get_disks(self):
        return self.devs

    def _zero_disk(self, dev):
        subprocess.check_call(["dd", "if=/dev/zero", f"of={dev}",
                               "bs=1M", f"count={self._size_to_zero}",
                               "oflag=direct"],
                              stderr=subprocess.DEVNULL)

    def zero_all_disks(self, size_to_zero):
        self._stop_and_create_disks()

        count = size_to_zero + self.MAX_SUPERBLOCK_SZ
        count = (count + (1 << 20) - 1) >> 20
        self._size_to_zero = count

        for dev in self.devs:
            self._zero_disk(dev)
        for dev in self.special_devs:
            self._zero_disk(dev)

    def _get_next_disk(self):
        if self.devs is None:
            self._stop_and_create_disks()

        if len(self.extra_devs):
            return self.extra_devs.pop(0)

        n = len(self.devs) + len(self.special_devs)
        if self.disk_type == 'ram':
            return f"/dev/ram{n}"
        elif self.disk_type == 'loopback':
            return self._create_loop_disk(n, self.disk_size)

        raise MDInvalidArgumentError("Can't grow array further without using loop or ram disks")

    def _get_next_zeroed_disk(self):
        disk = self._get_next_disk()
        if self._size_to_zero is not None:
            self._zero_disk(disk)
        return disk

    def get_special_disk(self):
        dev = self._get_next_zeroed_disk()
        self.special_devs.append(dev)
        return dev

    def grow(self):
        self.wait()
        dev = self._get_next_zeroed_disk()
        self.devs.append(dev)
        n = self.get_num_disks()
        subprocess.check_call(["mdadm", "--add", self.md_dev,
                               "--quiet", dev])
        subprocess.check_call(["mdadm", "--grow", "--raid-devices",
                               str(n + 1), self.md_dev])
        return n + 1

    def degrade(self, dev):
        self.wait()
        subprocess.check_call(["mdadm", "--manage", self.md_dev, "--quiet",
                               "--fail", dev])
        subprocess.check_call(["mdadm", "--manage", self.md_dev, "--quiet",
                               "--remove", dev], stderr=subprocess.DEVNULL)

    def recover(self, dev):
        subprocess.check_call(["mdadm", "--manage", self.md_dev, "--quiet",
                               "--add-spare", dev])
