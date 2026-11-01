**[فارسی](README-fa.md)** | English

<p align="center">
  <img src="./media/hachi-logo.png" width="160" height="160" alt="Hachi — Haji">
</p>

<h1 align="center">Hachi Smart DNS</h1>

<p align="center">
  <a href="https://github.com/Mamali63/hachi-smart-dns/releases"><img src="https://img.shields.io/github/v/release/Mamali63/hachi-smart-dns?style=for-the-badge&color=0ea5e9" alt="Release"></a>
  <a href="https://github.com/Mamali63/hachi-smart-dns/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-AGPL%20v3-14b8a6?style=for-the-badge" alt="License"></a>
  <a href="https://github.com/Mamali63/hachi-smart-dns/stargazers"><img src="https://img.shields.io/github/stars/Mamali63/hachi-smart-dns?style=for-the-badge&color=2563eb" alt="Stars"></a>
</p>

<p align="center">
  <b>Smart DNS registration &amp; management — route game logins and lobbies through your own server, without a VPN and without proxying game traffic.</b><br>
  PlayStation · Fortnite · YouTube · Roblox · Steam · Xbox · 50+ games
</p>

<p align="center">
  <a href="https://github.com/Mamali63/hachi-smart-dns/releases"><img src="https://img.shields.io/badge/%E2%AC%87%20Download%20Android%20App-14b8a6?style=for-the-badge&logo=android" alt="Download Android App"></a>
  <a href="#quick-start"><img src="https://img.shields.io/badge/%F0%9F%9A%80%20Quick%20Start-0ea5e9?style=for-the-badge" alt="Quick Start"></a>
</p>

> **Status:** Full version — Python core + automatic installer + admin panel + Android app.

## ✨ Features

<table>
<tr>
<td width="50%">

### 🎮 Game routing
Route login &amp; lobby traffic for **54 games** (Fortnite, PlayStation, Steam, Xbox, Nintendo, Roblox, YouTube…) through your server — game downloads and gameplay stay direct.

</td>
<td width="50%">

### 🔑 One IP per customer
Each customer has a single **/32** whitelist entry. A new registration **replaces** the old IP — it never adds one.

</td>
</tr>
<tr>
<td width="50%">

### 🖥️ Admin panel
Persian, right-to-left web panel — create, renew and delete users, add and remove game domains, manage the whitelist and blocklist, change the admin password.

</td>
<td width="50%">

### 📱 Android app
The customer just enters a **code** and presses Start — no server address to type. The app is not a VPN; it only registers the home IP.

</td>
</tr>
<tr>
<td width="50%">

### 🚫 Blocklist
Domains that **never open** (NXDOMAIN) — block a site, or test that the DNS is working: block a site, and if it does not open, the DNS works.

</td>
<td width="50%">

### 🐍 Python stdlib only
The server core uses **only the Python standard library** — no extra dependencies, no database to install. One command installs everything.

</td>
</tr>
</table>

## Table of Contents

- [What is this?](#what-is-this)
- [Quick Start](#quick-start)
- [Android app](#android-app)
- [Admin panel](#admin-panel)
- [Main rules](#main-rules)
- [Manual install](#manual-install)
- [Manage services](#manage-services)
- [Structure](#structure)
- [Before selling](#before-selling-you-must-do-these)
- [Contact](#contact)
- [Donate](#donate)
- [License](#license)

## What is this?

- **Registration server** (`server/reg_server.py`): an HTTP service using only the Python standard library, port 8792. Each customer has a code; the subscription clock starts on the first registration; later registrations only update the IP.
- **Admin panel** (`server/admin_panel.py`): a Persian, right-to-left web panel, port 8080 by default (changeable at install time with y/N; skipping keeps 8080) — create, delete and renew users, add and remove game domains (every change rebuilds the Unbound table and reloads the services instantly), view DNS addresses and the whitelist, and change the admin password. First login: `admin` / `admin` — change it after the first login.
- **Admin management** (`server/dns_admin.py`): create codes, renew, delete, list, and rebuild the whitelist — runs only on the server.
- **Expiry cleanup** (`server/dns_expire.py`): with an hourly systemd timer, it removes expired codes from the whitelist (the customer record is not deleted).
- **DNS core**: Unbound (port 53) + Sniproxy (ports 443/80) — configuration samples in `config-samples/`.

## Quick Start

On a fresh Ubuntu 24.04 VPS with root access, run just **this one command** — nothing else is needed:

```bash
sudo bash <(curl -Ls https://raw.githubusercontent.com/Mamali63/hachi-smart-dns/main/install.sh)
```

The script downloads and installs everything itself (Python, Unbound, Sniproxy, server files), asks for the server IP during install (it detects it automatically, you confirm), and prints the panel address at the end:

```
Admin panel: http://SERVER_IP:8080  (first login: admin / admin — change it!)
```

Open the panel, change the password, pick a user and months and create it; give the code to the buyer; the buyer enters it in the app, presses Start, and their IP is set in the whitelist. Each user always has only one IP. The default panel port is 8080 and can be changed at install with y/N; if the port is busy, the installer warns and asks for another; skipping keeps 8080.

## Android app

The app (`client/hachi-dns.apk`, version 1.2.0): the customer just enters the **user code** and presses Start — no server address to enter. The app is not a VPN; it only registers the home IP and must be opened on the same home Wi-Fi.

<p align="center">
  <a href="https://github.com/Mamali63/hachi-smart-dns/releases"><img src="https://img.shields.io/badge/%E2%AC%87%20Download%20hachi--dns.apk%20(v1.2.0)-14b8a6?style=for-the-badge&logo=android" alt="Download hachi-dns.apk v1.2.0"></a>
</p>

**Download the app:** from the [Releases](https://github.com/Mamali63/hachi-smart-dns/releases) of this repo, download `hachi-dns.apk`.

## Admin panel

- **Users:** full list (code, name, duration, start and end, status, current IP, traffic) + create (months or hours) + renew + delete.
- **Games:** default domain list (54 domains: Fortnite, PlayStation, Steam, Xbox, Nintendo, EA, Ubisoft, Battle.net, Riot, Rockstar, Minecraft, PUBG, Activision, Supercell, Roblox, YouTube and more) + add and remove by the admin + a "Reset to default" button that restores the original 54 domains (defaults are stored separately in `domains.default.json`).
- **Blocklist:** domains that **never open** (DNS answers NXDOMAIN for them) — to block a site or test that the DNS works (block a site: if it does not open, the DNS is working; removing it from the list opens it again). A domain cannot be in the games list and the blocklist at the same time.
- **Whitelist:** each user's latest IP + last connection + remove an IP from the whitelist + add an IP to a user (the whitelist is built from the users; removing an IP means that IP is dropped from that user and the user must register again).
- **Settings:** DNS addresses, current whitelist, change admin password.
- **Guides:** two pages inside the panel — "Games guide" (how to find a game's addresses: server log, PCAPdroid, Wireshark, smart guessing) and "App guide" (the Android app for customers: the home-Wi-Fi rule, press Start again whenever it does not connect so the new IP enters the whitelist, what the buttons mean, troubleshooting).
- The admin password is stored only as a salted hash (pbkdf2); on first run the password `admin` is created and the panel warns until it is changed.

## Main rules

- Each customer has only **one IP /32**; a new registration **replaces** the previous IP, it does not add one.
- A code carries no information (months, price, expiry) in itself; everything is server-side.
- The traffic counter is attached to the code, not the IP; it does not reset when the IP changes.
- The code is the full access key: never a name, phone number, or sequential number; only create it with `secrets` and only share it with the customer through a private channel.

## Manual install

If you do not want to use the installer, run these one by one in the server terminal (root access, fresh Ubuntu 24.04). Replace `SERVER_IP` with your server's public IP:

```bash
# 1) Packages
apt-get update -y
apt-get install -y python3 unbound sniproxy curl

# 2) Server files
mkdir -p /opt/hachi-dns
cp server/reg_server.py server/dns_admin.py server/dns_expire.py /opt/hachi-dns/
cp server/admin_panel.py server/domains.json server/domains.default.json /opt/hachi-dns/
chmod +x /opt/hachi-dns/*.py

# 3) DNS addresses shown to customers
python3 /opt/hachi-dns/dns_admin.py set-dns SERVER_IP SERVER_IP

# App version the server reports to clients (update check)
printf '{"versionCode": 3, "versionName": "1.2.0"}' > /opt/hachi-dns/version.json

# 4) Unbound config (samples use 203.0.113.10; change it)
mkdir -p /etc/unbound/unbound.conf.d
sed "s/203\.0\.113\.10/SERVER_IP/g" config-samples/hachi-dns.conf > /etc/unbound/unbound.conf.d/hachi-dns.conf

# 5) Build the SNI table from domains.json (the panel's source of truth)
cd /opt/hachi-dns
HACHI_SNI_CONF=/etc/unbound/unbound.conf.d/hachi-sni.conf HACHI_RELOAD=0 python3 -c "import admin_panel; print(admin_panel.rebuild_sni())"
cd -

# 6) Sniproxy config
cp config-samples/sniproxy.conf /etc/sniproxy.conf

# 7) Check configs
unbound-checkconf /etc/unbound/unbound.conf.d/hachi-dns.conf
unbound-checkconf /etc/unbound/unbound.conf.d/hachi-sni.conf

# 8) systemd units (default panel port is 8080; to change it, edit the Environment line in hachi-dns-panel.service)
cp systemd/hachi-dns-reg.service systemd/hachi-dns-expire.service systemd/hachi-dns-expire.timer systemd/hachi-dns-panel.service /etc/systemd/system/
# Always on: if unbound or sniproxy dies, systemd brings them back
for svc in unbound sniproxy; do mkdir -p /etc/systemd/system/$svc.service.d; printf '[Service]\nRestart=always\nRestartSec=5\n' > /etc/systemd/system/$svc.service.d/restart.conf; done
systemctl daemon-reload
systemctl enable --now hachi-dns-reg.service hachi-dns-expire.timer hachi-dns-panel.service

# 9) Restart DNS services
systemctl restart unbound sniproxy
systemctl enable unbound sniproxy
```

Then open the panel: `http://SERVER_IP:8080` — first login `admin` / `admin`, then change the password.

## Manage services

Three buttons for each service — **start / restart / stop** — inside the panel (the "Services" page: Unbound, Sniproxy, registration service, admin panel; each one's status is shown) and from the console:

```bash
systemctl restart unbound sniproxy hachi-dns-reg hachi-dns-panel  # restart all
systemctl stop unbound     # stop DNS
systemctl start unbound    # start DNS
systemctl status unbound   # see status
```

If the DNS does not work, restarting these services is usually enough.

**Always on:** all services come back automatically after a server reboot (`systemctl enable`) and restart automatically if they fail (`Restart=always`) — so nothing stops working when the VPS restarts.

## Structure

```
server/
  reg_server.py      # registration service (port 8792)
  admin_panel.py     # admin panel (port 8080)
  domains.json       # games list (editable in the panel)
  domains.default.json  # factory defaults (54 domains, for the reset button)
  blocked.json       # blocklist (editable in the panel; empty = nothing blocked)
  dns_admin.py       # admin management (create/renew/delete/list)
  dns_expire.py      # hourly expiry cleanup
client/
  hachi-dns.apk      # Android app 1.2.0 (the user enters the server address)
  src/               # app source
  build.sh           # build the APK
systemd/
  hachi-dns-reg.service
  hachi-dns-panel.service
  hachi-dns-expire.service
  hachi-dns-expire.timer
config-samples/
  hachi-dns.conf     # Unbound sample
  hachi-sni.conf     # domain table sample
  sniproxy.conf      # Sniproxy sample
media/
  hachi-logo.png     # Hachi logo
```

## ⚠️ Before selling, you must do these

1. **HTTPS**: this version is plain HTTP. Before selling, put the registration service behind your own domain with TLS (e.g. `https://dns.example.com`).
2. **Close the open resolver**: never leave `0.0.0.0/0 allow` open in production — only whitelisted IPs should reach the proxy; everyone else gets normal DNS.
3. **Never commit these files**: `customers.json`, `whitelist.txt`, `whitelist.json`, and any file containing customer codes, customer IPs, or passwords. The service creates empty files at runtime.

## Contact

- Email: [baxirani248059@gmail.com](mailto:baxirani248059@gmail.com)

## Donate

If this project is useful to you, support it with crypto — USDT on BEP20 (BSC):

`0xf714196efb17afac7395bb182d021c101b2b0206`

⚠️ **WARNING — only BEP20 (BSC).** Do NOT send USDT on TRON (TRC20), Ethereum (ERC20), or Polygon. Sending on any other network may lose the funds permanently and cannot be recovered.

## License

GNU Affero General Public License v3.0 (AGPL-3.0) — see `LICENSE`.
