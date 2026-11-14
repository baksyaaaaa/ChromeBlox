# Chrome Blox

Custom Roblox launcher in the Chrome Client style. It downloads the official Roblox client from Roblox's own servers, applies your mods, and starts it. It never touches the running game, so it stays clear of the anti-cheat.

## Run from source
```
pip install -r requirements.txt
python src/main.py
```

## Build the exe
Push to GitHub and Actions builds `ChromeBlox.exe` (under the run's Artifacts). Push a tag like `v1.0.0` to publish it as a Release.

## Features
- Auto-installs and updates Roblox into `%LOCALAPPDATA%\ChromeBlox`
- Set as default, so Play on roblox.com opens Chrome Blox
- Join by place ID or game link
- Mods folder overlay (old oof, sky, textures...), custom font, custom cursor
- Fast Flags editor with quick presets (Roblox only accepts allowlisted flags)
- Now Playing card, Discord status with server location
- Multi-instance toggle
- Recolorable accent/background, background image, glass buttons, one click sound (your own .wav supported)
- Never shows your Windows username or folder paths
