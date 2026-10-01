# AKATSYKI VPN WIFI

MVP Windows helper for two modes:
- Zapret mode: download and launch the public `zapret-discord-youtube` project automatically.
- VPN key mode: accept VLESS URL or HTTPS subscription, parse servers, measure ping, choose one, and run Xray.
- Wi‑Fi hotspot creation via Windows `netsh`.
- DNS override support for Xbox DNS / Google DNS / custom DNS.
- Launch with minimal GUI, logs in `logs/`.

## Important

This is a workable MVP. It is intended for Windows only and uses public projects:
- `Flowseal/zapret-discord-youtube`
- `XTLS/xray-core`

The app is not an original zapret implementation. It wraps public tools into a simpler interface.

## Features

- Hotspot SSID / password configuration
- DNS selection: Xbox DNS / Google DNS / Custom
- Zapret mode
- Xray/VLESS mode
- Auto-start toggle
- Logs in `logs/app.log`
- Minimal PySimpleGUI interface

## Requirements

Python 3.10+

```bash
pip install -r requirements.txt
```

## Run

```bash
python app.py
```

Run as Administrator if Windows prompts for hotspot / routing changes.

## Notes

- In Zapret mode, the app tries to download the latest release from the official repository if missing.
- In Xray mode, the app tries to download `xray.exe` if missing.
- Server list is created from VLESS URL or subscription content.
- The app writes logs into `logs/app.log`.

## License

MIT
