#!/usr/bin/env python3

import argparse
import os
import pathlib
import struct
import sys

import typing as t

MDRAID_MAGIC = 0xa92b4efc

SZ_1K = 1024
SZ_4K = 4 * SZ_1K
SZ_8K = 8 * SZ_4K

# MD Superblock layout from: https://raid.wiki.kernel.org/index.php/RAID_superblock_formats
class MDBlkDev:
    path: pathlib.Path
    fd: int
    sz: int
    sb_off: int
    sb_major: int
    sb_feature_map: t.Dict[str, bool]
    sb_set_uuid: bytes
    sb_set_name: str
    sb_ctime: float
    sb_level: int
    sb_layout: int
    sb_size: int
    sb_chunksize: int
    sb_raid_disks: int
    sb_bitmap_offset: int
    sb_new_level: int
    sb_reshape_pos: int
    sb_delta_disks: int
    sb_new_layout: int
    sb_new_chunk: int
    sb_data_offset: int
    sb_data_size: int
    sb_super_offset: int
    sb_recovery_offset: int
    sb_dev_number: int
    sb_cnt_corrected_read: int
    sb_device_uuid: bytes
    sb_devflags: t.Dict[str, bool]
    sb_utime: float
    sb_events: int
    sb_resync_offset: int
    sb_csum: int
    sb_max_dev: int
    sb_disk_roles: t.List[int]

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.fd = os.open(path, os.O_RDWR)
        self.sz = os.lseek(self.fd, 0, os.SEEK_END)

        self.sb_off = 0
        self.sb_ver = '1.1'

        if self._rd_ulong(0) != MDRAID_MAGIC:
            self.sb_off = SZ_4K
            self.sb_ver = '1.2'

        if self._rd_ulong(0) != MDRAID_MAGIC:
            self.sb_off = (self.sz & ~(SZ_4K-1)) - SZ_8K
            self.sb_ver = '1.0'

        if self._rd_ulong(0) != MDRAID_MAGIC:
            raise NotImplementedError('Only md raid superblock versions 1.0, 1.1, and 1.2 are supported by this tool')

        self.sb_major = self._rd_ulong(0x04)
        self.sb_feature_map = self._rd_longbits(0x08, ['bitmap_used', 'recovery_in_progress', 'reshape_in_progress'])
        self.sb_set_uuid = os.pread(self.fd, 16, self.sb_off + 0x10)
        self.sb_set_name = os.pread(self.fd, 32, self.sb_off + 0x20).decode()
        self.sb_ctime = self._rd_time(0x40)
        self.sb_level = self._rd_long(0x48)
        self.sb_layout = self._rd_ulong(0x4c)
        self.sb_size = self._rd_ulonglong(0x50)
        self.sb_chunksize = self._rd_ulong(0x58)
        self.sb_raid_disks = self._rd_ulong(0x5c)
        self.sb_bitmap_offset = self._rd_ulong(0x60)
        self.sb_new_level = self._rd_ulong(0x64)
        self.sb_reshape_pos = self._rd_ulonglong(0x68)
        self.sb_delta_disks = self._rd_ulong(0x70)
        self.sb_new_layout = self._rd_ulong(0x74)
        self.sb_new_chunk = self._rd_ulong(0x78)
        self.sb_data_offset = self._rd_ulonglong(0x80)
        self.sb_data_size = self._rd_ulonglong(0x88)
        self.sb_super_offset = self._rd_ulonglong(0x90)
        self.sb_recovery_offset = self._rd_ulonglong(0x98)
        self.sb_dev_number = self._rd_ulong(0xa0)
        self.sb_cnt_corrected_read = self._rd_ulong(0xa4)
        self.sb_device_uuid = os.pread(self.fd, 16, self.sb_off + 0xa8)
        self.sb_devflags = self._rd_longbits(0xb8, ['write_mostly_1'])
        self.sb_utime = self._rd_time(0xc0) 
        self.sb_events = self._rd_ulonglong(0xc8)
        self.sb_resync_offset = self._rd_ulonglong(0xd0)
        self.sb_csum = self._rd_ulong(0xd8)
        self.sb_max_dev = self._rd_ulong(0xdc)
        # TODO: better check on sb_raid_disks
        self.sb_disk_roles = []
        for i in range(min(self.sb_raid_disks, 128)):
            self.sb_disk_roles.append(self._rd_ushort(0x100 + 2 * i))

    def _rd_ushort(self, pos: int) -> int:
        return struct.unpack('<H', os.pread(self.fd, 2, self.sb_off + pos))[0]

    def _rd_ulong(self, pos: int) -> int:
        return struct.unpack('<L', os.pread(self.fd, 4, self.sb_off + pos))[0]

    def _rd_long(self, pos: int) -> int:
        return struct.unpack('<l', os.pread(self.fd, 4, self.sb_off + pos))[0]

    def _rd_longbits(self, pos: int, values: t.List[str]) -> t.Dict[str, bool]:
        ret: t.Dict[str, bool] = {}

        val = self._rd_long(pos)
        for i in range(len(values)):
            ret[values[i]] = bool((1 << i) & val)

        return ret

    def _rd_ulonglong(self, pos: int) -> int:
        return struct.unpack('<Q', os.pread(self.fd, 8, self.sb_off + pos))[0]

    def _rd_time(self, pos: int) -> float:
        ival = self._rd_ulonglong(pos)
        return (ival >> 40) + (ival & ((1 << 24) - 1)) * 1e-6

    def read_data(self, pos: int, count: int) -> bytes:
        return os.pread(self.fd, count, self.sb_data_offset * 512 + pos)

    def __str__(self) -> str:
        ret = ''
        ret += f"sb v{self.sb_ver}\n"
        ret += "  sb id area\n"
        ret += f"    major version: {self.sb_major}\n"
        ret += f"    feature map: {self.sb_feature_map}\n"
        ret += "  per-array id & cfg\n"
        ret += f"    set_uuid: {self.sb_set_uuid.hex()}\n"
        ret += f"    set_name: {self.sb_set_name}\n"
        ret += f"    ctime: {self.sb_ctime:.6f} s\n"
        ret += f"    level: {self.sb_level}\n"
        ret += f"    layout: 0x{self.sb_layout:x}\n"
        ret += f"    size: {self.sb_size}\n"
        ret += f"    chunksize: {self.sb_chunksize}\n"
        ret += f"    raid_disks: {self.sb_raid_disks}\n"
        ret += f"    bitmap_offset: {self.sb_bitmap_offset}\n"
        ret += "  reshape area\n"
        ret += f"    new_level: {self.sb_new_level}\n"
        ret += f"    reshape_pos: {self.sb_reshape_pos}\n"
        ret += f"    delta_disks: {self.sb_delta_disks}\n"
        ret += f"    new_layout: 0x{self.sb_new_layout:x}\n"
        ret += f"    new_chunk: {self.sb_new_chunk}\n"
        ret += "  this cmp dev info area\n"
        ret += f"    data_offset: {self.sb_data_offset}\n"
        ret += f"    data_size: {self.sb_data_size}\n"
        ret += f"    super_offset: {self.sb_super_offset}\n"
        ret += f"    recovery_offset: {self.sb_recovery_offset}\n"
        ret += f"    dev_number: {self.sb_dev_number}\n"
        ret += f"    cnt_corrected_read: {self.sb_cnt_corrected_read}\n"
        ret += f"    device_uuid: {self.sb_device_uuid.hex()}\n"
        ret += f"    devflags: {self.sb_devflags}\n"
        ret += "  array-state info area\n"
        ret += f"    utime: {self.sb_utime:.6f} s\n"
        ret += f"    events: {self.sb_events}\n"
        ret += f"    resync_offset: {self.sb_resync_offset}\n"
        ret += f"    sb_csum: 0x{self.sb_csum:x}\n"
        ret += f"    max_dev: {self.sb_max_dev}\n"
        ret += " device-roles area (0xffff = spare, 0xfffe = faulty)\n"
        for i in range(len(self.sb_disk_roles)):
            ret += f"    dev_role[{i}]: 0x{self.sb_disk_roles[i]:x}\n"
        return ret

if __name__ == '__main__':
    parser = argparse.ArgumentParser('MD array block device inspection utility')
    parser.add_argument('dev', help='block disk to scan for md superblock')
    parser.add_argument('--data', action='store_true',
                        help='Dump data region of raid disk')
    parser.add_argument('--start', type=int, default=0,
                        help='Start dumping data region from starting offset')
    parser.add_argument('--length', type=int, default=0,
                        help='Maximum number of bytes to dump, 0 will read to end of disk')
    args = parser.parse_args()

    md_dev = MDBlkDev(args.dev)

    if args.data:
        data_pos = args.start

        if args.length:
            data_len = args.length
        else:
            data_len = md_dev.sb_data_size * 512

        data_len = min(data_len, md_dev.sb_data_size * 512 - data_pos)

        while data_len:
            data = md_dev.read_data(data_pos, min(1 << 20, data_len))
            sys.stdout.buffer.write(data)
            data_len -= len(data)
            data_pos += len(data)
    else:
        print(md_dev, end='')
