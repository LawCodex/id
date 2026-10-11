#!/usr/bin/env python3
"""Convert the cached texts (_raw/id/text/) into Markdown files in the repository.

The texts are pdftotext -layout extractions of the official as-enacted PDFs (Setneg or BPK).
This script removes page furniture (running "PRESIDEN / REPUBLIK INDONESIA" headers, page
numbers, catchwords at the foot of each page, website watermarks), reflows the lines into
paragraphs and maps the structure of Indonesian legislation to Markdown headings:
BUKU > BAB > Bagian > Paragraf > Pasal, then PENJELASAN (I. UMUM / II. PASAL DEMI PASAL) and
LAMPIRAN. No wording is changed.

Usage: python id_convert.py [--kinds uu,perppu,...] [--retrieved YYYY-MM-DD]
"""
import argparse
import datetime
import os
import re
import sys

import id_common as C
import id_plan

ROMAN = r"[IVXLC]+"
RE_BUKU = re.compile(r"^BUKU\s+(KE[A-Z]+|[IVXLC]+|SATU|DUA|TIGA|EMPAT|LIMA)\b\s*(.*)$")
RE_BAB = re.compile(r"^BAB\s+([IVXLC]+[A-Z]?|[0-9]+[A-Z]?)\s*(?:[-–—:.]\s*)?(.*)$")
RE_BAGIAN = re.compile(r"^Bagian\s+(Ke[a-z]+(?:\s+[A-Z][a-z]+)?|Pertama|[A-Z][a-z]+)\s*$")
RE_PARAGRAF = re.compile(r"^Paragraf\s+(\d+[A-Z]?|Ke[a-z]+)\s*$", re.I)
RE_PASAL = re.compile(r"^Pasa[l1]\s+(\d+[A-Z]?|[IVXLC]+)\s*$")
RE_PAGENUM = re.compile(r"^[-–—]?\s*\d{1,4}\s*[-–—]?$")
RE_WEB = re.compile(r"^(www\.|https?://)\S+$|^\S+\.go\.id\s*$", re.I)
RE_CATCH = re.compile(r"(…|\.\s?\.\s?\.)\s*$")
RE_ENUM = re.compile(r"^(\(?[0-9]{1,3}[a-z]?[.)]|\([a-z0-9]{1,4}\)|[a-z]{1,2}[.)]|[IVX]+\.)\s")
RE_LEAD = re.compile(r"^(Menimbang|Mengingat|Memperhatikan|Menetapkan|MEMUTUSKAN|Memutuskan|"
                     r"Dengan Persetujuan|Dengan persetujuan|Disahkan di|Diundangkan di|Agar setiap)\b")


def is_upper_line(s):
    letters = re.sub(r"[^A-Za-z]", "", s)
    return len(letters) >= 3 and letters.isupper()


def clean_lines(text):
    """Return list of (indent, stripped_line) with page furniture removed; '' marks blank."""
    out = []
    pages = text.split("\f")
    for pg in pages:
        lines = pg.split("\n")
        # catchword: last non-blank line of the page ending in "..." / "…"
        nb = [i for i, l in enumerate(lines) if l.strip()]
        if nb:
            last = lines[nb[-1]].strip()
            if RE_CATCH.search(last) and len(last) <= 80:
                lines[nb[-1]] = ""
        i = 0
        while i < len(lines):
            raw = lines[i].rstrip()
            s = raw.strip()
            ind = len(raw) - len(raw.lstrip())
            if s == "PRESIDEN":
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and lines[j].strip() == "REPUBLIK INDONESIA":
                    i = j + 1
                    continue
            if (RE_PAGENUM.match(s) and (s.startswith("-") or ind >= 20 or len(s) <= 4)
                    and not re.match(r"^\d+\.$", s)):
                i += 1
                continue
            if RE_WEB.match(s) or s in ("SALINAN", "Salinan"):
                i += 1
                continue
            if RE_CATCH.search(s) and len(s) <= 60 and ind >= 20:
                i += 1
                continue
            out.append((ind, s))
            i += 1
        out.append((0, ""))
    return out


def is_table_line(s):
    return len(re.findall(r"\S {6,}\S", s)) >= 2


def join(prev, s):
    if prev.endswith("-") and not prev.endswith(" -"):
        return prev + s
    return prev + " " + s


def md_escape(s):
    if s.startswith(("#", ">", "+ ", "* ", "- ", "|", "=")):
        return "\\" + s
    return s


def convert_body(text):
    lines = clean_lines(text)
    # amending laws: "Pasal I", "Pasal II" are the operative articles; arabic "Pasal N" inside are
    # quoted provisions of the amended law -> do not make them headings
    roman_pasal = sum(1 for _, s in lines if re.match(r"^Pasal\s+(I|II)\s*$", s)) >= 1
    has_buku = any(RE_BUKU.match(s) for _, s in lines)
    lvl = {}
    n = 2
    if has_buku:
        lvl["buku"] = n
        n += 1
    lvl["bab"] = n
    lvl["bagian"] = n + 1
    lvl["paragraf"] = n + 2
    lvl["pasal"] = min(n + 3, 6)

    blocks = []  # list of strings (markdown blocks)
    para = None
    mode = "body"
    k = 0
    N = len(lines)

    def flush():
        nonlocal para
        if para:
            blocks.append(md_escape(re.sub(r"\s{2,}", " ", para)))
        para = None

    def h(level, txt):
        flush()
        blocks.append("#" * min(level, 6) + " " + txt)

    def title_after(k, max_lines, upper):
        """Collect heading title lines following position k."""
        parts = []
        j = k
        while j < N and len(parts) < max_lines:
            ind, s = lines[j]
            if not s:
                if parts:
                    break
                j += 1
                continue
            if (RE_PASAL.match(s) or RE_BAB.match(s) or RE_BAGIAN.match(s) or RE_PARAGRAF.match(s)
                    or RE_ENUM.match(s) or len(s) > 120):
                break
            if upper and not is_upper_line(s):
                break
            if not upper and parts and s[:1].islower() is False and not parts[-1].endswith(("dan", ",")):
                # a new capitalised line after a complete title starts the body
                if len(" ".join(parts)) > 15:
                    break
            parts.append(s)
            j += 1
            if not upper and s.endswith((".", ";", ":")):
                break
        return " ".join(parts), j

    prev_end = True  # previous paragraph ended (for Pasal heading detection)
    while k < N:
        ind, s = lines[k]
        if not s:
            # page breaks / blank lines inside a sentence: continue if the next line is lowercase
            j = k + 1
            while j < N and not lines[j][1]:
                j += 1
            nxt = lines[j][1] if j < N else ""
            if not (para and nxt[:1].islower() and not RE_ENUM.match(nxt)
                    and not para.endswith((".", ";", ":"))):
                flush()
                prev_end = True
            k = j
            continue
        # tables: >=3 consecutive columnar lines -> keep layout in a fenced block
        if is_table_line(s):
            j = k
            raw = []
            while j < N and lines[j][1] and is_table_line(lines[j][1]):
                raw.append(lines[j])
                j += 1
            if len(raw) >= 3:
                flush()
                base = min(i for i, _ in raw)
                blocks.append("```\n" + "\n".join(" " * (i - base) + t for i, t in raw) + "\n```")
                k = j
                prev_end = True
                continue
        if s == "PENJELASAN" or re.match(r"^PENJELASAN\s+ATAS\b", s):
            mode = "penjelasan"
            h(2, s)
            k += 1
            continue
        if re.match(r"^LAMPIRAN\b", s) and (para is None) and mode != "lampiran" and len(s) < 120:
            mode = "lampiran"
            h(2, s)
            k += 1
            continue
        if mode == "body":
            m = RE_BUKU.match(s)
            if m and prev_end:
                t, k2 = (m.group(2), k + 1) if m.group(2) else title_after(k + 1, 4, True)
                h(lvl["buku"], f"BUKU {m.group(1)}" + (f" — {t}" if t else ""))
                k = k2
                continue
            m = RE_BAB.match(s)
            if m and prev_end and (not m.group(2) or is_upper_line(m.group(2))):
                t, k2 = (m.group(2), k + 1) if m.group(2) else title_after(k + 1, 4, True)
                h(lvl["bab"], f"BAB {m.group(1)}" + (f" — {t}" if t else ""))
                k = k2
                continue
            if (RE_BAGIAN.match(s) or RE_PARAGRAF.match(s)) and prev_end:
                t, k2 = title_after(k + 1, 3, False)
                h(lvl["bagian" if s.lower().startswith("bagian") else "paragraf"],
                  s + (f" — {t}" if t else ""))
                k = k2
                continue
            m = RE_PASAL.match(s)
            if m and prev_end:
                is_roman = re.fullmatch(ROMAN, m.group(1)) is not None
                if (not roman_pasal) or is_roman:
                    h(lvl["pasal"], s)
                    k += 1
                    continue
                flush()
                blocks.append(f"**{s}**")
                k += 1
                continue
        elif mode == "penjelasan":
            if re.match(r"^(I|II|III)\.\s+[A-Z][A-Z ]+$", s):
                h(3, s)
                k += 1
                continue
            if RE_PASAL.match(s) and prev_end:
                h(4, s)
                k += 1
                continue
        if re.match(r"^(Ayat|Huruf|Angka|Butir)\s+(\(\w+\)|\w+)$", s):
            flush()
            blocks.append(s)
            prev_end = True
            k += 1
            continue
        # ordinary text
        upper = is_upper_line(s) and len(s) < 100
        starts_new = (para is None or RE_ENUM.match(s) or RE_LEAD.match(s) or upper
                      or is_upper_line(para.split("  ")[-1][:100]) and len(para) < 100
                      or para.endswith((".", ";", ":")) and ind <= 25 and s[:1].isupper())
        if starts_new:
            flush()
            para = s
        else:
            para = join(para, s)
        prev_end = s.endswith((".", ";", ":")) or upper
        k += 1
    flush()
    # collapse duplicate blank output
    return "\n\n".join(b for b in blocks if b.strip())


def yaml_str(s):
    s = (s or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def file_name(it):
    prefix = {"uu": "uu", "uudrt": "uu-darurat", "perppu": "perppu", "pp": "pp", "perpres": "perpres"}[it["kind"]]
    slug = C.slugify(it["tentang"], 70)
    return f"{prefix}-{it['number'].lower()}-{it['year']}-{slug}.md"


def full_title(it):
    t = f"{C.KIND_LABEL[it['kind']]} Nomor {it['number']} Tahun {it['year']}"
    if it["tentang"]:
        t += f" tentang {it['tentang']}"
    return t


def rel_list(b, prefix):
    out = []
    for lab, lst in (b.get("relations") or {}).items():
        if lab.lower().startswith(prefix):
            out += [x["label"] for x in lst]
    return out


def render(it, tx, retrieved):
    b, s = it.get("bpk") or {}, it.get("setneg") or {}
    fm = ["---", f"title: {yaml_str(full_title(it))}",
          f"identifier: {yaml_str(C.KIND_SHORT[it['kind']] + ' No. ' + it['number'] + ' Tahun ' + it['year'])}",
          f"type: {C.KIND_TYPE[it['kind']]}", "jurisdiction: id", "language: id",
          f"number: {yaml_str(it['number'])}", f"year: {it['year']}"]
    if it.get("date"):
        fm.append(f"date: {it['date']}")
    if b.get("date_promulgated"):
        fm.append(f"promulgated: {b['date_promulgated']}")
    if b.get("date_in_force"):
        fm.append(f"in_force_from: {b['date_in_force']}")
    fm.append(f"status: {it['status']}")
    if it.get("status_basis"):
        fm.append(f"status_basis: {yaml_str('; '.join(it['status_basis']))}")
    for key, pre in (("amended_by", "diubah dengan"), ("repealed_by", "dicabut dengan"),
                     ("partially_repealed_by", "dicabut sebagian dengan"), ("amends", "mengubah"),
                     ("repeals", "mencabut")):
        lst = rel_list(b, pre)
        if key == "repeals":
            lst = [x for x in lst if x not in rel_list(b, "mencabut sebagian")]
        if lst:
            fm.append(f"{key}:")
            fm += [f"  - {yaml_str(x)}" for x in lst]
    if b.get("sumber"):
        fm.append(f"gazette: {yaml_str(b['sumber'])}")
    if b.get("subjek"):
        fm.append(f"subject: {yaml_str(b['subjek'])}")
    part0 = tx["parts"][0]
    fm.append(f"source: {yaml_str(part0['url'])}")
    if tx["source"] == "setneg":
        fm.append(f"source_page: {yaml_str(s['url'])}")
    else:
        fm.append(f"source_page: {yaml_str(b['url'])}")
    if b:
        fm.append(f"bpk_page: {yaml_str(b['url'])}")
        if b.get("snapshot"):
            fm.append(f"bpk_metadata_archived: {yaml_str(b['snapshot'])}")
    if s and tx["source"] != "setneg":
        fm.append(f"setneg_page: {yaml_str(s['url'])}")
    fm.append("consolidated: false")
    fm.append(f"retrieved: {retrieved}")
    fm.append("---")
    body = [f"# {full_title(it)}"]
    for i, p in enumerate(tx["parts"]):
        if i > 0:
            body.append(f"## Berkas: {p['label']}")
        body.append(convert_body(p["text"]))
    for sk in tx.get("skipped") or []:
        body.append(f"> Berkas tidak disertakan ({sk['reason']}): [{sk['label']}]({sk['url']})")
    return "\n".join(fm) + "\n\n" + "\n\n".join(body).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kinds", default="uu,uudrt,perppu,pp,perpres")
    ap.add_argument("--retrieved", default=datetime.date.today().isoformat())
    a = ap.parse_args()
    kinds = a.kinds.split(",")
    plan = id_plan.build_plan()
    missing = []
    written = 0
    for it in plan:
        if it["kind"] not in kinds:
            continue
        tp = os.path.join(C.RAW, "text", it["kind"], f"{it['key']}.json")
        tx = C.jload(tp)
        outdir = os.path.join(C.REPO, C.KIND_DIR[it["kind"]], it["year"])
        if not tx or not tx.get("parts"):
            reason = "not fetched" if tx is None else (
                "; ".join(f"{t['source']}: {t['error']}" for t in tx.get("tried", [])) or
                "no PDF listed by any source")
            missing.append((it, reason))
            continue
        os.makedirs(outdir, exist_ok=True)
        path = os.path.join(outdir, file_name(it))
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(render(it, tx, a.retrieved))
        written += 1
    # missing list (all kinds handled in this run)
    mp = os.path.join(C.REPO, "missing.tsv")
    old = []
    if os.path.exists(mp):
        with open(mp, encoding="utf-8") as f:
            old = [l for l in f.read().splitlines()[1:] if l.split("\t")[0] not in kinds]
    rows = old + ["\t".join([it["kind"], it["number"], it["year"], it["tentang"].replace("\t", " "),
                             it["status"], reason,
                             (it.get("bpk") or {}).get("url", ""), (it.get("setneg") or {}).get("url", ""),
                             (it.get("dpr") or {}).get("url", "")]) for it, reason in missing]
    with open(mp, "w", encoding="utf-8", newline="\n") as f:
        f.write("kind\tnumber\tyear\ttentang\tstatus\treason\tbpk_page\tsetneg_page\tdpr_page\n")
        f.write("\n".join(sorted(rows, key=lambda r: (r.split("\t")[0], r.split("\t")[2]))) + "\n")
    print(f"written {written}, missing {len(missing)}")


if __name__ == "__main__":
    main()
