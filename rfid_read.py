from mfrc522 import SimpleMFRC522

reader = SimpleMFRC522()
print("Place your RFID tag near the reader...")

try:
    id, text = reader.read()
    print(f"RFID Tag ID: {id}")
    print(f"Data on Tag: {text}")
except Exception as e:
    print(f"Error: {e}")
finally:
    print("Test complete.")
