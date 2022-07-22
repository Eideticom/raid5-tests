from drgn.helpers.linux.block import for_each_disk
from drgn.helpers.linux.list import (hlist_for_each_entry, list_for_each_entry,
                                     list_empty, list_for_each)
from drgn import Object, sizeof

import enum

MD_MAJOR = 9

class MDException(Exception):
    def __init__(self, msg, mddev=None):
        if mddev is not None:
            disk_name = mddev.gendisk.disk_name.string_().decode()
            msg = f"{disk_name}: {msg}"
        super().__init__(msg)

def find_disk(prog, name):
    for disk in for_each_disk(prog):
        if disk.disk_name.string_() == name.encode():
            return disk

def find_mddev(prog, disk_name="md0"):
    disk = find_disk(prog, disk_name)
    if disk is None:
        raise MDException(f"{disk_name} doesn't exist")

    if disk.major != MD_MAJOR:
        raise MDException(f"{disk_name} is not an md device")

    return Object(prog, "struct mddev", address=disk.private_data)

def get_raid5_conf(mddev):
    if mddev.level not in (4, 5, 6):
        raise MDException(f"not a raid5 device", mddev)

    return Object(mddev.prog_, "struct r5conf", address=mddev.private)

def find_hashed_stripes(conf):
    PAGE_SIZE = 4096
    NR_HASH = PAGE_SIZE // sizeof(conf.stripe_hashtbl[0])

    stripes = []
    for i in range(NR_HASH):
        for s in hlist_for_each_entry('struct stripe_head',
                                      conf.stripe_hashtbl[i].address_of_(),
                                      'hash'):
            stripes.append(s)

    return stripes

def stripe_in_list(list_head, stripe):
    for s in list_for_each_entry("struct stripe_head", list_head, "lru"):
        if s == stripe:
            return True

    return False

NR_STRIPE_HASH_LOCKS=8
def stripe_in_inactive_list(conf, stripe):
    for i in range(NR_STRIPE_HASH_LOCKS):
        if stripe_in_list(conf.inactive_list[i].address_of_(), stripe):
            return True

    return False

def find_stripe_lru_list(conf, stripe):
    if list_empty(stripe.lru.address_of_()):
        return "none"
    if stripe_in_inactive_list(conf, stripe):
        return "inactive"

    lists = {"handle_list": conf.handle_list,
             "loprio_list": conf.loprio_list,
             "hold_list": conf.hold_list,
             "delayed_list": conf.delayed_list,
             "bitmap_list": conf.bitmap_list}

    for name, list_head in lists.items():
        if stripe_in_list(list_head.address_of_(), stripe):
            return name

    return "unknown"

class Raid5StripeState(enum.IntEnum):
    STRIPE_ACTIVE = 0
    STRIPE_HANDLE = enum.auto()
    STRIPE_SYNC_REQUESTED = enum.auto()
    STRIPE_SYNCING = enum.auto()
    STRIPE_INSYNC = enum.auto()
    STRIPE_REPLACED = enum.auto()
    STRIPE_PREREAD_ACTIVE = enum.auto()
    STRIPE_DELAYED = enum.auto()
    STRIPE_DEGRADED = enum.auto()
    STRIPE_BIT_DELAY = enum.auto()
    STRIPE_EXPANDING = enum.auto()
    STRIPE_EXPAND_SOURCE = enum.auto()
    STRIPE_EXPAND_READY = enum.auto()
    STRIPE_IO_STARTED = enum.auto()
    STRIPE_FULL_WRITE = enum.auto()
    STRIPE_BIOFILL_RUN = enum.auto()
    STRIPE_COMPUTE_RUN = enum.auto()
    STRIPE_ON_UNPLUG_LIST = enum.auto()
    STRIPE_DISCARD = enum.auto()
    STRIPE_ON_RELEASE_LIST = enum.auto()
    STRIPE_BATCH_READY = enum.auto()
    STRIPE_BATCH_ERR = enum.auto()
    STRIPE_BITMAP_PENDING = enum.auto()
    STRIPE_LOG_TRAPPED = enum.auto()
    STRIPE_R5C_CACHING = enum.auto()
    STRIPE_R5C_PARTIAL_STRIPE = enum.auto()
    STRIPE_R5C_FULL_STRIPE = enum.auto()
    STRIPE_R5C_PREFLUSH = enum.auto()

def stripe_states(state):
    states = []
    for s in Raid5StripeState:
        if (1 << s.value) & state:
            states.append(s)
    return states

def print_stripe_info(conf, stripe):
    print("Stripe Info:")
    print(f"  Address:      {stripe.value_():x}")
    print(f"  Sector:       {int(stripe.sector)}")
    print(f"  State:        {hex(stripe.state)}")
    for s in stripe_states(stripe.state):
        print(f"                {s.name}")

    lru_list = find_stripe_lru_list(conf, stripe)
    print(f"  LRU List:     {lru_list}")
