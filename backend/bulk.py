"""
Fair Value — bulk EDGAR transport (Phase 2, stdlib only).

The SEC publishes its ENTIRE XBRL + filing-metadata corpus as two nightly zips.
One conditional download apiece replaces ~520 throttled per-ticker API calls
(the 2026-07-07 ingest took ~5h; the bulk path re-reads the same JSON locally):

  companyfacts.zip  ~1.4GB · ~20k XBRL filers  · members CIK##########.json,
                    byte-identical shape to /api/xbrl/companyfacts/
  submissions.zip   ~1.6GB · ~976k filer files · filing metadata: SIC code,
                    tickers, exchanges, former names (incl. DELISTED filers —
                    the ticker→CIK map company_tickers.json no longer carries)

Usage:
  python bulk.py download          # conditional refresh (If-Modified-Since + resume)
  python bulk.py scan              # rebuild `filers` from submissions.zip (~5-10 min)
  python bulk.py probe AAPL        # trace one ticker through the bulk path

Module API (used by ingest_v1 / pit / value):
  facts_json(cik)        -> parsed companyfacts dict, or None if not in the zip
  submission_header(cik) -> {"cik","name","sic","sicDescription","tickers",
                             "exchanges","formerNames"...} or None
  ticker_cik_map(con)    -> {ticker: cik10} — filers table over company_tickers.json
  zips_present()         -> True when both zips exist (callers fall back to the API)
"""
import json, os, sqlite3, sys, time, urllib.error, urllib.request, zipfile
from pathlib import Path
from common import DB_PATH, SEC_UA, http_json

BULK_DIR = DB_PATH.parent / "bulk"
FACTS_ZIP = BULK_DIR / "companyfacts.zip"
SUBS_ZIP = BULK_DIR / "submissions.zip"
URLS = {
    FACTS_ZIP: "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip",
    SUBS_ZIP: "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip",
}

_zips = {}                                                # path -> open ZipFile (lazy)


def _zip(path):
    z = _zips.get(path)
    if z is None:
        z = _zips[path] = zipfile.ZipFile(path)
    return z


def zips_present():
    return FACTS_ZIP.exists() and SUBS_ZIP.exists()


def close():
    for z in _zips.values():
        z.close()
    _zips.clear()


def _member(path, name):
    """Read one member's bytes, or None when absent (new registrant since the nightly)."""
    try:
        return _zip(path).read(name)
    except KeyError:
        return None


def facts_json(cik):
    """companyfacts for one CIK from the local zip — same shape as the SEC API."""
    raw = _member(FACTS_ZIP, f"CIK{cik}.json")
    return json.loads(raw) if raw else None


# The submissions header (cik/name/sic/tickers/exchanges/formerNames) sits BEFORE the
# huge "filings" object in every machine-generated member. Reading just that prefix
# turns a multi-MB parse into a ~2KB one — the difference between a 5-minute and a
# multi-hour filers scan. Inside a JSON string the raw sequence "filings": cannot
# occur (quotes would be \"-escaped), so the cut point is unambiguous.
_FILINGS_KEY = b'"filings"'


def _header_from_stream(fh, cap=262144):
    buf = b""
    while len(buf) < cap:
        chunk = fh.read(8192)
        if not chunk:
            break
        buf += chunk
        i = buf.find(_FILINGS_KEY)
        if i >= 0:
            head = buf[:i].rstrip()
            if head.endswith(b","):
                head = head[:-1]
            try:
                return json.loads(head + b"}")
            except json.JSONDecodeError:
                return None
    return None


def submission_header(cik):
    """Filing metadata (SIC, tickers, exchanges, former names) for one CIK."""
    try:
        with _zip(SUBS_ZIP).open(f"CIK{cik}.json") as fh:
            return _header_from_stream(fh)
    except KeyError:
        return None


def filer_form(facts_doc):
    """Dominant annual form from a companyfacts doc: '10-K' (domestic) beats '20-F'/'40-F'
       (foreign private issuer / ADR) when both appear; None when the doc carries neither.
       Scans a handful of tags — form mix is a filer-level property, not per-fact."""
    if not facts_doc:
        return None
    forms = set()
    for ns in facts_doc.get("facts", {}).values():
        for tag in list(ns.values())[:8]:
            for arr in tag.get("units", {}).values():
                forms.update(u.get("form", "") for u in arr[:25])
        break                                             # first namespace (dei) suffices
    if any(f.startswith("10-K") for f in forms):
        return "10-K"
    if any(f.startswith(("20-F", "40-F")) for f in forms):
        return "20-F"
    return None


# ---------------- download ----------------
def _download_one(path, url):
    """Conditional GET with atomic replace. A good local zip is never clobbered by a
       failed transfer: the stream lands in .part and renames only on completion."""
    headers = dict(SEC_UA)
    if path.exists():
        headers["If-Modified-Since"] = time.strftime(
            "%a, %d %b %Y %H:%M:%S GMT", time.gmtime(path.stat().st_mtime))
    part = path.with_suffix(".part")
    req = urllib.request.Request(url, headers=headers)
    t0 = time.time()
    try:
        r = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code == 304:
            print(f"  {path.name}: unchanged upstream (kept local copy)")
            return False
        raise
    total = int(r.headers.get("Content-Length") or 0)
    done = 0
    with open(part, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total and done % (200 << 20) < (1 << 20):
                print(f"  {path.name}: {done/1e9:.1f}/{total/1e9:.1f} GB "
                      f"({done/max(time.time()-t0,1e-9)/1e6:.0f} MB/s)")
    if total and done != total:
        part.unlink(missing_ok=True)
        raise IOError(f"{path.name}: short read {done}/{total}")
    if path in _zips:                                     # release the old handle first
        _zips.pop(path).close()
    os.replace(part, path)
    lm = r.headers.get("Last-Modified")
    if lm:
        try:
            ts = time.mktime(time.strptime(lm, "%a, %d %b %Y %H:%M:%S GMT")) - time.timezone
            os.utime(path, (ts, ts))                      # mtime = upstream build time
        except Exception:
            pass
    print(f"  {path.name}: {done/1e9:.2f} GB in {time.time()-t0:.0f}s")
    return True


def download():
    BULK_DIR.mkdir(parents=True, exist_ok=True)
    changed = False
    for path, url in URLS.items():
        changed |= _download_one(path, url)
    # ticker->CIK for CURRENT registrants — tiny, refresh alongside the zips
    try:
        raw = http_json("https://www.sec.gov/files/company_tickers.json", SEC_UA)
        (DB_PATH.parent / "company_tickers.json").write_text(json.dumps(raw))
        print(f"  company_tickers.json: {len(raw)} registrants refreshed")
    except Exception as e:
        print(f"  company_tickers.json refresh failed ({e!r}) — kept cached copy")
    return changed


# ---------------- filers scan ----------------
# The header-prefix trick reads ~15k filers/s single-threaded (a full ~976k-file pass
# is ~1 min), so no thread pool — a shared ZipFile isn't thread-safe and the parse is
# I/O-cheap once the central directory is in memory.
import re as _re
_PAREN = _re.compile(r"\([^)]*\)")                        # "(Class A)", "(New)" …


def _norm_name(s):
    """Normalize a company name for delisted ticker→CIK matching (drop corp suffixes,
       class tags and punctuation so 'SVB Financial Group' ↔ 'SVB FINANCIAL GROUP /DE/'
       and 'Kohl's' ↔ 'KOHLS Corp' align)."""
    s = _PAREN.sub(" ", (s or "").upper())
    for junk in (" /DE/", " /MD/", " /DE", " \\DE\\", "/", "\\", "'", "’", "."):
        s = s.replace(junk, " " if junk in ("/", "\\") else "")
    out = []
    toks = s.replace(",", " ").replace("-", " ").split()
    for i, tok in enumerate(toks):
        if tok in ("INC", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LLC", "LP",
                   "PLC", "THE", "GROUP", "HOLDINGS", "HOLDING", "COM", "NEW", "&"):
            continue
        if tok in ("CLASS", "CL") and i + 1 < len(toks) and len(toks[i + 1]) == 1:
            continue                                       # 'CLASS A' / 'CL A' share-class tag
        if tok in ("A", "B", "C") and i > 0 and toks[i - 1] in ("CLASS", "CL"):
            continue
        out.append(tok)
    return " ".join(out)


def scan_filers(con=None):
    """submissions.zip -> `filers` table, one row per registrant that has OR HAD a
       ticker. Current registrants keep `tickers`; the SEC BLANKS that field when a
       company deregisters (SVB, First Republic read tickers:[]), so delisted names
       are recoverable only by NAME — we store the normalized current+former names
       so ticker_cik_map() can fall back to a name match for the backtest's dead
       members. SIC code is captured here for the warranted subsector defaults."""
    con = con or sqlite3.connect(DB_PATH)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS filers(
        cik TEXT PRIMARY KEY, name TEXT, sic TEXT, sic_desc TEXT,
        tickers TEXT, exchanges TEXT, former_names TEXT, norm_names TEXT);
    CREATE INDEX IF NOT EXISTS filers_tk ON filers(tickers);
    CREATE TABLE IF NOT EXISTS bulk_meta(key TEXT PRIMARY KEY, value TEXT);
    """)
    names = [n for n in _zip(SUBS_ZIP).namelist()
             if n.endswith(".json") and "-submissions-" not in n]
    print(f"Scanning {len(names):,} submission files (single pass)…")
    t0, rows, kept = time.time(), [], 0
    z = _zip(SUBS_ZIP)
    for i, n in enumerate(names, 1):
        try:
            with z.open(n) as fh:
                h = _header_from_stream(fh)
        except Exception:
            continue
        if not h:
            continue
        tickers = [t for t in (h.get("tickers") or []) if t]
        formers = [f.get("name", "") for f in (h.get("formerNames") or [])]
        # keep every filer that is or was exchange-listed: has a ticker now, or once
        # had a name we might match a delisted member against. Skip the long tail of
        # never-listed filers (funds, individuals) to keep the table lean.
        if not tickers and not h.get("sic"):
            continue
        norm = sorted({_norm_name(x) for x in ([h.get("name")] + formers) if x})
        exch = [e for e in (h.get("exchanges") or []) if e]
        rows.append((str(h.get("cik", n[3:13])).zfill(10), h.get("name"),
                     str(h.get("sic") or ""), h.get("sicDescription") or "",
                     ",".join(tickers), ",".join(exch),
                     " | ".join(formers), " | ".join(norm)))
        kept += 1
        if i % 200000 == 0:
            print(f"  {i:,}/{len(names):,} — {kept:,} kept ({time.time()-t0:.0f}s)")
    con.execute("DELETE FROM filers")
    con.executemany("INSERT OR REPLACE INTO filers VALUES (?,?,?,?,?,?,?,?)", rows)
    con.execute("INSERT OR REPLACE INTO bulk_meta VALUES ('filers_scanned_zip_mtime', ?)",
                (str(int(SUBS_ZIP.stat().st_mtime)),))
    con.execute("INSERT OR REPLACE INTO bulk_meta VALUES ('filers_scanned_at', ?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"),))
    con.commit()
    print(f"filers: {len(rows):,} rows in {time.time()-t0:.0f}s → {DB_PATH.name}")
    return len(rows)


def ticker_cik_map(con=None):
    """{ticker -> 10-digit CIK} for CURRENT registrants: the filers scan's live
       `tickers` layered under company_tickers.json (authoritative for collisions).
       Delisted names have no current ticker — resolve those via resolve_delisted()."""
    con = con or sqlite3.connect(DB_PATH)
    out = {}
    try:
        for cik, tickers in con.execute(
                "SELECT cik, tickers FROM filers WHERE tickers <> ''"):
            for t in tickers.split(","):
                out.setdefault(t.upper(), cik)
    except sqlite3.OperationalError:
        pass                                              # no scan yet — current-only map
    cache = DB_PATH.parent / "company_tickers.json"
    if cache.exists():
        raw = json.loads(cache.read_text())
        for v in raw.values():
            out[v["ticker"].upper()] = str(v["cik_str"]).zfill(10)
    return out


def resolve_delisted(con, ticker, name):
    """Best-effort CIK for a DELISTED ticker via normalized name match against the
       filers table (current + former names, from the SEC's own formerNames history).
       `name` comes from the caller (membership walk / Wikipedia) — the dead ticker is
       gone from every SEC ticker field. Two-tier to stay safe AND recover more:
         1. EXACT normalized match (one of a filer's names == key). Unique → accept.
         2. else UNIQUE substring match. Ambiguity at either tier → None (never guess)."""
    key = _norm_name(name)
    if not key:
        return None
    exact = [r[0] for r in con.execute(
        "SELECT cik FROM filers WHERE norm_names = ? OR norm_names LIKE ? "
        "OR norm_names LIKE ? OR norm_names LIKE ?",
        (key, f"{key} | %", f"% | {key}", f"% | {key} | %"))]
    if len(set(exact)) == 1:
        return exact[0]
    if exact:
        return None                                       # exact but ambiguous → don't guess
    sub = list({r[0] for r in con.execute(
        "SELECT cik FROM filers WHERE norm_names LIKE ?", (f"%{key}%",))})
    return sub[0] if len(sub) == 1 else None


def cik_name_matches(con, cik, name):
    """True iff `name` plausibly IS this filer — the reassigned-ticker guard. A delisted
       member's ticker may now belong to a namesake (Sprint's S→SentinelOne,
       Pepco's POM→POMDoctor); trusting the current ticker map would inject the wrong
       company's fundamentals. Match = the member's spaceless normalized name is a
       substring of any of the filer's own (current/former) spaceless names — accepts
       'SiriusXM'↔'SIRIUS XM' and 'VF'↔'V F' but rejects PEPCOHOLDINGS⊄POMDOCTOR.
       On no match the caller drops to no_cik (honest gap ≫ silent wrong data)."""
    key = _norm_name(name).replace(" ", "")
    if len(key) < 2:
        return False
    row = con.execute("SELECT norm_names FROM filers WHERE cik=?", (cik,)).fetchone()
    if not row:
        return False
    for p in (row[0] or "").split("|"):
        f = p.replace(" ", "")
        if f and key in f:
            return True
    return False


# ---------------- CLI ----------------
def _probe(ticker):
    con = sqlite3.connect(DB_PATH)
    cik = ticker_cik_map(con).get(ticker.upper())
    print(f"{ticker}: CIK {cik or 'NOT FOUND'}")
    if not cik:
        return
    h = submission_header(cik)
    if h:
        print(f"  submissions: {h.get('name')} · SIC {h.get('sic')} {h.get('sicDescription')}"
              f" · tickers {h.get('tickers')} · exchanges {h.get('exchanges')}")
    else:
        print("  submissions: MISSING from zip")
    f = facts_json(cik)
    if f:
        ns = list(f.get("facts", {}).keys())
        ng = len(f.get("facts", {}).get("us-gaap", {}))
        print(f"  companyfacts: {f.get('entityName')} · namespaces {ns} · {ng} us-gaap tags")
    else:
        print("  companyfacts: MISSING from zip")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "download"
    if cmd == "download":
        download()
    elif cmd == "scan":
        scan_filers()
    elif cmd == "probe" and len(sys.argv) > 2:
        _probe(sys.argv[2])
    else:
        print(__doc__)
