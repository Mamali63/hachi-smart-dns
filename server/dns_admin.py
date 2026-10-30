#!/usr/bin/env python3
"""Local admin CLI for Hachi Smart DNS. Run ONLY on the Latvia server.
Usage:
  dns_admin.py add [code] <months> [display_name]   # code omitted -> secure random
  dns_admin.py add-hours [code] <hours> [display_name]  # e.g. 24h test user, clock starts on first register
  dns_admin.py list
  dns_admin.py show <code>
  dns_admin.py renew <code> <months>
  dns_admin.py remove <code>
  dns_admin.py set-dns <primary> <secondary>
  dns_admin.py rebuild
Code rule (2026-10-27): never a name, phone or sequence. A generated code
is 5 chars (one group) from a confusion-free alphabet, via secrets.
"""
import json, os, secrets, sys, time
BASE = os.path.dirname(os.path.abspath(__file__))
CUSTOMERS = os.path.join(BASE, "customers.json")
DNS_SERVERS = os.path.join(BASE, "dns_servers.json")
DAY = 86400
ALPH = "abcdefghjkmnpqrstuvwxyz23456789"

def load():
    try:
        with open(CUSTOMERS, encoding="utf-8") as f: d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def save(d):
    tmp = CUSTOMERS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2); f.write("\n")
    os.replace(tmp, CUSTOMERS)

def gen_code(cs):
    while True:
        code = "".join(secrets.choice(ALPH) for _ in range(5))
        if code not in cs:
            return code

def rebuild(cs):
    now = int(time.time()); lines = []
    for code in sorted(cs):
        c = cs[code]; ip = c.get("current_ip")
        if c.get("start_ts") and c.get("end_ts") and now <= c["end_ts"] and ip:
            lines.append(f"{ip}  # {code}\n")
    with open(os.path.join(BASE, "whitelist.txt"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    return len(lines)

def fmt(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "-"

def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); return 2
    cs = load(); now = int(time.time())
    if a[0] == "add":
        # add [code] months [name]  -- code is optional; if the 2nd arg is a number, code is omitted
        rest = a[1:]
        if len(rest) >= 2 and not rest[0].isdigit():
            code, months, name = rest[0].strip().lower(), int(rest[1]), (rest[2] if len(rest) > 2 else "")
        elif len(rest) >= 1:
            code, months, name = gen_code(cs), int(rest[0]), (rest[1] if len(rest) > 1 else "")
        else:
            print("usage: add [code] <months> [display_name]"); return 2
        if code in cs:
            print(f"exists: {code}"); return 1
        cs[code] = {"display_name": name, "months": months, "start_ts": None, "end_ts": None,
                    "current_ip": None, "total_bytes": 0, "created_ts": now, "last_seen_ts": None}
        save(cs); rebuild(cs); print(f"OK code={code} months={months} name={name} (not started yet)")
    elif a[0] == "add-hours":
        rest = a[1:]
        if len(rest) >= 2 and not rest[0].isdigit():
            code, hours, name = rest[0].strip().lower(), int(rest[1]), (rest[2] if len(rest) > 2 else "")
        elif len(rest) >= 1:
            code, hours, name = gen_code(cs), int(rest[0]), (rest[1] if len(rest) > 1 else "")
        else:
            print("usage: add-hours [code] <hours> [display_name]"); return 2
        if code in cs:
            print(f"exists: {code}"); return 1
        cs[code] = {"display_name": name, "months": 0, "duration_hours": hours, "start_ts": None, "end_ts": None,
                    "current_ip": None, "total_bytes": 0, "created_ts": now, "last_seen_ts": None}
        save(cs); rebuild(cs); print(f"OK code={code} hours={hours} name={name} (not started yet, clock starts on first register)")
    elif a[0] == "list":
        for code in sorted(cs):
            c = cs[code]
            st = "not_started" if c.get("start_ts") is None else ("expired" if c.get("end_ts") and now > c["end_ts"] else "active")
            print(f"{code} | {c.get('display_name','')} | months={c.get('months')} | {st} | {fmt(c.get('start_ts'))} -> {fmt(c.get('end_ts'))} | ip={c.get('current_ip')}")
    elif a[0] == "show":
        c = cs.get(a[1].strip().lower())
        print(json.dumps(c, ensure_ascii=False, indent=2) if c else "not found")
    elif a[0] == "renew":
        code, months = a[1].strip().lower(), int(a[2]); c = cs.get(code)
        if not c: print("not found"); return 1
        c["months"] = int(c.get("months", 0)) + months
        if c.get("start_ts") is None:
            pass  # months accumulate; clock starts on first register
        elif c.get("end_ts") and now > c["end_ts"]:
            c["end_ts"] = now + months * 30 * DAY
        else:
            c["end_ts"] = int(c["end_ts"]) + months * 30 * DAY
        save(cs); rebuild(cs); print(f"OK {code} end={fmt(c.get('end_ts'))}")
    elif a[0] == "remove":
        code = a[1].strip().lower()
        if code in cs: del cs[code]; save(cs); n = rebuild(cs); print(f"OK removed {code}, whitelist now {n} IPs")
        else: print("not found"); return 1
    elif a[0] == "set-dns":
        tmp = DNS_SERVERS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"primary": a[1], "secondary": a[2]}, f, ensure_ascii=False, indent=2); f.write("\n")
        os.replace(tmp, DNS_SERVERS); print(f"OK dns={a[1]},{a[2]}")
    elif a[0] == "rebuild":
        print(f"OK whitelist {rebuild(cs)} IPs")
    else:
        print("unknown command"); return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
