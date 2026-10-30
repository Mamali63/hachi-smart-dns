# Hachi Smart DNS

A registration and management service for Smart DNS with a single-IP whitelist — route game login and lobbies (PlayStation, Fortnite, YouTube) through your own server, without a VPN and without proxying game traffic.

**[فارسی](README-fa.md)** | English

> **Status:** First version — Python core (registration server + admin management + expiry cleanup) + configuration samples. The automatic installer script, admin panel, and Android app come in the next update.

## What is this?

- **Registration server** (`server/reg_server.py`): an HTTP service using only the Python standard library, port 8792. Each customer has a code; the subscription clock starts on the first registration; later registrations only update the IP.
- **Admin management** (`server/dns_admin.py`): create codes, renew, delete, list, and rebuild the whitelist — runs only on the server.
- **Expiry cleanup** (`server/dns_expire.py`): with an hourly systemd timer, it removes expired codes from the whitelist (the customer record is not deleted).
- **DNS core**: Unbound (port 53) + Sniproxy (ports 443/80) — configuration samples in `config-samples/`.

## Main rules

- Each customer has only **one IP /32**; a new registration **replaces** the previous IP, it does not add one.
- A code carries no information (months, price, expiry) in itself; everything is server-side.
- The traffic counter is attached to the code, not the IP; it does not reset when the IP changes.
- The code is the full access key: never a name, phone number, or sequential number; only create it with `secrets` and only share it with the customer through a private channel.

## Manual install (first version)

On a fresh Ubuntu 24.04 with root access. Replace `SERVER_IP` with your server's public IP:

```bash
# 1) Packages
apt-get update -y
apt-get install -y python3 unbound sniproxy curl

# 2) Server files
mkdir -p /opt/hachi-dns
cp server/reg_server.py server/dns_admin.py server/dns_expire.py /opt/hachi-dns/
chmod +x /opt/hachi-dns/*.py

# 3) DNS addresses shown to customers
python3 /opt/hachi-dns/dns_admin.py set-dns SERVER_IP SERVER_IP

# 4) Unbound config (samples use 203.0.113.10; change it)
mkdir -p /etc/unbound/unbound.conf.d
sed "s/203\.0\.113\.10/SERVER_IP/g" config-samples/hachi-dns.conf > /etc/unbound/unbound.conf.d/hachi-dns.conf
sed "s/203\.0\.113\.10/SERVER_IP/g" config-samples/hachi-sni.conf > /etc/unbound/unbound.conf.d/hachi-sni.conf

# 5) Sniproxy config
cp config-samples/sniproxy.conf /etc/sniproxy.conf

# 6) Check configs
unbound-checkconf /etc/unbound/unbound.conf.d/hachi-dns.conf
unbound-checkconf /etc/unbound/unbound.conf.d/hachi-sni.conf

# 7) systemd units
cp systemd/hachi-dns-reg.service systemd/hachi-dns-expire.service systemd/hachi-dns-expire.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now hachi-dns-reg.service hachi-dns-expire.timer

# 8) Restart DNS services
systemctl restart unbound sniproxy
systemctl enable unbound sniproxy
```

## Create a customer

```bash
# Create a one-month customer (a secure random code is generated)
python3 /opt/hachi-dns/dns_admin.py add 1 "first customer"

# List customers
python3 /opt/hachi-dns/dns_admin.py list

# Renew (add 2 months) and delete
python3 /opt/hachi-dns/dns_admin.py renew <CODE> 2
python3 /opt/hachi-dns/dns_admin.py remove <CODE>

# Rebuild the whitelist (from customers)
python3 /opt/hachi-dns/dns_admin.py rebuild
```

The customer enters the code in the app and presses Start; the subscription clock starts at that moment and their IP is set in the whitelist.

## ⚠️ Before selling, you must do these

1. **HTTPS**: the first version is plain HTTP. Before selling, put the registration service behind your own domain with TLS (e.g. `https://dns.example.com`).
2. **Close the open resolver**: the `hachi-dns.conf` sample only answers localhost. Never leave `0.0.0.0/0 allow` open in production — only whitelisted IPs should reach the proxy; everyone else gets normal DNS.
3. **Never commit these files**: `customers.json`, `whitelist.txt`, `whitelist.json`, and any file containing customer codes, customer IPs, or passwords. The service creates empty files at runtime.

## Structure

```
server/
  reg_server.py      # registration service (port 8792)
  dns_admin.py       # admin management (create/renew/delete/list)
  dns_expire.py      # hourly expiry cleanup
systemd/
  hachi-dns-reg.service
  hachi-dns-expire.service
  hachi-dns-expire.timer
config-samples/
  hachi-dns.conf     # Unbound sample (change the sample IP 203.0.113.10)
  hachi-sni.conf     # SNI table sample (domains routed through the server)
  sniproxy.conf      # Sniproxy sample
```

## In the next update

- Automatic installer script (`install.sh`) — one-command install.
- Web admin panel (Persian, right-to-left) — create and manage users, game lists, whitelist and blocklist.
- Android app (1.2.0) — register the customer's IP with a code.

## Contact

- Email: [baxirani248059@gmail.com](mailto:baxirani248059@gmail.com)

## Donate

If this project is useful to you, support it with crypto — USDT on BEP20 (BSC):

`0xf714196efb17afac7395bb182d021c101b2b0206`

⚠️ **WARNING — only BEP20 (BSC).** Do NOT send USDT on TRON (TRC20), Ethereum (ERC20), or Polygon. Sending on any other network may lose the funds permanently and cannot be recovered.

## License

GNU Affero General Public License v3.0 (AGPL-3.0) — see `LICENSE`.
