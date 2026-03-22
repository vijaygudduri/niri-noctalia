#!/usr/bin/env python3

import pyudev
import time
import threading
from subprocess import Popen

device_memory = {}
last_event_time = {}
COOLDOWN = 1.0

def get_port_key(device):
    """
    Extract the stable USB port address from sys_path.
    e.g. /sys/devices/pci.../usb1/1-1/1-1.2  ->  '1-1.2'
    This is identical across all duplicate events for one physical plug.
    """
    return device.sys_path.split('/')[-1]

def send_notification(title, body, icon):
    threading.Thread(
        target=lambda: Popen(['notify-send', title, body, '-i', icon]),
        daemon=True
    ).start()

def notify_user(device):
    if device.device_type != 'usb_device':
        return

    action = device.action
    if action not in ('add', 'remove'):
        return

    # action logs for debug
    # print(f"[{action}] path={device.sys_path} key={get_port_key(device)}")

    key = (action, get_port_key(device))
    now = time.monotonic()

    if now - last_event_time.get(key, 0) < COOLDOWN:
        return
    last_event_time[key] = now

    sys_path = device.sys_path

    if action == 'add':
        props = device.properties  # No deprecation warning
        vendor = (props.get('ID_VENDOR_FROM_DATABASE')
                  or props.get('ID_VENDOR', 'Unknown Vendor'))
        model  = (props.get('ID_MODEL_FROM_DATABASE')
                  or props.get('ID_MODEL', 'Unknown Device'))
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

    print("Monitoring USB events... (Ctrl+C to stop)")
    observer = pyudev.MonitorObserver(monitor, callback=notify_user)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping.")
        observer.stop()

if __name__ == "__main__":
    main()
