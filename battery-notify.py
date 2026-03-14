#!/usr/bin/env python3
import os
import asyncio
import signal
import logging
from logging.handlers import RotatingFileHandler
from dataclasses import dataclass
from typing import Optional

# ──────────────────────────────── LOGGING SETUP ────────────────────────────────
LOG_FILE = os.path.expanduser("~/.cache/battery-notify.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

handler = RotatingFileHandler(LOG_FILE, maxBytes=20000, backupCount=1)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

logger = logging.getLogger("BatteryMonitor")
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# ──────────────────────────────── CONFIGURATION ────────────────────────────────
LOCK_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), ".battery-notify.lock")

CRITICAL_THRESHOLD = 5

@dataclass(frozen=True)
class Notification:
    title: str
    message: str       # Use {} for percentage substitution
    icon: str          # Use {0} for padded (080), {1} for unpadded (80)
    urgency: str

# --- Status change events ---
NOTIFY_PLUGGED   = Notification("Charger Plugged In",  "Battery at {}%. Charging started.",  "battery-{0}-charging-symbolic", "normal")
NOTIFY_UNPLUGGED = Notification("Charger Unplugged",   "Battery at {}%. Running on battery.", "battery-{0}-symbolic",          "normal")

# --- Critical repeat alert ---
NOTIFY_CRITICAL  = Notification("Battery Critically Low", "Battery at {}% — PLUG IN IMMEDIATELY!", "battery-000-symbolic", "critical")

# --- Discharging thresholds (state=2) ---
DISCHARGING_THRESHOLDS: dict[int, Notification] = {
    20: Notification("Battery Low", "Battery at 20% — consider plugging in.", "battery-020-symbolic", "critical"),
    15: Notification("Battery Low", "Battery at 15% — low power.",            "battery-020-symbolic", "critical"),
    10: Notification("Battery Low", "Battery at 10% — critically low.",       "battery-010-symbolic", "critical"),
}

# --- Charging thresholds (state=1 or 4) ---
CHARGING_THRESHOLDS: dict[int, Notification] = {
     80: Notification("Battery Charged", "Battery at 80% — good time to unplug.",  "battery-080-charging-symbolic", "normal"),
     85: Notification("Battery Charged", "Battery at 85% - unplug please",         "battery-080-charging-symbolic", "normal"),
     90: Notification("Battery Charged", "Battery at 90% - unplug the cable",      "battery-090-charging-symbolic", "normal"),
     95: Notification("Battery Charged", "Battery at 95% - lets remove the cord",  "battery-090-charging-symbolic", "normal"),
    100: Notification("Battery Charged", "Battery fully charged - Please unplug",  "battery-100-charging-symbolic", "normal"),
}

# ──────────────────────────────── CORE LOGIC ────────────────────────────────

class BatteryMonitor:
    def __init__(self):
        self.last_state: Optional[int] = None
        self.notified_levels: set = set()
        self.critical_task: Optional[asyncio.Task] = None
        self.current_percentage: int = 0

    def _icon_formats(self, percentage: int) -> tuple[str, str]:
        """Returns (padded '080', unpadded '80') icon format strings."""
        val = min(100, percentage // 10 * 10)
        return f"{val:03}", str(val)

    def _format_icon(self, icon_tmpl: str, padded: str, unpadded: str) -> str:
        return icon_tmpl.format(padded, unpadded) if "{" in icon_tmpl else icon_tmpl

    async def _notify(self, notif: Notification, percentage: int, padded: str, unpadded: str):
        icon    = self._format_icon(notif.icon, padded, unpadded)
        title   = notif.title
        message = notif.message.format(percentage)
        logger.info(f"NOTIFY [{notif.urgency}] {title} — {message}")
        try:
            await asyncio.create_subprocess_exec(
                "notify-send", "-u", notif.urgency, "-i", icon, "-e", title, message
            )
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")

    async def _critical_loop(self):
        """Fires every 2 seconds until the charger is plugged in."""
        padded, unpadded = self._icon_formats(self.current_percentage)
        while True:
            await self._notify(NOTIFY_CRITICAL, self.current_percentage, padded, unpadded)
            await asyncio.sleep(5)

    async def _stop_critical_loop(self):
        if self.critical_task:
            self.critical_task.cancel()
            try:
                await self.critical_task
            except asyncio.CancelledError:
                pass
            self.critical_task = None

    async def handle_change(self, percentage: int, state: int):
        self.current_percentage = percentage
        padded, unpadded = self._icon_formats(percentage)
        is_charging = state in (1, 4)

        # 1. Handle plug / unplug transitions
        if state == 2 and self.last_state not in (2, None):
            await self._notify(NOTIFY_UNPLUGGED, percentage, padded, unpadded)
            self.notified_levels.clear()

        elif is_charging and self.last_state == 2:
            await self._notify(NOTIFY_PLUGGED, percentage, padded, unpadded)
            self.notified_levels.clear()
            await self._stop_critical_loop()

        self.last_state = state

        # 2. Fire threshold notifications (once per level per session)
        thresholds = CHARGING_THRESHOLDS if is_charging else DISCHARGING_THRESHOLDS
        if percentage in thresholds and percentage not in self.notified_levels:
            await self._notify(thresholds[percentage], percentage, padded, unpadded)
            self.notified_levels.add(percentage)

        # 3. Critical loop control
        if state == 2 and percentage <= CRITICAL_THRESHOLD:
            if not self.critical_task:
                self.critical_task = asyncio.create_task(self._critical_loop())
        else:
            await self._stop_critical_loop()

# ──────────────────────────────── MAIN SYSTEM ────────────────────────────────

async def run_monitor():
    try:
        from dbus_next.aio import MessageBus
        from dbus_next import BusType
    except ImportError as e:
        logger.error(f"DEPENDENCY MISSING: {e}. Install 'python-dbus-next'.")
        return

    # Atomic lock using O_EXCL to prevent race conditions
    lock_fd: Optional[int] = None
    try:
        lock_fd = os.open(LOCK_FILE, os.O_CREAT | os.O_WRONLY | os.O_EXCL)
        os.write(lock_fd, str(os.getpid()).encode())
    except FileExistsError:
        try:
            with open(LOCK_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return  # Another instance is running
        except (ProcessLookupError, ValueError):
            os.remove(LOCK_FILE)
            return await run_monitor()  # Stale lock — retry

    logger.info("========== Battery Monitor Service Started ==========")

    try:
        bus     = await MessageBus(bus_type=BusType.SYSTEM).connect()
        intro   = await bus.introspect('org.freedesktop.UPower', '/org/freedesktop/UPower')
        obj     = bus.get_proxy_object('org.freedesktop.UPower', '/org/freedesktop/UPower', intro)
        upower  = obj.get_interface('org.freedesktop.UPower')

        devices = await upower.call_enumerate_devices()
        bat_path = next((d for d in devices if 'battery' in d), None)
        if not bat_path:
            logger.error("No battery detected.")
            return

        bat_intro = await bus.introspect('org.freedesktop.UPower', bat_path)
        bat_obj   = bus.get_proxy_object('org.freedesktop.UPower', bat_path, bat_intro)
        props     = bat_obj.get_interface('org.freedesktop.DBus.Properties')

        monitor = BatteryMonitor()

        async def _get_battery() -> tuple[int, int]:
            p = (await props.call_get('org.freedesktop.UPower.Device', 'Percentage')).value
            s = (await props.call_get('org.freedesktop.UPower.Device', 'State')).value
            return int(p), s

        async def on_properties_changed(interface, changed_props, invalidated):
            if 'Percentage' in changed_props or 'State' in changed_props:
                p, s = await _get_battery()
                await monitor.handle_change(p, s)

        props.on_properties_changed(on_properties_changed)

        # Initial check on startup
        p_init, s_init = await _get_battery()
        await monitor.handle_change(p_init, s_init)

        # Graceful shutdown on SIGINT / SIGTERM
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

        await stop_event.wait()
        logger.info("Stopping Battery Monitor...")

    except Exception:
        logger.exception("Fatal error in main loop:")
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)

if __name__ == "__main__":
    try:
        asyncio.run(run_monitor())
    except Exception as e:
        logger.error(f"Failed to start script: {e}")
        
