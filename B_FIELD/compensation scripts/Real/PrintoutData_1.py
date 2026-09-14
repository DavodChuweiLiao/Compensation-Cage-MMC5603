import time
import os

# Set Blinka environment variable for MCP2221
os.environ["BLINKA_MCP2221"] = "1"

import board
import adafruit_mmc56x3

i2c = board.I2C() 
sensor = adafruit_mmc56x3.MMC5603(i2c)

print("Degaussing sensor...")
sensor.set_reset()
print("Degauss complete.\n")

# Variables for our averaging loop
target_hz = 10.0
interval = 1.0 / target_hz  # 0.1 seconds per print

sum_x = 0.0
sum_y = 0.0
sum_z = 0.0
sample_count = 0

print("Starting 10Hz Oversampled Output...")

# Record the start time
last_print_time = time.monotonic()

while True:
    # 1. Read the raw data in micro-Teslas (uT)
    raw_x, raw_y, raw_z = sensor.magnetic


    OFFSET_X = 12.360
    OFFSET_Y = 18.990
    OFFSET_Z = -78.235

    mag_x = raw_x-OFFSET_X
    mag_y = raw_y-OFFSET_Y
    mag_z = raw_z-OFFSET_Z






    # 2. Add to our running totals
    sum_x += mag_x
    sum_y += mag_y
    sum_z += mag_z
    sample_count += 1
    
    # 3. Check if 0.1 seconds (10Hz) have passed
    current_time = time.monotonic()
    if current_time - last_print_time >= interval:
        
        # Calculate the average of all samples taken in the last 0.1s
        avg_x = sum_x / sample_count
        avg_y = sum_y / sample_count
        avg_z = sum_z / sample_count
        
        # Convert averages to milli-Gauss (mG)
        x_mG = avg_x * 10.0
        y_mG = avg_y * 10.0
        z_mG = avg_z * 10.0
        
        # Print the smoothed result (We can keep 1 decimal place now!)
        print(f"X: {x_mG:7.1f} mG | Y: {y_mG:7.1f} mG | Z: {z_mG:7.1f} mG   (Averaged {sample_count} samples)")
        
        # Reset totals and timers for the next 0.1 second block
        sum_x = 0.0
        sum_y = 0.0
        sum_z = 0.0
        sample_count = 0
        last_print_time = current_time