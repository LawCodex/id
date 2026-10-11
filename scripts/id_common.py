"""Shared helpers for the Indonesian LawCodex scripts (paths, HTTP, parsing, merging)."""
import gzip
import json
import os
import re
import sys
import threading
import time
import unicodedata

import requests

UA = "LawCodex/1.0 (+https://github.com/LawCodex)"
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RAW = os.environ.get("ID_RAW", os.path.join(os.path.dirname(REPO), "_raw", "id"))

SETNEG = "https://jdih.setneg.go.id"
BPK = "https://peraturan.bpk.go.id"
DPR = "https://jdih.dpr.go.id"
WAYBACK = "http://web.archive.org"

# Our kinds -> output directory
KIND_DIR = {
    "uud": "uud-1945",
    "uu": "uu",
    "uudrt": "uu-darurat",
    "perppu": "perppu",
    "pp": "pp",
    "perpres": "perpres",
}
KIND_LABEL = {
    "uu": "Undang-Undang",
    "uudrt": "Undang-Undang Darurat",
    "perppu": "Peraturan Pemerintah Pengganti Undang-Undang",
    "pp": "Peraturan Pemerintah",
    "perpres": "Peraturan Presiden",
}
KIND_SHORT = {"uu": "UU", "uudrt": "UU Darurat", "perppu": "Perppu", "pp": "PP", "perpres": "Perpres"}
KIND_TYPE = {"uud": "constitution", "uu": "act", "uudrt": "act", "perppu": "act",
             "pp": "regulation", "perpres": "regulation"}


def norm_kind(s):
    """Map a source's form label ('UU', 'PERPU', 'Perppu', 'UU Darurat', 'PP'...) to our kind."""
    if not s:
        return None
    k = re.sub(r"[^a-z]", "", s.lower())
    return {
        "uu": "uu", "undangundang": "uu",
        "uudrt": "uudrt", "uudarurat": "uudrt", "undangundangdarurat": "uudrt",
        "perpu": "perppu", "perppu": "perppu",
        "peraturanpemerintahpenggantiundangundang": "perppu",
        "pp": "pp", "peraturanpemerintah": "pp",
        "perpres": "perpres", "peraturanpresiden": "perpres",
        "uud": "uud",
    }.get(k)


def norm_num(s):
    s = (s or "").strip().upper()
    s = re.sub(r"\s+", "", s)
    m = re.match(r"^0*(\d+)([A-Z]?)$", s)
    if m:
        return m.group(1) + m.group(2)
    return s


_local = threading.local()


def session():
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers["User-Agent"] = UA
        _local.s = s
    return s


def http(method, url, delay=0.5, tries=6, timeout=120, ok=(200,), **kw):
    """GET/POST with retries + exponential backoff. Returns Response or None."""
    for i in range(tries):
        try:
            r = session().request(method, url, timeout=timeout, **kw)
            time.sleep(delay)
            if r.status_code in ok or r.status_code in (403, 404, 410):
                return r
            if r.status_code in (429, 500, 502, 503, 504, 520, 522, 524):
                wait = 10 * (2 ** i)
                ra = r.headers.get("Retry-After")
                if ra and ra.isdigit():
                    wait = max(wait, int(ra))
                print(f"  HTTP {r.status_code} {url} -> sleep {wait}s", file=sys.stderr)
                time.sleep(min(wait, 600))
                continue
            return r
        except requests.RequestException as e:
            print(f"  retry {i} {url}: {e}", file=sys.stderr)
            time.sleep(min(10 * (2 ** i), 600))
    return None


def jload(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def jsave(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def gz_write(path, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with gzip.open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def gz_read(path):
    with gzip.open(path, "rb") as f:
        return f.read()


def slugify(s, maxlen=80):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    if len(s) > maxlen:
        s = s[:maxlen].rsplit("-", 1)[0]
    return s or "untitled"


MONTHS = {
    "januari": 1, "februari": 2, "pebruari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "nopember": 11, "november": 11,
    "desember": 12, "january": 1, "february": 2, "march": 3, "may": 5, "june": 6, "july": 7,
    "august": 8, "october": 10, "december": 12,
}


def parse_date(s):
    """'10 Januari 2019' / '2019-01-10T00:00:00.000Z' / '02 January 2026' -> 'YYYY-MM-DD'."""
    if not s:
        return None
    s = s.strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", s)
    if m and m.group(2).lower() in MONTHS:
        return f"{int(m.group(3)):04d}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return None


# ---------------------------------------------------------------- BPK (via Wayback) parsing

def parse_bpk_details(html):
    """Parse a peraturan.bpk.go.id /Details/<id> page. Returns dict or None."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    meta = {}
    for lab in soup.select("div.col-lg-3.fw-bold"):
        val = lab.find_next_sibling("div")
        if val is None:
            continue
        key = lab.get_text(" ", strip=True)
        meta[key] = re.sub(r"\s+", " ", val.get_text(" ", strip=True))
    if "Judul" not in meta and "Tipe Dokumen" not in meta:
        return None
    files = []
    for a in soup.select("a.download-file[href]"):
        href = a["href"]
        if "/Download/" not in href or "preview" in (a.get("class") or []):
            continue
        href = re.sub(r"^https?://web\.archive\.org/web/\d+(id_)?/", "", href)
        href = re.sub(r"^https?://peraturan\.bpk\.go\.id", "", href)
        if href not in [f["href"] for f in files]:
            files.append({"id": a.get("data-id"), "href": href})
    rel = {}
    cur = None
    st = None
    for h in soup.find_all("h4"):
        if "STATUS" in h.get_text(" ", strip=True).upper():
            st = h
            break
    if st is not None:
        for el in st.find_all_next(["div", "a", "h4"]):
            if el.name == "h4":
                break
            cls = el.get("class") or []
            if el.name == "div" and "bg-light-primary" in cls:
                cur = re.sub(r"\s*:\s*$", "", el.get_text(" ", strip=True))
                rel.setdefault(cur, [])
            elif el.name == "a" and cur and "/Details/" in (el.get("href") or ""):
                m = re.search(r"/Details/\s*(?:%20)?(\d+)", el["href"])
                if m:
                    rel[cur].append({"id": m.group(1), "label": el.get_text(" ", strip=True)})
    catatan = None
    for b in soup.find_all(string=re.compile(r"CATATAN:")):
        p = b.find_parent()
        if p is not None:
            nxt = p.find_next_sibling()
            if nxt is not None:
                catatan = re.sub(r"\s+", " ", nxt.get_text(" ", strip=True))
        break
    return {"meta": meta, "files": files, "relations": rel, "catatan": catatan}


def bpk_record(bid, parsed, snapshot):
    m = parsed["meta"]
    kind = norm_kind(m.get("Bentuk Singkat")) or norm_kind(m.get("Bentuk"))
    title = m.get("Judul", "")
    tentang = title
    mm = re.search(r"\btentang\b\s+(.*)$", title, re.I | re.S)
    if mm:
        tentang = mm.group(1).strip()
    status = (m.get("Status") or "").strip()
    rel = parsed.get("relations") or {}
    return {
        "bpk_id": bid, "kind": kind, "number": norm_num(m.get("Nomor")),
        "year": (m.get("Tahun") or "").strip(), "title": title, "tentang": tentang,
        "date_enacted": parse_date(m.get("Tanggal Penetapan")),
        "date_promulgated": parse_date(m.get("Tanggal Pengundangan")),
        "date_in_force": parse_date(m.get("Tanggal Berlaku")),
        "place": m.get("Tempat Penetapan"), "sumber": m.get("Sumber"), "subjek": m.get("Subjek"),
        "status": status, "relations": rel, "files": parsed["files"],
        "catatan": parsed.get("catatan"), "snapshot": snapshot,
        "url": f"{BPK}/Details/{bid}",
    }
