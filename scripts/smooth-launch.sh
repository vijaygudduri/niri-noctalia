#!/bin/bash

# Default delay
delay=150

case "$1" in
    net.waterfox.waterfox|*waterfox*)
        delay=3000
        ;;
    google-chrome-stable|*chrome*)
        delay=2500
        ;;
esac

# Transition
niri msg action do-screen-transition --delay-ms "$delay"

# Small buffer (optional but helps)
sleep 0.05

# Correct execution (NO sh -c)
exec "$@"
