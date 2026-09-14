import time
import os

# Initialize for MCP2221
os.environ["BLINKA_MCP2221"] = "1"
import board
import adafruit_mmc56x3

i2c = board.I2C()
sensor = adafruit_mmc56x3.MMC5603(i2c)

# --- ENTER YOUR CURRENT OUTDOOR BIAS HERE ---
# These are subtracted from raw readings to see if the error is 0
CURRENT_BIAS_X = 12.50 
CURRENT_BIAS_Y = -5.20
CURRENT_BIAS_Z = 8.10

def get_averaged_reading(samples=50):
    """Takes 50 readings quickly and returns the average to beat noise."""
    sx, sy, sz = 0, 0, 0
    for _ in range(samples):
        mx, my, mz = sensor.magnetic
        sx += mx
        sy += my
        sz += mz
        time.sleep(0.01)
    return (sx/samples) - CURRENT_BIAS_X, (sy/samples) - CURRENT_BIAS_Y, (sz/samples) - CURRENT_BIAS_Z

print("--- MAGNETOMETER BIAS CROSS-VALIDATION ---")
print("Place the sensor flat on a non-magnetic surface (wood/plastic).")

# STEP 1: BASELINE
input("\n[1] Point X-axis North (or any direction). Press Enter to capture...")
pos1_x, pos1_y, pos1_z = get_averaged_reading()
print(f"    Captured: X={pos1_x:.2f}, Y={pos1_y:.2f}, Z={pos1_z:.2f}")

# STEP 2: FLIP X and Y
print("\n[2] FLIP: Rotate 180 degrees horizontally (Z stays up, X points South).")
input("    Keep it in the EXACT same spot on the table. Press Enter...")
pos2_x, pos2_y, pos2_z = get_averaged_reading()
print(f"    Captured: X={pos2_x:.2f}, Y={pos2_y:.2f}, Z={pos2_z:.2f}")

# STEP 3: FLIP Z and X
print("\n[3] FLIP: Turn sensor upside down (Z points down, X points North).")
input("    Keep it in the EXACT same spot. Press Enter...")
pos3_x, pos3_y, pos3_z = get_averaged_reading()
print(f"    Captured: X={pos3_x:.2f}, Y={pos3_y:.2f}, Z={pos3_z:.2f}")

# --- CALCULATION ---
# Error is the midpoint between the flipped readings. 
# If offset was perfect, the midpoint would be 0.
error_x = (pos1_x + pos2_x) / 2
error_y = (pos1_y + pos2_y) / 2
error_z = (pos1_z + pos3_z) / 2 # Z comparison between Step 1 and Step 3

print("\n" + "="*40)
print("RESULTS (uT Error from Zero)")
print("="*40)
print(f"X Axis Error: {error_x:6.2f} uT")
print(f"Y Axis Error: {error_y:6.2f} uT")
print(f"Z Axis Error: {error_z:6.2f} uT")
print("-" * 40)
print("NEW SUGGESTED BIAS VALUES (Current + Error):")
print(f"NEW_OFFSET_X = {CURRENT_BIAS_X + error_x:.2f}")
print(f"NEW_OFFSET_Y = {CURRENT_BIAS_Y + error_y:.2f}")
print(f"NEW_OFFSET_Z = {CURRENT_BIAS_Z + error_z:.2f}")
print("="*40)