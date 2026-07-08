"""
Data-quality dry run (Phase 2 gate). Measures how well the bulk-EDGAR ingest would
cover a BROAD universe — the S&P 1500 (500+400+600) — WITHOUT touching the live DB
or picker. Two numbers decide the NYSE go/no-go:

  • coverage       — % of names with ≥15/25 core concepts (the value engines' floor)
  • tag-fallback   — per concept, % of names whose value comes from a NON-primary
                     us-gaap tag (rank ≥1). A high fallback rate = the primary tag
                     map is thinning out on smaller filers → where NYSE breakage hides.

Emits data/data_quality.json (→ Methodology data-quality panel) + prints the gate.
Requires the bulk zips (python bulk.py download).  Usage: python dataquality.py [sp1500|sp500|…]
"""
import json, sqlite3, sys, time
from collections import Counter
from common import DB_PATH
from universe import build_union
from ingest_v1 import (CONCEPTS, IFRS_CONCEPTS, ANNUAL_FORMS, choose_currency,
                       fetch_financials, pick_annual)
import bulk

CORE_MIN = 15                                             # engines' concept floor (of 25)
DRY_RUN_UNIVERSES = {"sp1500": ["sp500", "sp400", "sp600"]}


def concept_tag_rank(ns, tags, ccy):
    """Rank (0-based) of the primary-most candidate tag that supplies the LATEST fiscal
       year for a concept, or None if the concept has no annual data. 0 = we're on the
       primary tag; ≥1 = relying on a fallback."""
    per_tag = {}
    for rank, tag in enumerate(tags):
        if tag not in ns:
            continue
        d = pick_annual(ns, [tag], ccy)
        if d:
            per_tag[rank] = set(d)
    if not per_tag:
        return None
    latest = max(fy for s in per_tag.values() for fy in s)
    ranks = sorted(r for r, s in per_tag.items() if latest in s)
    return ranks[0] if ranks else None


def namespace_for(facts):
    """Pick the us-gaap/ifrs namespace the way fetch_financials does -> (ns, cmap, ccy)."""
    for ns_name, cmap in [("us-gaap", CONCEPTS), ("ifrs-full", IFRS_CONCEPTS)]:
        ns = facts.get(ns_name, {})
        if not ns:
            continue
        ccy = choose_currency(ns, cmap["revenue"])
        if pick_annual(ns, cmap["revenue"], ccy) or pick_annual(ns, cmap["net_income"], ccy):
            return ns, cmap, ccy
    return None, None, None


def main(uid="sp1500"):
    if not bulk.zips_present():
        raise SystemExit("bulk zips absent — run `python bulk.py download` first")
    uids = DRY_RUN_UNIVERSES.get(uid, [uid])
    universe, _membership, srcs = build_union(uids)
    con = sqlite3.connect(DB_PATH)
    cikmap = bulk.ticker_cik_map(con)
    n = len(universe)
    print(f"Data-quality dry run: {uid} = {n} distinct names · {srcs}\n")

    concept_have = Counter()                              # names with the concept present
    concept_fallback = Counter()                          # names on a non-primary tag
    no_cik = no_facts = 0
    core_ok = 0
    t0 = time.time()
    for i, (t, _name, _sec) in enumerate(universe, 1):
        cik = cikmap.get(t)
        if not cik:
            no_cik += 1
            continue
        facts_doc = bulk.facts_json(cik)
        if not facts_doc:
            no_facts += 1
            continue
        fins, _sh, _ccy, _now = fetch_financials(cik, facts_doc)
        present = [c for c, s in fins.items() if s]
        core_ok += (len(present) >= CORE_MIN)
        for c in present:
            concept_have[c] += 1
        ns, cmap, ccy = namespace_for(facts_doc.get("facts", {}))
        if ns:
            for c, tags in cmap.items():
                if c == "shares":
                    continue
                r = concept_tag_rank(ns, tags, ccy)
                if r is not None and r >= 1:
                    concept_fallback[c] += 1
        if i % 200 == 0:
            print(f"  [{i}/{n}] core≥{CORE_MIN}: {core_ok} · {time.time()-t0:.0f}s")

    ingestable = n - no_cik - no_facts
    coverage = core_ok / n if n else 0.0
    # per-concept fallback rate over names that HAVE the concept (the honest denominator)
    fallback_rows = []
    for c in sorted(CONCEPTS):
        have = concept_have.get(c, 0)
        fb = concept_fallback.get(c, 0)
        fallback_rows.append({"concept": c, "have": have,
                              "have_pct": round(100 * have / n, 1) if n else 0.0,
                              "fallback": fb,
                              "fallback_pct": round(100 * fb / have, 1) if have else 0.0})
    out = {
        "universe": uid, "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "names": n, "no_cik": no_cik, "no_facts": no_facts, "ingestable": ingestable,
        "core_min": CORE_MIN, "core_covered": core_ok,
        "coverage_pct": round(100 * coverage, 1),
        "gate_pass": coverage >= 0.90,
        "elapsed_s": round(time.time() - t0, 1),
        "concepts": fallback_rows,
        "sources": srcs,
    }
    for d in [DB_PATH.parent, DB_PATH.parent.parent.parent / "frontend" / "public"]:
        if d.is_dir():                                    # mirror to the dashboard, like output.json
            (d / "data_quality.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    con.close()
    bulk.close()

    print(f"\n{'='*60}")
    print(f"  {uid}: {n} names · {no_cik} no-CIK · {no_facts} no-facts · "
          f"{ingestable} ingestable")
    print(f"  COVERAGE (≥{CORE_MIN}/25 concepts): {core_ok}/{n} = {100*coverage:.1f}%  "
          f"→ gate {'PASS ✅' if coverage >= 0.90 else 'FAIL ❌'} (≥90%)")
    worst = sorted([r for r in fallback_rows if r["have"] >= 50],
                   key=lambda r: -r["fallback_pct"])[:6]
    print("  Highest tag-fallback concepts (rely on non-primary tags):")
    for r in worst:
        print(f"    {r['concept']:16} have {r['have_pct']:5.1f}%  fallback {r['fallback_pct']:5.1f}%")
    print(f"  {time.time()-t0:.0f}s · wrote data/data_quality.json")
    print("=" * 60)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sp1500")
