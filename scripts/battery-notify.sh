#!/usr/bin/env bash
# battery-notify.sh — event-driven charger + battery level notifications

# --- Single-instance lock (prevents duplicate notifications) ---
# Uses $XDG_RUNTIME_DIR (user-owned, tmpfs-backed) instead of /tmp, which is
# world-writable and shared across all users on the machine.
RUN_DIR="${XDG_RUNTIME_DIR:-/tmp}/battery-notify"
mkdir -p "$RUN_DIR"

LOCK_FILE="$RUN_DIR/battery-notify.lock"
STATE_FILE="$RUN_DIR/battery-notify.state"

exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "Already running, exiting." >&2
    exit 1
fi

command -v notify-send >/dev/null 2>&1 || {
    echo "notify-send not found, cannot send notifications." >&2
    exit 1
}

# --- Auto-detect battery and AC adapter ---
BAT=$(find /sys/class/power_supply -maxdepth 1 -name 'BAT*' | head -n1)
AC=$(find /sys/class/power_supply -maxdepth 1 \( -name 'AC*' -o -name 'ADP*' \) | head -n1)

if [[ -z "$BAT" || -z "$AC" ]]; then
    echo "Could not detect battery/AC in /sys/class/power_supply" >&2
    exit 1
fi

echo "Started: BAT=$BAT AC=$AC"

# --- Config ---
APP_NAME="battery-notification"
THRESHOLDS_LOW=(25 20 15 10 5)
# Sorted descending, same as THRESHOLDS_LOW's implicit order, so both
# threshold checks can use the same simple forward-loop + break style.
THRESHOLDS_HIGH=(100 95 90 85 80)

# --- Load previous state ---
LAST_AC=""
LAST_CAPACITY=""
LAST_ALERTED_LOW=""
LAST_ALERTED_HIGH=""
[[ -f "$STATE_FILE" ]] && source "$STATE_FILE"

# True only for the very first check_state() call — just syncs the baseline
# state silently, without firing any startup notification.
INITIAL_RUN=1

# Picks a battery icon name based on percentage and charge state.
# Rounds down to the nearest 10 (standard Freedesktop icon naming only ships
# in steps of 10, e.g. battery-020-symbolic, battery-full-charging-symbolic).
battery_icon() {
    local percentage="$1" charging="$2"
    local step=$(( percentage / 10 * 10 ))
    (( step > 100 )) && step=100

    if (( step >= 100 )); then
        if [[ "$charging" == "1" ]]; then
            echo "battery-full-charging-symbolic"
        else
            echo "battery-full-symbolic"
        fi
    else
        printf -v padded "%03d" "$step"
        if [[ "$charging" == "1" ]]; then
            echo "battery-${padded}-charging-symbolic"
        else
            echo "battery-${padded}-symbolic"
        fi
    fi
}

check_state() {
    local CAPACITY ONLINE ICON t urgency

    # Read sysfs files directly, no subshells. STATUS is intentionally not
    # read anymore — $ONLINE is used for charging/discharging logic instead,
    # since some drivers report inconsistent status strings (e.g.
    # "Not charging" while plugged in) but AC online state is reliable.
    read -r CAPACITY < "$BAT/capacity"
    read -r ONLINE   < "$AC/online"

    # Charger connect/disconnect
    if [[ "$ONLINE" != "$LAST_AC" ]]; then
        if [[ "$INITIAL_RUN" == "1" ]]; then
            echo "Initial state sync: online=${ONLINE} battery=${CAPACITY}% (no notification)"
        else
            ICON=$(battery_icon "$CAPACITY" "$ONLINE")
            if [[ "$ONLINE" == "1" ]]; then
                echo "Charger connected (battery ${CAPACITY}%)"
                notify-send -h boolean:transient:true -a "$APP_NAME" -u normal -i "$ICON" "Charger Connected" "Battery at ${CAPACITY}%"
            else
                echo "Charger disconnected (battery ${CAPACITY}%)"
                notify-send -h boolean:transient:true -a "$APP_NAME" -u normal -i "$ICON" "Charger Disconnected" "Battery at ${CAPACITY}%"
            fi
        fi
        LAST_AC="$ONLINE"
    fi

    # Low battery thresholds — directional check (<=) instead of exact match,
    # so a fast drain that skips past a clean multiple (e.g. 22% -> 18%)
    # still triggers the alert instead of silently missing it.
    if [[ "$ONLINE" == "0" ]]; then
        local target=""
        # Scan all thresholds — don't stop at the first match. Since the
        # array is descending (20 15 10 5), the LAST match encountered here
        # is the smallest (most severe) one the battery has actually reached,
        # which is what matters if a fast drain skipped past 20%/15% between
        # two udev events (e.g. 22% -> 13% in one jump).
        for t in "${THRESHOLDS_LOW[@]}"; do
            [[ "$CAPACITY" -le "$t" ]] && target="$t"
        done
        if [[ -n "$target" ]]; then
            if [[ -z "$LAST_ALERTED_LOW" || "$LAST_ALERTED_LOW" -gt "$target" ]]; then
                urgency="normal"
                [[ "$target" -le 10 ]] && urgency="critical"
                ICON=$(battery_icon "$CAPACITY" "0")
                echo "Low battery threshold hit: ${target}% (actual ${CAPACITY}%)"
                notify-send -h boolean:transient:true -a "$APP_NAME" -u "$urgency" -i "$ICON" "Battery Low" "Battery at ${CAPACITY}%, please connect the charger"
                LAST_ALERTED_LOW="$target"
            fi
        fi
    else
        LAST_ALERTED_LOW=""   # reset once charging, so it can fire again next discharge
    fi

    # High/charged thresholds — same directional logic, inverted (>=).
    # THRESHOLDS_HIGH is sorted descending, so this loop reads identically
    # to the low-threshold one above: first match wins, then break.
    if [[ "$ONLINE" == "1" ]]; then
        for t in "${THRESHOLDS_HIGH[@]}"; do
            if [[ "$CAPACITY" -ge "$t" ]]; then
                if [[ -z "$LAST_ALERTED_HIGH" || "$LAST_ALERTED_HIGH" -lt "$t" ]]; then
                    ICON=$(battery_icon "$CAPACITY" "1")
                    echo "High battery threshold hit: ${t}% (actual ${CAPACITY}%)"
                    notify-send -h boolean:transient:true -a "$APP_NAME" -u normal -i "$ICON" "Battery Charged" "Battery at ${CAPACITY}%, please disconnect the charger"
                    LAST_ALERTED_HIGH="$t"
                fi
                break
            fi
        done
    else
        LAST_ALERTED_HIGH=""   # reset once discharging, so it can fire again next charge
    fi

    LAST_CAPACITY="$CAPACITY"
    printf 'LAST_AC=%q\nLAST_CAPACITY=%q\nLAST_ALERTED_LOW=%q\nLAST_ALERTED_HIGH=%q\n' \
        "$LAST_AC" "$LAST_CAPACITY" "$LAST_ALERTED_LOW" "$LAST_ALERTED_HIGH" > "$STATE_FILE"
}

# Sync state immediately on startup — silent, no notification
check_state
INITIAL_RUN=0

# Block on udev, only wake on real power_supply events.
# Wrapped in an outer retry loop: if udevadm monitor ever dies (udev daemon
# restart, suspend/resume edge case, etc.), the pipe closes and the inner
# loop exits — instead of the script going silent forever, it waits 1s and
# starts a fresh udevadm monitor automatically.
while true; do
    echo "Listening for power_supply events..."
    while read -r line; do
        [[ "$line" == *"power_supply"* ]] || continue
        check_state
    done < <(stdbuf -oL udevadm monitor --udev --subsystem-match=power_supply)

    echo "udevadm monitor exited unexpectedly, restarting in 1s..."
    sleep 1
done
