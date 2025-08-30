import time
import lgpio

# --- HC-SR04 Ultrasonic Sensor Pins (Raspberry Pi) ---
TRIG_PIN = 17  # Example pin - Connect to Trig
ECHO_PIN = 24  # Example pin - Connect to Echo
BUZZER_PIN = 18  # Example pin - Connect to Buzzer + (positive) pin

# --- lgpio Setup ---
h = lgpio.gpiochip_open(0)  # Open the default GPIO chip

# --- Set Pin Modes using lgpio ---
lgpio.gpio_claim_output(h, TRIG_PIN, 0)  # Set initial state to LOW
lgpio.gpio_claim_input(h, ECHO_PIN)  # Echo is an input
lgpio.gpio_claim_output(h, BUZZER_PIN, 0)  # Initially buzzer off


def get_distance():
    """Measures distance using the HC-SR04 ultrasonic sensor."""
    # Ensure trigger is LOW
    lgpio.gpio_write(h, TRIG_PIN, 0)
    time.sleep(0.1)

    # Send 10us pulse
    lgpio.gpio_write(h, TRIG_PIN, 1)
    time.sleep(0.00001)
    lgpio.gpio_write(h, TRIG_PIN, 0)

    # Measure pulse width
    pulse_start = time.time()
    pulse_end = time.time()

    timeout_start = time.time()
    while lgpio.gpio_read(h, ECHO_PIN) == 0:
        pulse_start = time.time()
        if pulse_start - timeout_start > 0.02:  # Timeout
            return -1

    timeout_start = time.time()
    while lgpio.gpio_read(h, ECHO_PIN) == 1:
        pulse_end = time.time()
        if pulse_end - timeout_start > 0.02:  # Timeout
            return -1

    pulse_duration = pulse_end - pulse_start
    distance = pulse_duration * 17150
    distance = round(distance, 2)
    return distance


def main():
    """Main function to test the ultrasonic sensor and buzzer."""
    try:
        while True:
            distance = get_distance()

            if distance != -1:  # Check for valid distance
                print(f"Distance: {distance} cm")

                if distance < 20:  # Adjust the threshold as needed
                    print("Obstacle detected!")
                    lgpio.gpio_write(h, BUZZER_PIN, 1)  # Turn on buzzer
                else:
                    lgpio.gpio_write(h, BUZZER_PIN, 0)  # Turn off buzzer
            else:
                print("Measurement timed out.")

            time.sleep(0.5)  # Delay between measurements

    except KeyboardInterrupt:
        print("Measurement stopped by user")
    finally:
        lgpio.gpiochip_close(h)  # Clean up lgpio on exit


if __name__ == "__main__":
    main()
