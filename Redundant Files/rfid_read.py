import serial
import time

# --- Configuration ---
SERIAL_PORT = "/dev/ttyUSB0"  # Replace with your ESP32's serial port
BAUD_RATE = 115200

# --- Setup Serial Connection ---
try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    ser.flush()  # Clear any leftover data in the buffer
except serial.SerialException as e:
    print(f"Error opening serial port: {e}")
    exit()  # Exit if we can't connect

print("Waiting for RFID card data...")

# --- Main Loop ---
while True:
    try:
        if ser.in_waiting > 0:  # Check if there's data available to read
            line = ser.readline().decode('utf-8').rstrip()  # Read a line, decode, and remove whitespace
            if line: #check to ensure the line isn't empty
                # Split the comma-separated string into individual hex values
                hex_values = line.split(',')

                print("Received UID:", hex_values)

                # Optional: Convert hex strings to integers (if needed)
                # int_values = [int(val, 16) for val in hex_values]
                # print("Received UID (integers):", int_values)

        time.sleep(0.1) #small delay to avoid maxing out CPU.

    except serial.SerialException as e:
        print(f"Serial communication error: {e}")
        break  # Exit the loop on serial error
    except KeyboardInterrupt:
        print("Exiting...")
        break
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        break

ser.close()  # Close the serial connection when done
print("Serial port closed.")
