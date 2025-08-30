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
lgpio.gpio_claim_input(h, IR_LEFT)
lgpio.gpio_claim_input(h, IR_CENTER)
lgpio.gpio_claim_input(h, IR_RIGHT)

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
def read_ir_sensors():
    left_value = lgpio.gpio_read(h, IR_LEFT)
    center_value = lgpio.gpio_read(h, IR_CENTER)  # Read center sensor
    right_value = lgpio.gpio_read(h, IR_RIGHT)
    # Invert logic if using pull-up resistors and active-low sensors
    return (left_value, center_value, right_value)

# --- Line Following Logic (3 Sensors) ---
def follow_line():
    left_sensor, center_sensor, right_sensor = read_ir_sensors()

    if not left_sensor and center_sensor and not right_sensor:
        return "CENTERED"
    elif left_sensor and not center_sensor and not right_sensor :
        return "SLIGHT_RIGHT" 
    elif not left_sensor and not center_sensor and right_sensor:
        return "SLIGHT_LEFT"
    elif left_sensor and center_sensor and not right_sensor:
        return "SLIGHT_LEFT"
    elif not left_sensor and center_sensor and right_sensor:
        return "SLIGHT_RIGHT" 

# --- Firebase Event Handlers ---
def handle_new_request(event):
    if event.data is None or event.path == "/":
        return

    print("New request received:", event.data)  # Keep for debugging
    request_id = event.path.split('/')[-1]
    shopping_list = event.data
    print(f"Request ID: {request_id}")  # Keep
    print(f"Shopping List: {shopping_list}")  # Keep

    processing_ref = ref.child(f'trolleyProcessing/{request_id}')
    if processing_ref.get() is True:
        print(f"Request {request_id} is already being processed.  Ignoring.")  # Keep
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
    #current_position = "home"  # Always start from home.  Important.
    status_ref = db.reference(f'trolleyStatus/{request_id}')

    # Navigate directly to the home node.
    navigate_to_node(current_position, "home", request_id) # Pass request_id
    current_position = "home"

    status_ref.set("Trolley at home position")
    print("[Trolley] Arrived at home position")

def process_shopping_list(request_id, shopping_list):
    status_ref = db.reference(f'trolleyStatus/{request_id}')
    current_position = "home"  # Start at the home node

    existing_cart_ref = db.reference(f'trolleyCarts/{request_id}')
    existing_cart = existing_cart_ref.get() or {}  # Initialize if None
    print(f"Existing Cart (Before Merge): {existing_cart}")  # Keep

    if isinstance(shopping_list, dict) and 'cart' in shopping_list:
        cart_data = shopping_list['cart']
        print(f"Cart Data: {cart_data}")  # Keep

        for product_id, quantity in cart_data.items():
            print(f"  Outer loop: product_id={product_id}, quantity={quantity}")  # Keep
            if product_id in ('processed', 'action'):  # Use 'in' for tuple
                print(f"    Skipping product_id: {product_id}")  # Keep
                continue
            # Use .get(product_id, 0) to handle missing keys safely
            existing_cart[product_id] = existing_cart.get(product_id, 0) + quantity
    else:
        print("Error: Invalid shopping_list format or missing 'cart' key.")  # Keep
        status_ref.set("error:invalid_request_format")
        return

    existing_cart_ref.set(existing_cart)
    print(f"Merged cart: {existing_cart}")  # Keep

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
            print(f"Warning: Product {product_id} has no assigned row.")  # Keep

    print(f"Row 1 List: {listRow1}")  # Keep
    print(f"Row 2 List: {listRow2}")  # Keep
    print(f"Row 3 List: {listRow3}")  # Keep

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
    print("[Trolley] Returning to home...")  # Keep
    status_ref.set("returning_home")
    print("    Prompting user to proceed home...")  # Keep
    status_ref.set("waiting_for_home_confirmation")
    wait_for_home_confirmation(request_id)  # Wait for "proceed to home"
    status_ref.set("returning_home")
    print("    User confirmed. Returning home.")  # Keep

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
    navigate_to_node(current_position, "home", request_id)
    current_position = "home"  # Update position

    status_ref.set("completed")
    print("[Trolley] Shopping complete. Returned to home.")  # Keep


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
    send_command('R')  # ALWAYS turn right at RFJs

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
        # ---  Wait for User Confirmation (Firebase) ---
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
    """Waits for the user to confirm adding an item."""
    confirmation_ref = db.reference(f'trolleyConfirmations/{request_id}/confirmed')
    print("Waiting for item confirmation...")
    while True:
        if confirmation_ref.get() is True:
            confirmation_ref.set(False)  # Reset confirmation
            print("Item confirmation received.")
            return
        time.sleep(0.5)  # Check every half second

def wait_for_home_confirmation(request_id):
    """Waits for the user to confirm proceeding home."""
    home_ref = db.reference(f'trolleyConfirmations/{request_id}/homeConfirmed')
    print("Waiting for home confirmation...")
    while True:
        if home_ref.get() is True:
            home_ref.set(False)  # Reset confirmation
            print("Home confirmation received.")
            return
        time.sleep(0.5)  # Check every half second

def navigate_to_node(current_position_name, destination_node_name, request_id):
    """Navigates to a specific node using RFID and line following."""
    status_ref = db.reference(f'trolleyStatus/{request_id}')
    current_position = NODE_MAPPING[current_position_name]
    destination_node = NODE_MAPPING[destination_node_name]
    turning = False  # Flag for turning state
    turn_direction = None # 'L' or 'R'

    if current_position == destination_node:
        print(f"Already at destination: {destination_node_name}")
        return

    # --- Initial Centering (ONLY when starting from 'home') ---
    if current_position_name == "home":
        if destination_node_name.startswith("RFJ"):
            print("Centering at home...")
            while True:
                left_sensor, center_sensor, right_sensor = read_ir_sensors()
                if not left_sensor and center_sensor and not right_sensor:  # Centered
                    #send_command('S')  # Stop when centered  <- NO STOP NEEDED
                    print("Centered at home.")
                    send_command('F')  # NOW move forward after centering
                    time.sleep(0.75)
                    break  # Exit centering loop
                elif (left_sensor and not center_sensor) or (left_sensor and center_sensor and not right_sensor) :
                    send_command('N')   # Correct to the right using slight right.
                    time.sleep(0.05)
                elif (not left_sensor and not center_sensor and right_sensor) or (not left_sensor and center_sensor and right_sensor):
                    send_command('M')   # Correct to the left. using slight left
                    time.sleep(0.05)
                elif all([left_sensor,center_sensor,right_sensor]): # All on black
                  break #stop centering and proceed
                elif not any ([left_sensor, center_sensor, right_sensor]):
                    send_command('S') #stop if lost
                    print("Lost Line during centering!")
                    return #exit
                time.sleep(0.05)


        else:  # Error if not going to RFJ from home
             print("Error can only move to RFJ")
             return

    # --- Turn Logic (BEFORE main loop) ---
    # RFJ to pdt
    elif current_position_name.startswith("RFJ") and destination_node_name.startswith("pdt"):
        send_command('F') # move forward a bit
        time.sleep(1.0)  # delay
        send_command('R')  # Turn right from RFJ to product
        turning = True
        turn_direction = 'R'

    #RBJ to RFJ turn logic
    elif current_position_name.startswith("RBJ") and destination_node_name.startswith("RFJ"):
        send_command("F") #added fwd before turn
        time.sleep(1.0)  #added delay
        send_command("L") #Turn left
        turning = True
        turn_direction = 'L'

    #RBJ to RBJ
    elif current_position_name.startswith("RBJ") and destination_node_name.startswith("RBJ"):
        send_command('F')
        time.sleep(0.5)
    #RFJ TO RBJ
    elif current_position_name.startswith("RFJ") and destination_node_name.startswith("RBJ"):
        send_command('F')
        time.sleep(0.5)

    #going back home from RFJ
    elif current_position_name.startswith("RFJ") and destination_node_name == "home":
        send_command('F')
        time.sleep(1.0)
        send_command('R')
        turning = True
        turn_direction = 'R'
        time.sleep(0.5)


     #going from pdt to pdt, or pdt to RBJ
    elif current_position_name.startswith("pdt") and (destination_node_name.startswith("pdt") or destination_node_name.startswith("RBJ")):
        send_command('F')
        time.sleep(0.5)

    # --- Main Navigation Loop ---
    while True:
        # --- 1. RFID Check (Highest Priority) ---
        if esp32.in_waiting > 0:
            response = esp32.readline().decode('utf-8').rstrip()
            if response.startswith("RFID:"):
                uid = response[5:]
                print(f"RFID Detected: {uid}")
                expected_uid = get_expected_uid(destination_node_name)

                if expected_uid is None:
                    print(f"No expected UID found for {destination_node_name}.")
                    continue

                if uid == expected_uid:
                    print(f"Reached destination: {destination_node_name}")
                    status_ref.set(f"waiting_for_rfid:{destination_node_name}")
                    send_command('S')  # Stop
                    return  # Exit navigation loop

                else:
                    print(f"Incorrect RFID. Expected: {expected_uid}, Got: {uid}")
                    send_command("F") # Continue forward.

        # --- 2. IR Sensor Reading and Turn Completion Check ---
        left_sensor, center_sensor, right_sensor = read_ir_sensors()

        if turning:
            if turn_direction == 'R':
                # Right Turn Completion Check:
                #print(left_sensor, center_sensor, right_sensor) #for debugging purposes
                if not left_sensor and center_sensor and not right_sensor: #back to center
                    turning = False  # Turn complete
                    turn_direction = None
                    send_command('F')
                    print("Right turn complete, resuming forward motion.")


            elif turn_direction == 'L':
                # Left Turn Completion Check:
                #print(left_sensor, center_sensor, right_sensor) #for debugging purposes
               if not left_sensor and center_sensor and not right_sensor:   #back to center
                    turning = False
                    turn_direction = None
                    send_command('F')
                    print("Left turn complete, resuming forward motion.")



        # --- 3. Line Following (if not turning) ---
        elif not turning:  # Normal line following
            response = follow_line()
            if response == "LOST":
                send_command('S')  # All white, stop.
                print("Line Lost!")
                return #exit function
            elif response == "CENTERED":
               send_command("F")
            elif response == "SLIGHT_LEFT":
                send_command('M')  # Slight right
            elif response == "SLIGHT_RIGHT":
                send_command('N')  # Slight left
            #No need for other since it will be taken care by the above conditions
        time.sleep(0.05)  # Short delay

def get_node_number_for_product(product_id):
    try:
        product_data = db.reference(f'/products/{product_id}').get()
        if product_data and 'node' in product_data:
            return int(product_data['node'])
        else:
            print(f"Error: No node mapping for product ID {product_id}")
            return -1  # Or raise an exception
    except Exception as e:
        print(f"Error fetching product node: {e}")
        return -1  # Or re-raise the exception

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
    """Gets the expected UID for a given node name."""
    try:
        product_data = db.reference(f'/products/{node_name}').get()
        if product_data and 'uid' in product_data:
             return product_data['uid'].lower() #important
        else:
            print(f"Error: No UID found for node ID: {node_name}")
            return None
    except Exception as e:
        print(f"Error fetching product UID: {e}")
        return None
# --- Main Execution ---
if __name__ == "__main__":
    ref = db.reference('/')  # Get a reference to the root of the database
    requests_ref = ref.child('trolleyRequests')
    requests_ref.listen(handle_new_request)  # Listen for new requests

    print("Trolley controller started. Listening for requests...")

    try:
        while True:
            time.sleep(1)  # Keep the main thread alive
    except KeyboardInterrupt:
        print("Trolley controller stopped.")
    finally:
        lgpio.gpiochip_close(h)  # Release GPIO resources
