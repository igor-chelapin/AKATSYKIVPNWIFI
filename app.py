from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
import PySimpleGUI as sg

APP_NAME = "AKATSYKI VPN WIFI"
APP_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = APP_ROOT / "config.json"
STATE_PATH = APP_ROOT / "state.json"
LOG_DIR = APP_ROOT / "logs"
LOG_PATH = LOG_DIR / "app.log"
ZAPRET_DIR = APP_ROOT / "zapret"
XRAY_DIR = APP_ROOT / "xray"
XRAY_EXE = XRAY_DIR / "xray.exe"
ZAPRET_GENERAL = ZAPRET_DIR / "general.bat"

DNS_OPTIONS = {
    "Xbox DNS": ["111.88.96.54", "111.88.96.55"],
    "Google DNS": ["8.8.8.8", "8.8.4.4"],
    "Custom": [],
}


def log(msg: str) -> None:
    LOG_DIR.mkdir(exist_ok=True, parents=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"[{timestamp}] {msg}\n")


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "ssid": "AKATSYKI_WIFI",
        "password": "12345678",
        "dns_mode": "Xbox DNS",
        "custom_dns": "111.88.96.54, 111.88.96.55",
        "mode": "zapret",
        "subscription_url": "",
        "selected_server": "",
        "autostart": False,
    }


def save_config(data: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def set_status(window: sg.Window, text: str) -> None:
    if window is not None:
        window["-STATUS-"].update(text)
    log(text)


def ensure_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("This app is intended for Windows only.")


def download_file(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=60, stream=True)
    response.raise_for_status()
    with path.open("wb") as fh:
        for chunk in response.iter_content(chunk_size=65536):
            if chunk:
                fh.write(chunk)


def get_latest_release_asset(repo: str, asset_name_contains: str) -> str:
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    resp = requests.get(api_url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if asset_name_contains.lower() in name.lower():
            return asset.get("browser_download_url")
    raise RuntimeError(f"No matching asset found for {repo} with filter '{asset_name_contains}'")


def ensure_zapret() -> Path:
    if ZAPRET_GENERAL.exists():
        return ZAPRET_DIR

    ZAPRET_DIR.mkdir(exist_ok=True, parents=True)
    try:
        url = get_latest_release_asset("Flowseal/zapret-discord-youtube", "zip")
        archive_path = ZAPRET_DIR / "zapret.zip"
        download_file(url, archive_path)
        shutil.unpack_archive(str(archive_path), str(ZAPRET_DIR))
        archive_path.unlink(missing_ok=True)
        log("Zapret archive downloaded and extracted.")
    except Exception as exc:
        log(f"Zapret download failed: {exc}")
        raise

    if not ZAPRET_GENERAL.exists():
        raise RuntimeError("Zapret files not found after extraction.")

    return ZAPRET_DIR


def ensure_xray() -> Path:
    if XRAY_EXE.exists():
        return XRAY_EXE

    XRAY_DIR.mkdir(exist_ok=True, parents=True)
    try:
        url = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-windows-64.zip"
        archive_path = XRAY_DIR / "xray.zip"
        download_file(url, archive_path)
        shutil.unpack_archive(str(archive_path), str(XRAY_DIR))
        archive_path.unlink(missing_ok=True)
        log("Xray-core downloaded and extracted.")
    except Exception as exc:
        log(f"Xray download failed: {exc}")
        raise

    xray_path = XRAY_DIR / "xray.exe"
    if not xray_path.exists():
        raise RuntimeError("xray.exe not found after extraction.")
    return xray_path


def parse_vless_line(raw: str) -> dict:
    value = raw.strip()
    if not value:
        return {}
    if value.startswith("vless://"):
        payload = value[len("vless://") :]
        if "@" in payload:
            left, right = payload.split("@", 1)
            uuid = left
            remaining = right
            if "?" in remaining:
                host_port, query = remaining.split("?", 1)
            else:
                host_port = remaining
                query = ""
            if ":" in host_port:
                host, port = host_port.rsplit(":", 1)
            else:
                host, port = host_port, "443"
            params = parse_qs(query)
            path = params.get("path", [""])[0]
            sni = params.get("sni", [host])[0]
            return {
                "uuid": uuid,
                "host": host,
                "port": int(port),
                "path": path,
                "sni": sni,
                "raw": value,
            }
    return {}


def fetch_subscription_text(url_or_raw: str) -> str:
    text = url_or_raw.strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://"):
        response = requests.get(text, timeout=30)
        response.raise_for_status()
        return response.text
    return text


def parse_subscription_entries(url_or_raw: str) -> list[dict]:
    text = fetch_subscription_text(url_or_raw)
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        entry = parse_vless_line(line)
        if entry:
            entries.append(entry)
    return entries


def ping_host(host: str) -> int:
    try:
        out = subprocess.run(
            ["ping", "-n", "1", host],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        match = re.search(r"time\s*=\s*(\d+)ms", out.stdout, re.I)
        if match:
            return int(match.group(1))
        match = re.search(r"Minimum\s*=\s*(\d+)ms", out.stdout, re.I)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return 999


def build_server_list(subscription_url: str) -> list[dict]:
    entries = parse_subscription_entries(subscription_url)
    servers = []
    for entry in entries:
        host = entry.get("host", "")
        if not host:
            continue
        ping = ping_host(host)
        servers.append({
            "host": host,
            "port": entry.get("port", 443),
            "uuid": entry.get("uuid", ""),
            "path": entry.get("path", ""),
            "sni": entry.get("sni", host),
            "ping": ping,
            "raw": entry.get("raw", ""),
        })
    servers.sort(key=lambda item: item["ping"])
    return servers


def detect_interface_name() -> str:
    try:
        result = subprocess.check_output(["netsh", "interface", "ipv4", "show", "interfaces"], text=True, stderr=subprocess.STDOUT)
        lines = result.splitlines()
        for line in lines:
            if "Connected" in line or "Disconnected" in line:
                clean = line.strip().split()
                if not clean:
                    continue
                candidate = clean[-1]
                if candidate not in {"Loopback", "lo"}:
                    return candidate
        return "Wi-Fi"
    except Exception:
        return "Wi-Fi"


def set_dns(dns_mode: str, custom_dns: str = "") -> bool:
    ensure_windows()
    iface = detect_interface_name()
    if dns_mode == "Custom":
        servers = [part.strip() for part in custom_dns.split(",") if part.strip()]
    else:
        servers = DNS_OPTIONS.get(dns_mode, ["8.8.8.8", "8.8.4.4"])

    if not servers:
        log(f"DNS list empty for mode {dns_mode}")
        return False

    try:
        for idx, dns_ip in enumerate(servers[:2], start=1):
            # more reliable netsh command shape
            subprocess.run(["netsh", "interface", "ip", "set", "dns", f"name={iface}", f"source=static", f"addr={dns_ip}"], check=False)
        return True
    except Exception as exc:
        log(f"DNS setup failed: {exc}")
        return False


def start_hotspot(ssid: str, password: str) -> bool:
    ensure_windows()
    commands = [
        ["netsh", "wlan", "set", "hostednetwork", f"mode=allow", f"ssid={ssid}", f"key={password}"],
        ["netsh", "wlan", "start", "hostednetwork"],
    ]
    try:
        for cmd in commands:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return True
    except Exception as exc:
        print(f'[✗] Ошибка запуска hotspot: {str(exc)}')
        return False


def stop_hotspot() -> bool:
    try:
        subprocess.run(["netsh", "wlan", "stop", "hostednetwork"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return True
    except Exception as exc:
        print(f'[✗] Ошибка остановки hotspot: {str(exc)}')
        return False


def create_xray_config(server: dict) -> Path:
    config_path = APP_ROOT / "xray-config.json"
    port = server.get("port", 443)
    uuid = server.get("uuid", "")
    host = server.get("host", "")
    path = server.get("path", "/")
    sni = server.get("sni", host)

    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "port": 10808,
                "listen": "0.0.0.0",
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True},
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
            }
        ],
        "outbounds": [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": host,
                            "port": int(port),
                            "users": [{"id": uuid, "encryption": "none", "level": 0}],
                        }
                    ]
                },
                "streamSettings": {
                    "network": "ws",
                    "security": "tls",
                    "tlsSettings": {"serverName": sni},
                    "wsSettings": {"path": path or "/"},
                },
                "tag": "proxy",
            },
            {"protocol": "freedom", "tag": "direct"},
            {"protocol": "blackhole", "tag": "block"},
        ],
        "routing": {"rules": [{"type": "field", "outboundTag": "proxy", "network": "tcp,udp"}]},
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


def start_xray(server: dict) -> bool:
    try:
        xray_path = ensure_xray()
        config_path = create_xray_config(server)
        process = subprocess.Popen([str(xray_path), "-config", str(config_path)], cwd=str(APP_ROOT), creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        log(f"Xray started: {process.pid}")
        return True
    except Exception as exc:
        log(f"Xray start failed: {exc}")
        return False


def start_zapret() -> bool:
    try:
        ensure_zapret()
        subprocess.Popen(["cmd", "/c", str(ZAPRET_GENERAL)], cwd=str(ZAPRET_DIR), creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        log("Zapret launched.")
        return True
    except Exception as exc:
        log(f"Zapret start failed: {exc}")
        return False


def enable_autostart() -> bool:
    try:
        startup_dir = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        startup_dir.mkdir(parents=True, exist_ok=True)
        shortcut = startup_dir / "AKATSYKI_VPN_WIFI.bat"
        target = APP_ROOT / "app.py"
        content = f'@echo off\n"{sys.executable}" "{target}"\n'
        shortcut.write_text(content, encoding="utf-8")
        return True
    except Exception as exc:
        log(f"Autostart setup failed: {exc}")
        return False


def disable_autostart() -> bool:
    try:
        startup_dir = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        target = startup_dir / "AKATSYKI_VPN_WIFI.bat"
        if target.exists():
            target.unlink()
        return True
    except Exception as exc:
        log(f"Autostart removal failed: {exc}")
        return False


def main() -> None:
    sg.theme("DarkBlue3")
    config = load_config()

    dns_values = list(DNS_OPTIONS.keys())
    server_list = []

    layout = [
        [sg.Text(APP_NAME, font=("Segoe UI", 20, "bold"))],
        [sg.Radio("Zapret", "MODE", default=(config.get("mode") != "xray"), key="-MODE_ZAPRET-"), sg.Radio("Xray key", "MODE", default=(config.get("mode") == "xray"), key="-MODE_XRAY-")],
        [sg.Text("Wi‑Fi SSID"), sg.InputText(config.get("ssid", "AKATSYKI_WIFI"), key="-SSID-")],
        [sg.Text("Password"), sg.InputText(config.get("password", "12345678"), key="-PASS-")],
        [sg.Text("DNS"), sg.Combo(dns_values, default_value=config.get("dns_mode", "Xbox DNS"), key="-DNS-")],
        [sg.Text("Custom DNS"), sg.InputText(config.get("custom_dns", "111.88.96.54, 111.88.96.55"), key="-CUSTOM_DNS-")],
        [sg.Text("VLESS / subscription URL"), sg.InputText(config.get("subscription_url", ""), key="-SUB_URL-")],
        [sg.Button("Load Servers"), sg.Button("Start"), sg.Button("Stop"), sg.Button("Exit")],
        [sg.Checkbox("Autostart", default=bool(config.get("autostart", False)), key="-AUTO-")],
        [sg.Listbox(server_list, size=(90, 8), key="-SERVER_LIST-", select_mode=sg.LISTBOX_SELECT_MODE_SINGLE)],
        [sg.Text("Status: ready", key="-STATUS-")],
    ]

    window = sg.Window(APP_NAME, layout, finalize=True)

    def update_server_list(items: list[dict]) -> None:
        value_list = [f"{item['host']}:{item['port']} | ping {item['ping']} ms" for item in items]
        window["-SERVER_LIST-"].update(value_list)

    while True:
        event, values = window.read(timeout=300)
        if event in (sg.WIN_CLOSED, "Exit"):
            break

        if event == "Load Servers":
            url = values["-SUB_URL-"]
            if not url.strip():
                set_status = lambda window, text: window["-STATUS-"].update(text)
                set_status(window, "Insert VLESS URL or HTTPS subscription first.")
                continue
            try:
                items = build_server_list(url)
                if not items:
                    window["-STATUS-"].update("No valid servers found.")
                    continue
                server_list = items
                update_server_list(items)
                window["-STATUS-"].update(f"Loaded {len(items)} server(s).")
            except Exception as exc:
                log(f"Load Servers failed: {exc}")
                window["-STATUS-"].update(f"Failed to load servers: {exc}")

        if event == "Start":
            config = {
                "ssid": values["-SSID-"],
                "password": values["-PASS-"],
                "dns_mode": values["-DNS-"],
                "custom_dns": values["-CUSTOM_DNS-"],
                "mode": "xray" if values["-MODE_XRAY-"] else "zapret",
                "subscription_url": values["-SUB_URL-"],
                "autostart": bool(values["-AUTO-"]),
            }
            save_config(config)

            if values["-AUTO-"]:
                enable_autostart()
            else:
                disable_autostart()

            try:
                if values["-MODE_ZAPRET-"]:
                    window["-STATUS-"].update("Starting Zapret mode...")
                    start_hotspot(config["ssid"], config["password"])
                    set_dns(config["dns_mode"], config["custom_dns"])
                    start_zapret()
                    window["-STATUS-"].update("Zapret mode started.")
                else:
                    window["-STATUS-"].update("Starting Xray mode...")
                    selected = None
                    if values["-SERVER_LIST-"]:
                        selected_index = values["-SERVER_LIST-"][0]
                        if selected_index:
                            idx = [f"{item['host']}:{item['port']} | ping {item['ping']} ms" for item in server_list].index(selected_index)
                            selected = server_list[idx]
                    if selected is None:
                        if server_list:
                            selected = server_list[0]
                        else:
                            url = config["subscription_url"]
                            if url:
                                server_list = build_server_list(url)
                                if server_list:
                                    selected = server_list[0]
                            if selected is None:
                                raise RuntimeError("No valid server selected. Load servers first.")
                    start_hotspot(config["ssid"], config["password"])
                    set_dns(config["dns_mode"], config["custom_dns"])
                    start_xray(selected)
                    window["-STATUS-"].update(f"Xray started to {selected['host']}:{selected['port']}.")
            except Exception as exc:
                log(f"Start failed: {exc}")
                window["-STATUS-"].update(f"Start failed: {exc}")

        if event == "Stop":
            stop_hotspot()
            window["-STATUS-"].update("Stopped hotspot and network route.")

    window.close()


if __name__ == "__main__":
    try:
        ensure_windows()
        main()
    except Exception as exc:
        sg.popup_error(f"Failed to start app:\n{exc}")
        log(f"Critical startup failure: {exc}")
        raise
