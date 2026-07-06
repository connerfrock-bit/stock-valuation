"""
Build FairValue-SHARE.html — the whole dashboard as ONE self-contained file
(app + styles + current data + both backtests inlined). Send it to anyone;
they double-click it. No server, no install, works offline (fonts fall back).
Run `npm run build` in frontend/ first.   python share.py
"""
import json, re, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
DIST = ROOT / "frontend" / "dist"
OUT = ROOT / "FairValue-SHARE.html"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def script_safe(s):
    """Neutralize '</script' sequences so inlining can't terminate the tag early."""
    return re.sub(r"</script", r"<\\/script", s, flags=re.I)


def main():
    html = (DIST / "index.html").read_text(encoding="utf-8")

    # inline the JS bundle
    m = re.search(r'<script type="module"[^>]*src="/(assets/[^"]+\.js)"[^>]*></script>', html)
    if not m:
        raise SystemExit("no module script found in dist/index.html — run npm run build")
    js = (DIST / m.group(1)).read_text(encoding="utf-8")
    html = html.replace(m.group(0), f'<script type="module">{script_safe(js)}</script>')

    # inline the stylesheet
    m = re.search(r'<link rel="stylesheet"[^>]*href="/(assets/[^"]+\.css)"[^>]*>', html)
    if m:
        css = (DIST / m.group(1)).read_text(encoding="utf-8")
        html = html.replace(m.group(0), f"<style>{css}</style>")

    # embed the data (compact) ahead of the app bundle
    data = json.loads((BASE / "data" / "output.json").read_text(encoding="utf-8"))
    bts = {}
    for key, fn in [("ndx", "backtest.json"), ("sp500", "backtest_sp500.json")]:
        p = BASE / "data" / fn
        if p.exists():
            bts[key] = json.loads(p.read_text(encoding="utf-8"))
    lp = BASE / "data" / "ledger.json"
    ledger = json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else None
    moms = {}
    for key, fn in [("ndx", "momentum.json"), ("sp500", "momentum_sp500.json")]:
        p = BASE / "data" / fn
        if p.exists():
            moms[key] = json.loads(p.read_text(encoding="utf-8"))
    inject = ("<script>window.__FV_DATA__=" + script_safe(json.dumps(data))
              + ";window.__FV_BT__=" + script_safe(json.dumps(bts))
              + ";window.__FV_LEDGER__=" + script_safe(json.dumps(ledger))
              + ";window.__FV_MOM__=" + script_safe(json.dumps(moms)) + "</script>")
    html = html.replace("<script type=\"module\">", inject + "\n<script type=\"module\">", 1)

    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT}  ({OUT.stat().st_size/1024:.0f} KB · "
          f"{len(data['companies'])} companies · backtests: {', '.join(bts) or 'none'})")


if __name__ == "__main__":
    main()
