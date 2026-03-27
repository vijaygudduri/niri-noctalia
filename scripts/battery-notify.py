#!/usr/bin/env python3
import os
import asyncio
import signal
import logging
from logging.handlers import RotatingFileHandler
from dataclasses import dataclass
from typing import Optional

# ──────────────────────────────── LOGGING SETUP ────────────────────────────────
# Set up a rotating log file in ~/.cache/ so it doesn't grow unboundedly.
# maxBytes=20000 keeps ~20 KB per file, with 1 backup (battery-notify.log.1).
LOG_FILE = os.path.expanduser("~/.cache/battery-notify.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

handler = RotatingFileHandler(LOG_FILE, maxBytes=20000, backupCount=1)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

logger = logging.getLogger("BatteryMonitor")
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# ──────────────────────────────── CONFIGURATION ────────────────────────────────
# Lock file stored in XDG_RUNTIME_DIR (e.g. /run/user/1000/) or /tmp as fallback.
# Used to prevent multiple instances of this script from running simultaneously.
LOCK_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), ".battery-notify.lock")

# Battery percentage at or below which the critical repeat-alert loop is triggered.
CRITICAL_THRESHOLD = 5

@dataclass(frozen=True)
class Notification:
    title: str
    message: str       # Use {} for percentage substitution
    icon: str          # Use {0} for padded (080), {1} for unpadded (80)
    urgency: str

# ── Status change events ──────────────────────────────────────────────────────
# Fired once whenever the charger is connected or disconnected.
NOTIFY_PLUGGED   = Notification("Charger Plugged In",  "Battery at {}%. Charging started.",  "battery-{0}-charging-symbolic", "normal")
NOTIFY_UNPLUGGED = Notification("Charger Unplugged",   "Battery at {}%. Running on battery.", "battery-{0}-symbolic",          "normal")

# ── Critical repeat alert ─────────────────────────────────────────────────────
# This notification repeats every 5 seconds until the charger is connected.
NOTIFY_CRITICAL  = Notification("Battery Critically Low", "Battery at {}% — PLUG IN IMMEDIATELY!", "battery-000-symbolic", "critical")

# ── Discharging thresholds (UPower state = 2) ─────────────────────────────────
# Each entry fires once per discharge session when the battery hits that exact %.
# Keys are the battery percentages that trigger the notification.
DISCHARGING_THRESHOLDS: dict[int, Notification] = {
    20: Notification("Battery Low", "Battery at 20% — Consider inserting the cord",          "battery-020-symbolic", "critical"),
    15: Notification("Battery Low", "Battery at 15% — Low on juice, lets insert some power", "battery-020-symbolic", "critical"),
    10: Notification("Battery Low", "Battery at 10% — Critically low, dude insert it now",   "battery-010-symbolic", "critical"),
}

# ── Charging thresholds (UPower state = 1 or 4) ───────────────────────────────
# Each entry fires once per charge session when the battery hits that exact %.
# Only 90%, 95%, and 100% are included — lower thresholds (80%, 85%) are omitted
# to avoid nagging the user too early while charging.
CHARGING_THRESHOLDS: dict[int, Notification] = {
     90: Notification("Battery Charged", "Battery at 90% - Enough power to last few hours",    "battery-090-charging-symbolic", "normal"),
     95: Notification("Battery Charged", "Battery at 95% - Juice filled up, please remove it", "battery-090-charging-symbolic", "normal"),
    100: Notification("Battery Charged", "Battery fully charged - Pull Out Right Now",         "battery-100-charging-symbolic", "normal"),
}

# ──────────────────────────────── CORE LOGIC ────────────────────────────────

class BatteryMonitor:
    def __init__(self):
        # Tracks the previous UPower state to detect plug/unplug transitions.
        self.last_state: Optional[int] = None
        # Tracks which percentage thresholds have already been notified this session,
        # so each threshold fires at most once per charge/discharge cycle.
        self.notified_levels: set = set()
        # Holds the asyncio Task for the critical repeat-alert loop, if active.
        self.critical_task: Optional[asyncio.Task] = None
        # Cached current percentage, used inside the critical loop.
        self.current_percentage: int = 0

    def _icon_formats(self, percentage: int) -> tuple[str, str]:
        """Returns (padded '080', unpadded '80') icon format strings.

        Icons are named in steps of 10 (e.g. battery-080-symbolic), so we
        round down to the nearest 10 and format both zero-padded and plain variants.
        """
        val = min(100, percentage // 10 * 10)
        return f"{val:03}", str(val)

    def _format_icon(self, icon_tmpl: str, padded: str, unpadded: str) -> str:
        """Substitutes {0} and {1} placeholders in an icon template string.

        If the template has no placeholders (e.g. 'battery-000-symbolic'),
        it is returned as-is.
        """
        return icon_tmpl.format(padded, unpadded) if "{" in icon_tmpl else icon_tmpl

    async def _notify(self, notif: Notification, percentage: int, padded: str, unpadded: str):
        """Sends a desktop notification via notify-send.

        Resolves the icon name and percentage substitution before calling the
        system command. Errors are logged rather than raised so the monitor
        keeps running even if notifications fail.
        """
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
        """Fires a critical battery alert every 5 seconds until the charger is plugged in.

        Runs as a background asyncio Task. The Task is cancelled by
        _stop_critical_loop() when the battery state leaves the critical zone.
        """
        padded, unpadded = self._icon_formats(self.current_percentage)
        while True:
            await self._notify(NOTIFY_CRITICAL, self.current_percentage, padded, unpadded)
            await asyncio.sleep(5)

    async def _stop_critical_loop(self):
        """Cancels the critical alert Task if one is currently running.

        Safe to call even when no Task is active — it's a no-op in that case.
        """
        if self.critical_task:
            self.critical_task.cancel()
            try:
                await self.critical_task
            except asyncio.CancelledError:
                pass
            self.critical_task = None

    async def handle_change(self, percentage: int, state: int):
        """Main handler called whenever the battery percentage or charge state changes.

        UPower state values:
          1 = Charging
          2 = Discharging
          4 = Fully charged (also treated as charging for threshold purposes)

        The method does three things in order:
          1. Detects plug/unplug transitions and fires the appropriate event notification.
          2. Checks whether the current percentage matches any threshold and fires
             that threshold notification (each fires at most once per session).
          3. Starts or stops the critical alert loop based on state and percentage.
        """
        self.current_percentage = percentage
        padded, unpadded = self._icon_formats(percentage)
        is_charging = state in (1, 4)

        # ── 1. Handle plug / unplug transitions ──────────────────────────────
        # When transitioning from a non-discharging state to discharging, notify
        # the user the charger was unplugged and reset the threshold tracker so
        # the same levels can fire again in this new discharge session.
        if state == 2 and self.last_state not in (2, None):
            await self._notify(NOTIFY_UNPLUGGED, percentage, padded, unpadded)
            self.notified_levels.clear()

        # When transitioning from discharging to charging, notify the user the
        # charger was plugged in, reset the threshold tracker for the new charge
        # session, and cancel any active critical alert loop.
        elif is_charging and self.last_state == 2:
            await self._notify(NOTIFY_PLUGGED, percentage, padded, unpadded)
            self.notified_levels.clear()
            await self._stop_critical_loop()

        self.last_state = state

        # ── 2. Fire threshold notifications (once per level per session) ──────
        # Choose the correct threshold table based on charge direction, then check
        # if the current percentage matches an entry that hasn't been notified yet.
        thresholds = CHARGING_THRESHOLDS if is_charging else DISCHARGING_THRESHOLDS
        if percentage in thresholds and percentage not in self.notified_levels:
            await self._notify(thresholds[percentage], percentage, padded, unpadded)
            self.notified_levels.add(percentage)

        # ── 3. Critical loop control ──────────────────────────────────────────
        # Start the repeat-alert loop if discharging and at or below the critical
        # threshold, but only if it isn't already running.
        # Stop the loop in all other cases (charging, or above threshold).
        if state == 2 and percentage <= CRITICAL_THRESHOLD:
            if not self.critical_task:
                self.critical_task = asyncio.create_task(self._critical_loop())
        else:
            await self._stop_critical_loop()

# ──────────────────────────────── MAIN SYSTEM ────────────────────────────────

async def run_monitor():
    """Sets up the D-Bus connection and starts listening for battery property changes.

    Uses dbus-next to subscribe to the UPower device's PropertiesChanged signal.
    An atomic lock file prevents duplicate instances from running concurrently.
    The monitor shuts down gracefully on SIGINT or SIGTERM.
    """
    try:
        from dbus_next.aio import MessageBus
        from dbus_next import BusType
    except ImportError as e:
        logger.error(f"DEPENDENCY MISSING: {e}. Install 'python-dbus-next'.")
        return

    # ── Atomic lock file ──────────────────────────────────────────────────────
    # O_CREAT | O_WRONLY | O_EXCL atomically creates the file only if it doesn't
    # exist, preventing a race condition between two concurrent startups.
    lock_fd: Optional[int] = None
    try:
        lock_fd = os.open(LOCK_FILE, os.O_CREAT | os.O_WRONLY | os.O_EXCL)
        os.write(lock_fd, str(os.getpid()).encode())
    except FileExistsError:
        # Lock exists — check if the recorded PID is still alive.
        try:
            with open(LOCK_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)          # Signal 0 = existence check only.
            return                   # Process alive — another instance is running.
        except (ProcessLookupError, ValueError):
            # Stale lock (process gone or PID unreadable) — remove it and retry.
            os.remove(LOCK_FILE)
            return await run_monitor()

    logger.info("========== Battery Monitor Service Started ==========")

    try:
        # ── Connect to UPower via D-Bus ───────────────────────────────────────
        bus     = await MessageBus(bus_type=BusType.SYSTEM).connect()
        intro   = await bus.introspect('org.freedesktop.UPower', '/org/freedesktop/UPower')
        obj     = bus.get_proxy_object('org.freedesktop.UPower', '/org/freedesktop/UPower', intro)
        upower  = obj.get_interface('org.freedesktop.UPower')

        # Find the first device path that contains 'battery' (e.g. /org/freedesktop/UPower/devices/battery_BAT0).
        devices = await upower.call_enumerate_devices()
        bat_path = next((d for d in devices if 'battery' in d), None)
        if not bat_path:
            logger.error("No battery detected.")
            return

        # Obtain the proxy object for the battery device and its Properties interface.
        bat_intro = await bus.introspect('org.freedesktop.UPower', bat_path)
        bat_obj   = bus.get_proxy_object('org.freedesktop.UPower', bat_path, bat_intro)
        props     = bat_obj.get_interface('org.freedesktop.DBus.Properties')

        monitor = BatteryMonitor()

        async def _get_battery() -> tuple[int, int]:
            """Reads the current Percentage and State from UPower D-Bus properties."""
            p = (await props.call_get('org.freedesktop.UPower.Device', 'Percentage')).value
            s = (await props.call_get('org.freedesktop.UPower.Device', 'State')).value
            return int(p), s

        async def on_properties_changed(interface, changed_props, invalidated):
            """D-Bus signal handler fired whenever any battery property changes.

            We only care about Percentage and State — other properties (like
            TimeToEmpty) are ignored to avoid unnecessary processing.
            """
            if 'Percentage' in changed_props or 'State' in changed_props:
                p, s = await _get_battery()
                await monitor.handle_change(p, s)

        # Subscribe to the PropertiesChanged signal on the battery device.
        props.on_properties_changed(on_properties_changed)

        # ── Initial check on startup ──────────────────────────────────────────
        # Process the current battery state immediately so the user gets an alert
        # if the battery is already in a notable condition when the script starts.
        p_init, s_init = await _get_battery()
        await monitor.handle_change(p_init, s_init)

        # ── Graceful shutdown on SIGINT / SIGTERM ─────────────────────────────
        # Register signal handlers that simply set an asyncio Event, allowing the
        # event loop to exit cleanly without raising exceptions.
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

        # Block here until a shutdown signal is received.
        await stop_event.wait()
        logger.info("Stopping Battery Monitor...")

    except Exception:
        logger.exception("Fatal error in main loop:")
    finally:
        # ── Cleanup ───────────────────────────────────────────────────────────
        # Always release the lock file descriptor and remove the lock file on exit,
        # whether the exit is clean or due to an unhandled exception.
        if lock_fd is not None:
            os.close(lock_fd)
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)

if __name__ == "__main__":
    try:
        asyncio.run(run_monitor())
    except Exception as e:
        logger.error(f"Failed to start script: {e}")
        
