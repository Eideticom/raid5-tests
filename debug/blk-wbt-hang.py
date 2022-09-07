#!/usr/bin/env drgn

import argparse
import sys

import md

import subprocess

from drgn import container_of, cast, Object

from drgn.helpers.linux import find_task, for_each_task
from drgn.helpers.linux.list import list_for_each_entry

def dmesg_filter(filt):
    p = subprocess.Popen(f"dmesg | grep '{filt}'", shell=True,
                         stdout=subprocess.PIPE, text=True)

    for line in p.stdout.readlines():
        yield line.split("]", 1)[1].strip()

def dmesg_find_hung():
    """Find task PIDs from dmesg hung task warnings"""

    for line in dmesg_filter("INFO: task"):
        line = line.split()
        yield int(line[2].split(":")[-1])

def find_wbt_hung_bios(hung_rwb):
    """This does the same as the dmesg parser, but by examining kernel
       memory"""

    wq = hung_rwb.rq_wait[0].wait

    in_progress_bios = []

    for e in list_for_each_entry("struct wait_queue_entry",
                                 wq.head.address_of_(), "entry"):

        wait_data = container_of(e, "struct rq_qos_wait_data", "wq")

        for t in prog.stack_trace(wait_data.task):
            if t.name == "wbt_wait":
                in_progress_bios.append(t["bio"])

    return in_progress_bios

def print_bio(b, indent=2):
    print(f"{' '*indent}Bio {b.value_():x} {int(b.bi_opf):x} " +
          f"{b.bi_bdev.bd_device.kobj.name.string_().decode()}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    args = parser.parse_args()

    try:
        hung_rwbs = []
        plugs = {}

        for tsk in for_each_task(prog):
            if not tsk.plug:
                continue

            if tsk.plug.mq_list.value_():
                print(f"Found blk-plug with bios in task " +
                      f"{tsk.comm.string_().decode()}:{tsk.pid}")
                rq = tsk.plug.mq_list
                while rq:
                    print(f"  Req {rq.value_():x}")
                    print_bio(rq.bio, indent=4)
                    rq = rq.rq_next
                print()

        for tsk in dmesg_find_hung():
            task = find_task(prog, tsk)
            trace = prog.stack_trace(task)

            if trace[4].name != "rq_qos_wait":
                continue
            rwb = cast("struct wbt_wait_data *",
                       trace[4]["data"].private_data).rwb
            if rwb not in hung_rwbs:
                hung_rwbs.append(rwb)

        hung_rwb = list(hung_rwbs)[0]
        print(f"Found hung rwb: {hung_rwb.value_():x} (of {len(hung_rwbs)})")

        hung_bios = find_wbt_hung_bios(hung_rwb)
        print(f"Found hung bios: {len(hung_bios)}")
        for b in hung_bios:
            print_bio(b)

    except md.MDException as e:
        print(e)
