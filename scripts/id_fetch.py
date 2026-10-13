#!/usr/bin/env python3
"""Fetch Indonesian legislation metadata and texts into the local cache (_raw/id/).

Steps (run in this order; each is resumable / cached):

  bpk-cdx    List the JDIH BPK "Database Peraturan" detail pages (peraturan.bpk.go.id/Details/<id>)
             known to the Internet Archive (CDX API). peraturan.bpk.go.id serves its HTML pages
             behind a Cloudflare JS challenge, which we do not attempt to pass, so the metadata
             (incl. the in-force status "Berlaku"/"Dicabut") is read from Wayback Machine copies.
  bpk-meta   Download the latest Wayback copy of each detail page and parse it.
  setneg     List UU / Perppu / PP / Perpres from JDIH Kementerian Sekretariat Negara
             (jdih.setneg.go.id, public JSON API used by its own web UI) incl. per-item details.
  dpr        List UU from JDIH Setjen DPR RI (jdih.dpr.go.id) year pages (cross-check).
  text       For every instrument in the merged plan, download its PDF(s) (BPK /Download/ links first -
             fast; then Setneg, also used when the BPK text looks like poor OCR), extract the text with pdftotext, keep only the text in
             _raw/id/text/, and delete the PDF straight away.

Politeness: User-Agent "LawCodex/1.0 (+https://github.com/LawCodex)", sequential requests per
host with a delay, retries with exponential backoff. robots.txt (checked 2026-10-12):
jdih.setneg.go.id allows everything; peraturan.bpk.go.id disallows only /Admin, /Identity,
/Account, /Manage, /health, /Error; jdih.dpr.go.id robots.txt returns HTTP 500. No Crawl-delay.

Usage: python id_fetch.py STEP [--kinds uu,perppu,...] [--limit N]
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import id_common as C

BPK_SLUG_KIND = {"uu": "uu", "uudrt": "uudrt", "perpu": "perppu", "perppu": "perppu", "pp": "pp",
                 "perpres": "perpres", "uud": "uud"}


# ------------------------------------------------------------------------------------ BPK

def step_bpk_cdx(args):
    url = (f"{C.WAYBACK}/cdx/search/cdx?url=peraturan.bpk.go.id/Details/&matchType=prefix"
           "&fl=original,timestamp&filter=statuscode:200&collapse=urlkey")
    r = C.http("GET", url, delay=1, timeout=900)
    if r is None or r.status_code != 200:
        sys.exit("CDX query failed")
    idx = {}
    for line in r.text.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        orig, ts = parts
        m = re.search(r"/Details/(?:%20|\s)*(\d+)(?:/([^/?#]*))?", orig, re.I)
        if not m:
            continue
        bid, slug = m.group(1), (m.group(2) or "").lower()
        sk = re.match(r"([a-z]+)", slug)
        kind = BPK_SLUG_KIND.get(sk.group(1)) if sk else None
        e = idx.setdefault(bid, {"kinds": [], "snaps": []})
        if kind and kind not in e["kinds"]:
            e["kinds"].append(kind)
        e["snaps"].append([ts, orig])
    for e in idx.values():
        e["snaps"].sort(reverse=True)
        e["snaps"] = e["snaps"][:4]
    C.jsave(os.path.join(C.RAW, "bpk_index.json"), idx)
    from collections import Counter
    cnt = Counter(k for e in idx.values() for k in e["kinds"])
    print(f"{len(idx)} ids; by slug kind: {dict(cnt)}")


def fetch_bpk_page(bid, snaps):
    """Fetch the newest usable Wayback copy of BPK /Details/<bid>; returns (html, ts, orig)."""
    for ts, orig in snaps:
        wb = f"{C.WAYBACK}/web/{ts}id_/{orig}"
        r = C.http("GET", wb, delay=1.0, timeout=180)
        if r is None or r.status_code != 200:
            continue
        html = r.content.decode("utf-8", "replace")
        if "Tipe Dokumen" in html or "Bentuk Singkat" in html:
            return html, ts, orig
    return None, None, None


def step_bpk_meta(args):
    idx = C.jload(os.path.join(C.RAW, "bpk_index.json"))
    kinds = set(args.kinds.split(","))
    hdir = os.path.join(C.RAW, "bpk", "html")
    mdir = os.path.join(C.RAW, "bpk", "meta")
    todo = [(bid, e) for bid, e in sorted(idx.items(), key=lambda x: int(x[0]))
            if kinds & set(e["kinds"])]
    if args.extra_ids:
        for bid in args.extra_ids.split(","):
            if bid in idx:
                todo.append((bid, idx[bid]))
    prio = {"uud": 0, "uu": 1, "uudrt": 1, "perppu": 1, "pp": 2, "perpres": 3}
    todo.sort(key=lambda x: (min(prio.get(k, 9) for k in x[1]["kinds"] or ["?"]), int(x[0])))
    todo = [(bid, e) for bid, e in todo if not os.path.exists(os.path.join(mdir, f"{bid}.json"))]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(todo)} BPK pages to fetch", flush=True)

    def one(item):
        bid, e = item
        mp = os.path.join(mdir, f"{bid}.json")
        hp = os.path.join(hdir, f"{bid}.html.gz")
        if os.path.exists(hp):
            html = C.gz_read(hp).decode("utf-8", "replace")
            snap = (C.jload(hp + ".json") or {}).get("snapshot")
        else:
            html, ts, orig = fetch_bpk_page(bid, e["snaps"])
            if html is None:
                C.jsave(mp, {"bpk_id": bid, "error": "no usable snapshot"})
                return
            snap = f"{C.WAYBACK}/web/{ts}/{orig}"
            C.gz_write(hp, html.encode("utf-8"))
            C.jsave(hp + ".json", {"snapshot": snap})
        parsed = C.parse_bpk_details(html)
        if parsed is None:
            C.jsave(mp, {"bpk_id": bid, "error": "unparseable"})
            return
        C.jsave(mp, C.bpk_record(bid, parsed, snap))

    n = 0
    # 3 concurrent requests to the Wayback Machine (each worker waits 1 s between requests)
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for _ in ex.map(one, todo):
            n += 1
            if n % 100 == 0:
                print(f"  {n}/{len(todo)}", flush=True)
    print("bpk-meta done", flush=True)


def step_bpk_follow(args):
    """Fetch metadata for BPK ids referenced in status relations of UU-level instruments but not
    yet in the cache, if the Wayback Machine has a copy (one CDX lookup per id)."""
    mdir = os.path.join(C.RAW, "bpk", "meta")
    idx = C.jload(os.path.join(C.RAW, "bpk_index.json"))
    have = {f[:-5] for f in os.listdir(mdir) if f.endswith(".json")}
    want = set()
    kinds = set(args.kinds.split(","))
    for f in os.listdir(mdir):
        if not f.endswith(".json"):
            continue
        r = C.jload(os.path.join(mdir, f))
        for lst in (r.get("relations") or {}).values():
            for x in lst:
                lab = x["label"].lower()
                k = C.norm_kind(lab.split(" no.")[0]) if " no." in lab else None
                if k in kinds and x["id"] not in have:
                    want.add(x["id"])
    print(f"{len(want)} referenced ids missing", flush=True)
    for bid in sorted(want, key=int):
        if bid in idx:
            snaps = idx[bid]["snaps"]
        else:
            q = (f"{C.WAYBACK}/cdx/search/cdx?url=peraturan.bpk.go.id/Details/{bid}/"
                 "&matchType=prefix&fl=original,timestamp&filter=statuscode:200&limit=-3")
            r = C.http("GET", q, delay=1.0)
            snaps = []
            if r is not None and r.status_code == 200:
                for line in r.text.splitlines():
                    p = line.split()
                    if len(p) == 2:
                        snaps.append([p[1], p[0]])
            snaps.sort(reverse=True)
            if not snaps:
                C.jsave(os.path.join(mdir, f"{bid}.json"), {"bpk_id": bid, "error": "not archived"})
                continue
        html, ts, orig = fetch_bpk_page(bid, snaps)
        mp = os.path.join(mdir, f"{bid}.json")
        if html is None:
            C.jsave(mp, {"bpk_id": bid, "error": "no usable snapshot"})
            continue
        snap = f"{C.WAYBACK}/web/{ts}/{orig}"
        hp = os.path.join(C.RAW, "bpk", "html", f"{bid}.html.gz")
        C.gz_write(hp, html.encode("utf-8"))
        C.jsave(hp + ".json", {"snapshot": snap})
        parsed = C.parse_bpk_details(html)
        C.jsave(mp, C.bpk_record(bid, parsed, snap) if parsed else {"bpk_id": bid, "error": "unparseable"})
    print("bpk-follow done", flush=True)


# --------------------------------------------------------------------------------- Setneg

SETNEG_JNS = {"uu": "UU", "perppu": "PERPU", "pp": "PP", "perpres": "PERPRES"}


def step_setneg(args):
    sdir = os.path.join(C.RAW, "setneg")
    for kind in args.kinds.split(","):
        jns = SETNEG_JNS.get(kind)
        if not jns:
            continue
        lp = os.path.join(sdir, f"list_{kind}.json")
        lst = C.jload(lp)
        if lst is None:
            body = {"tentang": "", "jns": [jns], "thn": [], "status": "", "p_lihan": "semua",
                    "terx": "All", "sortOrder": "asc", "length": 5000, "start": 0}
            r = C.http("POST", f"{C.SETNEG}/api/hukumproduk/produkhukum", json=body, delay=1)
            d = r.json()
            lst = d["data"]
            if len(lst) != d["jml"]:
                print(f"WARNING {jns}: got {len(lst)} of {d['jml']}", file=sys.stderr)
            C.jsave(lp, lst)
        print(f"setneg {jns}: {len(lst)} items", flush=True)
        n = 0
        for it in lst:
            dp = os.path.join(sdir, "detail", f"{it['idperaturan']}.json")
            if os.path.exists(dp) or int(it.get("file_jj") or 0) <= 1:
                continue  # single-file items: the list row already names the file
            body = {"jns": it["jns"], "no": it["no_peraturan"], "thn": it["tahun"], "k": ""}
            r = C.http("POST", f"{C.SETNEG}/api/hukumproduk/detaildata", json=body, delay=0.5)
            if r is None or r.status_code != 200:
                print(f"  detail failed {it['idperaturan']}", file=sys.stderr)
                continue
            d = r.json()
            # several instruments can share jns/no/thn (data errors) - keep the matching row
            rows = [x for x in d.get("row", []) if x.get("idperaturan") == it["idperaturan"]]
            d["row"] = rows or d.get("row", [])
            C.jsave(dp, d)
            n += 1
            if n % 200 == 0:
                print(f"  {jns} details {n}", flush=True)
    print("setneg done", flush=True)


# ------------------------------------------------------------------------------------ DPR

DPR_LISTS = {
    "uu": "Undang-undang-BAGIAN-PERTIMBANGAN-DAN-DOKUMENTASI-INFORMASI-HUKUM",
}  # the DPR Perppu pages list titles without numbers, so they are not used


def step_dpr(args):
    out = []
    for kind, page in DPR_LISTS.items():
        for year in range(1945, time.gmtime().tm_year + 1):
            url = f"{C.DPR}/setjen/index/id/{page}/year/{year}"
            r = C.http("GET", url, delay=1.0)
            if r is None or r.status_code != 200:
                print(f"  dpr fail {url}", file=sys.stderr)
                continue
            for m in re.finditer(r"href='(/setjen/detail-dokumen/tipe/[a-z]+/id/(\d+))'>([^<]*)</a>"
                                 r"(.*?)</tr>", r.text, re.S):
                title = re.sub(r"\s+", " ", m.group(3)).strip()
                pdf = re.search(r'href="(https://berkas\.dpr\.go\.id/[^"]+)"', m.group(4))
                nm = re.search(r"NOMOR\s+([0-9A-Z]+)\s+TAHUN\s+(\d{4})", title, re.I)
                out.append({"kind": kind, "dpr_id": m.group(2), "url": C.DPR + m.group(1),
                            "title": title, "number": C.norm_num(nm.group(1)) if nm else None,
                            "year": nm.group(2) if nm else str(year), "list_year": year,
                            "pdf": pdf.group(1) if pdf else None})
        print(f"dpr {kind}: {sum(1 for x in out if x['kind'] == kind)}", flush=True)
    C.jsave(os.path.join(C.RAW, "dpr_list.json"), out)


# ----------------------------------------------------------------------------------- text

MAX_PDF = 120 * 1024 * 1024


def doc_to_text(data):
    with tempfile.TemporaryDirectory(dir=os.path.join(C.RAW, "tmp")) as td:
        p = os.path.join(td, "in.doc")
        with open(p, "wb") as f:
            f.write(data)
        r = subprocess.run(["textutil", "-convert", "txt", "-encoding", "UTF-8", "-stdout", p],
                           capture_output=True, timeout=300)
        txt = r.stdout.decode("utf-8", "replace")
        return txt, max(1, len(txt) // 2500)


def pdf_to_text(data):
    if data.startswith(b"\xd0\xcf\x11\xe0") or data.startswith(b"{\\rtf"):
        return doc_to_text(data)
    with tempfile.TemporaryDirectory(dir=os.path.join(C.RAW, "tmp")) as td:
        p = os.path.join(td, "in.pdf")
        with open(p, "wb") as f:
            f.write(data)
        try:
            pages = 0
            info = subprocess.run(["pdfinfo", p], capture_output=True, text=True, timeout=120)
            m = re.search(r"^Pages:\s+(\d+)", info.stdout, re.M)
            if m:
                pages = int(m.group(1))
            r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", p, "-"], capture_output=True,
                               timeout=600)
            return r.stdout.decode("utf-8", "replace"), pages
        except subprocess.TimeoutExpired:
            return "", 0


def text_quality(txt, pages):
    chars = len(re.sub(r"\s", "", txt))
    words = re.findall(r"[A-Za-z]{3,}", txt)
    return chars, (chars / pages if pages else chars), len(words)


def is_scanned(txt, pages):
    chars, cpp, words = text_quality(txt, pages)
    return cpp < 150 or words < 30


RE_GARBAGE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)(?!\d+[A-Za-z]{1,2}$)(?!\d+[.,]?\d*$)[A-Za-z0-9]+$")


def garbage_ratio(txt):
    """Share of OCR-garbage tokens (letters and digits mixed: '2OO8', 'lZ', 'a286'...)."""
    toks = re.findall(r"[A-Za-z0-9]+", txt)
    if not toks:
        return 1.0
    bad = sum(1 for t in toks if RE_GARBAGE.match(t) and not re.match(r"^(\d+[A-Za-z]|[A-Z]+\d+)$", t))
    bad += txt.count("{") + txt.count("\\") + txt.count("|")
    return bad / len(toks)


HOST_SEM = {"jdih.setneg.go.id": threading.Semaphore(1), "peraturan.bpk.go.id": threading.Semaphore(3)}


def download(url, host_delay, tries=4, max_size=MAX_PDF, deadline=900):
    """Download with at most 1 concurrent request to Setneg (slow server) and 3 to BPK."""
    sem = HOST_SEM.get(urllib.parse.urlparse(url).hostname)
    if sem is None:
        return _download(url, host_delay, tries, max_size, deadline)
    with sem:
        return _download(url, host_delay, tries, max_size, deadline)


def _download(url, host_delay, tries, max_size, deadline):
    t0 = time.time()
    for attempt in range(tries):
        r = C.http("GET", url, delay=host_delay, timeout=300, stream=True, tries=3)
        if r is None or r.status_code != 200:
            return None, (r.status_code if r is not None else "error")
        cl = r.headers.get("Content-Length")
        if cl and cl.isdigit() and int(cl) > max_size:
            r.close()
            return None, f"too large ({int(cl) // 1048576} MB)"
        buf = bytearray()
        try:
            for chunk in r.iter_content(1 << 16):
                buf.extend(chunk)
                if time.time() - t0 > deadline:
                    r.close()
                    return None, "download too slow"
                if len(buf) > max_size:
                    r.close()
                    return None, "too large"
            break
        except Exception as e:  # connection broken mid-transfer: retry
            print(f"  broken transfer {url}: {e}", file=sys.stderr)
            time.sleep(10 * (attempt + 1))
    else:
        return None, "transfer failed"
    data = bytes(buf)
    if data.startswith(b"\xd0\xcf\x11\xe0") or data.startswith(b"{\\rtf"):
        if shutil.which("textutil"):
            return data, 200  # legacy Word / RTF file - converted with macOS textutil
        return None, "not a pdf (Word/RTF)"
    if not data.startswith(b"%PDF") and b"%PDF" not in data[:1024]:
        return None, "not a pdf"
    return data, 200


def candidates(item):
    """Ordered list of PDF source sets: [(source_name, [(label, url)])]."""
    out = []
    bp = item.get("bpk")
    if bp and bp.get("files"):
        fl = [(urllib.parse.unquote(f["href"].rsplit("/", 1)[-1]), C.BPK + f["href"])
              for f in bp["files"]]
        out.append(("bpk", fl))
    sn = item.get("setneg")
    if sn and sn.get("files"):
        fl = []
        for f in sn["files"]:
            q = urllib.parse.urlencode({"l": "uploads", "f": f["realName"], "fl": sn["id"]})
            fl.append((f["realName"], f"{C.SETNEG}/api/hukumproduk/pdf?{q}"))
        out.append(("setneg", fl))
    return out


def process_item(item, max_files=12):
    key = item["key"]
    tp = os.path.join(C.RAW, "text", item["kind"], f"{key}.json")
    cands = candidates(item)
    if not cands:
        return  # nothing to download (yet) - e.g. BPK metadata not cached
    tried = []
    best = None
    for src, files in cands:
        delay = 1.0
        parts = []
        skipped = []
        main_ok = False
        for i, (label, url) in enumerate(files):
            if i > 0 and src == "setneg":
                # the Setneg file server is slow and drops large transfers: attachments are linked
                skipped.append({"label": label, "url": url, "reason": "attachment not downloaded"})
                continue
            if i >= max_files:
                skipped.append({"label": label, "url": url, "reason": "too many attachments"})
                continue
            if i == 0:
                data, st = download(url, delay)
            else:  # attachments: smaller budget
                data, st = download(url, delay, tries=2, max_size=15 * 1024 * 1024, deadline=180)
            if data is None:
                if i == 0:
                    tried.append({"source": src, "url": url, "error": str(st)})
                    break
                skipped.append({"label": label, "url": url, "reason": str(st)})
                continue
            txt, pages = pdf_to_text(data)
            del data
            scanned = is_scanned(txt, pages)
            if i == 0:
                if scanned:
                    tried.append({"source": src, "url": url, "error": "scanned (no text layer)",
                                  "pages": pages})
                    break
                main_ok = True
            if scanned:
                skipped.append({"label": label, "url": url, "reason": "scanned (no text layer)"})
                continue
            parts.append({"label": label, "url": url, "pages": pages, "text": txt})
        if main_ok:
            g = garbage_ratio(parts[0]["text"])
            cand = {"source": src, "parts": parts, "skipped": skipped, "garbage": round(g, 4)}
            if best is None or g < best["garbage"]:
                best = cand
            if g < 0.05:
                break  # good enough; otherwise also try the next source and keep the cleaner text
    res = {"key": key, "tried": tried, "compared": len(cands) > 1}
    if best:
        res.update(best)
    C.jsave(tp, res)


UUD_PARTS = [  # BPK file name -> (output key, title, date)
    ("UUD45.pdf", "uud-1945-naskah-asli", "Undang-Undang Dasar 1945 (naskah asli)", "1945-08-18"),
    ("UUD45_perubahan1.pdf", "uud-1945-perubahan-pertama", "Perubahan Pertama Undang-Undang Dasar Negara Republik Indonesia Tahun 1945", "1999-10-19"),
    ("UUD45_perubahan2.pdf", "uud-1945-perubahan-kedua", "Perubahan Kedua Undang-Undang Dasar Negara Republik Indonesia Tahun 1945", "2000-08-18"),
    ("UUD45_perubahan3.pdf", "uud-1945-perubahan-ketiga", "Perubahan Ketiga Undang-Undang Dasar Negara Republik Indonesia Tahun 1945", "2001-11-09"),
    ("UUD45_perubahan4.pdf", "uud-1945-perubahan-keempat", "Perubahan Keempat Undang-Undang Dasar Negara Republik Indonesia Tahun 1945", "2002-08-10"),
    ("UUD45_SatuNaskah.pdf", "uud-1945", "Undang-Undang Dasar Negara Republik Indonesia Tahun 1945 (dalam satu naskah)", "1945-08-18"),
]


def step_uud():
    import id_plan
    recs = id_plan.uud_records()
    files = {}
    for r in recs:
        for f in r.get("files") or []:
            name = urllib.parse.unquote(f["href"].rsplit("/", 1)[-1])
            files.setdefault(name, (C.BPK + f["href"], r))
    for name, key, title, date in UUD_PARTS:
        tp = os.path.join(C.RAW, "text", "uud", f"{key}.json")
        if os.path.exists(tp) or name not in files:
            continue
        url, r = files[name]
        data, st = download(url, 1.0)
        if data is None:
            print(f"UUD {name}: {st}", file=sys.stderr)
            continue
        txt, pages = pdf_to_text(data)
        C.jsave(tp, {"key": key, "title": title, "date": date, "source": "bpk",
                     "parts": [{"label": name, "url": url, "pages": pages, "text": txt}],
                     "bpk": {k: r.get(k) for k in ("url", "snapshot", "status", "bpk_id")}})
    print("uud done", flush=True)


def step_text(args):
    import id_plan
    os.makedirs(os.path.join(C.RAW, "tmp"), exist_ok=True)
    if "uud" in args.kinds.split(","):
        step_uud()
    plan = id_plan.build_plan()
    kinds = set(args.kinds.split(","))
    items = [it for it in plan if it["kind"] in kinds]
    os.makedirs(os.path.join(C.RAW, "tmp"), exist_ok=True)
    def done_ok(it):
        p = os.path.join(C.RAW, "text", it["kind"], f"{it['key']}.json")
        if not os.path.exists(p):
            return False
        if args.retry_failed:
            r = C.jload(p)
            if not r.get("parts") and any("scanned" not in t.get("error", "") for t in r.get("tried", [])):
                return False
            # poor OCR text and an untried alternative source
            if r.get("parts") and r.get("garbage", 1) >= 0.05 and len(candidates(it)) > 1 \
                    and len(r.get("tried", [])) + 1 < len(candidates(it)) and not r.get("compared"):
                return False
            # retry if a source that was not tried is now available
            if not r.get("parts") and len(r.get("tried", [])) < len(candidates(it)):
                return False
        return True
    todo = [it for it in items if not done_ok(it)]
    # items with a BPK PDF first (fast server); Setneg-only items afterwards
    todo.sort(key=lambda it: not (it.get("bpk") or {}).get("files"))
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(items)} items, {len(todo)} to process", flush=True)
    # two workers: Setneg- and BPK-sourced items interleave, so each host sees ~1-2 requests at once
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        def safe(it):
            try:
                process_item(it)
            except Exception as e:  # never let one item stop the run
                print(f"  ERROR {it['key']}: {e!r}", file=sys.stderr)
        for _ in ex.map(safe, todo):
            done += 1
            if done % 50 == 0:
                print(f"  text {done}/{len(todo)}", flush=True)
    print("text done", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["bpk-cdx", "bpk-meta", "bpk-follow", "setneg", "dpr", "text"])
    ap.add_argument("--kinds", default="uud,uu,uudrt,perppu,pp,perpres")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--extra-ids", default="")
    ap.add_argument("--retry-failed", action="store_true")
    a = ap.parse_args()
    {"bpk-cdx": step_bpk_cdx, "bpk-meta": step_bpk_meta, "bpk-follow": step_bpk_follow,
     "setneg": step_setneg, "dpr": step_dpr, "text": step_text}[a.step](a)


if __name__ == "__main__":
    main()
