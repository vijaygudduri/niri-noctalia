#!/usr/bin/env python3

import pyudev
import signal
import socket
import sys
import threading
from subprocess import Popen

# --- SINGLE INSTANCE LOCK ---
# Bind a unique abstract Unix socket to ensure only one instance runs at a time.
# If the socket is already bound, another instance is running — exit immediately.
try:
    lock_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    lock_socket.bind('\0usb_notify_lock_99')
except socket.error:
    print("USB Notify is already running. Exiting.")
    sys.exit(0)
# ----------------------------

# How long to ignore duplicate events for the same device action (in seconds)
COOLDOWN = 1.5

# How long to wait for a block device to appear before declaring "not ready" (in seconds)
# Only reached if no block device event arrives — normal pendrives resolve in ~100-500ms
NOT_READY_TIMEOUT = 4.0

# Stores sys_path -> (full_name, icon) for connected devices
# Used at disconnect time when udev properties may no longer be available
device_memory = {}

# Stores sys_path -> {name, timer, resolved} for USB devices awaiting block device confirmation
# Entries are added on USB add and removed on USB remove or once resolved
pending_usb = {}

# Tracks the last event time per (action, sys_path) key to enforce COOLDOWN
last_event_time = {}

# Lock to protect pending_usb from race conditions between the
# MonitorObserver thread and Timer threads firing simultaneously
pending_lock = threading.Lock()

def send_notification(title, body, icon):
    # Fire-and-forget: spawn notify-send in a daemon thread so it never blocks the event loop.
    # -t 5000        : auto-dismiss after 5 seconds
    # -h transient:1 : mark as transient so it's not persisted in notification history
    threading.Thread(
        target=lambda: Popen([
            'notify-send', title, body,
            '-i', icon,
            '-a', 'USB-Monitor',
            '-t', '5000',
            '-h', 'int:transient:1'
        ]),
        daemon=True
    ).start()

def is_hid_device(device):
    # Check USB interface class 03 = HID (keyboards, mice, joysticks)
    # ID_USB_INTERFACES format is like ':03:' or '03xx:' so we check both
    interface_class = device.properties.get('ID_USB_INTERFACES', '')
    if ':03' in interface_class or interface_class.startswith('03'):
        return True
    # Fallback: check udev input flags set for known input devices
    if any(device.properties.get(k) == '1' for k in (
        'ID_INPUT_KEYBOARD', 'ID_INPUT_MOUSE', 'ID_INPUT_JOYSTICK'
    )):
        return True
    return False

def on_not_ready(usb_sys_path):
    # This fires only if no block device event arrived within NOT_READY_TIMEOUT seconds.
    # Guarded by 'resolved' flag to prevent double-notification if block event and
    # timer fire at nearly the same time (race condition guard).
    with pending_lock:
        entry = pending_usb.get(usb_sys_path)
        if entry is None or entry['resolved']:
            return
        entry['resolved'] = True
        name = entry['name']
    send_notification(
        "USB Connected But Not Ready",
        f"{name} — Block device not created, try after a reboot.",
        'dialog-warning'
    )

def on_usb_add(device):
    sys_path = device.sys_path
    props = device.properties

    # Prefer human-readable names from udev database, fall back to raw IDs
    vendor = props.get('ID_VENDOR_FROM_DATABASE') or props.get('ID_VENDOR', 'Unknown')
    model  = props.get('ID_MODEL_FROM_DATABASE')  or props.get('ID_MODEL',  'Device')
    full_name = f"{vendor} {model}".replace("0000 ", "").strip()

    # Determine icon at connect time while all udev properties are still available.
    # Stored in device_memory so disconnect notification uses the correct icon
    # (udev properties may be gone by the time the remove event fires).
    icon = 'input-mouse' if is_hid_device(device) else 'drive-removable-media'
    device_memory[sys_path] = (full_name, icon)

    if is_hid_device(device):
        # HID devices (mouse, keyboard) don't create block devices — notify immediately
        send_notification("USB Connected", full_name, icon)
        return

    # For storage devices, start a fallback timer.
    # If a block device add event arrives first (on_block_add), the timer is cancelled
    # and "Ready" is notified instantly. The timer only fires if no block device appears.
    timer = threading.Timer(NOT_READY_TIMEOUT, on_not_ready, args=[sys_path])

    with pending_lock:
        pending_usb[sys_path] = {
            'name': full_name,
            'timer': timer,
            'resolved': False  # flipped to True once either ready or not-ready fires
        }

    timer.start()

def on_usb_remove(device):
    sys_path = device.sys_path

    # Cancel any pending timer for this device in case it's removed
    # before the block device check resolves
    with pending_lock:
        entry = pending_usb.pop(sys_path, None)
    if entry:
        entry['timer'].cancel()

    # Retrieve stored name and icon — udev properties are unreliable at remove time
    full_name, icon = device_memory.pop(sys_path, ("Unknown Device", "drive-removable-media"))
    send_notification("USB Disconnected", full_name, icon)

def on_block_add(device):
    # A block device (e.g. sdb) was created. Walk up its ancestor chain to find
    # the parent USB device and match it against pending_usb.
    # We skip usb_interface nodes (DEVTYPE != usb_device) and only match
    # the actual usb_device entry that was keyed in pending_usb during on_usb_add.
    for ancestor in device.ancestors:
        if ancestor.subsystem != 'usb':
            continue
        if ancestor.get('DEVTYPE') != 'usb_device':
            continue

        usb_sys_path = ancestor.sys_path

        with pending_lock:
            entry = pending_usb.get(usb_sys_path)
            if entry is None or entry['resolved']:
                return
            entry['resolved'] = True
            entry['timer'].cancel()  # cancel the not-ready fallback timer
            name = entry['name']

        send_notification("USB Connected & Ready", name, 'drive-removable-media')
        return

def notify_user(device):
    action = device.action
    subsystem = device.subsystem

    # Deduplicate rapid duplicate events for the same device using a cooldown
    key = (action, device.sys_path)
    now = __import__('time').monotonic()
    if now - last_event_time.get(key, 0) < COOLDOWN:
        return
    last_event_time[key] = now

    # Route USB device events to add/remove handlers
    if subsystem == 'usb' and device.get('DEVTYPE') == 'usb_device':
        if action == 'add':
            on_usb_add(device)
        elif action == 'remove':
            on_usb_remove(device)

    # Route block device add events to check if they belong to a pending USB device
    elif subsystem == 'block' and action == 'add':
        on_block_add(device)

def main():
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)

    # Monitor both USB and block subsystems:
    # - 'usb' fires when a USB device is plugged or unplugged
    # - 'block' fires when the kernel creates a block device (e.g. sdb) for storage
    monitor.filter_by(subsystem='usb')
    monitor.filter_by(subsystem='block')

    # MonitorObserver runs a background thread blocked on the netlink socket.
    # It consumes zero CPU until the kernel pushes an event.
    observer = pyudev.MonitorObserver(monitor, callback=notify_user)
    observer.daemon = True
    observer.start()

    print("Monitoring USB events (event-driven mode)...")

    # Handle SIGTERM (e.g. from systemctl stop) for clean shutdown
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    try:
        # signal.pause() suspends the main thread with zero CPU wakeups.
        # The process sleeps entirely until SIGINT (Ctrl+C) or SIGTERM arrives.
        # This is the most battery-efficient way to keep the process alive.
        signal.pause()
    except KeyboardInterrupt:
        observer.stop()

if __name__ == "__main__":
    main()
    
