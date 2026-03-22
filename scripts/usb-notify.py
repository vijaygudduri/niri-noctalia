#!/usr/bin/env python3

import pyudev
import time
import socket
import sys
import threading
from subprocess import Popen

# --- SINGLE INSTANCE LOCK ---
# This opens a unique abstract socket. If it's already open, the script exits.
try:
    lock_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    lock_socket.bind('\0usb_notify_lock_99')
except socket.error:
    print("USB Notify is already running. Exiting.")
    sys.exit(0)
# ----------------------------

device_memory = {}
last_event_time = {}
COOLDOWN = 1.5

def send_notification(title, body, icon):
    threading.Thread(
        target=lambda: Popen(['notify-send', title, body, '-i', icon, '-a', 'USB-Monitor']),
        daemon=True
    ).start()

def notify_user(device):
    if device.get('DEVTYPE') != 'usb_device':
        return

    action = device.action
    if action not in ('add', 'remove'):
        return

    sys_path = device.sys_path
    key = (action, sys_path)
    now = time.monotonic()

    if now - last_event_time.get(key, 0) < COOLDOWN:
        return
    last_event_time[key] = now

    if action == 'add':
        props = device.properties
        vendor = props.get('ID_VENDOR_FROM_DATABASE') or props.get('ID_VENDOR', 'Unknown')
        model = props.get('ID_MODEL_FROM_DATABASE') or props.get('ID_MODEL', 'Device')
        full_name = f"{vendor} {model}".replace("0000 ", "").strip()
        
        device_memory[sys_path] = full_name
        send_notification("USB Connected", full_name, 'drive-removable-media')

    elif action == 'remove':
        full_name = device_memory.pop(sys_path, "Unknown Device")
        send_notification("USB Disconnected", full_name, 'drive-removable-media')

def main():
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem='usb')

    print("Monitoring USB (Single Instance Mode)...")
    observer = pyudev.MonitorObserver(monitor, callback=notify_user)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

if __name__ == "__main__":
    main()
    
