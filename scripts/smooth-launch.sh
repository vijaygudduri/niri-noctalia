#!/bin/bash

# Default delay
delay=150

case "$1" in
    net.waterfox.waterfox|*waterfox*)
        delay=2500
        ;;
    google-chrome-stable|*chrome*)
        delay=2000
        ;;
    nautilus)
        delay=200
        ;;
esac

# Transition
niri msg action do-screen-transition --delay-ms "$delay"

# Small buffer (optional but helps)
sleep 0.05

# Correct execution (NO sh -c)
exec "$@"
