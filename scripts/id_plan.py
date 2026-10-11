"""Merge BPK (Wayback), Setneg and DPR metadata into one list of instruments."""
import os
import re
from collections import defaultdict

import id_common as C


def load_bpk():
    mdir = os.path.join(C.RAW, "bpk", "meta")
    out = []
    if not os.path.isdir(mdir):
        return out
    for f in os.listdir(mdir):
        if f.endswith(".json"):
            r = C.jload(os.path.join(mdir, f))
            if r and not r.get("error") and r.get("kind"):
                out.append(r)
    return out


def load_setneg():
    sdir = os.path.join(C.RAW, "setneg")
    out = []
    for kind in ("uu", "perppu", "pp", "perpres"):
        lst = C.jload(os.path.join(sdir, f"list_{kind}.json")) or []
        for it in lst:
            d = C.jload(os.path.join(sdir, "detail", f"{it['idperaturan']}.json")) or {}
            row = (d.get("row") or [{}])[0]
            out.append({
                "id": it["idperaturan"], "kind": kind, "number": C.norm_num(it["no_peraturan"]),
                "year": str(it["tahun"]).strip(), "tentang": (it.get("tentang") or "").strip(),
                "date_enacted": C.parse_date(it.get("tgl_di")),
                "date_promulgated": C.parse_date(it.get("diundangkan")),
                "status_hukum": it.get("status_hukum"),
                "dicabut": row.get("dicabut") or "", "diubah": row.get("diubah") or "",
                "mencabut": row.get("mencabut") or "",
                "ln": row.get("ln"), "tln": row.get("tln"),
                "files": d.get("file") or ([{"realName": it["files"]}] if it.get("files") else []),
                "url": f"{C.SETNEG}/detailperaturan?jns={it['jns']}&no={it['no_peraturan']}&thn={it['tahun']}",
            })
    return out


def load_dpr():
    return C.jload(os.path.join(C.RAW, "dpr_list.json")) or []


def _snapts(r):
    m = re.search(r"/web/(\d+)/", r.get("snapshot") or "")
    return m.group(1) if m else ""


def build_plan():
    bpk = load_bpk()
    setneg = load_setneg()
    dpr = load_dpr()

    # BPK repeal relations: X "Dicabut dengan" Y, or Y "Mencabut" X
    repealed_by = defaultdict(set)
    for r in bpk:
        for lab, lst in (r.get("relations") or {}).items():
            l = lab.lower()
            if "sebagian" in l:
                continue
            if l.startswith("dicabut dengan"):
                for x in lst:
                    repealed_by[r["bpk_id"]].add(x["label"])
            elif l.startswith("mencabut"):
                for x in lst:
                    repealed_by[x["id"]].add(f"{C.KIND_SHORT.get(r['kind'], r['kind'])} No. {r['number']} Tahun {r['year']}")

    items = {}

    def get(kind, num, year):
        key = f"{kind}-{num.lower()}-{year}"
        return items.setdefault(key, {"key": key, "kind": kind, "number": num, "year": year})

    by_key_bpk = defaultdict(list)
    for r in bpk:
        if r["kind"] == "uud":
            continue
        if not r["number"] or not re.fullmatch(r"\d{4}", r["year"] or ""):
            continue
        by_key_bpk[(r["kind"], r["number"], r["year"])].append(r)
    for (kind, num, year), lst in by_key_bpk.items():
        # prefer the entry with files, then most recent snapshot
        lst.sort(key=lambda r: (bool(r.get("files")), _snapts(r)), reverse=True)
        it = get(kind, num, year)
        it["bpk"] = lst[0]
        it["bpk_alt"] = [r["bpk_id"] for r in lst[1:]]
    for s in setneg:
        if not s["number"] or not re.fullmatch(r"\d{4}", s["year"]):
            continue
        it = get(s["kind"], s["number"], s["year"])
        if "setneg" not in it or (s["files"] and not it["setneg"]["files"]):
            it["setneg"] = s
    for d in dpr:
        if not d.get("number"):
            continue
        it = get(d["kind"], d["number"], d["year"])
        it.setdefault("dpr", d)

    for it in items.values():
        b, s, d = it.get("bpk"), it.get("setneg"), it.get("dpr")
        tentang = (b and b.get("tentang")) or (s and s.get("tentang").title()) or ""
        if not tentang and d:
            m = re.search(r"\bTENTANG\s+(.*)$", d["title"], re.I)
            tentang = m.group(1).strip().capitalize() if m else ""
        it["tentang"] = re.sub(r"\s+", " ", tentang).strip()
        it["date"] = ((b and (b.get("date_enacted") or b.get("date_promulgated")))
                      or (s and (s.get("date_enacted") or s.get("date_promulgated"))))
        # status
        st, why = "unknown", []
        if b and b.get("status"):
            bs = b["status"].lower()
            if "dicabut" in bs or "tidak berlaku" in bs:
                st = "repealed"
            elif "berlaku" in bs:
                st = "in_force"
            why.append(f"BPK: {b['status']}")
        if b and repealed_by.get(b["bpk_id"]):
            st = "repealed"
            why.append("BPK relation: dicabut dengan " + "; ".join(sorted(repealed_by[b["bpk_id"]])))
        if s and s.get("status_hukum"):
            sh = s["status_hukum"].lower()
            why.append(f"Setneg: {sh}")
            if sh == "dicabut" or s.get("dicabut"):
                st = "repealed"
            elif st == "unknown" and sh in ("berlaku", "sebagian"):
                st = "in_force"
        it["status"] = st
        it["status_basis"] = why
    return sorted(items.values(), key=lambda x: (x["kind"], int(x["year"]),
                                                 int(re.match(r"\d*", x["number"]).group(0) or 0),
                                                 x["number"]))


def uud_records():
    return [r for r in load_bpk() if r["kind"] == "uud"]


if __name__ == "__main__":
    from collections import Counter
    p = build_plan()
    print(Counter(i["kind"] for i in p))
    print(Counter((i["kind"], "bpk" in i, "setneg" in i, "dpr" in i) for i in p))
    print(Counter((i["kind"], i["status"]) for i in p))
