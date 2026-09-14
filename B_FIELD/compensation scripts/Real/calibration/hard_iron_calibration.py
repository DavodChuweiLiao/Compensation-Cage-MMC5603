import time
import os

# Tell Blinka we are using the MCP2221 adapter
os.environ["BLINKA_MCP2221"] = "1"

import board
import adafruit_mmc56x3

# Initialize the I2C bus and sensor
i2c = board.I2C() 
sensor = adafruit_mmc56x3.MMC5603(i2c)

# Degauss the sensor before calibrating to ensure a clean slate
print("Degaussing...")
sensor.set_reset()

# Start with extreme opposite values so they are immediately overwritten
min_x = min_y = min_z = 99999.0
max_x = max_y = max_z = -99999.0

print("\n--- CALIBRATION MODE ---")
print("Slowly rotate the sensor in all 3D directions (Figure-8 pattern).")
print("Press CTRL+C when the numbers stop changing.\n")

try:
    while True:
        # Read raw data
        mag_x, mag_y, mag_z = sensor.magnetic
        
        # Check for new minimums
        min_x = min(min_x, mag_x)
        min_y = min(min_y, mag_y)
        min_z = min(min_z, mag_z)
        
        # Check for new maximums
        max_x = max(max_x, mag_x)
        max_y = max(max_y, mag_y)
        max_z = max(max_z, mag_z)
        
        # Calculate the center offset dynamically
        offset_x = (max_x + min_x) / 2.0
        offset_y = (max_y + min_y) / 2.0
        offset_z = (max_z + min_z) / 2.0
        
        # Print over the same line repeatedly so it doesn't flood your screen
        print(f"Current Bias -> X: {offset_x:6.2f} | Y: {offset_y:6.2f} | Z: {offset_z:6.2f} uT", end='\r')
        time.sleep(0.05)

except KeyboardInterrupt:
    print("\n\n--- CALIBRATION COMPLETE ---")
    print("Copy these numbers into your main tracking code:")
    print(f"OFFSET_X = {offset_x:.2f}")
    print(f"OFFSET_Y = {offset_y:.2f}")
    print(f"OFFSET_Z = {offset_z:.2f}")