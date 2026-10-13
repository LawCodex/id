# Indonesia — LawCodex

Legislation of the Republic of Indonesia as plain Markdown, in Bahasa Indonesia, one file per
instrument. Part of [LawCodex](https://github.com/LawCodex).

> **Texts are as enacted, not consolidated.** Indonesia publishes no official consolidated
> ("as amended") text of its statutes. Each file reproduces the official PDF of the instrument as
> enacted (the *salinan* published by the State Secretariat / JDIH), converted to text. Later
> amendments are **not** applied. Front matter lists the amending / repealing instruments
> known to the JDIH BPK database (`amended_by`, `repealed_by`, ...). The one exception is the
> Constitution, for which the MPR's official text "dalam satu naskah" (with all four amendments
> incorporated) is provided alongside the original text and the amendments.
>
> Many source PDFs, especially older ones, are scans with an OCR text layer of the publishing
> agency. Their text is reproduced as extracted; OCR errors (e.g. `2OO8` for `2008`, `l` for `1`)
> are **not** corrected. Nothing here is an official text; check the official PDF (`source` in
> the front matter) before relying on any provision.

## Contents

<!-- COUNTS -->
| Category | Directory | Files | of which in force | Known but missing (`missing.tsv`) |
|---|---|---|---|---|
| UUD 1945 (consolidated text, original, 4 amendments) | `uud-1945/` | 6 | 6 | - |
| Undang-Undang | `uu/` | 1922 | 1551 | 7 |
| Undang-Undang Darurat | `uu-darurat/` | 174 | 159 | 0 |
| Peraturan Pemerintah Pengganti Undang-Undang | `perppu/` | 164 | 148 | 8 |
| Peraturan Pemerintah | `pp/` | 5004 | 3345 | 4 |
| Peraturan Presiden | `perpres/` | 2527 | 1754 | 113 |
| **Total** | | **9797** | **6963** | **132** |
<!-- /COUNTS -->

## Structure

```
uud-1945/uud-1945.md                         # UUD NRI 1945 in one text (with the 1999-2002 amendments)
uud-1945/uud-1945-naskah-asli.md             # original 1945 text
uud-1945/uud-1945-perubahan-{pertama,...}.md # the four amendments (1999, 2000, 2001, 2002)
uu/<year>/uu-<n>-<year>-<slug>.md            # Undang-Undang (Acts of Parliament), 1945-
uu-darurat/<year>/uu-darurat-<n>-<year>-<slug>.md   # Undang-Undang Darurat (emergency acts, 1950-1951)
perppu/<year>/perppu-<n>-<year>-<slug>.md    # Peraturan Pemerintah Pengganti Undang-Undang
pp/<year>/pp-<n>-<year>-<slug>.md            # Peraturan Pemerintah (government regulations)
perpres/<year>/perpres-<n>-<year>-<slug>.md  # Peraturan Presiden (presidential regulations), 2005-
missing.tsv                                  # instruments known to the sources but without a usable text
```

`<year>` is the year of the instrument's number (`Nomor 13 Tahun 2003` -> `2003`), `<slug>` is
derived from the subject (`tentang ...`).

Each file has YAML front matter:

| key | meaning |
|---|---|
| `title` | e.g. `Undang-Undang Nomor 13 Tahun 2003 tentang Ketenagakerjaan` |
| `identifier` | short citation, e.g. `UU No. 13 Tahun 2003` |
| `type` | `constitution`, `act` (UU, UU Darurat, Perppu) or `regulation` (PP, Perpres) |
| `number`, `year` | official number and year |
| `date` | date of enactment (*tanggal penetapan*); `promulgated` = *tanggal pengundangan*; `in_force_from` = *tanggal berlaku* (as recorded by BPK) |
| `status` | `in_force`, `repealed` or `unknown` — see below; `status_basis` says where it comes from |
| `amended_by`, `repealed_by`, `partially_repealed_by`, `amends`, `repeals` | relations recorded by JDIH BPK |
| `gazette` | Lembaran Negara / Tambahan Lembaran Negara reference (BPK "Sumber") |
| `subject` | BPK subject classification |
| `source` | the PDF the text was extracted from |
| `source_page`, `bpk_page`, `setneg_page` | catalogue pages of the instrument |
| `bpk_metadata_archived` | Internet Archive copy of the BPK page the metadata was read from |
| `consolidated` | always `false` except for the UUD 1945 "satu naskah" text |

The H1 is the full title. The body follows the official document: title block, *Menimbang*,
*Mengingat*, *Memutuskan / Menetapkan*, then the hierarchy of the instrument mapped to headings —
`BUKU` (if any) > `BAB` > `Bagian` > `Paragraf` > `Pasal` (deepest heading, at most `######`) —
then the signature block, the official elucidation (`## PENJELASAN`, with `### I. UMUM`,
`### II. PASAL DEMI PASAL` and `#### Pasal n`) and annexes (`## LAMPIRAN`). In amending laws
the operative articles are `Pasal I`, `Pasal II`...; the amended provisions they quote
(`Pasal 5`, ...) are rendered in bold, not as headings. Running page headers ("PRESIDEN
REPUBLIK INDONESIA"), page numbers and page-foot catchwords are removed; lines are reflowed into
paragraphs; tabular passages are kept in fenced blocks with their original layout. Additional
PDF files attached to an instrument (separate *lampiran*, *penjelasan*, treaty texts) follow
under `## Berkas: <file name>`; attachments that are scans without text, larger than 15 MB,
beyond the 12th file, or (for Setneg-sourced texts) any attachment — the Setneg file server is slow
and drops large transfers — are linked at the end of the file instead.

## Status (in force / repealed)

`status` is derived, in this order, from

1. the JDIH BPK record of the instrument ("Status: Berlaku / Dicabut / Tidak Berlaku" and the
   "Dicabut dengan" list), as captured by the Internet Archive (date in `bpk_metadata_archived`);
2. any other BPK record saying it repeals ("Mencabut") the instrument;
3. JDIH Setneg's `status_hukum` (`berlaku`, `sebagian`, `dicabut`) and repeal links.

An instrument is `repealed` if any of these says it was repealed in full, `in_force` if a source
says it is in force, `unknown` otherwise. Partial repeals/amendments do not change `status`.
Since BPK pages are read from archived copies (2023-2026), a repeal enacted after the capture
date may be missing. Decisions of the Constitutional Court (Mahkamah Konstitusi) declaring
provisions void are not reflected.

## Sources

| Source | Used for |
|---|---|
| [JDIH BPK — Database Peraturan](https://peraturan.bpk.go.id) (Badan Pemeriksa Keuangan) | metadata (dates, status, relations, gazette, subject) and PDFs (`/Download/<id>/...`) |
| [JDIH Kementerian Sekretariat Negara](https://jdih.setneg.go.id) (State Secretariat, publisher of UU/PP/Perpres) | catalogue, legal status and PDFs, via the JSON API used by its own website (`/api/hukumproduk/...`) |
| [JDIH Sekretariat Jenderal DPR RI](https://jdih.dpr.go.id) | list of Undang-Undang per year (cross-check of completeness) |
| [Internet Archive Wayback Machine](https://web.archive.org) | archived copies of the JDIH BPK detail pages (see below) |

Notes on access (checked 2026-10-12, from a non-Indonesian network, identifying as
`LawCodex/1.0 (+https://github.com/LawCodex)`):

- **peraturan.bpk.go.id** serves its HTML pages (search, detail pages, sitemap) behind a
  Cloudflare JavaScript challenge. LawCodex does not attempt to pass bot challenges, so the
  metadata of each instrument was read from the Internet Archive's copies of the official BPK
  detail pages (≈9,250 pages; the archive URL is recorded in each file). The PDF download links
  (`/Download/...`) are not behind the challenge and were fetched directly from BPK.
  robots.txt allows both (it disallows only `/Admin/`, `/Identity/`, `/Account/`, `/Manage/`,
  `/health`, `/Error`; no Crawl-delay).
- **jdih.setneg.go.id**: robots.txt allows everything. Its catalogue is incomplete (e.g. ~900 of
  ~1,930 UU; few instruments before 1990 or from 2002-2004), so it is a secondary source.
- **jdih.dpr.go.id** pages are reachable, but the PDFs on `berkas.dpr.go.id` return
  *Access Denied* (Akamai) to this client; they were not used.
- **peraturan.go.id** (Ministry of Law) and **jdihn.go.id** did not respond (connection timeouts)
  and were not used.

Requests were made sequentially per worker (at most 3 concurrent), with a 1-second delay and
exponential back-off on errors.

## Not covered

- Instruments for which no source holds a PDF with a text layer — mostly scans of older laws
  without OCR (no OCR was performed) — are listed in [`missing.tsv`](missing.tsv) with links to
  their catalogue pages.
- Instruments not known to JDIH BPK as archived by the Internet Archive nor to JDIH Setneg.
- Ketetapan MPR, Keputusan Presiden, Instruksi Presiden, ministerial and regional regulations,
  court decisions.
- Images, signatures, coats of arms and maps in the PDFs (text only).

## Copyright / licence

Under Article 42 of Law No. 28 of 2014 on Copyright (*Undang-Undang Nomor 28 Tahun 2014 tentang
Hak Cipta*), there is no copyright in (a) the results of open sessions of state institutions,
(b) *peraturan perundang-undangan* (statutory instruments), (c) state speeches or speeches of
government officials, (d) court decisions, and (e) holy scriptures or religious symbols. The texts here are therefore in the public domain in
Indonesia. The JDIH network exists to disseminate these texts to the public (Perpres
No. 33 Tahun 2012 on JDIHN). The metadata compilations of BPK and Setneg are used for
reference; the conversion scripts in `scripts/` are released into the public domain.

## Regenerating

Requires Python 3 with the packages in `scripts/requirements.txt` and poppler-utils
(`pdftotext`, `pdfinfo`). Intermediate data go to `../_raw/id/` (override with `ID_RAW`).

```sh
cd scripts
python id_fetch.py bpk-cdx        # list archived BPK detail pages (Wayback CDX API)
python id_fetch.py bpk-meta       # fetch + parse them (≈9,250 pages)
python id_fetch.py bpk-follow     # archived pages of instruments referenced in relations
python id_fetch.py setneg         # JDIH Setneg catalogue (UU, Perppu, PP, Perpres)
python id_fetch.py dpr            # JDIH DPR list of UU (cross-check)
python id_fetch.py text           # download PDFs, extract text (PDFs are not kept)
python id_fetch.py text --retry-failed
python id_convert.py --kinds uud,uu,uudrt,perppu,pp,perpres
```

`id_plan.py` merges the three catalogues on (form, number, year). Text source preference: BPK
PDF, then Setneg; when the first text looks like poor OCR (more than 5% of tokens mixing letters
and digits), the other source is also tried and the cleaner text is kept.

Retrieved: 2026-10-12 / 2026-10-13 (`retrieved` in the front matter).
