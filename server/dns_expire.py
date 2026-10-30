#!/usr/bin/env python3
"""Hourly expiry sweep: rebuild the whitelist so expired codes drop out.
Expired codes are NOT deleted (their history/remaining logic stays in
customers.json); they simply stop being whitelisted until renewed."""
import json, os, time
BASE = os.path.dirname(os.path.abspath(__file__))
CUSTOMERS = os.path.join(BASE, "customers.json")
try:
    with open(CUSTOMERS, encoding="utf-8") as f: cs = json.load(f)
except Exception:
    cs = {}
now = int(time.time()); lines = []; dropped = []
for code in sorted(cs):
    c = cs[code]; ip = c.get("current_ip")
    if c.get("start_ts") and c.get("end_ts") and now <= c["end_ts"] and ip:
        lines.append(f"{ip}  # {code}\n")
    elif c.get("start_ts") and c.get("end_ts") and now > c["end_ts"] and ip:
        dropped.append(code)
with open(os.path.join(BASE, "whitelist.txt"), "w", encoding="utf-8") as f:
    f.writelines(lines)
print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} whitelist={len(lines)} dropped_expired={dropped}")
