import time
import numpy as np
from smbus2 import SMBus
import pyvisa

# ------------------------------
# Configuration
# ------------------------------
COIL_K_X = 100.0  
COIL_K_Y = 100.0
COIL_K_Z = 100.0

# PID Tuning (The proven parameters)
KP = 0.1 / COIL_K_X  
KI = 2.5 / COIL_K_X   
KD = 0.0              

# Hardware connections
I2C_BUS = 1            # Usually 1 on Raspberry Pi / Linux DAQs
SENSOR_ADDR = 0x30     # Your specific sensor address
TARGET_HZ = 10.0       # Control loop speed (10 Hz = 0.1s dt)

# ------------------------------
# PID Controller Class
# ------------------------------
class PIDController:
    def __init__(self, kp, ki, kd, setpoint=0.0, output_limit=None):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint
        self.output_limit = output_limit
        self.integral = 0.0
        self.prev_error = 0.0

    def compute(self, measurement, dt):
        if dt <= 0.0: return 0.0
        error = self.setpoint - measurement
        
        p_term = self.kp * error
        self.integral += error * dt
        i_term = self.ki * self.integral
        
        d_term = self.kd * ((error - self.prev_error) / dt)
        self.prev_error = error
        
        output = p_term + i_term + d_term
        
        if self.output_limit is not None:
            if output > self.output_limit:
                output = self.output_limit
                self.integral -= error * dt 
            elif output < -self.output_limit:
                output = -self.output_limit
                self.integral -= error * dt 
        return output

# ------------------------------
# Hardware Interface Functions
# ------------------------------
def setup_kepco():
    """Connects to the Kepco BOP Power Supply via VISA"""
    rm = pyvisa.ResourceManager()
    
    # Update this string with your actual Kepco VISA address (e.g., 'GPIB0::6::INSTR' or 'ASRL3::INSTR')
    # If you aren't sure, run print(rm.list_resources()) to find it.
    kepco = rm.open_resource('GPIB0::6::INSTR') 
    
    # Configure Kepco to Current (Amps) mode and turn output on
    kepco.write("FUNC:MODE CURR")
    kepco.write("OUTP ON")
    return kepco

def read_sensor(bus):
    """
    Reads the I2C sensor at 0x30. 
    You will need to replace the register addresses (0x00 to 0x05) 
    with the actual data registers from your sensor's datasheet.
    """
    try:
        # Read 6 bytes of data (Assuming 16 or 20-bit data spread across bytes)
        # Register 0x00 is a placeholder for the start of the data registers.
        data = bus.read_i2c_block_data(SENSOR_ADDR, 0x00, 6)
        
        # Combine bytes (Standard 16-bit signed conversion example)
        # Check your datasheet for exact bit-shifting (especially since yours is 20-bit!)
        raw_x = (data[1] << 8) | data[0]
        raw_y = (data[3] << 8) | data[2]
        raw_z = (data[5] << 8) | data[4]
        
        # Convert to signed integer if necessary
        if raw_x > 32767: raw_x -= 65536
        if raw_y > 32767: raw_y -= 65536
        if raw_z > 32767: raw_z -= 65536
        
        # Convert LSB to milliGauss (You stated 0.0625 mG per LSB)
        resolution = 0.0625
        mG_x = raw_x * resolution
        mG_y = raw_y * resolution
        mG_z = raw_z * resolution
        
        return mG_x, mG_y, mG_z
    
    except Exception as e:
        print(f"I2C Read Error: {e}")
        return 0.0, 0.0, 0.0

# ------------------------------
# Main Execution
# ------------------------------
if __name__ == "__main__":
    print("Initializing Hardware...")
    
    # 1. Initialize I2C Bus
    bus = SMBus(I2C_BUS)
    
    # 2. Initialize Kepco Power Supply
    # kepco = setup_kepco() # Uncomment when plugged in!
    
    # 3. Initialize Controllers
    pid_x = PIDController(kp=KP, ki=KI, kd=KD, setpoint=0.0, output_limit=20.0)
    pid_y = PIDController(kp=KP, ki=KI, kd=KD, setpoint=0.0, output_limit=20.0)
    pid_z = PIDController(kp=KP, ki=KI, kd=KD, setpoint=0.0, output_limit=20.0)
    
    dt = 1.0 / TARGET_HZ
    
    print("Starting Active Cancellation Loop. Press Ctrl+C to stop.")
    try:
        while True:
            loop_start_time = time.time()
            
            # --- 1. SENSE ---
            mag_x, mag_y, mag_z = read_sensor(bus)
            
            # --- 2. COMPUTE ---
            cmd_amps_x = pid_x.compute(mag_x, dt)
            cmd_amps_y = pid_y.compute(mag_y, dt)
            cmd_amps_z = pid_z.compute(mag_z, dt)
            
            # --- 3. ACTUATE ---
            # Send current commands to the Kepco BOP
            # Example SCPI commands. Uncomment when Kepco is connected!
            # kepco.write(f"CURR:LEV:X {cmd_amps_x:.4f}")
            # kepco.write(f"CURR:LEV:Y {cmd_amps_y:.4f}")
            # kepco.write(f"CURR:LEV:Z {cmd_amps_z:.4f}")
            
            # Print status to console
            print(f"Residual [mG]: X={mag_x:7.2f} | Y={mag_y:7.2f} | Z={mag_z:7.2f}  --->  Command [A]: X={cmd_amps_x:6.3f} | Y={cmd_amps_y:6.3f} | Z={cmd_amps_z:6.3f}")
            
            # --- 4. WAIT ---
            # Sleep precisely enough to maintain the target loop speed
            elapsed = time.time() - loop_start_time
            sleep_time = dt - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
                
    except KeyboardInterrupt:
        print("\nStopping...")
        # Safely zero out the power supply before quitting!
        # kepco.write("CURR:LEV 0")
        # kepco.write("OUTP OFF")
        bus.close()
        print("Hardware safely shut down.")