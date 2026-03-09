***Follow this after a fresh OS installation without any DE (This is tested only on CachyOS)***

1.  **Install niri, sddm, chrome and alacritty**

      ```bash
      sudo pacman -S niri sddm alacritty ; sudo systemctl enable sddm
      ```

2.  **Install necessaries**

      ```bash      
      sudo pacman -S --needed --noconfirm nwg-drawer nwg-look polkit-gnome gnome-keyring wl-clipboard starship network-manager-applet gnome-calculator gnome-text-editor gnome-clocks blueman nautilus transmission-gtk smplayer swappy evince brightnessctl playerctl wlsunset cachyos-kernel-manager
      ```

      ```bash
      paru -S --needed --noconfirm sddm-sugar-candy-git catppuccin-gtk-theme-mocha bibata-cursor-theme visual-studio-code-bin libinput-gestures
      ```

4.  **Clone the dotfiles repo**

      ```bash
      git clone --depth=1 git@github.com:vijaygudduri/niri-noctalia.git
      ```

5.  **Copy the configs from cloned repo to ~/.config**

      ```bash
      cd ~/niri-noctalia #cd to cloned repo
      ```
      
      ```bash
      cp -r wallpapers ~/ && cp -r fastfetch niri kitty nwg-drawer chrome-flags.conf ~/.config/
      ```

6.  **Install noctalia-shell**

      ```bash
      sudo pacman -S noctalia-shell
      ```

7.  **Apply themes from nwg-look (theme is 'catppuccin mocha' and cursor theme is 'bibata modern ice')**

8.  **Configure libinput-gestures for touchpad gestures**

      ```bash
      sudo usermod -aG input $USER
      newgrp input  # reboot needed for the config to take effect
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

10.  **To decrease boot order timeout prompt of systemd while rebooting, switch to root and change timeout to 2 (or 0 to disable completly) in /boot/loader/loader.conf**

11.  **Change to cloudflare dns, replace 'Interstellar' with your connection name**

      ```bash
      nmcli con mod 'Interstellar' ipv4.dns '1.1.1.1 1.0.0.1'
      nmcli con mod 'Interstellar' ipv6.dns '2606:4700:4700::1111 2606:4700:4700::1001'
      
      nmcli con mod 'Interstellar' ipv4.ignore-auto-dns yes
      nmcli con mod 'Interstellar' ipv6.ignore-auto-dns yes
      
      nmcli con up 'Interstellar'
      ```

12.  **Add starship config and modify ls alias in fish**

      ```bash
      echo -e "\n\nalias ls='eza --color=always --group-directories-first --icons'\n\nstarship init fish | source" >> ~/.config/fish/config.fish
      ```


***Reboot after all the process is done***
