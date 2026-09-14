# Save as: bfield_logger_server.py
import time
import os
import csv
import socket
import json
import datetime
import msvcrt  # Built-in Windows library for non-blocking keyboard input

# Initialize hardware
os.environ["BLINKA_MCP2221"] = "1"
import board
import adafruit_mmc56x3

i2c = board.I2C()
sensor = adafruit_mmc56x3.MMC5603(i2c)

print("[*] Performing initial sensor degauss...")
sensor.set_reset()
print("[*] Degauss complete.")

# --- YOUR GROUND TRUTH OFFSETS (In Sensor Coordinates) ---
OFFSET_X = 12.360
OFFSET_Y = 18.990
OFFSET_Z = -78.235

# --- COORDINATE TRANSFORMATION FUNCTION ---
def sensor_to_lab(sx, sy, sz):
    """
    Converts local sensor coordinates to global lab coordinates.
    Based on mapping: sensor_x = -REALz | sensor_y = REALx | sensor_z = -REALy
    """
    real_x = sy
    real_y = -sz
    real_z = -sx
    return real_x, real_y, real_z

# Setup Local UDP Broadcasting
UDP_IP = "127.0.0.1" # Localhost (your computer only)
UDP_PORT = 5555      # The "channel" we are broadcasting on
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# --- FOLDER SETUP ---
LOG_DIR = "b_field_files"
os.makedirs(LOG_DIR, exist_ok=True) # Creates the folder if it doesn't exist

print(f"[*] Starting background logger...")
print(f"[*] Broadcasting live LAB coordinates on port {UDP_PORT}")
print("[*] ===========================================")
print("[*] PRESS 'd' AT ANY TIME TO MANUALLY DEGAUSS")
print("[*] PRESS CTRL+C TO QUIT SAFELY")
print("[*] ===========================================")

# --- INITIAL FILE SETUP ---
current_date = datetime.date.today().strftime("%Y-%m-%d")
filename = f"bfield_data_{current_date}.csv"
filepath = os.path.join(LOG_DIR, filename)

print(f"[*] Logging to initial file: {filepath}")

# Open the file inside the log directory
f = open(filepath, 'a', newline='')
writer = csv.writer(f)
if f.tell() == 0:
    # Header updated to reflect Lab Coordinates
    writer.writerow(['Timestamp', 'Lab_X_mG', 'Lab_Y_mG', 'Lab_Z_mG'])

# --- LOOP TIMING & DEGAUSS SETUP ---
loop_count = 0
TARGET_LOOP_TIME = 0.01  # 10 milliseconds (100 Hz)
DEGAUSS_INTERVAL = 600   # 10 minutes (in seconds)
PRINT_INTERVAL = 5.0     # 5 seconds

last_degauss_time = time.time()
last_print_time = time.time()

try:
    while True:
        # Mark the exact time the loop started
        loop_start_time = time.time()

        # --- 1. NON-BLOCKING KEYBOARD INPUT ---
        if msvcrt.kbhit():
            try:
                # Read the key pressed, ignore weird keys like arrows
                key = msvcrt.getch().decode('utf-8', errors='ignore').lower()
                if key == 'd':
                    print("\n[*] --- MANUAL DEGAUSS TRIGGERED ---")
                    try:
                        sensor.set_reset()
                    except (OSError, RuntimeError):
                        print("[!] I2C busy/EMI spike, manual degauss skipped.")
                    # Reset the 10-minute automatic timer
                    last_degauss_time = time.time() 
            except Exception:
                pass

        # --- 2. CHECK FOR MIDNIGHT (FILE ROTATION) ---
        new_date = datetime.date.today().strftime("%Y-%m-%d")
        if new_date != current_date:
            print(f"\n[*] Midnight reached! Closing {filename}...")
            f.close() # Safely close yesterday's file
            
            # Update date and create new filepath
            current_date = new_date
            filename = f"bfield_data_{current_date}.csv"
            filepath = os.path.join(LOG_DIR, filename)
            
            print(f"[*] Now logging to new file: {filepath}")
            
            f = open(filepath, 'a', newline='')
            writer = csv.writer(f)
            writer.writerow(['Timestamp', 'Lab_X_mG', 'Lab_Y_mG', 'Lab_Z_mG'])

        # --- 3. DEGAUSS SENSOR EVERY 10 MINUTES ---
        if time.time() - last_degauss_time >= DEGAUSS_INTERVAL:
            try:
                sensor.set_reset()
            except (OSError, RuntimeError):
                pass # Ignore if EMI happens right as we try to degauss
            last_degauss_time = time.time()

        # --- 4. READ AND CORRECT SENSOR (WITH EMI SAFETY NET) ---
        try:
            raw_x, raw_y, raw_z = sensor.magnetic
        except (OSError, RuntimeError) as e:
            time.sleep(0.005) 
            continue 

        # Correct offsets and convert to mG (Still in Sensor Coordinates)
        sx = (raw_x - OFFSET_X) * 10.0
        sy = (raw_y - OFFSET_Y) * 10.0
        sz = (raw_z - OFFSET_Z) * 10.0

        # --- 5. TRANSFORM TO LAB COORDINATES ---
        real_x, real_y, real_z = sensor_to_lab(sx, sy, sz)

        # --- 6. BROADCAST IMMEDIATELY (Full precision Lab Coords for PID) ---
        payload = json.dumps({"x": real_x, "y": real_y, "z": real_z}).encode('utf-8')
        sock.sendto(payload, (UDP_IP, UDP_PORT))

        # --- 7. FORMAT AND WRITE TO CSV ---
        writer.writerow([f"{time.time():.3f}", f"{real_x:.2f}", f"{real_y:.2f}", f"{real_z:.2f}"])
        
        loop_count += 1
        if loop_count >= 100:
            f.flush()
            loop_count = 0
            
        # --- 8. PRINT TO TERMINAL EVERY 5 SECONDS ---
        if time.time() - last_print_time >= PRINT_INTERVAL:
            print(f"[*] Lab Data -> X: {real_x:7.2f} mG | Y: {real_y:7.2f} mG | Z: {real_z:7.2f} mG")
            last_print_time = time.time()
                
        # --- 9. DYNAMIC SLEEP FOR STRICT 100Hz TIMING ---
        time_spent = time.time() - loop_start_time 
        time_left_to_sleep = TARGET_LOOP_TIME - time_spent
        
        if time_left_to_sleep > 0:
            time.sleep(time_left_to_sleep)
            
except KeyboardInterrupt:
    print("\n[*] Logger stopped manually via CTRL+C.")
except Exception as e:
    print(f"\n[!] LOGGER CRASHED due to an unexpected error: {e}")
finally:
    print("[*] Safely closing the current log file...")
    try:
        f.close()
    except:
        pass
    print("[*] Hardware released. Goodbye.")