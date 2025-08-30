# -*- coding: utf-8 -*-
"""
Raspberry Pi Controller for Automated Shopping Trolley (Refactored Version)
... (Includes sensor print for debugging line following) ...
- Turn logic now stops when *any* sensor detects the new line.
- NOTE: LINE_LOST logic is currently commented out in LineFollower.
"""

import firebase_admin
from firebase_admin import credentials, db
import time
import serial
import lgpio
import sys # For exiting

# --- Constants ---
# Commands for ESP32
CMD_FORWARD = 'F'
CMD_BACKWARD = 'B'
CMD_STOP = 'S'
CMD_LEFT = 'L'  # Turn left (pivot)
CMD_RIGHT = 'R' # Turn right (pivot)
CMD_SLIGHT_LEFT = 'M'  # ESP32's command for slight left correction (Veer Left)
CMD_SLIGHT_RIGHT = 'N' # ESP32's command for slight right correction (Veer Right)

# Line Follower States (Returned by LineFollower class)
LINE_CENTERED = "CENTERED"
LINE_SLIGHT_LEFT = "SLIGHT_LEFT"   # Trolley is too far left, needs right correction (N)
LINE_SLIGHT_RIGHT = "SLIGHT_RIGHT" # Trolley is too far right, needs left correction (M)
LINE_LOST = "LOST" # NOTE: Logic returning this state is commented out below

# GPIO Pins (Configuration) - *** VERIFY THESE MATCH YOUR WIRING ***
IR_PIN_LEFT = 27
IR_PIN_CENTER = 22
IR_PIN_RIGHT = 23

# Serial Port (Configuration) - *** VERIFY THIS PORT NAME ***
SERIAL_PORT = "/dev/ttyUSB0"
SERIAL_BAUD = 115200

# Firebase (Configuration) - *** VERIFY PATH & URL ***
FIREBASE_CRED_PATH = "/home/pie/shopping_trolley/serviceAccountKey.json" # Use absolute path
FIREBASE_DB_URL = 'https://shopping-trolley-6f99a-default-rtdb.asia-southeast1.firebasedatabase.app'

# Node Mapping (Easier Reference) - *** VERIFY AGAINST FIREBASE /products ***
NODE_MAPPING = {
    "home": 0,
    "RFJ1": 1, "RFJ2": 2, "RFJ3": 3,
    "RBJ1": 4, "RBJ2": 5, "RBJ3": 6,
    "pdt1": 7, "pdt2": 8, "pdt3": 9,
    "pdt4": 10, "pdt5": 11, "pdt6": 12,
    "pdt7": 13, "pdt8": 14, "pdt9": 15,
}
# Reverse mapping for convenience (Node number to name)
NODE_ID_TO_NAME = {v: k for k, v in NODE_MAPPING.items()}

# Product to Row Mapping - *** VERIFY THESE ASSIGNMENTS ***
PRODUCT_ROWS = {
    "pdt1": 1, "pdt2": 1, "pdt3": 1,
    "pdt4": 2, "pdt5": 2, "pdt6": 2,
    "pdt7": 3, "pdt8": 3, "pdt9": 3,
}

# --- Hardware Abstraction ---
class HardwareInterface:
    """Handles direct interaction with GPIO (sensors) and Serial (ESP32)."""
    def __init__(self, serial_port, baud_rate, ir_left, ir_center, ir_right):
        self.h_gpio = None
        self.esp32 = None
        self.ir_pins = {'left': ir_left, 'center': ir_center, 'right': ir_right}

        try:
            self.h_gpio = lgpio.gpiochip_open(0)
            lgpio.gpio_claim_input(self.h_gpio, self.ir_pins['left'])
            lgpio.gpio_claim_input(self.h_gpio, self.ir_pins['center'])
            lgpio.gpio_claim_input(self.h_gpio, self.ir_pins['right'])
            print("GPIO initialized.")
        except Exception as e:
            print(f"FATAL: Failed to initialize GPIO: {e}")
            self.close() # Attempt cleanup even if partial init failed
            raise RuntimeError("GPIO Initialization Failed") from e

        try:
            self.esp32 = serial.Serial(serial_port, baud_rate, timeout=0.1) # Shorter timeout
            print(f"Attempting connection to ESP32 on {serial_port}...")
            time.sleep(2) # Allow ESP32 to reset and boot
            self.esp32.reset_input_buffer() # Clear any startup messages
            print(f"Connected to ESP32 on {serial_port}")
        except serial.SerialException as e:
            print(f"FATAL: Failed to connect to ESP32: {e}")
            self.close() # Cleanup GPIO if serial failed
            raise RuntimeError("ESP32 Connection Failed") from e

    def read_ir_sensors(self):
        """Reads the state of the IR sensors."""
        # Assumes sensor logic: 0 = Black/On Line, 1 = White/Off Line
        try:
            left = lgpio.gpio_read(self.h_gpio, self.ir_pins['left'])
            center = lgpio.gpio_read(self.h_gpio, self.ir_pins['center'])
            right = lgpio.gpio_read(self.h_gpio, self.ir_pins['right'])
            return (left, center, right)
        except Exception as e:
            print(f"Error reading IR sensors: {e}")
            return (1, 1, 1) # Return 'off line' state as a failsafe?

    def send_command(self, command):
        """Sends a single character command to the ESP32."""
        if self.esp32 and self.esp32.is_open:
            try:
                # print(f"Sending: {command}") # Uncomment for detailed debug
                self.esp32.write(command.encode('utf-8'))
                self.esp32.flush() # Ensure data is sent immediately
            except serial.SerialException as e:
                print(f"Error sending command '{command}': {e}")
        else:
            print("Warning: ESP32 not connected. Cannot send command.")

    def receive_line(self):
        """Reads a line from the ESP32, returns None if timeout/error/empty."""
        if self.esp32 and self.esp32.is_open:
            try:
                if self.esp32.in_waiting > 0:
                    line_bytes = self.esp32.readline()
                    line = line_bytes.decode('utf-8').strip()
                    if line:
                        # print(f"Received: {line}") # Uncomment for debug
                        return line
            except serial.SerialException as e:
                print(f"Error receiving data: {e}")
            except UnicodeDecodeError as e:
                print(f"Serial decode error: {e} - Received bytes: {line_bytes}")
        return None

    def close(self):
        """Cleans up resources."""
        print("Closing hardware interface...")
        if self.esp32 and self.esp32.is_open:
            try:
                self.send_command(CMD_STOP)
                time.sleep(0.1)
                self.esp32.close()
                print("Serial port closed.")
            except serial.SerialException as e:
                 print(f"Error closing serial port: {e}")
        if self.h_gpio is not None:
            try:
                lgpio.gpiochip_close(self.h_gpio)
                print("GPIO chip closed.")
            except Exception as e:
                 print(f"Error closing GPIO chip: {e}")
        self.h_gpio = None
        self.esp32 = None

# --- Line Following Logic (LINE_LOST COMMENTED OUT) ---
class LineFollower:
    """Interprets sensor readings to determine line state."""

    def get_state(self, left_sensor, center_sensor, right_sensor):
        """
        Determines the trolley's position relative to the line.
        Assumes: 0 = Black/On Line, 1 = White/Off Line
        Returns: State constant (e.g., LINE_CENTERED)
        """
        if left_sensor and not center_sensor and right_sensor: # 1 0 1
            return LINE_CENTERED
        elif left_sensor and not center_sensor and not right_sensor: # 1 0 0
             return LINE_SLIGHT_LEFT # Robot is LEFT, needs RIGHT correction (N)
        elif not left_sensor and not center_sensor and right_sensor: # 0 0 1
             return LINE_SLIGHT_RIGHT # Robot is RIGHT, needs LEFT correction (M)
        # --- LINE LOST Condition 1 (Commented Out) ---
        # elif left_sensor and left_sensor and left_sensor: # 1 1 1
        #      # return LINE_LOST
        #      pass
        elif not left_sensor and not center_sensor and not right_sensor: # 0 0 0
             return LINE_CENTERED # Assume junction or wide line
        elif not left_sensor and left_sensor and left_sensor: # 0 1 1
             return LINE_SLIGHT_RIGHT # Sharp Left deviation -> Needs LEFT correction (M)
        elif left_sensor and left_sensor and not right_sensor: # 1 1 0
             return LINE_SLIGHT_LEFT # Sharp Right deviation -> Needs RIGHT correction (N)
        # --- LINE LOST Condition 2 (Commented Out) ---
        # else: # Catches remaining cases like 0 1 0
            # print(f"Warning: Unusual sensor state ({left_sensor}{center_sensor}{right_sensor}). Treating as LOST.")
            # return LINE_LOST
        return LINE_CENTERED # Default if LINE_LOST cases are commented

# --- Firebase Communication ---
class FirebaseComm:
    """Handles all communication with Firebase Realtime Database."""
    # (Code remains the same as previous version)
    def __init__(self, cred_path, db_url):
        try:
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred, {'databaseURL': db_url})
            self.db = db
            print("Firebase initialized.")
        except Exception as e:
            print(f"FATAL: Failed to initialize Firebase: {e}")
            raise RuntimeError("Firebase Initialization Failed") from e
    def listen_for_requests(self, callback):
        try:
            requests_ref = self.db.reference('/trolleyRequests')
            requests_ref.listen(callback)
            print("Listening for Firebase requests...")
        except Exception as e: print(f"Error starting Firebase listener: {e}")
    def set_processing_status(self, request_id, status):
        try: self.db.reference(f'/trolleyProcessing/{request_id}').set(status)
        except Exception as e: print(f"Firebase Error: Could not set processing status for {request_id}: {e}")
    def delete_processing_status(self, request_id):
         try: self.db.reference(f'/trolleyProcessing/{request_id}').delete()
         except Exception as e: print(f"Firebase Error: Could not delete processing status for {request_id}: {e}")
    def is_processing(self, request_id):
        try: return self.db.reference(f'/trolleyProcessing/{request_id}').get() is True
        except Exception as e: print(f"Firebase Error: Could not check processing status for {request_id}: {e}"); return False
    def update_trolley_status(self, request_id, status_message):
        try:
            ref = self.db.reference(f'/trolleyStatus/{request_id}')
            ref.set(status_message)
            print(f"[Status:{request_id}] {status_message}")
        except Exception as e: print(f"Firebase Error: Could not update status for {request_id}: {e}")
    def get_cart(self, request_id):
        try: return self.db.reference(f'/trolleyCarts/{request_id}').get() or {}
        except Exception as e: print(f"Firebase Error: Could not get cart for {request_id}: {e}"); return {}
    def set_cart(self, request_id, cart_data):
        try: self.db.reference(f'/trolleyCarts/{request_id}').set(cart_data)
        except Exception as e: print(f"Firebase Error: Could not set cart for {request_id}: {e}")
    def get_product_name(self, product_id):
        try:
            ref = self.db.reference(f'/inventory/{str(product_id)}/name')
            name = ref.get(); return name if name else "Unknown Product"
        except Exception as e: print(f"Firebase Error: Could not get name for {product_id}: {e}"); return "Unknown Product"
    def get_expected_uid(self, node_name):
        try:
            ref = self.db.reference(f'/products/{str(node_name)}/uid')
            uid = ref.get(); return uid.lower() if uid else None
        except Exception as e: print(f"Firebase Error: Could not get UID for {node_name}: {e}"); return None
    def _wait_for_flag(self, path, poll_interval=0.5, timeout=60):
        start_time = time.time()
        try:
            flag_ref = self.db.reference(path)
            while time.time() - start_time < timeout:
                if flag_ref.get() is True:
                    try: flag_ref.set(False)
                    except Exception: print(f"Warning: Could not reset flag at {path}")
                    return True
                time.sleep(poll_interval)
            print(f"Timeout waiting for flag at {path}"); return False
        except Exception as e: print(f"Firebase Error: Waiting for flag at {path}: {e}"); return False
    def wait_for_confirmation(self, request_id, timeout=60):
        print(f"Waiting for item confirmation ({request_id})...")
        path = f'/trolleyConfirmations/{request_id}/confirmed'
        if self._wait_for_flag(path, timeout=timeout): print(f"Item confirmation received ({request_id})."); return True
        print(f"Failed to get item confirmation ({request_id})."); return False
    def wait_for_home_confirmation(self, request_id, timeout=60):
        print(f"Waiting for home confirmation ({request_id})...")
        path = f'/trolleyConfirmations/{request_id}/homeConfirmed'
        if self._wait_for_flag(path, timeout=timeout): print(f"Home confirmation received ({request_id})."); return True
        print(f"Failed to get home confirmation ({request_id})."); return False

# --- Navigation Logic (Sensor print added) ---
class Navigator:
    """Handles trolley movement, turning, and navigation between nodes."""
    # ... (NAV_STATE constants remain the same) ...
    NAV_STATE_IDLE = 0
    NAV_STATE_MOVING = 1
    NAV_STATE_TURNING = 2
    NAV_STATE_LOST = 3
    NAV_STATE_ARRIVED = 4
    
    # --- Add NEW method to class Navigator ---
    def reverse_until_node(self, destination_node_name, request_id):
        """Moves backward without line following until destination RFID is detected."""
        # WARNING: Assumes robot reverses reasonably straight! No line correction!
        # WARNING: Assumes ESP32 uses CMD_BACKWARD ('B') for reverse!

        # Cannot reverse from home or to home using this method
        if self.current_node == "home" or destination_node_name == "home":
             print("ERROR: reverse_until_node cannot be used to/from home.")
             return False

        print(f"Reversing from '{self.current_node}' towards '{destination_node_name}'...")
        self.fb.update_trolley_status(request_id, f"reversing_to:{destination_node_name}")

        expected_uid = self.fb.get_expected_uid(destination_node_name)
        print(f"DEBUG: Expecting UID for {destination_node_name}: {expected_uid}")
        if expected_uid is None:
             print(f"ERROR: Cannot reverse, no UID for destination '{destination_node_name}'")
             self.fb.update_trolley_status(request_id, f"error:no_uid:{destination_node_name}"); return False

        # Send Backward Command
        self.hw.send_command(CMD_BACKWARD)

        start_time = time.time()
        # Use navigation_timeout or a specific reverse_timeout? Let's use navigation_timeout for now.

        while time.time() - start_time < self.navigation_timeout:
            # 1. Check for RFID
            serial_line = self.hw.receive_line()
            if serial_line and serial_line.startswith("RFID:"):
                received_uid = serial_line[5:].lower()
                print(f"DEBUG: RFID Detected UID (Reversing): {received_uid}")
                # print(f"DEBUG: RFID Expected UID: {expected_uid}") # Already printed

                if received_uid == expected_uid:
                    print(f"SUCCESS: Reached destination '{destination_node_name}' while reversing (UID Match)")
                    self.hw.send_command(CMD_STOP) # Stop ESP32
                    self.current_node = destination_node_name # Update position
                    self.fb.update_trolley_status(request_id, f"arrived_at:{destination_node_name}")
                    time.sleep(0.5) # Small pause after stopping
                    return True
                else:
                    # ESP32 stops on ANY RFID read. Tell it to reverse again if wrong tag seen.
                    print(f"Incorrect RFID tag while reversing. Expected {expected_uid}, Got {received_uid}. Continuing reverse...")
                    self.hw.send_command(CMD_BACKWARD)
                    time.sleep(0.3) # Avoid immediate re-read

            # No line following check in this simple reverse mode
            time.sleep(0.05) # Check RFID periodically

        # --- Loop End (Timeout) ---
        print(f"ERROR: Reversing timed out after {self.navigation_timeout}s!")
        self.hw.send_command(CMD_STOP)
        self.fb.update_trolley_status(request_id, f"error:reverse_timeout:{self.current_node}->{destination_node_name}")
        return False

    def __init__(self, hw_interface: HardwareInterface, line_follower: LineFollower, firebase_comm: FirebaseComm):
        # (Code remains the same as previous version)
        self.hw = hw_interface
        self.lf = line_follower
        self.fb = firebase_comm
        self.current_node = "home"
        self.navigation_timeout = 60
        self.turn_timeout = 20

    def get_current_node(self):
        # (Code remains the same as previous version)
        return self.current_node

    def _get_turn_for_transition(self, start_node, end_node):
        # (Code remains the same as previous version with corrections 2 & 3)
        print(f"DEBUG: Determining turn for {start_node} -> {end_node}")
        if start_node == "home" and end_node.startswith("RFJ"):
            print("DEBUG: home->RFJ = FWD"); return None
        if start_node.startswith("RFJ") and end_node.startswith("pdt"):
             print("DEBUG: RFJ->pdt = RIGHT"); return CMD_RIGHT
        if start_node.startswith("RBJ") and end_node.startswith("RFJ"):
             print("DEBUG: RBJ->RFJ = RIGHT"); return CMD_RIGHT
        if start_node.startswith("RBJ") and end_node.startswith("RBJ"):
             print("DEBUG: RBJ->RBJ = LEFT"); return CMD_LEFT
        if start_node.startswith("RFJ") and end_node == "home":
             print("DEBUG: RFJ->home = RIGHT"); return CMD_RIGHT
        print(f"DEBUG: Default transition {start_node}->{end_node} = FWD"); return None

    # Inside the Navigator class:

    # --- In class Navigator ---

    # Inside Navigator class

# --- In class Navigator ---
    def execute_simple_turn(self, turn_command, request_id="debug"):
        """
        Executes turn (L or R). Stops when ANY sensor detects a line ('0').
        Simplified: No check for leaving initial line first.
        """
        print(f"Executing simplified turn (Stop on Any Detect): {turn_command}")
        self.hw.send_command(turn_command)
        start_time = time.time()
        # Brief initial delay to ensure turn physically starts before checking sensors
        time.sleep(1.5) # TUNABLE: Adjust if needed

        while time.time() - start_time < self.turn_timeout:
            sensors = self.hw.read_ir_sensors()
            left, center, right = sensors
            # Assumes 0=Black, 1=White
            print(f"Turning... Sensors: {left}{center}{right}") # Keep print uncommented

            # Look for ANY sensor to detect the new line (a '0')
            if left == 1 or center == 1 or right == 0:
                print(f"DEBUG: New line detected by at least one sensor ({left}{center}{right}). Stopping turn.")
                time.sleep(0.9)
                self.hw.send_command(CMD_STOP)
                time.sleep(0.2) # Pause briefly
                return True # Indicate turn procedure finished

            time.sleep(0.05) # Small delay in loop

        # Timeout handling
        print(f"ERROR: Turn timed out after {self.turn_timeout}s! Sensors: {left}{center}{right}")
        self.hw.send_command(CMD_STOP)
        self.fb.update_trolley_status(request_id, f"error:turn_timeout:{turn_command}")
        return False

        
    def navigate_to_node(self, destination_node_name, request_id):
        """Navigates from the current_node to the destination_node_name."""
        # (Code includes RFID debug prints from previous answer)
        if self.current_node == destination_node_name:
            print(f"Already at destination: {destination_node_name}")
            return True

        print(f"Navigating from '{self.current_node}' to '{destination_node_name}'")
        self.fb.update_trolley_status(request_id, f"moving_to:{destination_node_name}")

        expected_uid = self.fb.get_expected_uid(destination_node_name)
        print(f"DEBUG: Expecting UID for {destination_node_name}: {expected_uid}")
        if expected_uid is None:
             print(f"ERROR: Cannot navigate, no UID found for destination '{destination_node_name}'")
             self.fb.update_trolley_status(request_id, f"error:no_uid:{destination_node_name}")
             return False

        initial_turn = self._get_turn_for_transition(self.current_node, destination_node_name)
        if initial_turn:
            if not self.execute_simple_turn(initial_turn, request_id):
                return False
            self.hw.send_command(CMD_FORWARD) # Start forward after successful turn
        else:
            self.hw.send_command(CMD_FORWARD) # Start forward if no initial turn

        start_time = time.time()
        last_line_state = None
        last_command_sent = CMD_FORWARD

        while time.time() - start_time < self.navigation_timeout:
            # 1. Check for RFID first (as it causes ESP32 to stop)
            serial_line = self.hw.receive_line()
            if serial_line and serial_line.startswith("RFID:"):
                received_uid = serial_line[5:].lower()
                print(f"DEBUG: RFID Detected UID: {received_uid}")
                print(f"DEBUG: RFID Expected UID: {expected_uid}")
                if received_uid == expected_uid:
                    print(f"SUCCESS: Reached destination '{destination_node_name}' (UID Match)")
                    # ESP32 already stopped, ensure Pi knows to stop sending commands
                    last_command_sent = CMD_STOP # Update internal state
                    self.current_node = destination_node_name
                    self.fb.update_trolley_status(request_id, f"arrived_at:{destination_node_name}")
                    time.sleep(0.5) # Pause after arrival confirmation
                    return True
                else:
                    print(f"Incorrect RFID tag. Expected {expected_uid}, Got {received_uid}. Continuing...")
                    # Tell ESP32 (which stopped) to move again
                    self.hw.send_command(CMD_FORWARD)
                    last_command_sent = CMD_FORWARD
                    time.sleep(0.3) # Avoid immediate re-read
                    continue # Skip line following for this iteration

            # 2. Read Sensors and Determine Required Command
            sensors = self.hw.read_ir_sensors()
            # --- ADDED SENSOR PRINT ---
            #print(f"DEBUG: Sensors LCR = {sensors}") # Print raw sensor values
            # ---
            line_state = self.lf.get_state(*sensors)
            required_command = last_command_sent # Default to previous command

            if line_state == LINE_CENTERED:
                required_command = CMD_FORWARD
            elif line_state == LINE_SLIGHT_LEFT: # Robot is LEFT -> needs RIGHT correction
                required_command = CMD_SLIGHT_RIGHT # Command 'N'
            elif line_state == LINE_SLIGHT_RIGHT: # Robot is RIGHT -> needs LEFT correction
                required_command = CMD_SLIGHT_LEFT # Command 'M'
            # Note: LINE_LOST handling is currently disabled in LineFollower

            # 3. Send Command (Only if changed)
            if required_command != last_command_sent:
                #print(f"DEBUG: State={line_state}, Sending Command={required_command}") # Added State Info
                self.hw.send_command(required_command)
                last_command_sent = required_command

            # Small delay in loop
            time.sleep(0.05) # Adjust as needed

        # --- Loop End (Timeout) ---
        print(f"ERROR: Navigation timed out after {self.navigation_timeout}s!")
        self.hw.send_command(CMD_STOP)
        self.fb.update_trolley_status(request_id, f"error:nav_timeout:{self.current_node}->{destination_node_name}")
        return False


    def set_current_position(self, node_name):
        """Manually set the current node position"""
        # (Code remains the same as previous version)
        if node_name in NODE_MAPPING or node_name == "home":
            print(f"Manually setting current node to: {node_name}")
            self.current_node = node_name
        else:
            print(f"Warning: Attempted to set invalid node position: {node_name}")


# --- Main Controller ---
class TrolleyController:
	# --- MODIFY method in class TrolleyController ---
    def _move_trolley_to_home(self, request_id):
        """Navigates the trolley back to the home position, using REVERSE from RBJ."""
        print("[Trolley] Request received to move to home position...")
        self.firebase_comm.update_trolley_status(request_id, "moving_to:home")
        current_node = self.navigator.get_current_node()
        print(f"Current Node: {current_node}")

        if current_node == "home":
             print("Already at home."); self.firebase_comm.update_trolley_status(request_id, "arrived_at:home"); return

        path_ok = True
        target_rfj = None # Keep track of the RFJ we are aiming for from aisle

        # Step 1: If in aisle (pdt or RBJ), move towards the corresponding RFJ
        if current_node.startswith("pdt") or current_node.startswith("RBJ"):
            try:
                row_num_str = current_node[-1]
                target_rfj = f"RFJ{row_num_str}"
                print(f"Path: {current_node} -> {target_rfj} -> home")

                # --- MODIFIED SECTION: RBJ to RFJ ---
                # Step 1a: If at RBJ, REVERSE to RFJ (no turn needed first)
                if current_node.startswith("RBJ"):
                    print(f"Reversing from {current_node} towards {target_rfj}...")
                    if not self.navigator.reverse_until_node(target_rfj, request_id):
                         path_ok = False # Failed reversing step

                # Step 1b: If started at pdt, navigate FORWARD to RFJ (using standard navigate)
                elif current_node.startswith("pdt"):
                    print(f"Navigating forward from {current_node} towards {target_rfj}...")
                    if not self.navigator.navigate_to_node(target_rfj, request_id):
                         path_ok = False
                # --- END MODIFIED SECTION ---

            except Exception as e:
                 print(f"Error determining path from aisle node {current_node}: {e}")
                 path_ok = False

        # Step 2: Check if we are now at an RFJ
        current_node = self.navigator.get_current_node() # Update position
        if path_ok and current_node.startswith("RFJ"):
             # Turn towards home direction
             print(f"Currently at {current_node}. Turning right towards home area...")
             if not self.navigator.execute_simple_turn(CMD_RIGHT, request_id):
                  path_ok = False

        # Step 3: Final navigation to home
        if path_ok:
            if self.navigator.get_current_node() != "home":
                 print("Proceeding to 'home' node...")
                 if not self.navigator.navigate_to_node("home", request_id):
                      path_ok = False

        # Final Status Update
        if path_ok and self.navigator.get_current_node() == "home":
             self.firebase_comm.update_trolley_status(request_id, "arrived_at:home"); print("[Trolley] Arrived at home position.")
        else:
             print("[Trolley] Failed to return home.")
    """Orchestrates the shopping process using Firebase, Navigator, etc."""
    # ... (__init__, _handle_new_request_callback, process_request, _move_trolley_to_home methods remain the same) ...
    # ... (process_shopping_list method remains the same) ...
    # ... (_process_row method remains the same - including forward nudge) ...
    # ... (run, stop, cleanup methods remain the same) ...

    # NOTE: Duplicating all methods for completeness, ensure correct versions used.
    def __init__(self,):
        self.firebase_comm = None
        self.hw_interface = None
        self.line_follower = None
        self.navigator = None
        self._running = False
        try:
            self.firebase_comm = FirebaseComm(FIREBASE_CRED_PATH, FIREBASE_DB_URL)
            self.hw_interface = HardwareInterface(SERIAL_PORT, SERIAL_BAUD, IR_PIN_LEFT, IR_PIN_CENTER, IR_PIN_RIGHT)
            self.line_follower = LineFollower()
            self.navigator = Navigator(self.hw_interface, self.line_follower, self.firebase_comm)
            self.navigator.set_current_position("home")
        except Exception as e:
             print(f"FATAL: Error during TrolleyController initialization: {e}")
             self.cleanup()
             sys.exit(1)

    def _handle_new_request_callback(self, event):
        if event.event_type in ['put', 'patch']:
            request_id = event.path.split('/')[-1]
            if not request_id or request_id == 'trolleyRequests' or event.data is None: return
            print(f"\n--- New Event Received ---")
            print(f"Data: {event.data}")
            print(f"Request ID derived: {request_id}")
            if self.firebase_comm.is_processing(request_id):
                print(f"Request {request_id} is already being processed. Ignoring.")
                return
            self.firebase_comm.set_processing_status(request_id, True)
            print(f"Processing request {request_id}...")
            try:
                self.process_request(request_id, event.data)
                print(f"Finished processing {request_id}.")
            except Exception as e:
                 print(f"!!! CRITICAL ERROR during processing {request_id}: {e}")
                 try:
                      self.firebase_comm.update_trolley_status(request_id, f"error:critical_processing_exception")
                      self.hw_interface.send_command(CMD_STOP)
                 except: pass
            finally:
                 print(f"Deleting processing flag for {request_id}.")
                 self.firebase_comm.delete_processing_status(request_id)
                 print(f"--- Event Handling Complete ({request_id}) ---\n")

    def process_request(self, request_id, data):
        action = data.get('action')
        if action == 'home':
            self._move_trolley_to_home(request_id)
            if success:
                self.firebase_comm.update_trolley_status(request_id, "completed")

        elif 'cart' in data and isinstance(data['cart'], dict):
            self.process_shopping_list(request_id, data)
        else:
            print(f"Error: Invalid request format for {request_id}.")
            self.firebase_comm.update_trolley_status(request_id, "error:invalid_request_format")


    def process_shopping_list(self, request_id, request_data):
        self.firebase_comm.update_trolley_status(request_id, "processing_list")
        print(f"[Trolley:{request_id}] Processing shopping list...")
        new_cart_items = request_data.get('cart', {})
        existing_cart = self.firebase_comm.get_cart(request_id)
        for product_id, quantity in new_cart_items.items():
            if product_id in ('processed', 'action'): continue
            try:
                current_qty = existing_cart.get(product_id, 0)
                add_qty = int(quantity)
                existing_cart[product_id] = current_qty + add_qty
            except (ValueError, TypeError): continue
        final_cart = {pid: qty for pid, qty in existing_cart.items() if qty > 0}
        print(f"Final Cart (qty > 0): {final_cart}")
        self.firebase_comm.set_cart(request_id, final_cart)
        products_by_row = {1: [], 2: [], 3: []}
        valid_products_in_cart = []
        highest_row_with_items = 0
        for product_id in sorted(final_cart.keys()):
             row = PRODUCT_ROWS.get(product_id)
             if row in products_by_row:
                 products_by_row[row].append(product_id)
                 valid_products_in_cart.append(product_id)
                 highest_row_with_items = max(highest_row_with_items, row)
             else: print(f"Warning: Product {product_id} has no assigned row. Skipping.")
        print(f"Products for Row 1: {products_by_row[1]}")
        print(f"Products for Row 2: {products_by_row[2]}")
        print(f"Products for Row 3: {products_by_row[3]}")
        if not valid_products_in_cart:
             print("No valid products in cart to process.")
             self.firebase_comm.update_trolley_status(request_id, "completed_empty_cart")
             self._move_trolley_to_home(request_id)
             return
        navigation_ok = True
        processed_rows = []
        for row_num in sorted(products_by_row.keys()):
            if products_by_row[row_num]:
                processed_rows.append(row_num)
                print(f"\n--- Processing Row {row_num} ---")
                is_last_row_to_process = (row_num == highest_row_with_items)
                navigation_ok = self._process_row(request_id, products_by_row[row_num], row_num, is_last_row_to_process)
                if not navigation_ok: break
        if navigation_ok:
            print("\n--- Returning to Home ---")
            self.firebase_comm.update_trolley_status(request_id, "waiting_for_home_confirmation")
            if not self.firebase_comm.wait_for_home_confirmation(request_id):
                 print("Home confirmation failed or timed out. Stopping.")
                 self.firebase_comm.update_trolley_status(request_id, "error:home_confirmation_failed")
                 self.hw_interface.send_command(CMD_STOP)
                 return
            self.firebase_comm.update_trolley_status(request_id, "returning_home")
            print("User confirmed. Returning home.")
            self._move_trolley_to_home(request_id)
        else: print("[Trolley] Processing stopped due to error.")

    def _process_row(self, request_id, product_list, row_number, is_last_row):
        self.firebase_comm.update_trolley_status(request_id, f"processing_row:{row_number}")
        row_front_junction = f"RFJ{row_number}"
        row_back_junction = f"RBJ{row_number}"
        print(f"Moving to start of row {row_number}: {row_front_junction}")
        if not self.navigator.navigate_to_node(row_front_junction, request_id): return False
        #print(f"DEBUG: Nudging forward slightly at {row_front_junction}...")
        self.hw_interface.send_command(CMD_FORWARD)
        time.sleep(0.5)
        self.hw_interface.send_command(CMD_STOP)
        time.sleep(0.1)
        print(f"Turning right into row {row_number} aisle...")
        if not self.navigator.execute_simple_turn(CMD_RIGHT, request_id): return False
        sorted_product_list = sorted(product_list, key=lambda pid: NODE_MAPPING.get(pid, float('inf')))
        for product_id in sorted_product_list:
            product_node_name = product_id
            product_name = self.firebase_comm.get_product_name(product_id)
            print(f"  Seeking product: {product_name} ({product_node_name})")
            self.firebase_comm.update_trolley_status(request_id, f"moving_to_product:{product_node_name}")
            if not self.navigator.navigate_to_node(product_node_name, request_id): return False
            print(f"  Arrived at {product_name}. Prompting user...")
            self.firebase_comm.update_trolley_status(request_id, f"waiting_for_item:{product_id}:{product_name}")
            if not self.firebase_comm.wait_for_confirmation(request_id):
                 print("Item confirmation failed or timed out.")
                 self.firebase_comm.update_trolley_status(request_id, f"error:item_confirmation_failed:{product_id}")
                 self.hw_interface.send_command(CMD_STOP)
                 return False
            print(f"  User added {product_name}. Proceeding...")
            self.firebase_comm.update_trolley_status(request_id, f"item_added:{product_id}")
        print(f"Finished products in row {row_number}. Moving to end: {row_back_junction}")
        if not self.navigator.navigate_to_node(row_back_junction, request_id): return False
        if not is_last_row:
            print(f"More rows to process. Turning left at {row_back_junction}...")
            if not self.navigator.execute_simple_turn(CMD_LEFT, request_id): return False
        else: print(f"This was the last row ({row_number}). No turn needed at {row_back_junction}.")
        print(f"--- Row {row_number} Processing Complete ---")
        return True

    def run(self):
        print("Starting Trolley Controller...")
        self._running = True
        try:
            self.firebase_comm.listen_for_requests(self._handle_new_request_callback)
            while self._running: time.sleep(0.75)
        except KeyboardInterrupt: print("\nKeyboardInterrupt received.")
        finally: self.stop()

    def stop(self):
        if not self._running: return
        print("Stopping Trolley Controller...")
        self._running = False
        self.cleanup()
        print("Trolley Controller stopped.")

    def cleanup(self):
        print("Cleaning up resources...")
        if self.hw_interface: self.hw_interface.close()
        print("Cleanup finished.")

# --- Main Execution ---
if __name__ == "__main__":
    print("------------------------------------")
    print("  Automated Shopping Trolley Ctrl   ")
    print("------------------------------------")
    controller = None
    try:
        controller = TrolleyController()
        controller.run()
    except RuntimeError as e:
         print(f"Could not start Trolley Controller: {e}")
         if controller: controller.cleanup()
    except Exception as e:
         print(f"An unexpected error occurred in main: {e}")
         if controller: controller.cleanup()
    finally:
        print("Exiting application.")
        sys.exit(0)

