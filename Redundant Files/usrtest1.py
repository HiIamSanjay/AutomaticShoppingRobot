from signal import signal, SIGTERM, SIGHUP, pause
from time import sleep
from threading import Thread
from gpiozero import DistanceSensor

reading = True
sensor = DistanceSensor(echo=17, trigger=24)

def safe_exit(signum, frame):
    exit(1)

def read_distance():
    while reading:
        message = f"Distance: {sensor.value:1.2f} m"
        print(message)

        sleep(0.1)

try:
    signal(SIGTERM, safe_exit)
    signal(SIGHUP, safe_exit)

    reader = Thread(target=read_distance, daemon=True)
    reader.start()

    pause()

except KeyboardInterrupt:
    pass

finally:
    reading = False
    reader.join()
    sensor.close()
