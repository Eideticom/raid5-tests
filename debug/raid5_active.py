#!/usr/bin/env drgn

import argparse
import sys

import md

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("disk", nargs="?", default="md0")
    args = parser.parse_args()

    try:
        mddev = md.find_mddev(prog, args.disk)
        conf = md.get_raid5_conf(mddev)

        print(f"Active Stripes:  {int(conf.active_stripes.counter)}")
        print(f"Max Stripes:     {int(conf.max_nr_stripes)}")
        print(f"Reshape Stripes: {int(conf.reshape_stripes.counter)}")
        print(f"Recovery Active: {int(mddev.recovery_active.counter)}")
        print(f"Quiesce:         {int(conf.quiesce)}")
        print()

        stripes = md.find_hashed_stripes(conf)
        print(f"Hashed Stripes: {len(stripes)}")

        state_map = {}
        for s in stripes:
            state_map.setdefault(hex(s.state), []).append(s)

        for state, lst in state_map.items():
            print(f"  -- State: {state} Count: {len(lst)}")

        non_lru_stripes = []
        for s in stripes:
            if md.list_empty(s.lru.address_of_()):
                non_lru_stripes.append(s)
        print(f"Hashed Stripes not in LRU: {len(non_lru_stripes)}")

        if non_lru_stripes:
            md.print_stripe_info(conf, non_lru_stripes[0])

    except md.MDException as e:
        print(e)
