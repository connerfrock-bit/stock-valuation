"""Cross-sectional calibration — does predicted upside actually predict forward return?

The forward ledger (ledger.py) asks ONE question per snapshot: did the top-quintile basket
beat the benchmark? That is 18 names collapsed to a single number, and consecutive baskets
overlap ~90%, so it needs years of accrual before it separates from noise.

This asks a sharper question of the SAME frozen snapshots, using every name instead of the
top quintile: across the whole cross-section, do the names the model called cheap actually
out-return the ones it called expensive? Same look-ahead guarantee (the snapshot was
committed before the return existed), ~1,400 observations per session instead of 1.

What it measures, and why each piece is here:

  RANK IC   Spearman correlation between predicted upside and realized forward return.
            Rank-based on purpose: `upside` is unbounded above (the live S&P 1500 run
            tops out near +24,000%) so a Pearson correlation or a raw-return average
            would be decided by two or three broken denominators.
  DECILES   Bucket by predicted upside, look at realized return per bucket. IC says
            "is there signal"; the decile curve says WHERE — a model that only works in
            the top bucket needs a different fix than one that is monotone but flat.
  BETA      Mean beta per decile. If the cheap decile is simply the high-beta decile, the
            spread is a market-exposure bet wearing a valuation costume.
  SECTOR-   IC recomputed after demeaning forward returns within sector. If the raw IC
  NEUTRAL   survives this, the model is picking names; if it collapses, it is picking
            sectors, which is a different (and much less durable) claim.
  BY CONF /  Same IC split by the model's own confidence and quality scores. This is the
  QUALITY   directly actionable cut: if the signal only exists where conf is high, the fix
            is to gate on conf, not to rebuild the valuation.

POWER IS REPORTED BEFORE RESULTS, ON PURPOSE. Every snapshot marked to the same exit date
is very nearly the same measurement; a mean IC over overlapping windows is not evidence and
its t-stat is not a t-stat. `independentWindows` counts non-overlapping horizons only, and
`readable` stays False until there are enough of them. This file is deliberately built to
refuse to flatter the model — the ledger already made that mistake once.
stdlib only.   python calibration.py [universe_id|all]     (run after value.py)
"""
import json, sqlite3, sys
from datetime import datetime
from math import isclose
from common import DB_PATH, UNIVERSES, ACTIVE, resolve_universe

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HORIZON = 5                    # sessions forward — one trading week
MIN_NAMES = 30                 # a session with fewer scored names can't support an IC
MIN_WINDOWS = 12               # non-overlapping windows before mean IC is worth reading

CAVEATS = [
    "Every name in the snapshot is used, not just the basket — the top quintile is a 18-name sliver of the evidence.",
    "Spearman (rank) correlation throughout: predicted upside is unbounded above, so raw-return averages are decided by outliers.",
    "Forward returns are total-return (adjclose), split- and dividend-adjusted on both ends.",
    "Sessions overlap: each snapshot is a fresh cross-section but consecutive ones share names and calendar. Only independentWindows counts.",
    "Delisted names leave price_daily and are dropped, which biases the surviving sample upward — counted as `dropped`, not hidden.",
    "A positive IC over a handful of overlapping windows is not evidence. `readable` gates on non-overlapping windows for that reason.",
]


# ---------- statistics (pure, stdlib) ----------
def _ranks(xs):
    """Average ranks, ties shared.

       Ties are matched with a tolerance, not `==`, and that is load-bearing. Demeaning
       (neutralize) turns values that are equal in exact arithmetic into floats that
       differ in the last bit or two — 0.005 vs 0.005000000000000004. Under exact
       equality those become 50 distinct ranks ordered by rounding error, and because
       the error correlates with the group that was demeaned, it manufactures a nonzero
       IC out of pure noise: the beta-neutral test case scored -0.136 when the true
       answer is 0. `conf` (integers 2-5) ties exactly and is unaffected either way.
       Each run is compared to its FIRST member so a tolerance chain cannot drift."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out, i = [0.0] * len(xs), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and isclose(xs[order[j + 1]], xs[order[i]],
                                             rel_tol=1e-9, abs_tol=1e-15):
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def spearman(pairs):
    """Rank correlation of (pred, realized). None when undefined (n<3 or no variance)."""
    if len(pairs) < 3:
        return None
    rx, ry = _ranks([p[0] for p in pairs]), _ranks([p[1] for p in pairs])
    n = len(pairs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    return None if dx == 0 or dy == 0 else round(num / (dx * dy), 4)


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _median(xs):
    if not xs:
        return None
    s = sorted(xs)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def buckets(rows, key, n=10):
    """Split rows into n equal-count buckets by `key`, low to high. Returns the bucket
       lists; equal-count (not equal-width) because upside's distribution is pathological."""
    ok = [r for r in rows if r.get(key) is not None]
    ok.sort(key=lambda r: r[key])
    if len(ok) < n:
        return []
    return [ok[i * len(ok) // n:(i + 1) * len(ok) // n] for i in range(n)]


def neutralize(rows, group_of):
    """Demean forward returns within group, so the IC that survives is the part NOT
       explained by belonging to that group. Groups thinner than 3 names are dropped
       rather than demeaned against themselves."""
    groups = {}
    for r in rows:
        groups.setdefault(group_of(r), []).append(r)
    out = []
    for group in groups.values():
        if len(group) < 3:
            continue
        m = _mean([r["fwd"] for r in group])
        out.extend({**r, "fwd": r["fwd"] - m} for r in group)
    return out


def sector_neutral(rows):
    """Kills the 'it just picked energy' explanation."""
    return neutralize(rows, lambda r: r["sector"] or "?")


def beta_neutral(rows, n=5):
    """Kills the 'it just picked low-beta names in a down market' explanation — the one
       that matters most here, because a valuation model that flags expensive names will
       naturally flag high-beta ones, and in a falling market that looks like skill.
       Buckets by beta quintile within the session, then demeans inside each bucket."""
    ok = [r for r in rows if r.get("beta") is not None]
    if len(ok) < n * 3:
        return []
    ok.sort(key=lambda r: r["beta"])
    band = {}
    for i, r in enumerate(ok):
        band[r["ticker"]] = min(n - 1, i * n // len(ok))
    return neutralize(ok, lambda r: band[r["ticker"]])


# ---------- the report ----------
def build_calibration(panel, sessions, horizon=HORIZON, min_windows=MIN_WINDOWS):
    """panel:   {session: [row, ...]} where row has ticker/upside/score/quality/conf/beta/
                 sector/fwd, and `fwd` is the realized total return over `horizon` sessions.
       sessions: the full trading calendar, so window overlap can be measured honestly.
       Pure — no database, no clock."""
    dates = sorted(s for s, rows in panel.items() if len(rows) >= MIN_NAMES)
    if not dates:
        return None

    def ic_series(rows_of, field):
        per = []
        for d in dates:
            rows = rows_of(panel[d])
            ic = spearman([(r[field], r["fwd"]) for r in rows if r.get(field) is not None])
            if ic is not None:
                per.append({"session": d, "ic": ic, "n": len(rows)})
        ics = [p["ic"] for p in per]
        return {"perSession": per,
                "mean": None if not ics else round(_mean(ics), 4),
                "hitRate": None if not ics else round(sum(i > 0 for i in ics) / len(ics), 3),
                "sessions": len(per)}

    # Non-overlapping windows are the only ones that carry independent information.
    # Greedy walk: take a session, skip everything inside its horizon, repeat.
    idx = {d: i for i, d in enumerate(sessions)}
    independent, last = [], None
    for d in dates:
        if last is None or idx.get(d, 0) - idx.get(last, 0) >= horizon:
            independent.append(d)
            last = d

    ic = {"upside": ic_series(lambda rs: rs, "upside"),
          "score": ic_series(lambda rs: rs, "score"),
          "upsideSectorNeutral": ic_series(sector_neutral, "upside"),
          "upsideBetaNeutral": ic_series(beta_neutral, "upside")}

    pooled = [r for d in dates for r in panel[d]]
    dec = []
    for i, b in enumerate(buckets(pooled, "upside"), 1):
        dec.append({"decile": i, "n": len(b),
                    "meanUpside": round(_mean([r["upside"] for r in b]), 4),
                    "meanFwd": round(_mean([r["fwd"] for r in b]), 4),
                    "medianFwd": round(_median([r["fwd"] for r in b]), 4),
                    "meanBeta": (lambda v: None if v is None else round(v, 3))(
                        _mean([r["beta"] for r in b if r.get("beta") is not None]))})

    def split(field, edges):
        out = []
        for lo, hi in edges:
            rows = [r for r in pooled
                    if r.get(field) is not None and lo <= r[field] <= hi]
            if len(rows) >= MIN_NAMES:
                out.append({"band": f"{lo}-{hi}", "n": len(rows),
                            "ic": spearman([(r["upside"], r["fwd"]) for r in rows]),
                            "meanFwd": round(_mean([r["fwd"] for r in rows]), 4)})
        return out

    n_ind = len(independent)
    readable = n_ind >= min_windows
    top, bot = (dec[-1]["meanFwd"], dec[0]["meanFwd"]) if dec else (None, None)
    return {
        "power": {"snapshotSessions": len(dates), "independentWindows": n_ind,
                  "windowsNeeded": min_windows, "horizonSessions": horizon,
                  "namesPerSession": int(_mean([len(panel[d]) for d in dates])),
                  "independentSessions": independent},
        "readable": readable,
        "verdict": (_verdict(ic, dec) if readable else
                    f"NOT READABLE — {n_ind} independent {horizon}-session window(s), "
                    f"need {min_windows}. Every number below is a placeholder for a real "
                    f"answer that does not exist yet; the sign of the IC at this sample "
                    f"size is a coin flip."),
        "ic": ic,
        "deciles": dec,
        "decileSpread": None if top is None else round(top - bot, 4),
        "byConf": split("conf", [(1, 2), (3, 3), (4, 5)]),
        "byQuality": split("quality", [(0, 39), (40, 59), (60, 79), (80, 100)]),
        "caveats": CAVEATS,
    }


def _verdict(ic, dec):
    """One line, written to be falsifiable rather than encouraging. The raw IC is the
       claim; the two neutralized ICs are the ways that claim can be a mirage, so the
       verdict leads with how much of the edge survives them."""
    m = ic["upside"]["mean"]
    if m is None:
        return "No measurable IC."
    parts = [f"Upside {'predicts' if m > 0 else 'ANTI-predicts'} forward return "
             f"(mean rank IC {m:+.3f})"]
    for key, label, alt in (("upsideSectorNeutral", "sector", "a sector bet"),
                            ("upsideBetaNeutral", "beta", "a market-exposure bet")):
        v = ic[key]["mean"]
        if v is None:
            parts.append(f"{label}-neutral not measurable")
        elif m and v / m >= 0.5:
            parts.append(f"{label}-neutral {v:+.3f} — survives ({v / m * 100:.0f}% retained)")
        else:
            keep = 0.0 if not m else max(0.0, v / m) * 100
            parts.append(f"{label}-neutral {v:+.3f} — MOSTLY {alt} "
                         f"(only {keep:.0f}% retained)")
    if dec:
        b = [d["meanBeta"] for d in dec if d["meanBeta"] is not None]
        if len(b) >= 2 and abs(b[-1] - b[0]) > 0.15:
            parts.append(f"cheap decile beta {b[-1]:.2f} vs expensive {b[0]:.2f}")
    return "; ".join(parts) + "."


# ---------- data loading ----------
def load_panel(con, universe, model, horizon=HORIZON):
    """Frozen snapshots -> {session: [rows]} with realized forward total return.
       Returns (panel, sessions, dropped). `dropped` counts names whose price series
       ends before the window closes — mostly delistings, and a source of upward bias."""
    sessions = [r[0] for r in
                con.execute("SELECT DISTINCT date FROM price_daily ORDER BY date")]
    if not sessions:
        return {}, [], 0
    pos = {d: i for i, d in enumerate(sessions)}

    def session_of(day):                          # latest session <= day (weekend -> Fri)
        lo, hi, best = 0, len(sessions) - 1, None
        while lo <= hi:
            mid = (lo + hi) // 2
            if sessions[mid] <= day:
                best, lo = sessions[mid], mid + 1
            else:
                hi = mid - 1
        return best

    snaps = {}                                    # session -> {ticker: row}; earliest wins
    for rd, t, up, score, q, conf in con.execute(
            "SELECT run_date, ticker, upside, score, quality, conf FROM snapshots "
            "WHERE universe=? AND model=?", (universe, model)):
        s = session_of(rd[:10])
        if s is None:
            continue
        snaps.setdefault(s, {}).setdefault(t, {
            "ticker": t, "upside": up, "score": score, "quality": q, "conf": conf})

    betas = {t: b for t, b in con.execute("SELECT ticker, beta FROM betas")}
    sectors = {t: s for t, s in con.execute("SELECT ticker, sector FROM companies")}

    # Only the prices actually needed: each snapshot session and its horizon exit.
    need = set()
    for s in snaps:
        i = pos[s]
        need.add(s)
        if i + horizon < len(sessions):
            need.add(sessions[i + horizon])
    px = {}
    if need:
        need = sorted(need)
        for d, t, v in con.execute(
                "SELECT date, ticker, adjclose FROM price_daily WHERE date IN (%s)"
                % ",".join("?" * len(need)), need):
            if v:
                px[(d, t)] = v

    panel, dropped = {}, 0
    for s, rows in snaps.items():
        i = pos[s]
        if i + horizon >= len(sessions):          # window still open — no forward return
            continue
        exit_day = sessions[i + horizon]
        out = []
        for t, r in rows.items():
            e, x = px.get((s, t)), px.get((exit_day, t))
            if not e or not x:
                dropped += 1
                continue
            out.append({**r, "fwd": x / e - 1,
                        "beta": betas.get(t), "sector": sectors.get(t)})
        if out:
            panel[s] = out
    return panel, sessions, dropped


def main(universe_id=ACTIVE, horizon=HORIZON):
    ucfg = resolve_universe(universe_id)
    uid, uname = ucfg["id"], ucfg["name"]
    con = sqlite3.connect(DB_PATH)
    try:
        model = con.execute(
            "SELECT model FROM snapshots WHERE universe=? ORDER BY run_date DESC LIMIT 1",
            (uname,)).fetchone()
    except sqlite3.OperationalError:
        print("No snapshots table yet — run value.py first.")
        return
    if not model:
        print(f"No {uname} snapshots yet — run value.py {uid} first.")
        return
    model = model[0]
    panel, sessions, dropped = load_panel(con, uname, model, horizon)
    con.close()

    payload = build_calibration(panel, sessions, horizon)
    if not payload:
        print(f"[{uname}/{model}] No session has a closed {horizon}-session window yet.")
        return
    payload["meta"] = {"generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       "universe": uname, "universeId": uid, "model": model,
                       "dropped": dropped}

    fnames = [f"calibration_{uid}.json"] + (["calibration.json"] if uid == ACTIVE else [])
    for d in [DB_PATH.parent, DB_PATH.parent.parent.parent / "frontend" / "public"]:
        if d.is_dir():
            for fn in fnames:
                (d / fn).write_text(
                    json.dumps(payload, indent=1 if d == DB_PATH.parent else None),
                    encoding="utf-8")
    _print_report(payload, uname, model, dropped)


def _print_report(p, uname, model, dropped):
    pw = p["power"]
    print(f"\n=== CALIBRATION · {uname} · {model} · {pw['horizonSessions']}-session horizon ===")
    print(f"{pw['snapshotSessions']} snapshot session(s) · ~{pw['namesPerSession']} names each · "
          f"{pw['independentWindows']} INDEPENDENT window(s) of {pw['windowsNeeded']} needed"
          + (f" · {dropped} name-observations dropped (no price)" if dropped else ""))
    print(f"\n{'READABLE' if p['readable'] else 'NOT READABLE'}: {p['verdict']}\n")

    f = lambda v, w=7: "     —" if v is None else f"{v:+{w}.4f}"
    print(f"{'RANK IC':26}{'MEAN':>9}{'HIT':>7}{'SESSIONS':>10}")
    print("-" * 52)
    for k, label in (("upside", "upside -> fwd return"),
                     ("score", "score  -> fwd return"),
                     ("upsideSectorNeutral", "upside (sector-neutral)"),
                     ("upsideBetaNeutral", "upside (beta-neutral)")):
        s = p["ic"][k]
        hr = "  —" if s["hitRate"] is None else f"{s['hitRate']*100:.0f}%"
        print(f"{label:26}{f(s['mean']):>9}{hr:>7}{s['sessions']:>10}")

    if p["deciles"]:
        print(f"\n{'DEC':>4}{'N':>7}{'MEAN UPSIDE':>13}{'MEAN FWD':>11}{'MED FWD':>10}{'BETA':>8}")
        print("-" * 53)
        for d in p["deciles"]:
            b = "    —" if d["meanBeta"] is None else f"{d['meanBeta']:5.2f}"
            print(f"{d['decile']:>4}{d['n']:>7}{d['meanUpside']:>13.3f}"
                  f"{d['meanFwd']*100:>10.2f}%{d['medianFwd']*100:>9.2f}%{b:>8}")
        print(f"decile 10 − decile 1 spread: {p['decileSpread']*100:+.2f}%")

    for key, title in (("byConf", "BY CONFIDENCE"), ("byQuality", "BY QUALITY")):
        if p[key]:
            print(f"\n{title:14}{'N':>8}{'IC':>10}{'MEAN FWD':>11}")
            print("-" * 43)
            for r in p[key]:
                print(f"{r['band']:14}{r['n']:>8}{f(r['ic'], 6):>10}{r['meanFwd']*100:>10.2f}%")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ACTIVE
    if arg == "all":
        for _uid in UNIVERSES:
            main(_uid)
    else:
        main(arg)
