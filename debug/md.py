from drgn.helpers.linux.block import for_each_disk
from drgn.helpers.linux.list import hlist_for_each_entry
from drgn import Object, sizeof

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
