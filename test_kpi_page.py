"""2026-11-24: KPI dashboard page (operator_page.html): the PURE part (address parsing, number format, chart SVG, list values) runs in node, no browser."""
import json, os, re, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
page = open(os.path.join(HERE, "operator_page.html"), encoding="utf-8").read()
FAILS = 0
def check(name, cond):
    global FAILS
    print(("PASS " if cond else "FAIL ") + name); FAILS += 0 if cond else 1
m = re.search(r"/\*KPI-PURE-START\*/(.*?)/\*KPI-PURE-END\*/", page, re.S)
check("P1 the pure block exists in the page", bool(m))
TEST = r"""
const out = {};
out.p1 = kpiParse('#kpi'); out.p2 = kpiParse('#kpi/cost_avg?w=7d&n=50'); out.p3 = kpiParse('#kpi?w=zz'); out.p4 = kpiParse('#other'); out.p5 = kpiParse('#kpi/nope?n=9999');
out.h1 = kpiHash(null, '7d'); out.h2 = kpiHash('failed', '30d', 10);
out.n = [kpiNum(null, ''), kpiNum(12.345, 'EUR'), kpiNum(9.54, 'min'), kpiNum(1234.6, ''), kpiNum(0, '')];
const pts = [0,1,3,0,2].map((v,i)=>({t:'2026-11-24T1'+i+':00:00', v:v}));
const bars = kpiChart(pts, null, true, '', '24h');
out.bars = (bars.match(/<rect /g) || []).length; out.barsSvg = bars.startsWith('<svg') && bars.endsWith('</svg>');
const gap = kpiChart([{t:'2026-11-24T10:00:00',v:5},{t:'2026-11-24T11:00:00',v:null},{t:'2026-11-24T12:00:00',v:7}], null, false, 'min', '24h');
out.gapPaths = (gap.match(/ M/g) || []).length + (gap.match(/d="M/g) || []).length; out.circles = (gap.match(/<circle /g) || []).length;
out.empty = kpiChart([{t:'2026-11-24T10:00:00',v:null}], null, false, '', '24h').indexOf('nessun dato') >= 0;
out.two = (kpiChart(pts, pts, false, '%', '24h').match(/stroke-dasharray/g) || []).length;
out.esc = kpiChart([{t:'2026-11-24T10:00:00<b>',v:1}], null, true, '', '24h').indexOf('<b>') < 0;
const fake = {window:'24h', tiles:{}}; KPI_ORDER.forEach(k => { fake.tiles[k] = {label:'L<'+k, unit:'', points:[{t:'2026-11-24T10:00:00',v:1},{t:'2026-11-24T11:00:00',v:2}], total:2, total2:3, detail:'d"x'}; });
const strip = kpiStripHtml(fake, s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])));
out.stripTiles = (strip.match(/class="kt"/g) || []).length; out.stripEsc = strip.indexOf('L<') < 0 && strip.indexOf('d"x') < 0; out.stripEmpty = kpiStripHtml({tiles:{}}, s => s) === '';
out.v = [kpiValueText('cost', {value: 12}), kpiValueText('gen_time', {value: 9.5}), kpiValueText('rework', {value: 2}), kpiValueText('stuck', {value: 61}), kpiValueText('failed', {value: 'input_not_suitable'})];
console.log(JSON.stringify(out));
"""
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
    f.write(m.group(1) + TEST); name = f.name
r = subprocess.run(["node", name], capture_output=True, text=True); os.remove(name)
o = json.loads(r.stdout.strip() or "{}")
check("P2 '#kpi' = tiles, 24h", o.get("p1") == {"tile": None, "w": "24h", "n": 20})
check("P3 '#kpi/cost_avg?w=7d&n=50' parsed", o.get("p2") == {"tile": "cost_avg", "w": "7d", "n": 50})
check("P4 a bad window falls back to 24h; a foreign hash is not ours; bad tile and absurd n are cleaned", o.get("p3", {}).get("w") == "24h" and o.get("p4") is None and o.get("p5") == {"tile": None, "w": "24h", "n": 20})
check("P5 addresses are built back the same way", o.get("h1") == "#kpi?w=7d" and o.get("h2") == "#kpi/failed?w=30d&n=10")
check("P6 numbers: dash for none, euro with 2 decimals, 1 decimal, rounded when large", o.get("n") == ["—", "12.35 EUR", "9.5 min", "1235", "0"])
check("P7 counts are drawn as bars (only the non-zero ones) in one SVG", o.get("bars") == 3 and o.get("barsSvg") is True)
check("P8 a line breaks where there is no data and every point has a tooltip circle", o.get("circles") == 2 and o.get("gapPaths", 0) >= 2)
check("P9 no data in the window says so", o.get("empty") is True)
check("P10 a second series is drawn dashed", o.get("two") == 1)
check("P11 text inside the chart is escaped", o.get("esc") is True)
check("P12 list values: cost, minutes, rework, stuck, failure code", o.get("v") == ["12.00 EUR", "9.5 min", "2 scene rifatte", "fermo da 61 min", "input_not_suitable"])
check("P13 the page has the Indicatori button, the view box and the route hook", 'id="kpi-btn"' in page and 'id="kpiview"' in page and "addEventListener('hashchange'" in page and "kpiRoute();" in page)
check("P14 the preview strip builds one small tile per KPI with the same chart, text escaped, empty data gives nothing", o.get("stripTiles") == 7 and o.get("stripEsc") is True and o.get("stripEmpty") is True)
check("P15 the main dashboard has the strip box, a 'tutti gli indicatori' link and a refresh every 60 s", 'id="kpistrip"' in page and "tutti gli indicatori" in page and "setInterval(kpiPaintStrip, 60000)" in page)
print("test_kpi_page FAILS", FAILS); sys.exit(1 if FAILS else 0)
