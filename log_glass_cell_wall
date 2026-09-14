#!/usr/bin/env python3
"""
Log two MMC5603 magnetometers (each on its own MCP2221A USB->I2C
adapter) into two separate CSV files, "glass_cell" and "wall",
with one new file per calendar day (filename = the date).

For each 1-second window, samples are read from the sensor as fast
as the I2C bus allows, then averaged into a single data point for
that second.

Run identify_sensors.py first to find each board's HID path, then
fill in CONFIG below so the names always map to the correct
physical board, regardless of enumeration order or which USB port
order the OS reports.
"""

import os

os.environ["BLINKA_MCP2221"] = "1"
os.environ["BLINKA_MCP2221_RESET_DELAY"] = "-1"

import csv
import time
from datetime import datetime

import hid
import busio
import adafruit_mmc56x3

MCP2221_VID = 0x04D8
MCP2221_PID = 0x00DD

WINDOW_SECONDS = 1.0  # one averaged data point per second

# --- Fill these in after running: python identify_sensors.py --list ---
# Example: CONFIG = {b"2-3.3:1.2": "glass_cell", b"2-3.2:1.2": "wall"}
# Leave empty ({}) to fall back to enumeration order (1st found =
# glass_cell, 2nd = wall) -- NOT guaranteed stable across reboots/replugs.
CONFIG = {
    # b"<path from identify_sensors.py --list>": "glass_cell",
    # b"<path from identify_sensors.py --list>": "wall",
}


def find_mcp2221_paths():
    return [dev["path"] for dev in hid.enumerate(MCP2221_VID, MCP2221_PID)]


def resolve_names(paths):
    """Return a list of (path, name) pairs matching `paths`, in order."""
    if CONFIG:
        pairs = []
        for path in paths:
            if path in CONFIG:
                pairs.append((path, CONFIG[path]))
        missing = set(CONFIG.values()) - {n for _, n in pairs}
        if missing:
            raise RuntimeError(
                f"Configured sensor(s) not found on USB: {missing}. "
                "Check connections or re-run identify_sensors.py --list."
            )
        return pairs
    else:
        print(
            "WARNING: CONFIG is empty, falling back to enumeration order. "
            "This is NOT guaranteed stable -- run identify_sensors.py and "
            "fill in CONFIG for reliable naming."
        )
        fallback_names = ["glass_cell", "wall"]
        return list(zip(paths, fallback_names))


class DailyCSVWriter:
    """Writes rows to <base_name>_<YYYY-MM-DD>.csv, rotating at midnight
    and resuming (not overwriting) if a file for today already exists."""

    def __init__(self, base_name, header):
        self.base_name = base_name
        self.header = header
        self.current_date = None
        self.file = None
        self.writer = None

    def _rotate_if_needed(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self.current_date:
            if self.file:
                self.file.close()
            filename = f"{self.base_name}_{today}.csv"
            file_exists = os.path.exists(filename)
            self.file = open(filename, "a", newline="")
            self.writer = csv.writer(self.file)
            if not file_exists:
                self.writer.writerow(self.header)
            self.current_date = today
            action = "Resuming" if file_exists else "Created"
            print(f"[{self.base_name}] {action} {filename}")

    def write_row(self, row):
        self._rotate_if_needed()
        self.writer.writerow(row)
        self.file.flush()


def collect_window(sensors, window_s):
    """Read all sensors as fast as possible for window_s seconds.
    Returns a list (one per sensor) of lists of (x, y, z) samples."""
    samples = [[] for _ in sensors]
    start = time.monotonic()
    while time.monotonic() - start < window_s:
        for i, sensor in enumerate(sensors):
            try:
                samples[i].append(sensor.magnetic)
            except OSError:
                pass  # skip a dropped I2C read, keep sampling
    return samples


def average(samples):
    n = len(samples)
    if n == 0:
        return None, 0
    xs, ys, zs = zip(*samples)
    return (sum(xs) / n, sum(ys) / n, sum(zs) / n), n


def main():
    paths = find_mcp2221_paths()
    if len(paths) < 2:
        raise RuntimeError(f"Found {len(paths)} MCP2221 device(s), need 2.")

    pairs = resolve_names(paths)
    sensors = []
    loggers = []
    header = ["timestamp_s", "mag_x_uT", "mag_y_uT", "mag_z_uT", "n_samples"]

    for path, name in pairs:
        i2c = busio.I2C(bus_id=path)
        sensors.append(adafruit_mmc56x3.MMC5603(i2c))
        loggers.append(DailyCSVWriter(name, header))
        print(f"Bound {name} -> {path}")

    print(f"Logging 1 averaged point/sec per sensor. Ctrl+C to stop.\n")
    try:
        while True:
            samples = collect_window(sensors, WINDOW_SECONDS)
            ts = int(time.time())  # Unix epoch, seconds
            for i, (path, name) in enumerate(pairs):
                avg, n = average(samples[i])
                if avg is None:
                    print(f"[{name}] no samples this window, skipping")
                    continue
                loggers[i].write_row([ts, avg[0], avg[1], avg[2], n])
                print(f"[{name}] t={ts} x={avg[0]:.2f} y={avg[1]:.2f} z={avg[2]:.2f} (n={n})")
    except KeyboardInterrupt:
        print("\nStopped by user.")


if __name__ == "__main__":
    main()
