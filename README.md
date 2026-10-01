from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs

import requests
import PySimpleGUI as sg

APP_NAME = "AKATSYKI VPN WIFI"
APP_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = APP_ROOT / "config.json"
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


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"[{ts}] {message}\n")


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
        "autostart": False,
    }


def save_config(data: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def ensure_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("This app is intended for Windows only.")


def download_file(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=60, stream=True)
    response.raise_for_status()
    with target.open("wb") as fh:
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
    raise RuntimeError(f"No suitable asset found for {repo}: {asset_name_contains}")


def ensure_zapret() -> Path:
    if ZAPRET_GENERAL.exists():
        return ZAPRET_DIR

    ZAPRET_DIR.mkdir(parents=True, exist_ok=True)
    try:
        archive_url = get_latest_release_asset("Flowseal/zapret-discord-youtube", "zip")
        archive = ZAPRET_DIR / "zapret.zip"
        download_file(archive_url, archive)
        shutil.unpack_archive(str(archive), str(ZAPRET_DIR))
        archive.unlink(missing_ok=True)
        log("Zapret downloaded and extracted")
    except Exception as exc:
        log(f"Zapret download failed: {exc}")
        raise

    if not ZAPRET_GENERAL.exists():
        raise RuntimeError("Zapret files were not extracted correctly")
    return ZAPRET_DIR


def ensure_xray() -> Path:
    if XRAY_EXE.exists():
        return XRAY_EXE

    XRAY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        url = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-windows-64.zip"
        archive_file = XRAY_DIR / "xray.zip"
        download_file(url, archive_file)
        shutil.unpack_archive(str(archive_file), str(XRAY_DIR))
        archive_file.unlink(missing_ok=True)
        log("Xray-core downloaded and extracted")
    except Exception as exc:
        log(f"Xray download failed: {exc}")
        raise

    if not XRAY_EXE.exists():
        raise RuntimeError("xray.exe was not found after extraction")
    return XRAY_EXE


def list_windows_interfaces() -> list[str]:
    try:
        output = subprocess.check_output(["netsh", "interface", "show", "interface"], text=True, stderr=subprocess.STDOUT)
        names = []
        for line in output.splitlines():
            if "Admin State" in line or "State" in line:
                continue
            if "----------" in line:
                continue
            if "Interface Name" in line:
                continue
            parts = line.split()
            if len(parts) >= 4 and parts[0] != "There":
                names.append(parts[0])
        return names
    except Exception:
        return ["Ethernet", "Wi-Fi", "Local Area Connection"]


def detect_interface_name() -> str:
    candidates = list_windows_interfaces()
    for candidate in candidates:
        lower = candidate.lower()
        if "wi-fi" in lower or "wireless" in lower:
            return candidate
    if candidates:
        return candidates[0]
    return "Wi-Fi"


def set_dns(dns_mode: str, custom_dns: str = "") -> bool:
    ensure_windows()
    iface = detect_interface_name()
    servers = DNS_OPTIONS.get(dns_mode, ["8.8.8.8"]) if dns_mode != "Custom" else [p.strip() for p in custom_dns.split(",") if p.strip()]
    if not servers:
        log(f"DNS list empty for {dns_mode}")
        return False
    try:
        for dns_ip in servers[:2]:
            subprocess.run(["netsh", "interface", "ip", "set", "dns", f"name={iface}", "source=static", f"addr={dns_ip}"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log(f"DNS set for {iface}: {servers[:2]}")
        return True
    except Exception as exc:
        log(f"DNS setup failed: {exc}")
        return False


def start_hotspot(ssid: str, password: str) -> bool:
    ensure_windows()
    try:
        subprocess.run(["netsh", "wlan", "set", "hostednetwork", f"mode=allow", f"ssid={ssid}", f"key={password}"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["netsh", "wlan", "start", "hostednetwork"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log(f"Hotspot started: {ssid}")
        return True
    except Exception as exc:
        log(f"Hotspot failed: {exc}")
        return False


def stop_hotspot() -> bool:
    try:
        subprocess.run(["netsh", "wlan", "stop", "hostednetwork"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as exc:
        log(f"Hotspot stop failed: {exc}")
        return False


def parse_vless_line(line: str) -> dict:
    value = line.strip()
    if not value or not value.startswith("vless://"):
        return {}
    rest = value[len("vless://") :]
    if "@" not in rest:
        return {}
    userinfo, tail = rest.split("@", 1)
    if "?" in tail:
        host_port, query = tail.split("?", 1)
    else:
        host_port, query = tail, ""
    if ":" in host_port:
        host, port = host_port.rsplit(":", 1)
    else:
        host, port = host_port, "443"
    params = parse_qs(query)
    return {
        "uuid": userinfo,
        "host": host,
        "port": int(port),
        "path": params.get("path", ["/"])[0],
        "sni": params.get("sni", [host])[0],
        "raw": value,
    }


def fetch_subscription_text(url_or_raw: str) -> str:
    value = url_or_raw.strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        r = requests.get(value, timeout=30)
        r.raise_for_status()
        return r.text
    return value


def build_server_list(subscription_url: str) -> list[dict]:
    text = fetch_subscription_text(subscription_url)
    items: list[dict] = []
    for line in text.splitlines():
        server = parse_vless_line(line)
        if server:
            items.append(server)
    for item in items:
        item["ping"] = ping_host(item["host"])
    items.sort(key=lambda x: x["ping"])
    return items


def ping_host(host: str) -> int:
    try:
        proc = subprocess.run(["ping", "-n", "1", host], capture_output=True, text=True, timeout=10)
        matches = re.findall(r"time\s*[<=]\s*(\d+)ms", proc.stdout, flags=re.I)
        if matches:
            return int(matches[0])
        return 999
    except Exception:
        return 999


def create_xray_config(server: dict) -> Path:
    config_path = APP_ROOT / "xray-config.json"
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "port": 10808,
            "listen": "0.0.0.0",
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True},
        }],
        "outbounds": [{
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": server.get("host", ""),
                    "port": int(server.get("port", 443)),
                    "users": [{"id": server.get("uuid", ""), "encryption": "none"}]
                }]
            },
            "streamSettings": {
                "network": "ws",
                "security": "tls",
                "tlsSettings": {"serverName": server.get("sni", server.get("host", ""))},
                "wsSettings": {"path": server.get("path", "/")},
            },
            "tag": "proxy"
        }, {"protocol": "freedom", "tag": "direct"}, {"protocol": "blackhole", "tag": "block"}],
        "routing": {"rules": [{"type": "field", "outboundTag": "proxy", "network": "tcp,udp"}]}
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


def start_xray(server: dict) -> bool:
    try:
        exe = ensure_xray()
        config = create_xray_config(server)
        subprocess.Popen([str(exe), "-config", str(config)], cwd=str(APP_ROOT), creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        log(f"Xray launched for {server.get('host')}:{server.get('port')}")
        return True
    except Exception as exc:
        log(f"Xray start failed: {exc}")
        return False


def start_zapret() -> bool:
    try:
        ensure_zapret()
        subprocess.Popen(["cmd", "/c", str(ZAPRET_GENERAL)], cwd=str(ZAPRET_DIR), creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        log("Zapret launched")
        return True
    except Exception as exc:
        log(f"Zapret start failed: {exc}")
        return False


def enable_autostart() -> bool:
    try:
        startup = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        startup.mkdir(parents=True, exist_ok=True)
        runner = startup / "AKATSYKI_VPN_WIFI.bat"
        runner.write_text(f'@echo off\n"{sys.executable}" "{APP_ROOT / "app.py"}"\n', encoding="utf-8")
        return True
    except Exception as exc:
        log(f"Autostart failed: {exc}")
        return False


def disable_autostart() -> bool:
    try:
        startup = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        runner = startup / "AKATSYKI_VPN_WIFI.bat"
        if runner.exists():
            runner.unlink()
        return True
    except Exception as exc:
        log(f"Autostart remove failed: {exc}")
        return False


def make_layout(config: dict) -> list:
    return [
        [sg.Text(APP_NAME, font=("Segoe UI", 22, "bold"))],
        [sg.Radio("Zapret", "MODE", default=config.get("mode") != "xray", key="-MODE_ZAPRET-"), sg.Radio("Xray Key", "MODE", default=config.get("mode") == "xray", key="-MODE_XRAY-")],
        [sg.Text("Wi-Fi SSID"), sg.InputText(config.get("ssid", "AKATSYKI_WIFI"), key="-SSID-")],
        [sg.Text("Wi-Fi Password"), sg.InputText(config.get("password", "12345678"), key="-PASS-", password_char="•")],
        [sg.Text("DNS"), sg.Combo(list(DNS_OPTIONS.keys()), default_value=config.get("dns_mode", "Xbox DNS"), key="-DNS-", readonly=True)],
        [sg.Text("Custom DNS"), sg.InputText(config.get("custom_dns", "111.88.96.54, 111.88.96.55"), key="-CUSTOM_DNS-")],
        [sg.Text("VLESS / subscription URL"), sg.InputText(config.get("subscription_url", ""), key="-SUB_URL-")],
        [sg.Button("Load Servers"), sg.Button("Start"), sg.Button("Stop"), sg.Button("Exit")],
        [sg.Checkbox("Autostart", default=bool(config.get("autostart", False)), key="-AUTO-")],
        [sg.Listbox([], size=(90, 8), key="-SERVER_LIST-", select_mode=sg.LISTBOX_SELECT_MODE_SINGLE)],
        [sg.Text("Status: ready", key="-STATUS-")],
    ]


def main() -> None:
    sg.theme("DarkBlue3")
    config = load_config()
    window = sg.Window(APP_NAME, make_layout(config), finalize=True)
    server_list: list[dict] = []

    while True:
        event, values = window.read(timeout=300)
        if event in (sg.WIN_CLOSED, "Exit"):
            break

        if event == "Load Servers":
            url = values["-SUB_URL-"].strip()
            if not url:
                window["-STATUS-"].update("Insert VLESS URL or HTTPS subscription first")
                continue
            try:
                items = build_server_list(url)
                server_list = items
                window["-SERVER_LIST-"].update([f"{item['host']}:{item['port']} | ping {item['ping']} ms" for item in items])
                window["-STATUS-"].update(f"Loaded {len(items)} server(s)")
                log(f"Loaded {len(items)} server(s)")
            except Exception as exc:
                window["-STATUS-"].update(f"Failed to load servers: {exc}")
                log(f"Load servers failed: {exc}")

        if event == "Start":
            result = {
                "ssid": values["-SSID-"].strip(),
                "password": values["-PASS-"].strip(),
                "dns_mode": values["-DNS-"],
                "custom_dns": values["-CUSTOM_DNS-"].strip(),
                "mode": "xray" if values["-MODE_XRAY-"] else "zapret",
                "subscription_url": values["-SUB_URL-"].strip(),
                "autostart": bool(values["-AUTO-"]),
            }
            save_config(result)
            if result["autostart"]:
                enable_autostart()
            else:
                disable_autostart()

            try:
                if result["mode"] == "zapret":
                    if not result["ssid"] or not result["password"]:
                        raise RuntimeError("SSID and password are required")
                    window["-STATUS-"].update("Starting Zapret mode...")
                    start_hotspot(result["ssid"], result["password"])
                    set_dns(result["dns_mode"], result["custom_dns"])
                    start_zapret()
                    window["-STATUS-"].update("Zapret mode started")
                else:
                    if not server_list:
                        if result["subscription_url"]:
                            server_list = build_server_list(result["subscription_url"])
                        if not server_list:
                            raise RuntimeError("No servers loaded. Paste a VLESS/HTTPS subscription first.")
                    selected = server_list[0]
                    selected_names = [f"{item['host']}:{item['port']} | ping {item['ping']} ms" for item in server_list]
                    listbox_values = values["-SERVER_LIST-"]
                    if listbox_values:
                        selected_name = listbox_values[0]
                        for idx, item_name in enumerate(selected_names):
                            if item_name == selected_name:
                                selected = server_list[idx]
                                break
                    if not result["ssid"] or not result["password"]:
                        raise RuntimeError("SSID and password are required")
                    window["-STATUS-"].update("Starting Xray mode...")
                    start_hotspot(result["ssid"], result["password"])
                    set_dns(result["dns_mode"], result["custom_dns"])
                    start_xray(selected)
                    window["-STATUS-"].update(f"Xray started: {selected['host']}:{selected['port']}")
            except Exception as exc:
                window["-STATUS-"].update(f"Start failed: {exc}")
                log(f"Start failed: {exc}")

        if event == "Stop":
            stop_hotspot()
            window["-STATUS-"].update("Stopped hotspot")

    window.close()


if __name__ == "__main__":
    try:
        ensure_windows()
        log("AKATSYKI VPN WIFI started")
        main()
    except Exception as exc:
        log(f"Critical startup failure: {exc}")
        sg.popup_error(f"Startup failed:\n{exc}")
        raise

# End of file
