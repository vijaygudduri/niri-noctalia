***Follow this after a fresh OS installation without any DE (This is tested only on CachyOS)***

1.  **Install niri, sddm, chrome and alacritty**

      ```bash
      sudo pacman -S niri sddm alacritty ; sudo systemctl enable sddm
      ```

2.  **Install necessaries**

      ```bash      
      sudo pacman -S --needed --noconfirm nwg-drawer nwg-look polkit-gnome gnome-keyring wl-clipboard wl-clip-persist gnome-calculator gnome-text-editor gnome-clocks blueman nautilus swappy evince brightnessctl playerctl wlsunset xdg-desktop-portal-gnome xwayland-satellite python-dbus-next noctalia-shell jq
      ```

      ```bash
      paru -S --needed --noconfirm sddm-sugar-candy-git catppuccin-gtk-theme-mocha bibata-cursor-theme visual-studio-code-bin libinput-gestures
      ```

4.  **Clone the dotfiles repo**

      ```bash
      git clone --depth=1 https://github.com/vijaygudduri/niri-noctalia.git
      ```

5.  **Copy the configs from cloned repo to ~/.config**

      ```bash
      cd ~/niri-noctalia #cd to cloned repo
      ```
      
      ```bash
      cp -r Wallpapers ~/Pictures/ && cp -r fastfetch niri kitty nwg-drawer scripts chrome-flags.conf libinput-gestures.conf ~/.config/
      ```

7.  **Execute the scripts**

      ```bash
      chmod +x ~/.config/scripts/*
      ```

9.  **Configure libinput-gestures for touchpad gestures**

      ```bash
      sudo gpasswd -a $USER input #reboot needed for the config to take effect
      ```

7.  **Download Candy icon theme & extract it to ~/.icons and Apply themes from nwg-look**

      candy icons --> https://www.gnome-look.org/p/1305251/
      
      ```bash
      mkdir -p ~/.icons && tar -xJf ~/Downloads/candy-icons.tar.xz -C ~/.icons
      ```

8.  **To apply sugar-candy theme on sddm, run below commands**

      ```bash
      sudo mkdir -p /etc/sddm.conf.d ; sudo touch /etc/sddm.conf.d/sddm.conf
      ```
      
      ```bash
      bash -c "sudo tee /etc/sddm.conf.d/sddm.conf > /dev/null <<'EOF'
      [General]
      Numlock=on
      
      [Theme]
      Current=sugar-candy
      CursorTheme=Bibata-Modern-Ice
      CursorSize=24
      EOF"
      ```

10.  **To decrease boot order timeout prompt of limine while rebooting, switch to root and change timeout to 2 (or 0 to disable completly) in /boot/limine.conf**

11.  **Change to cloudflare dns, replace 'Interstellar' with your connection name**

      ```bash
      nmcli con mod 'Interstellar' ipv4.dns '1.1.1.1 1.0.0.1'
      nmcli con mod 'Interstellar' ipv6.dns '2606:4700:4700::1111 2606:4700:4700::1001'
      
      nmcli con mod 'Interstellar' ipv4.ignore-auto-dns yes
      nmcli con mod 'Interstellar' ipv6.ignore-auto-dns yes
      
      nmcli con up 'Interstellar'
      ```
12. **Change the shell to zsh**

      ```bash
      chsh -s $(which zsh)
      ```  

13.  **Copy some custom configs to .zshrc**

      ```bash
      cat << 'EOF' | cat - ~/.zshrc > ~/.zshrc.tmp && mv ~/.zshrc.tmp ~/.zshrc
      # Show fastfetch everywhere EXCEPT in VS Code
      # Sending to /dev/tty prevents the P10K Instant Prompt warning
      if [[ "$TERM_PROGRAM" != "vscode" ]]; then
        if command -v fastfetch >/dev/null; then
          fastfetch > /dev/tty
        fi
      fi
      
      alias top='clear && command top'
      
      waterone() {
          net.waterfox.waterfox -P "profile-2" --no-remote "$@" &>/dev/null &
          disown
          niri msg action do-screen-transition --delay-ms 3000
          if [[ "$TERM" == "xterm-kitty" ]]; then
              exec kitty @ close-window
          else
              exit
          fi
      }
      alias waterone=' waterone'
      
      EOF
      ```


***Reboot after all the process is done***
