#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scrape a nuLiga Team Portrait page (all matches for a single team) into a
Google Calendar-compatible CSV.

CSV columns:
Subject, Start Date, Start Time, End Date, End Time, All Day Event, Description, Location, Private
"""

import re
import csv
import argparse
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; nuLiga-team-portrait-scraper/1.0)"}

# Regexes
DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")  # 30.09.2025
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")          # 19:30

def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text

def norm(s: str) -> str:
    return " ".join((s or "").replace("\xa0", " ").split()).strip()

def fmt_date(dt: datetime) -> str:
    return dt.strftime("%m/%d/%Y")

def fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")

def parse_datetime(date_text: str, time_text: str | None) -> datetime | None:
    """
    Robust date/time parser for cells like:
    - date: '30.09.2025'
    - time: '19:30', '19:30 Uhr', '19:30 v', '19:30  v'
    """
    date_text = norm(date_text)
    time_text = norm(time_text or "")

    m = DATE_RE.search(date_text)
    if not m:
        return None
    day, month, year = map(int, m.groups())

    hh, mm = 0, 0
    mt = TIME_RE.search(time_text)
    if mt:
        hh, mm = int(mt.group(1)), int(mt.group(2))

    return datetime(year, month, day, hh, mm)

def find_schedule_tables(soup: BeautifulSoup):
    """
    Returns list of table elements corresponding to Spieltermine (Vorrunde/Rückrunde).
    We detect them by the preceding h2/h3 headings containing 'Spieltermine'.
    """
    tables = []
    for heading in soup.find_all(["h2", "h3"]):
        if "Spieltermine" in heading.get_text():
            # Next table sibling holds the rows
            tbl = heading.find_next("table")
            if tbl:
                tables.append(tbl)
    return tables

def hall_address_from_cell(cell, page_url: str) -> str:
    """
    If the hall short code (e.g., LY, TU) is linked, follow it and try to extract
    a concise hall address from the target page. Otherwise, return the cell text.
    """
    fallback = norm(cell.get_text(" ", strip=True))
    a = cell.find("a")
    if not a or not a.get("href"):
        return fallback

    hall_url = urljoin(page_url, a["href"])
    try:
        html = fetch(hall_url)
    except Exception:
        return fallback
    hs = BeautifulSoup(html, "html.parser")

    # Look for a 'Hallenadresse' header and collect a couple of lines below
    addr_lines = []
    for tag in hs.find_all(re.compile(r"^h[1-4]$")):
        if "Hallenadresse" in tag.get_text():
            # collect a few blocks after
            cur = tag
            for sib in tag.find_all_next():
                if sib.name and re.match(r"^h[1-4]$", sib.name):
                    break
                if sib.name in ("p", "div", "address"):
                    text = norm(sib.get_text(" ", strip=True))
                    if text:
                        addr_lines.append(text)
                if len(addr_lines) >= 3:
                    break
            break

    code = norm(a.get_text(strip=True))
    addr = " | ".join(addr_lines) if addr_lines else fallback
    if code and code not in addr:
        addr = f"{code} – {addr}"
    return addr

def parse_team_portrait(url: str, default_duration: int = 120, enrich_halls: bool = True) -> list[dict]:
    """
    Parse both Spieltermine tables (Vorrunde & Rückrunde) from a Team Portrait page.
    """
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    # Optional: surface team name from the page (used in Subject if you want)
    team_name_el = soup.find(string=re.compile(r"^\s*TSV\s+Wedding", re.I))  # loose find; page shows the team prominently
    team_name = norm(team_name_el.strip()) if team_name_el else None

    tables = find_schedule_tables(soup)
    if not tables:
        raise RuntimeError("Konnte die Spieltermine-Tabellen nicht finden.")

    rows_out: list[dict] = []

    for tbl in tables:
        for tr in tbl.find_all("tr"):
            tds = tr.find_all("td")
            # Expect the standard 8 columns (Tag, Datum, Zeit, Sporthalle, Nr., Heim, Gast, Spiele)
            if len(tds) < 7:
                continue

            # Extract cells
            # tds[0] = Tag (weekday), tds[1] = Datum, tds[2] = Zeit
            date_txt = norm(tds[1].get_text(" ", strip=True))
            time_txt = norm(tds[2].get_text(" ", strip=True))
            hall_cell = tds[3]
            nr_txt = norm(tds[4].get_text(" ", strip=True)) if len(tds) >= 5 else ""
            home = norm(tds[5].get_text(" ", strip=True)) if len(tds) >= 6 else ""
            away = norm(tds[6].get_text(" ", strip=True)) if len(tds) >= 7 else ""
            result = norm(tds[7].get_text(" ", strip=True)) if len(tds) >= 8 else ""

            # Skip header / separator rows that lack a proper date
            if not DATE_RE.search(date_txt):
                continue

            start_dt = parse_datetime(date_txt, time_txt or "19:30")
            if not start_dt:
                continue

            # nuLiga does not include end times; use a default duration
            end_dt = start_dt + timedelta(minutes=default_duration)

            # Location
            location = hall_address_from_cell(hall_cell, url) if enrich_halls else norm(hall_cell.get_text(" ", strip=True))

            # Description
            desc_parts = []
            if nr_txt:
                desc_parts.append(f"Spiel Nr.: {nr_txt}")
            if result:
                # keep only a score-like pattern
                mscore = re.search(r"\d+:\d+", result)
                if mscore:
                    desc_parts.append(f"Ergebnis: {mscore.group(0)}")
            description = " | ".join(desc_parts)

            subject = f"{home} vs. {away}"

            rows_out.append({
                "Subject": subject,
                "Start Date": fmt_date(start_dt),
                "Start Time": fmt_time(start_dt),
                "End Date": fmt_date(end_dt),
                "End Time": fmt_time(end_dt),
                "All Day Event": "False",
                "Description": description,
                "Location": location,
                "Private": "False",
            })

    return rows_out

def write_csv(rows: list[dict], out_path: str) -> None:
    fieldnames = [
        "Subject", "Start Date", "Start Time", "End Date", "End Time",
        "All Day Event", "Description", "Location", "Private"
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

def main():
    ap = argparse.ArgumentParser(description="Scrape a nuLiga Team Portrait page into Google Calendar CSV.")
    ap.add_argument("--url", required=True, help="nuLiga teamPortrait URL")
    ap.add_argument("--out", default="team_events.csv", help="Output CSV path")
    ap.add_argument("--duration", type=int, default=120, help="Default event duration minutes")
    ap.add_argument("--no-enrich", action="store_true", help="Do not follow hall links for full address")

    args = ap.parse_args()

    rows = parse_team_portrait(args.url, default_duration=args.duration, enrich_halls=not args.no_enrich)
    write_csv(rows, args.out)
    print(f"✅ Wrote {len(rows)} events → {args.out}")

if __name__ == "__main__":
    main()

