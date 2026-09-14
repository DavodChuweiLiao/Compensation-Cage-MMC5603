import time
import os

# Initialize for MCP2221
os.environ["BLINKA_MCP2221"] = "1"
import board
import adafruit_mmc56x3

i2c = board.I2C()
sensor = adafruit_mmc56x3.MMC5603(i2c)

# Clean the sensor internal domains before starting
sensor.set_reset()

def get_raw_average(samples=60):
    """Takes 60 raw samples to filter out any minor electrical noise."""
    sx, sy, sz = 0, 0, 0
    for _ in range(samples):
        mx, my, mz = sensor.magnetic
        sx += mx
        sy += my
        sz += mz
        time.sleep(0.01)
    return (sx/samples), (sy/samples), (sz/samples)

# Definitions of the 8 orientations
steps = [
    {"label": "X North, Y West, Z Up", "desc": "Flat on table, chip facing ceiling."},
    {"label": "X East, Y North, Z Up", "desc": "Flat, rotate 90 deg clockwise."},
    {"label": "X South, Y East, Z Up", "desc": "Flat, rotate 90 deg clockwise again."},
    {"label": "X West, Y South, Z Up", "desc": "Flat, rotate 90 deg clockwise again."},
    {"label": "X North, Y East, Z Down", "desc": "FLIP OVER. Chip facing table. X forward."},
    {"label": "X East, Y South, Z Down", "desc": "Upside down, rotate 90 deg clockwise."},
    {"label": "X South, Y West, Z Down", "desc": "Upside down, rotate 90 deg clockwise again."},
    {"label": "X West, Y North, Z Down", "desc": "Upside down, rotate 90 deg clockwise again."},
]

data_points = []

print("--- 8-POINT PRECISION TUMBLE CALIBRATION ---")
print("Place the sensor on a flat, elevated non-magnetic surface.")

for i, step in enumerate(steps):
    print(f"\n[STEP {i+1}/8]: {step['label']}")
    print(f"Instruction: {step['desc']}")
    input("Press Enter when positioned and perfectly still...")
    
    print("Capturing...")
    avg_x, avg_y, avg_z = get_raw_average()
    data_points.append((avg_x, avg_y, avg_z))
    print(f"Captured: X={avg_x:.2f}, Y={avg_y:.2f}, Z={avg_z:.2f}")

# --- MATH ---
# In a perfect 360-degree rotation across both faces, 
# the external field (Earth) sums to zero. The average is the bias.
final_bias_x = sum(d[0] for d in data_points) / 8
final_bias_y = sum(d[1] for d in data_points) / 8
final_bias_z = sum(d[2] for d in data_points) / 8

print("\n" + "="*50)
print("FINAL GROUND TRUTH BIAS RESULTS")
print("="*50)
print(f"Use these values in your compensation code:")
print(f"OFFSET_X = {final_bias_x:.3f}")
print(f"OFFSET_Y = {final_bias_y:.3f}")
print(f"OFFSET_Z = {final_bias_z:.3f}")
print("="*50)
print("Calibration Complete.")