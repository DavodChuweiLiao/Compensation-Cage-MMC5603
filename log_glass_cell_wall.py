#!/usr/bin/env python3
"""
MMC5603 dual-sensor B-field logger over two MCP2221A USB-I2C bridges.

Reads two MMC5603 magnetometers (one at the glass cell, one at the wall),
converts native sensor axes into lab coordinates, averages over a time
window, and appends to daily CSV files.

Usage:
    python mmc5603_dual_logger.py --list-devices
    python mmc5603_dual_logger.py
    python mmc5603_dual_logger.py --window 2.0 --output-dir D:\\data

Environment overrides (useful when USB ports change):
    MMC_GLASS_HID_PATH, MMC_WALL_HID_PATH
"""

import os

# Blinka reads these at import time, so they must be set first.
os.environ.setdefault("BLINKA_MCP2221", "1")
os.environ.setdefault("BLINKA_MCP2221_RESET_DELAY", "-1")

import argparse
import csv
import math
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import hid
import adafruit_mmc56x3

from adafruit_blinka.microcontroller.mcp2221.mcp2221 import MCP2221 as _MCP2221


# ============================================================
# CONFIGURATION
# ============================================================

MCP2221_VID = 0x04D8
MCP2221_PID = 0x00DD

# MCP2221A exposes several HID interfaces; the control interface
# we want reports this usage page. Filtering on it stops the same
# physical device from appearing two or three times.
MCP2221_USAGE_PAGE = 0xFF00

I2C_FREQUENCY = 100_000
AVERAGING_WINDOW_S = 1.0

# Abort if a sensor fails this many reads in a row. At full speed a
# dead USB device produces errors in a tight loop, so this stops the
# logger instead of filling the console and the disk.
MAX_CONSECUTIVE_ERRORS = 50

# Blinka reports MMC5603 values in microtesla. 1 uT = 10 mG.
UT_TO_MG = 10.0

DEFAULT_OUTPUT_DIRECTORY = Path(
    r"C:\Users\jolab\OneDrive\Documents\B_FieldLogging\MMC5603_glasscell_wall"
)

# NOTE: these are raw byte strings. A Windows HID path begins with the
# four characters \\?\ -- writing it as a non-raw literal silently eats
# a backslash and the path will never match anything hid.enumerate()
# returns.
DEFAULT_GLASS_CELL_HID_PATH = (
    rb"\\?\HID#VID_04D8&PID_00DD&MI_02"
    rb"#a&cc2a97&0&0000"
    rb"#{4d1e55b2-f16f-11cf-88cb-001111000030}"
)

DEFAULT_WALL_HID_PATH = (
    rb"\\?\HID#VID_04D8&PID_00DD&MI_02"
    rb"#9&92a1a44&0&0000"
    rb"#{4d1e55b2-f16f-11cf-88cb-001111000030}"
)

CSV_HEADER = [
    "timestamp_s",
    "timestamp_iso",
    "mag_x_lab_mG",
    "mag_y_lab_mG",
    "mag_z_lab_mG",
    "std_x_mG",
    "std_y_mG",
    "std_z_mG",
    "n_samples",
    "n_errors",
]


# ============================================================
# SENSOR COORDINATE TRANSFORMATIONS
# ============================================================

# Each entry maps a lab axis to (native axis index, sign).
# Native order is (x, y, z) = (0, 1, 2).
AXIS_MAPS = {
    "glass_cell": (
        (1, -1.0),  # lab_x = -raw_y
        (2, +1.0),  # lab_y = +raw_z
        (0, -1.0),  # lab_z = -raw_x
    ),
    "wall": (
    (2, -1.0),  # lab_x = -raw_z
    (0, +1.0),  # lab_y = +raw_x
    (1, -1.0),  # lab_z = -raw_y
    ),
}


def convert_to_lab(sensor_name, raw):
    """Convert native MMC5603 axes into laboratory coordinates."""
    try:
        axis_map = AXIS_MAPS[sensor_name]
    except KeyError:
        raise ValueError(
            f"Unknown sensor name: {sensor_name!r}. "
            f"Known: {sorted(AXIS_MAPS)}"
        ) from None

    return tuple(sign * raw[index] for index, sign in axis_map)


# ============================================================
# MCP2221A DEVICE
# ============================================================

class MCP2221Device(_MCP2221):
    """
    One specific MCP2221A, opened by HID path.

    The stock Blinka MCP2221 support keeps a single module-level device,
    which makes two adapters in one process impossible. Bypassing the
    parent __init__ is the workaround.

    CAUTION: this depends on Blinka internals (_hid, _gp_config,
    _i2c_configure). Verify against adafruit_blinka after any upgrade.
    """

    def __init__(self, hid_path):
        self._hid = hid.device()
        self._hid.open_path(hid_path)
        self._gp_config = [0x07] * 4
        self.hid_path = hid_path

    def close(self):
        if self._hid is None:
            return
        try:
            self._hid.close()
        except Exception:
            pass
        finally:
            self._hid = None


# ============================================================
# INDEPENDENT MCP2221 I2C WRAPPER
# ============================================================

class MCP2221I2C:
    """
    CircuitPython-compatible I2C interface bound to one MCP2221A,
    avoiding the global object the normal Blinka implementation uses.
    """

    def __init__(self, mcp2221_device, frequency=I2C_FREQUENCY):
        self._mcp2221 = mcp2221_device
        self._mcp2221._i2c_configure(frequency)
        self._locked = False

    def try_lock(self):
        if self._locked:
            return False
        self._locked = True
        return True

    def unlock(self):
        self._locked = False

    def scan(self):
        return self._mcp2221.i2c_scan()

    def writeto(self, address, buffer, *, start=0, end=None, stop=True):
        # `stop` is accepted for API compatibility. The MCP2221 firmware
        # always issues a stop on a plain write, so it cannot be honoured.
        self._mcp2221.i2c_writeto(address, buffer, start=start, end=end)

    def readfrom_into(self, address, buffer, *, start=0, end=None):
        self._mcp2221.i2c_readfrom_into(address, buffer, start=start, end=end)

    def writeto_then_readfrom(
        self,
        address,
        buffer_out,
        buffer_in,
        *,
        out_start=0,
        out_end=None,
        in_start=0,
        in_end=None,
        stop=False,
    ):
        self._mcp2221.i2c_writeto_then_readfrom(
            address,
            buffer_out,
            buffer_in,
            out_start=out_start,
            out_end=out_end,
            in_start=in_start,
            in_end=in_end,
        )


# ============================================================
# HID DISCOVERY
# ============================================================

def enumerate_mcp2221():
    """Return the MCP2221A control interfaces currently attached."""
    return [
        device
        for device in hid.enumerate(MCP2221_VID, MCP2221_PID)
        if device.get("usage_page") in (MCP2221_USAGE_PAGE, None)
    ]


def print_detected_devices(stream=sys.stdout):
    devices = enumerate_mcp2221()

    print("\nDetected MCP2221A devices:", file=stream)

    if not devices:
        print("  None found.", file=stream)
        return

    for index, device in enumerate(devices):
        serial = device.get("serial_number") or "<none>"
        print(f"  [{index}] serial={serial}", file=stream)
        print(f"       path={device['path']!r}", file=stream)


def verify_configured_paths(paths_by_sensor):
    """Raise unless every configured HID path is actually present."""
    connected = {device["path"] for device in enumerate_mcp2221()}

    missing = [
        name for name, path in paths_by_sensor.items() if path not in connected
    ]

    if missing:
        print_detected_devices()
        raise RuntimeError(
            "Missing configured sensor(s): "
            + ", ".join(missing)
            + ". Re-run with --list-devices and update the HID paths "
              "(they change when a device moves to a different USB port)."
        )


# ============================================================
# DAILY CSV WRITER
# ============================================================

class DailyCSVWriter:
    def __init__(self, directory, base_name, header=CSV_HEADER):
        self.directory = Path(directory)
        self.base_name = base_name
        self.header = list(header)

        self.directory.mkdir(parents=True, exist_ok=True)

        self.current_date = None
        self.file = None
        self.writer = None

        self.rotate_if_needed()

    def _existing_header(self, path):
        """Return the header row of an existing CSV, or None."""
        if not path.exists() or path.stat().st_size == 0:
            return None
        try:
            with open(path, "r", newline="", encoding="utf-8") as handle:
                return next(csv.reader(handle), None)
        except OSError:
            return None

    def _target_path(self, date_string):
        """
        Pick today's file, avoiding appending rows to a file whose header
        does not match ours -- that would produce a silently mixed schema.
        """
        candidate = self.directory / f"{self.base_name}_{date_string}.csv"
        existing = self._existing_header(candidate)

        if existing is None or existing == self.header:
            return candidate, existing is not None

        stamp = datetime.now().strftime("%H%M%S")
        fallback = self.directory / f"{self.base_name}_{date_string}_{stamp}.csv"
        print(
            f"\n  Header mismatch in {candidate.name}; "
            f"writing to {fallback.name} instead."
        )
        return fallback, False

    def rotate_if_needed(self):
        date_string = datetime.now().strftime("%Y-%m-%d")

        if date_string == self.current_date:
            return

        if self.file is not None:
            self.file.flush()
            self.file.close()
            self.file = None

        path, has_header = self._target_path(date_string)

        self.file = open(path, "a", newline="", encoding="utf-8")
        self.writer = csv.writer(self.file)

        if not has_header:
            self.writer.writerow(self.header)
            self.file.flush()

        # Only set once the new file is actually open, so a failed
        # rotation retries instead of leaving a stale date recorded.
        self.current_date = date_string

        print(f"\nWriting {self.base_name} data to:")
        print(f"  {path}")

    def write(self, row):
        self.rotate_if_needed()
        self.writer.writerow(row)
        self.file.flush()

    def close(self):
        if self.file is not None:
            self.file.flush()
            self.file.close()
            self.file = None


# ============================================================
# SENSOR READING
# ============================================================

def read_sensor_lab_mG(sensor_name, sensor):
    """One sample, in lab coordinates, in milligauss."""
    raw_uT = sensor.magnetic
    raw_mG = tuple(value * UT_TO_MG for value in raw_uT)
    return convert_to_lab(sensor_name, raw_mG)


def mean_and_std(values):
    count = len(values)
    mean = sum(values) / count

    if count < 2:
        return mean, 0.0

    variance = sum((value - mean) ** 2 for value in values) / (count - 1)
    return mean, math.sqrt(variance)


class SensorChannel:
    """One magnetometer plus its accumulating window statistics."""

    def __init__(self, name, sensor, writer):
        self.name = name
        self.sensor = sensor
        self.writer = writer
        self.consecutive_errors = 0
        self.reset_window()

    def reset_window(self):
        self.samples = []
        self.errors = 0
        self.last_error_report = 0.0

    def sample(self):
        try:
            self.samples.append(read_sensor_lab_mG(self.name, self.sensor))
            self.consecutive_errors = 0
        except Exception as error:
            self.errors += 1
            self.consecutive_errors += 1

            # Rate-limit the console so a disconnected device does not
            # drown everything else.
            now = time.monotonic()
            if now - self.last_error_report > 1.0:
                self.last_error_report = now
                print(
                    f"  {self.name}: read error "
                    f"({self.consecutive_errors} in a row): {error}"
                )

            if self.consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                raise RuntimeError(
                    f"{self.name} failed {self.consecutive_errors} "
                    f"consecutive reads; last error: {error}"
                ) from error

    def summarize(self):
        """Return (means, stds, n) for the window, or None if it was empty."""
        if not self.samples:
            return None

        means = []
        stds = []
        for axis in range(3):
            mean, std = mean_and_std([sample[axis] for sample in self.samples])
            means.append(mean)
            stds.append(std)

        return means, stds, len(self.samples)


def collect_window(channels, window_s, sample_interval_s):
    """
    Sample every channel inside one shared window.

    Reading the sensors in an interleaved loop (rather than one full
    window each, back to back) keeps their rows genuinely simultaneous
    and keeps the loop period equal to the window length.
    """
    for channel in channels:
        channel.reset_window()

    start_wall = time.time()
    start = time.monotonic()

    while time.monotonic() - start < window_s:
        for channel in channels:
            channel.sample()

        if sample_interval_s > 0:
            time.sleep(sample_interval_s)

    elapsed = time.monotonic() - start

    # Midpoint of the window is the right timestamp for an average.
    return start_wall + elapsed / 2.0


# ============================================================
# MAIN
# ============================================================

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Dual MMC5603 B-field logger over two MCP2221A bridges."
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="print attached MCP2221A devices and exit",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.environ.get("MMC_OUTPUT_DIR", DEFAULT_OUTPUT_DIRECTORY)),
        help="directory for the daily CSV files",
    )
    parser.add_argument(
        "--window",
        type=float,
        default=AVERAGING_WINDOW_S,
        metavar="SECONDS",
        help="averaging window length (default: %(default)s)",
    )
    parser.add_argument(
        "--sample-interval",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="delay between sample passes; 0 means as fast as USB allows",
    )
    parser.add_argument(
        "--i2c-frequency",
        type=int,
        default=I2C_FREQUENCY,
        help="I2C bus frequency in Hz (default: %(default)s)",
    )
    return parser.parse_args(argv)


def resolve_hid_paths():
    def from_env(variable, default):
        value = os.environ.get(variable)
        return value.encode("utf-8") if value else default

    return {
        "glass_cell": from_env("MMC_GLASS_HID_PATH", DEFAULT_GLASS_CELL_HID_PATH),
        "wall": from_env("MMC_WALL_HID_PATH", DEFAULT_WALL_HID_PATH),
    }


def build_row(timestamp_s, summary, errors):
    means, stds, count = summary
    return [
        f"{timestamp_s:.6f}",
        datetime.fromtimestamp(timestamp_s).isoformat(timespec="milliseconds"),
        f"{means[0]:.6f}",
        f"{means[1]:.6f}",
        f"{means[2]:.6f}",
        f"{stds[0]:.6f}",
        f"{stds[1]:.6f}",
        f"{stds[2]:.6f}",
        count,
        errors,
    ]


def main(argv=None):
    args = parse_args(argv)

    if args.list_devices:
        print_detected_devices()
        return 0

    if args.window <= 0:
        print("--window must be positive.", file=sys.stderr)
        return 2

    print("\n==============================================")
    print("MMC5603 Dual-Sensor B-Field Logger")
    print("==============================================")

    hid_paths = resolve_hid_paths()

    print("\nChecking MCP2221A devices...")
    verify_configured_paths(hid_paths)

    # SIGTERM (service stop, shutdown) should shut down as cleanly as Ctrl+C.
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))

    devices = {}
    writers = {}

    try:
        channels = []

        for name in ("glass_cell", "wall"):
            print(f"\nOpening {name} MCP2221A...")
            device = MCP2221Device(hid_paths[name])
            devices[name] = device

            i2c = MCP2221I2C(device, frequency=args.i2c_frequency)

            print(f"Initializing {name} MMC5603...")
            sensor = adafruit_mmc56x3.MMC5603(i2c)

            found = i2c.scan()
            print(f"  I2C scan: {[hex(address) for address in found]}")

            writers[name] = DailyCSVWriter(args.output_dir, name)
            channels.append(SensorChannel(name, sensor, writers[name]))

        print("\nSensor initialization successful.")
        print(f"Window: {args.window} s")
        print("\nLogging started. Press Ctrl+C to stop.\n")

        while True:
            timestamp_s = collect_window(
                channels, args.window, args.sample_interval
            )
            clock = datetime.fromtimestamp(timestamp_s).strftime("%H:%M:%S")

            for channel in channels:
                summary = channel.summarize()

                if summary is None:
                    print(
                        f"[{clock}] {channel.name}: no valid samples "
                        f"({channel.errors} errors) -- row skipped"
                    )
                    continue

                channel.writer.write(
                    build_row(timestamp_s, summary, channel.errors)
                )

                means, stds, count = summary
                print(
                    f"[{clock}] {channel.name:<10} "
                    f"X={means[0]:10.3f} "
                    f"Y={means[1]:10.3f} "
                    f"Z={means[2]:10.3f} mG  "
                    f"(sd {stds[0]:.3f}/{stds[1]:.3f}/{stds[2]:.3f}, "
                    f"N={count}, err={channel.errors})"
                )

            print()

    except KeyboardInterrupt:
        print("\nStopping logger...")
        return 0

    except RuntimeError as error:
        print(f"\nFATAL: {error}", file=sys.stderr)
        return 1

    finally:
        print("Closing CSV files...")
        for writer in writers.values():
            writer.close()

        print("Closing MCP2221A devices...")
        for device in devices.values():
            device.close()

        print("Logger stopped.")


if __name__ == "__main__":
    sys.exit(main())
