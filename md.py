#!/usr/bin/env python3

import argparse
import os
import pathlib
import re
import subprocess

class EnvironmentArgumentParser(argparse.ArgumentParser):
    class _CustomHelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
        def _get_help_string(self, action):
            help = super()._get_help_string(action)
            if action.dest != 'help':
                help += ' [env: {}]'.format(action.dest.upper())
            return help

    def __init__(self, *, formatter_class=_CustomHelpFormatter,
                 **kwargs):
        super().__init__(formatter_class=formatter_class, **kwargs)

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

    def _add_action(self, action):
        envval = os.environ.get(action.dest.upper(),
                                action.default)
        if isinstance(action, argparse._StoreTrueAction):
            envval = self.to_bool(envval)
        if envval != "":
            action.default = envval

        return super()._add_action(action)

UNITS = {"B": 1,
         "K": 1 << 10,
         "M": 1 << 20,
         "G": 1 << 30,
         "T": 1 << 40,
}

def suffix_parse(val):
    m = re.match(r'^(\d+)([KMGTB]?)B?$', val.upper())
    if m:
        number, unit = m.groups()
        return int(number) * UNITS[unit]
    raise TypeError("Not a valid size")

class MDInvalidArgumentError(Exception):
    pass

class MDInstance:
    def __init__(self, md="md0"):
        self._md_dev = f"/dev/{md}"
        self._sysfs = pathlib.Path("/sys/block") / md / "md"

    def open_direct(self):
        return os.open(self._md_dev, os.O_RDWR|os.O_DIRECT)

    def wait(self):
        subprocess.call(["mdadm", "--wait", self._md_dev, "--quiet"],
                        stderr=subprocess.DEVNULL)

    def stop(self):
        subprocess.call(["mdadm", "--stop", self._md_dev, "--quiet"],
                        stderr=subprocess.DEVNULL)

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

    def setup(self, level=5, disks=None, ram_disks=None, loop_disks=None,
              size=None, chunk_size=64 << 10, assume_clean=True, force=True,
              run=False, policy="resync", journal=None, quiet=False,
              thread_cnt=4, cache_size=8192):

        self.wait()
        self.stop()

        if disks is None and ram_disks is None and loop_disks is None:
            raise MDInvalidArgumentError("No disks specified for an array")

        if ram_disks is not None:
            if disks:
                raise MDInvalidArgumentError("Must not specify both disks and ram_disks")
            subprocess.check_call(["modprobe", "brd", "rd_size=131072"])
            disks = [f"/dev/ram{i}" for i in range(ram_disks)]

        if loop_disks is not None:
            if disks:
                raise MDInvalidArgumentError("Must not specify both disks and loop_disks")
            if size is None:
                raise MDInvalidArgumentError("Must specify size with loop_disks")

            disks = self._create_loop_disks(loop_disks, size)
            size = None

        mdadm_args = ["mdadm", "--create", self._md_dev,
                      "--level", str(level),
                      "--chunk", str(chunk_size >> 10),
                      "--raid-devices", str(len(disks)),
                      "--consistency-policy", policy]

        if policy == "bitmap":
            mdadm_args.append("--bitmap=internal")
        if assume_clean:
            mdadm_args.append("--assume-clean")
        if force:
            mdadm_args.append("--force")
        if run:
            mdadm_args.append("--run")
        if quiet:
            mdadm_args.append("--quiet")
        if journal is not None:
            mdadm_args += ["--write-journal", journal]
        if size is not None:
            mdadm_args += ["--size", str(size >> 10)]

        subprocess.check_call(mdadm_args + disks)

        if thread_cnt is not None:
            (self._sysfs / "group_thread_cnt").write_text(str(thread_cnt))
        if cache_size is not None and cache_size > 0:
            (self._sysfs / "stripe_cache_size").write_text(str(cache_size))

    def setup_from_args(self, args=None):
        parser = EnvironmentArgumentParser()
        parser.add_argument("-l", "--level", type=int, default=5,
                            help="raid level")
        parser.add_argument("-c", "--chunk-size", default=64 << 10,
                            type=suffix_parse,
                            help="md chunk size")

        group = parser.add_mutually_exclusive_group()
        group.add_argument("-d", "--disks", "--ram-disks", type=int,
                           help="number of disks to create")
        group.add_argument("--loop-disks", type=int,
                           help="use loop devices instead of ram disks")
        group.add_argument("--devs", nargs="+",
                           help="specific disks to use")

        parser.add_argument("--assume-clean", action="store_false",
                            help="don't sync after creating the array")
        parser.add_argument("--force", action="store_true",
                            help="force mdadm creation")
        parser.add_argument("--zero-first", action="store_true",
                            help="don't prompt to start the array")
        parser.add_argument("--run", action="store_true",
                            help="don't prompt to start the array")
        parser.add_argument("--policy", default="resync",
                            help="consistency policy")
        parser.add_argument("--quiet", action="store_true",
                            help="be quiet")
        parser.add_argument("--thread-cnt", default=4, type=int,
                            help="group thread count for array")
        parser.add_argument("--cache-size", default=8192, type=int,
                            help="cache size")
        parser.add_argument("--journal", help="journal type")
        parser.add_argument("--size", type=suffix_parse,
                            help="size used from each disk")

        args = parser.parse_args(args)

        if args.devs:
            args.disks = None
            args.loop_disks = None
        if args.loop_disks:
            args.disks = None

        if not args.devs and not args.loop_disks and not args.disks:
            args.disks = 3

        self.setup(level=args.level,
                   ram_disks=args.disks,
                   loop_disks=args.loop_disks,
                   size=args.size,
                   chunk_size=args.chunk_size,
                   assume_clean=args.assume_clean,
                   force=args.force,
                   run=args.run or args.zero_first,
                   policy=args.policy,
                   journal=args.journal,
                   quiet=args.quiet,
                   thread_cnt=args.thread_cnt,
                   cache_size=args.cache_size)

    def get_level(self):
        return (self._sysfs / "level").read_text().strip()

    def get_num_disks(self):
        return int((self._sysfs / "raid_disks").read_text().strip())

    def get_disks(self):
        for d in range(self.get_num_disks()):
            disk = (self._sysfs / f"rd{d}" / "block").readlink().name
            yield f"/dev/{disk}"

    def get_next_disk(self):
        disk = (self._sysfs / "rd0" / "block").readlink().name

        n = self.get_num_disks()
        if "ram" in disk:
            return f"/dev/ram{n}"
        if "loop" in disk:
            sectors = int((self._sysfs / "rd0" / "block" / "size").read_text())
            return self._create_loop_disk(n, sectors << 9)

        raise MDInvalidArgumentError("Can't grow array with out using loop or ram disks")

    def grow(self):
        self.wait()
        dev = self.get_next_disk()
        n = self.get_num_disks()
        subprocess.check_call(["mdadm", "--add", self._md_dev,
                               "--quiet", dev])
        subprocess.check_call(["mdadm", "--grow", "--raid-devices",
                               str(n + 1), self._md_dev])
        return n + 1

    def degrade(self, dev):
        self.wait()
        subprocess.check_call(["mdadm", "--manage", self._md_dev, "--quiet",
                               "--fail", dev])
        subprocess.check_call(["mdadm", "--manage", self._md_dev, "--quiet",
                               "--remove", dev], stderr=subprocess.DEVNULL)

    def recover(self, dev):
        subprocess.check_call(["mdadm", "--manage", self._md_dev, "--quiet",
                               "--add-spare", dev])
