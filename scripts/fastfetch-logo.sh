#!/usr/bin/env bash
# Picks a random logo from ~/.config/fastfetch/logo/

LOGO_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/fastfetch/logo"

find -L "$LOGO_DIR" -maxdepth 1 -type f \
    \( -name "*.png" -o -name "*.jpg" -o -name "*.jpeg" \
       -o -name "*.icon" -o -name "*logo*" \) \
    2>/dev/null | shuf -n 1
    
