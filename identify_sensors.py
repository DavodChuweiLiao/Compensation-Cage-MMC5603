#!/usr/bin/env python3
"""
Identify / test script for two MCP2221A + MMC5603 boards.

Use this BEFORE running the logger to figure out which physical
USB port / board is "glass_cell" and which is "wall".

Usage:
    python identify_sensors.py --list
        Lists every MCP2221 found, with its unique HID path.

    python identify_sensors.py --one 1
    python identify_sensors.py --one 2
        Opens ONLY the 1st or 2nd MCP2221 found and streams live
        magnetometer readings from it. Move a magnet near one
        physical board while running --one 1, then again while
        running --one 2 (unplug nothing in between) to see which
        index corresponds to which board.

    python identify_sensors.py --both
        Opens both at once and streams readings side by side, so
        you can wave a magnet at one board and watch which column
        reacts, without having to swap scripts.

Once you know which HID path is which board, copy the paths into
the CONFIG dict at the top of log_glass_cell_wall.py.
"""

import os

os.environ["BLINKA_MCP2221"] = "1"
os.environ["BLINKA_MCP2221_RESET_DELAY"] = "-1"

import argparse
import time

import hid
import busio
import adafruit_mmc56x3

MCP2221_VID = 0x04D8
MCP2221_PID = 0x00DD

UT_TO_MG = 10.0  # 1 microtesla = 10 milligauss


def find_mcp2221_paths():
    return [dev["path"] for dev in hid.enumerate(MCP2221_VID, MCP2221_PID)]


def open_sensor(path):
    i2c = busio.I2C(bus_id=path)
    return adafruit_mmc56x3.MMC5603(i2c)


def list_devices(paths):
    if not paths:
        print("No MCP2221 devices found. Check USB connections.")
        return
    print(f"Found {len(paths)} MCP2221 device(s):")
    for idx, path in enumerate(paths, start=1):
        print(f"  [{idx}] path={path}")


def stream_one(paths, index):
    if index < 1 or index > len(paths):
        print(f"Index {index} out of range (found {len(paths)} devices).")
        return
    path = paths[index - 1]
    print(f"Opening device [{index}] path={path}")
    sensor = open_sensor(path)
    print("Streaming readings. Wave a magnet near the board you're testing. Ctrl+C to stop.\n")
    try:
        while True:
            x, y, z = sensor.magnetic
            x, y, z = x * UT_TO_MG, y * UT_TO_MG, z * UT_TO_MG
            print(f"[{index}] x={x:8.2f}  y={y:8.2f}  z={z:8.2f} mG")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopped.")


def stream_both(paths):
    if len(paths) < 2:
        print(f"Found {len(paths)} device(s), need 2 for --both.")
        return
    print(f"Device [1] path={paths[0]}")
    print(f"Device [2] path={paths[1]}")
    s1 = open_sensor(paths[0])
    s2 = open_sensor(paths[1])
    print("Streaming both. Wave a magnet near one board and watch which column moves. Ctrl+C to stop.\n")
    try:
        while True:
            x1, y1, z1 = s1.magnetic
            x2, y2, z2 = s2.magnetic
            x1, y1, z1 = x1 * UT_TO_MG, y1 * UT_TO_MG, z1 * UT_TO_MG
            x2, y2, z2 = x2 * UT_TO_MG, y2 * UT_TO_MG, z2 * UT_TO_MG
            print(
                f"[1] x={x1:8.2f} y={y1:8.2f} z={z1:8.2f}  |  "
                f"[2] x={x2:8.2f} y={y2:8.2f} z={z2:8.2f}  (mG)"
            )
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopped.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="List connected MCP2221 devices")
    group.add_argument("--one", type=int, metavar="N", help="Stream only device N (1 or 2)")
    group.add_argument("--both", action="store_true", help="Stream both devices at once")
    args = parser.parse_args()

    paths = find_mcp2221_paths()

    if args.list:
        list_devices(paths)
    elif args.one is not None:
        stream_one(paths, args.one)
    elif args.both:
        stream_both(paths)


if __name__ == "__main__":
    main()
