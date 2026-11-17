#!/usr/bin/env python3
"""Weekly cruise schedule updater for TLC Radar (v3.42).

Fetches the CruiseMapper New York port schedule (current month + next 2
months), assigns each ship call to the Manhattan or Brooklyn terminal by
cruise line, adds cabin counts, and writes radar/cruise-schedule.json.

Runs in GitHub Actions (weekly, .github/workflows/cruise-schedule.yml).
Same pattern as the restrooms.json weekly refresh. No dependencies (stdlib).

Why a file, not a live in-app fetch: CruiseMapper sends no CORS headers,
so the app cannot fetch it directly (tested in v3.40); the weekly job
fetches it server-side and the app reads the same-origin JSON instead.

Terminal mapping (verified against the official schedule, Nov 2026):
- Brooklyn serves Cunard, MSC, Virgin Voyages, Princess (every verified
  Princess call Oct-Nov 2026 was Brooklyn; Princess officially uses either
  terminal, so Princess rows are flagged in the JSON note).
- Manhattan serves Carnival, NCL, Oceania, Regent, TUI/Mein Schiff, AIDA,
  Holland America, Silversea, Azamara, Viking, ACL, Hapag-Lloyd, Costa,
  Crystal, Disney, Seabourn, Windstar, Explora Journeys (MSC Group).
- Royal Caribbean / Celebrity use Cape Liberty (Bayonne) — excluded.
- Unknown lines go to the "unknown" list; the app shows them in both
  terminals' modals marked as terminal unknown.
"""
import json
import os
import re
import html as H
import urllib.request
from datetime import date, timedelta

PORT_URL = "https://www.cruisemapper.com/ports/new-york-port-98?month={ym}"
UA = {"User-Agent": "Mozilla/5.0 (TLC-Radar schedule updater)"}

# cruise line (from the row's line-icon alt text, minus " Cruises cruise line")
# -> terminal id: 'cruise1' = Manhattan, 'cruise2' = Brooklyn, None = exclude
LINE_TERMINAL = {
    "Cunard": "cruise2",
    "MSC Cruises": "cruise2",
    "Virgin Voyages": "cruise2",
    "Princess Cruises": "cruise2",  # verified Brooklyn Oct-Nov 2026; see note above
    "Explora Journeys": "cruise2",  # MSC Group
    "Carnival Cruise Line": "cruise1",
    "Norwegian Cruise Line": "cruise1",
    "Oceania Cruises": "cruise1",
    "Regent Seven Seas Cruises": "cruise1",
    "TUI Cruises": "cruise1",
    "AIDA Cruises": "cruise1",
    "Holland America Line": "cruise1",
    "Silversea Cruises": "cruise1",
    "Azamara": "cruise1",
    "Viking": "cruise1",
    "American Cruise Lines": "cruise1",
    "Hapag-Lloyd Cruises": "cruise1",
    "Costa Cruises": "cruise1",
    "Crystal Cruises": "cruise1",
    "Disney Cruise Line": "cruise1",
    "Seabourn": "cruise1",
    "Windstar Cruises": "cruise1",
    "Royal Caribbean International": None,
    "Celebrity Cruises": None,
}

# ship -> cabins (verified from CruiseMapper ship pages, 2026-11-15)
CABINS = {
    "Norwegian Bliss": 2069,
    "Volendam": 716,
    "Queen Mary 2": 1363,
    "Queen Victoria": 1037,
    "Europa": 204,
    "Europa 2": 251,
    "Costa Deliziosa": 1130,
}

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
# v3.48: oy nomi noto'g'ri bo'lsa ValueError o'rniga o'tkazib yuboriladi (AUD-32)
MONTHS_IDX = {name: i + 1 for i, name in enumerate(MONTHS)}


def clean(t):
    t = re.sub(r"<[^>]+>", " ", t)
    t = H.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def fetch(url, retries=2):
    # v3.48: tarmoq xatosida 2 marta qayta urinish (AUD-07)
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            print(f"fetch failed (attempt {attempt + 1}/{retries + 1}): {url}: {e}")
    raise last


def ship_cabins(ship_url):
    """Fetch a CruiseMapper ship page and parse the Cabins spec row."""
    try:
        h = fetch(ship_url)
        for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", h, re.S):
            cells = [clean(c) for c in
                     re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", m.group(1), re.S)]
            if cells and cells[0].strip().lower() == "cabins" and len(cells) > 1:
                num = re.sub(r"\D", "", cells[1])
                return int(num) if num else None
    except Exception:
        return None
    return None


def norm_ship(name):
    name = re.sub(r"^(ms|rms)\s+", "", name.strip(), flags=re.I)
    return re.sub(r"\s+", " ", name).strip()


def parse_month(ym, today):
    """Return list of dicts for one CruiseMapper month page."""
    html = fetch(PORT_URL.format(ym=ym))
    rows = {}
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        tr = m.group(1)
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(cells) < 2:
            continue
        day = clean(cells[0])
        dm = re.match(r"(\d+)\s+(\w+),\s*(\d{4})", day)
        if not dm:
            continue
        mo = MONTHS_IDX.get(dm.group(2))
        if mo is None:
            continue  # kutilmagan oy nomi — qator o'tkazib yuboriladi
        try:
            d = date(int(dm.group(3)), mo, int(dm.group(1)))
        except ValueError:
            continue  # noto'g'ri sana (masalan, 31 Feb) — qator o'tkazib yuboriladi
        if d < today:
            continue
        ship = norm_ship(clean(cells[1]))
        arr = clean(cells[2]) if len(cells) > 2 else ""
        dep = clean(cells[3]) if len(cells) > 3 else ""
        if dep.startswith("01 Jan"):
            dep = ""  # CruiseMapper placeholder for unknown departure
        # cruise line from the line-icon alt text in the ship cell
        lm = re.search(r'alt="([^"]+?) Cruises cruise line"', cells[1])
        line = lm.group(1) if lm else ""
        # ship page url for cabin lookup
        um = re.search(r'href="(https://www\.cruisemapper\.com/ships/[^"]+)"',
                       cells[1])
        ship_url = um.group(1) if um else ""
        key = (d.isoformat(), ship)
        row = rows.get(key)
        if row is None:
            row = {"d": d.isoformat(), "ship": ship, "arr": arr, "dep": dep,
                   "line": line, "url": ship_url}
            rows[key] = row
        else:  # merge a duplicate row, filling blanks
            if not row["arr"]:
                row["arr"] = arr
            if not row["dep"]:
                row["dep"] = dep
    return list(rows.values())


def main():
    today = date.today()
    months = []
    y, m = today.year, today.month
    for _ in range(3):  # current month + next 2
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    out = {"updated": today.isoformat(),
           "source": "CruiseMapper + official schedule",
           "cruise1": [], "cruise2": []}
    unknown = []
    for ym in months:
        # v3.48: bitta oy yiqilsa ham qolgan oylar ishlanadi (AUD-07)
        try:
            month_rows = parse_month(ym, today)
        except Exception as e:
            print(f"parse_month {ym} failed, skipping: {e}")
            continue
        for r in month_rows:
            term = LINE_TERMINAL.get(r["line"])
            row = {"d": r["d"], "ship": r["ship"], "arr": r["arr"],
                   "dep": r["dep"]}
            if not r["arr"] and not r["dep"]:
                row["depDay"] = True
            cabins = CABINS.get(r["ship"])
            if cabins is None and r["url"]:
                cabins = ship_cabins(r["url"])
                if cabins:
                    CABINS[r["ship"]] = cabins
            if cabins:
                row["cabins"] = cabins
            if term in ("cruise1", "cruise2"):
                out[term].append(row)
            elif term is None and r["line"] in LINE_TERMINAL:
                continue  # Cape Liberty line — not our terminals
            else:
                unknown.append(row)
    for k in ("cruise1", "cruise2"):
        out[k].sort(key=lambda r: (r["d"], r["ship"]))
    if unknown:
        unknown.sort(key=lambda r: (r["d"], r["ship"]))
        out["unknown"] = unknown
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_path = os.environ.get("CRUISE_OUT",
                              os.path.join(root, "radar", "cruise-schedule.json"))
    # v3.48: bo'sh yoki keskin kamaygan jadval eski yaxshi faylni ezmasin (AUD-07)
    total = len(out["cruise1"]) + len(out["cruise2"])
    if total == 0:
        print("ERROR: no cruise rows parsed — refusing to overwrite the schedule")
        raise SystemExit(1)
    if os.path.exists(out_path):
        try:
            prev = json.load(open(out_path, encoding="utf-8"))
            prev_total = len(prev.get("cruise1", [])) + len(prev.get("cruise2", []))
            if prev_total > 0 and total < prev_total * 0.5:
                print(f"ERROR: parsed {total} rows vs previous {prev_total} — refusing to overwrite")
                raise SystemExit(1)
        except SystemExit:
            raise
        except Exception as e:
            print(f"warning: could not read previous schedule ({e}) — continuing")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    n1, n2 = len(out["cruise1"]), len(out["cruise2"])
    print(f"wrote {out_path}: Manhattan {n1}, Brooklyn {n2}, "
          f"unknown {len(unknown)}, updated {out['updated']}")


if __name__ == "__main__":
    main()
