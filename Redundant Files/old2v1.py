import firebase_admin
from firebase_admin import credentials
from firebase_admin import db
import time
import serial  # For serial communication
import lgpio  # For GPIO access

# --- Firebase Configuration ---
cred = credentials.Certificate("/home/pie/shopping_trolley/serviceAccountKey.json")  # VERIFY PATH!
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://shopping-trolley-6f99a-default-rtdb.asia-southeast1.firebasedatabase.app'
})

# --- lgpio Setup ---
h = lgpio.gpiochip_open(0)  # Open the default GPIO chip

# --- IR Sensor Pins (Raspberry Pi) ---  **CHANGE THESE TO YOUR ACTUAL PINS**
IR_LEFT = 27    # Left IR sensor
IR_CENTER = 22  # Center IR sensor
IR_RIGHT = 23   # Right IR sensor

# Set IR sensor pins as inputs
# lgpio.gpio_claim_input(h, IR_LEFT)
# lgpio.gpio_claim_input(h, IR_CENTER)
# lgpio.gpio_claim_input(h, IR_RIGHT)


# --- Serial Communication with ESP32 ---
try:
    esp32 = serial.Serial("/dev/ttyUSB0", 115200, timeout=1)  # Adjust port/baud
    print("Connected to ESP32")
except serial.SerialException as e:
    print(f"Failed to connect to ESP32: {e}")
    esp32 = None
    exit()

# --- Node Mapping (for easier reference) ---
NODE_MAPPING = {
    "home": 0,
    "RFJ1": 1, "RFJ2": 2, "RFJ3": 3,
    "RBJ1": 4, "RBJ2": 5, "RBJ3": 6,
    "pdt1": 7, "pdt2": 8, "pdt3": 9,
    "pdt4": 10, "pdt5": 11, "pdt6": 12,
    "pdt7": 13, "pdt8": 14, "pdt9": 15,
}

# --- Product to Row Mapping ---
PRODUCT_ROWS = {
    "pdt1": 1, "pdt2": 1, "pdt3": 1,
    "pdt4": 2, "pdt5": 2, "pdt6": 2,
    "pdt7": 3, "pdt8": 3, "pdt9": 3,
}

# --- Send Command to ESP32 ---
def send_command(command):
    if esp32:
        print(f"Sending command: {command}")  # Keep print for debugging
        esp32.write(command.encode())
        esp32.flush()  # Ensure command is sent immediately
    else:
        print("ESP32 not connected. Cannot send command.")

# --- Read IR Sensors (Raspberry Pi) using lgpio ---
# def read_ir_sensors():
#     left_value = lgpio.gpio_read(h, IR_LEFT)
#     center_value = lgpio.gpio_read(h, IR_CENTER)  # Read center sensor
#     right_value = lgpio.gpio_read(h, IR_RIGHT)
#     # Invert logic if using pull-up resistors and active-low sensors
#     return (left_value, center_value, right_value)

# --- Line Following Logic (3 Sensors) ---
# def follow_line():
#     left_sensor, center_sensor, right_sensor = read_ir_sensors()

#     if not left_sensor and not center_sensor and not right_sensor:
#         pass
#         # All sensors on white (off the line) - Stop or search
#         #send_command('S')
#         #print("Lost Line!")
#         #return "LOST"  # Indicate line is lost
#     elif not left_sensor and center_sensor and not right_sensor:
#         # Center sensor on black, sides on white (centered)
#         # send_command('F')  <- REMOVE THIS - No need to send 'F' repeatedly
#         return "CENTERED"
#     elif left_sensor and center_sensor and not right_sensor:
#         return "SLIGHT_RIGHT"
#     elif not left_sensor and center_sensor and right_sensor:
#         return "SLIGHT_LEFT"
#     elif left_sensor and not center_sensor and not right_sensor:
#         # Left and center on black - sharper right
#         #send_command('N')
#         return "SLIGHT_LEFT"
#     elif not left_sensor and not center_sensor and right_sensor:
#         # Right and center on black - sharper left
#         #send_command('M')
#         return "SLIGHT_RIGHT"
#     #elif left_sensor and center_sensor and right_sensor:
#         #return "CENTERED"
#     return "OTHER"
    # --- Firebase Event Handlers ---
def handle_new_request(event):
    if event.data is None or event.path == "/":
        return

    print("New request received:", event.data)
    request_id = event.path.split('/')[-1]
    shopping_list = event.data
    print(f"Request ID: {request_id}")
    print(f"Shopping List: {shopping_list}")

    processing_ref = ref.child(f'trolleyProcessing/{request_id}')
    if processing_ref.get() is True:
        print(f"Request {request_id} is already being processed.  Ignoring.")
        return

    processing_ref.set(True)

    if 'action' in shopping_list and shopping_list['action'] == 'home':
        move_trolley_to_home(request_id)
        processing_ref.delete()
        return

    process_shopping_list(request_id, shopping_list)
    processing_ref.delete()
def move_trolley_to_home(request_id):
    print("[Trolley] Moving to home position...")
    current_position = "home"  # Always start from home.  Important.
    status_ref = db.reference(f'trolleyStatus/{request_id}')

    # Navigate directly to the home node.
    navigate_to_node(current_position, "home", request_id) # Pass request_id
    current_position = "home"

    status_ref.set("Trolley at home position")
    print("[Trolley] Arrived at home position")
     


def process_row(request_id, product_list, current_position, row_number, other_rows_exist):
    status_ref = db.reference(f'trolleyStatus/{request_id}')
    print(f"[Trolley] Processing Row {row_number}...")

    # --- Move to the appropriate row start ---
    if row_number == 1:
        row_front_junction = "RFJ1"
        row_back_junction = "RBJ1"
    elif row_number == 2:
        row_front_junction = "RFJ2"
        row_back_junction = "RBJ2"
    elif row_number == 3:
        row_front_junction = "RFJ3"
        row_back_junction = "RBJ3"
    else:
        print(f"Error: Invalid row number {row_number}")
        return None, None  # Return None for both values

    # Navigate to the front junction of the row
    if current_position != row_front_junction:
        print(f"Moving to {row_front_junction}")
        navigate_to_node(current_position, row_front_junction, request_id)  # Pass request_id
    current_position = row_front_junction

    # Turn to face the products
    # send_command('R')  # ALWAYS turn right at RFJs- removed turning logic
    # time.sleep(0.5)  # Short delay for turn

    # --- Iterate through products on the row ---
    for product_id in product_list:
        product_node_name = f"pdt{product_id[-1]}"  # "pdt1", "pdt2", etc.
        product_node = NODE_MAPPING.get(product_node_name)
        if product_node is None:  # Check if node name is valid
            print(f"Error:  Invalid product node name: {product_node_name}")
            status_ref.set(f"error:invalid_product_node:{product_id}")
            continue

        product_name = get_product_name(product_id)
        if not product_name:
            product_name = "Unknown Product"

        print(f"  [Trolley] Seeking product: {product_name} (Node {product_node_name})")
        status_ref.set(f"moving_to_node:{product_node_name}:{product_name}")

        # Navigate to the product node (using RFID for confirmation)
        navigate_to_node(current_position, product_node_name, request_id) # Pass request_id
        current_position = product_node_name  # Update position

        # --- User Interaction (Simulated) ---
        print(f"    Prompting user to add {product_name} to cart...")
        # --- Wait for User Confirmation (Firebase) ---
        wait_for_user_confirmation(request_id)
        print(f"    User added {product_name} to cart.")
        status_ref.set(f"product_added:{product_id}")

    # --- Move to the back junction of the row ---
    print(f"Moving to {row_back_junction}")
    navigate_to_node(current_position, row_back_junction, request_id) # Pass request_id
    current_position = row_back_junction  # Update position

    # --- Turn Logic---
    if other_rows_exist:
      if (row_number == 1 or row_number == 2): #only if the current row is not last do a left turn.
        send_command("L") # Turn left if there are more items
        time.sleep(0.5)

    else:  # No other rows have items.  Prompt for home and turn.
        pass

    return current_position, row_number #return current position and row number

def wait_for_user_confirmation(request_id):
    """Waits for the user to confirm adding an item (or proceeding home)."""
    confirmation_ref = db.reference(f'trolleyConfirmations/{request_id}/confirmed')
    print("Waiting for item confirmation...")  # Clearer message
    while True:
        if confirmation_ref.get() is True:
            confirmation_ref.set(False)  # Reset for next confirmation
            print("Item confirmation received.")
            return
        time.sleep(0.5)
def process_shopping_list(request_id, shopping_list):
    status_ref = db.reference(f'trolleyStatus/{request_id}')
    current_position = "home"  # Start at the home node

    existing_cart_ref = db.reference(f'trolleyCarts/{request_id}')
    existing_cart = existing_cart_ref.get() or {}  # Initialize if None
    print(f"Existing Cart (Before Merge): {existing_cart}")

    if isinstance(shopping_list, dict) and 'cart' in shopping_list:
        cart_data = shopping_list['cart']
        print(f"Cart Data: {cart_data}")

        for product_id, quantity in cart_data.items():
            print(f"  Outer loop: product_id={product_id}, quantity={quantity}")
            if product_id in ('processed', 'action'):  # Use 'in' for tuple
                print(f"    Skipping product_id: {product_id}")
                continue
            # Use .get(product_id, 0) to handle missing keys safely
            existing_cart[product_id] = existing_cart.get(product_id, 0) + quantity
    else:
        print("Error: Invalid shopping_list format or missing 'cart' key.")
        status_ref.set("error:invalid_request_format")
        return

    existing_cart_ref.set(existing_cart)
    print(f"Merged cart: {existing_cart}")

    # --- Organize products by row ---
    listRow1 = []
    listRow2 = []
    listRow3 = []

    for product_id in existing_cart:
        row = PRODUCT_ROWS.get(product_id)  # Use .get() for safety
        if row == 1:
            listRow1.append(product_id)
        elif row == 2:
            listRow2.append(product_id)
        elif row == 3:
            listRow3.append(product_id)
        else:
            print(f"Warning: Product {product_id} has no assigned row.")

    print(f"Row 1 List: {listRow1}")
    print(f"Row 2 List: {listRow2}")
    print(f"Row 3 List: {listRow3}")

    # --- Process each row sequentially ---
    current_row = None  # Keep track of the current row
    if listRow1:
        # Check if other rows have items *before* processing row 1
        other_rows_exist = bool(listRow2 or listRow3)  # True if either list is not empty
        current_position, current_row = process_row(request_id, listRow1, current_position, 1, other_rows_exist)
        if current_position is None: return  # Stop on error
    if listRow2:
        # Check if row 3 has items before processing row 2
        other_rows_exist = bool(listRow3)
        if current_position.startswith("RBJ"): #if current position is at back junction
            #navigate to next back junction
            if int(current_position[-1]) < 2:
                navigate_to_node(current_position, "RBJ2", request_id)
                current_position = "RBJ2"
        current_position, current_row = process_row(request_id, listRow2, current_position, 2, other_rows_exist)
        if current_position is None: return
    if listRow3:
        # No rows after row 3, so no need to check.
        other_rows_exist = bool(listRow2 or listRow1)
        if current_position.startswith("RBJ"):
            if int(current_position[-1]) < 3:
                #navigate to next back junction
                navigate_to_node(current_position, "RBJ3", request_id)
                current_position = "RBJ3"
        current_position, current_row = process_row(request_id, listRow3, current_position, 3, False) # Pass False
        if current_position is None: return

    # --- Return to Home ---
    print("[Trolley] Returning to home...")
    status_ref.set("returning_home")
    print("    Prompting user to proceed home...")
    status_ref.set("waiting_for_home_confirmation")
    wait_for_home_confirmation(request_id)  # Wait for "proceed to home"
    status_ref.set("returning_home")
    print("    User confirmed. Returning home.")
     # --- Go Home based on current row ---
    if current_row == 1:
        navigate_to_node(current_position, "RFJ1", request_id)
        current_position = "RFJ1"
    elif current_row == 2:
        navigate_to_node(current_position, "RFJ2", request_id)
        current_position = "RFJ2"
    elif current_row == 3:
        navigate_to_node(current_position, "RFJ3", request_id)
        current_position = "RFJ3"
    # Turn Logic for facing home
    send_command('F')
    time.sleep(1.0)
    send_command('R')
    turning = True
    turn_direction = 'R'
    navigate_to_node(current_position, "home", request_id)
    current_position = "home"  # Update position

    status_ref.set("completed")
    print("[Trolley] Shopping complete. Returned to home.")

def wait_for_home_confirmation(request_id):
    """Waits for the user to confirm proceeding home."""
    home_ref = db.reference(f'trolleyConfirmations/{request_id}/homeConfirmed') #correct path
    print("Waiting for home confirmation...")
    while True:
        if home_ref.get() is True:
            home_ref.set(False)  # Reset for next use
            print("Home confirmation received.")
            return
        time.sleep(0.5)
def navigate_to_node(current_position_name, destination_node_name, request_id):
    """Navigates to a specificnode using RFID and line following."""
    status_ref = db.reference(f'trolleyStatus/{request_id}')
    current_position = NODE_MAPPING[current_position_name]
    destination_node = NODE_MAPPING[destination_node_name]
    to_home = False
    turning = False  # Flag for turning state, still used for RFID-triggered turns
    turn_direction = None  # 'L' or 'R', still used for RFID-triggered turns

    if current_position == destination_node:
        print(f"Already at destination: {destination_node_name}")
        return
    
    if destination_node_name == 'home':
      to_home = True # Set the flag
    # --- Initial Centering (ONLY when starting from 'home') ---
    # if current_position_name == "home":
    #     if destination_node_name.startswith("RFJ"):
    #         print("Centering at home...")
    #         while True:
    #             left_sensor, center_sensor, right_sensor = read_ir_sensors()
    #             if not left_sensor and center_sensor and not right_sensor:  # Centered
    #                 print("Centered at home.")
    #                 break  # Exit centering loop
    #             elif (left_sensor and not center_sensor) or (left_sensor and center_sensor and not right_sensor):
    #                 send_command('N')  # Correct to the right
    #             elif (not left_sensor and not center_sensor and right_sensor) or (not left_sensor and center_sensor and right_sensor):
    #                 send_command('M')  # Correct to the left
    #             elif all([left_sensor, center_sensor, right_sensor]):  # All on black
    #                 break  # Stop centering and proceed
    #             elif not any([left_sensor, center_sensor, right_sensor]):
    #                 send_command('S')  # Stop if lost
    #                 print("Lost Line during centering!")
    #                 return  # Exit
    #             time.sleep(0.05)

        #     send_command('F')  # Move forward after centering
        #     time.sleep(0.75)  # Delay after initial move.
        # else:  # Error if not going to RFJ from home
        #     print("Error can only move to RFJ from home")
        #     return
    if current_position_name == "home":
        if destination_node_name.startswith("RFJ"):
            send_command("F")
            time.sleep(1.5)  # Adjust as needed for initial forward movement
        else:
            print("Error: Can only go to RFJ nodes from home.")
            return

    # --- Main Navigation Loop ---
    while True:
        # --- 1. RFID Check (Highest Priority) ---
        if esp32.in_waiting > 0:
            response = esp32.readline().decode('utf-8').rstrip()
            if response.startswith("RFID:"):
                uid = response[5:]
                print(f"RFID Detected: {uid}")
                expected_uid = get_expected_uid(destination_node_name)

                # --- RFID-Triggered Turning Logic ---
                # Check for ANY valid RFJ or RBJ UID (not just the destination)
                rfj_uids = [get_expected_uid(f"RFJ{i}") for i in range(1, 4) if get_expected_uid(f"RFJ{i}") is not None]  # List of RFJ UIDs, handle None
                rbj_uids = [get_expected_uid(f"RBJ{i}") for i in range(1, 4) if get_expected_uid(f"RBJ{i}") is not None]  # List of RBJ UIDs, handle None

                if uid in rfj_uids:
                    print(f"At RFJ junction: {uid}")
                    current_rfj_num = int(uid[-1])  # Extract number from UID

                    if destination_node_name.startswith("pdt"):
                        dest_product_num = int(destination_node_name[3:])
                        dest_row = (dest_product_num - 1) // 3 + 1
                        if dest_row == current_rfj_num:
                            send_command('F') #added fwd
                            time.sleep(1.0)
                            send_command('R')
                            turning = True  # Keep turning logic
                            turn_direction = 'R'
                            print("Turning RIGHT at RFJ to face products.")

                    elif to_home:
                      send_command("F") #added FWD
                      time.sleep(0.7)
                      send_command("R")
                      turning = True
                      turn_direction = "R"
                      print("Turning RIGHT at RFJ for home journey.")


                elif uid in rbj_uids:
                    print(f"At RBJ junction: {uid}")
                    current_rbj_num = int(uid[-1])
                    # --- Turn Left at RBJ if going to a *different* RFJ ---
                    if destination_node_name.startswith("RFJ"):
                        dest_rfj_num = int(destination_node_name[3:])
                        if dest_rfj_num > current_rbj_num:
                            send_command('L')
                            turning = True  # Keep turning logic
                            turn_direction = 'L'
                            print("Turning LEFT at RBJ to face next RFJ.")
                            time.sleep(0.7)
                    elif destination_node_name.startswith("RBJ"): #added this for RBJ TO RBJ
                      send_command("F") #continue Forward
                      time.sleep(0.5)


                # --- Destination Reached Check ---
                if expected_uid is not None and uid == expected_uid:
                    print(f"Reached destination: {destination_node_name}")
                    status_ref.set(f"waiting_for_rfid:{destination_node_name}")
                    send_command('S')  # Stop
                    return  # Exit

                elif expected_uid is not None:
                    print(f"Incorrect RFID. Expected: {expected_uid}, Got: {uid}")
                    send_command("F")


        # --- 2. IR Sensor Reading and Turn Completion Check ---
        # left_sensor, center_sensor, right_sensor = read_ir_sensors()

        # if turning:
        #     if turn_direction == 'R':
        #         if not left_sensor and center_sensor and not right_sensor:
        #             turning = False
        #             turn_direction = None
        #             send_command('F') #continue fwd after turn
        #             print("Right turn complete, resuming forward motion.")
        #     elif turn_direction == 'L':
        #         if not left_sensor and center_sensor and not right_sensor:
        #             turning = False
        #             turn_direction = None
        #             send_command("F")
        #             print("Left turn complete, resuming forward motion.")
        if turning:
          turning = False #no line following, only turn
          turn_direction = None #no line followinf, only turn
        # --- 3. Line Following (if not turning) ---
        # elif not turning:
        #     response = follow_line()
        #     if response == "LOST":
        #         send_command('S')
        #         print("Line Lost!")
        #         return
        #     elif response == "CENTERED":
        #         send_command("F")
        #     elif response == "SLIGHT_LEFT":
        #         send_command('N')  # Slight right
        #     elif response == "SLIGHT_RIGHT":
        #         send_command('M')  # Slight left

        time.sleep(0.05)  # Keep a small delay, even without line following
# --- Helper Functions (Firebase) ---

def get_node_number_for_product(product_id):
    try:
        product_data = db.reference(f'/products/{product_id}').get()
        if product_data and 'node' in product_data:
            return int(product_data['node'])
        else:
            print(f"Error: No node mapping for product ID {product_id}")
            return -1
    except Exception as e:
        print(f"Error fetching product node: {e}")
        return -1

def get_product_name(product_id):
    try:
        product_data = db.reference(f'/inventory/{product_id}').get()
        if product_data and 'name' in product_data:
            return product_data['name']
        else:
            print(f"Error: No name found for product ID {product_id}")
            return None
    except Exception as e:
        print(f"Error fetching product name: {e}")
        return None

def get_expected_uid(node_name):
    """Gets the expected UID for a given node name (e.g., 'pdt1', 'RFJ2')."""
    try:
        product_data = db.reference(f'/products/{node_name}').get()
        if product_data and 'uid' in product_data:
                return product_data['uid'].lower() #Return in lower case
        else:
            print(f"Error: No UID found for node ID: {node_name}")  # Corrected error message
            return None
    except Exception as e:
        print(f"Error fetching product UID: {e}")
        return None

# --- Main Execution ---
if __name__ == "__main__":
    ref = db.reference('/')
    requests_ref = ref.child('trolleyRequests')
    requests_ref.listen(handle_new_request)

    print("Trolley controller started. Listening for requests...")

    try:
        while True:
            time.sleep(1)  # Keep the main thread alive
    except KeyboardInterrupt:
        print("Trolley controller stopped.")
    finally:
        lgpio.gpiochip_close(h)  # Clean up lgpio on exit
