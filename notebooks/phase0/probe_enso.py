"""Phase 0 probe: ENSO outlook (official NOAA CPC probabilities) + IRI / NMME reachability.

Machine-readable source: the static HTML table #probabilities-table on CPC's
"ENSO Strength Probabilities" page. Rows are overlapping 3-month seasons; the 9
columns are RONI strength bins from <= -2.0 C (very strong La Nina) to >= +2.0 C.
We sum bins into La Nina / Neutral / El Nino, checking the column headers first
so a layout change fails loudly instead of mis-summing.
"""

import re
from html.parser import HTMLParser

from _probe import run

CPC_STRENGTHS = "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/strengths/"
CPC_DISC = "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml"
IRI_PLOT = "https://ensoforecast.iri.columbia.edu/figure3_plot/{y}/{m}"
IRI_DL = "https://iridl.ldeo.columbia.edu/"


class TableParser(HTMLParser):
    """Collects rows of <table id="probabilities-table"> as lists of cell text."""

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.rows: list[list[str]] = []
        self.cell: list[str] | None = None
        self.skip = 0  # inside tooltip spans

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table" and a.get("id") == "probabilities-table":
            self.depth = 1
        elif self.depth:
            if tag == "table":
                self.depth += 1
            elif tag == "tr":
                self.rows.append([])
            elif tag in ("td", "th"):
                self.cell = []
            elif tag == "span" and "tooltip" in (a.get("class") or ""):
                self.skip += 1

    def handle_endtag(self, tag):
        if not self.depth:
            return
        if tag == "table":
            self.depth -= 1
        elif tag in ("td", "th") and self.cell is not None and self.rows:
            self.rows[-1].append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "span" and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if self.depth and self.cell is not None and not self.skip:
            self.cell.append(data)


def body(p):
    r = p.http("cpc_strengths", "GET", CPC_STRENGTHS, timeout=60)
    p.save_raw("cpc_enso_strengths.html", r.content)
    # Strip comments (the page keeps an old "Issued ..." heading commented out)
    # and normalise Unicode minus signs used in the column headers.
    html = re.sub(r"<!--.*?-->", "", r.text, flags=re.S).replace("−", "-")
    m = re.search(r"<h2>\s*Issued\s+([A-Za-z]+\s+\d{4})\s*</h2>", html)
    p.note("cpc_issued", m.group(1) if m else None)

    tp = TableParser()
    tp.feed(html)
    rows = [row for row in tp.rows if row]
    if len(rows) < 2:
        raise RuntimeError("probabilities table not found")
    header, data = rows[0], rows[1:]
    p.note("table_header", header)
    if len(header) != 10 or "-0.5" not in header[5] or "0.5" not in header[5]:
        raise RuntimeError(f"unexpected column layout: {header}")

    seasons = []
    for row in data:
        vals = [float(v) for v in row[1:]]
        seasons.append({
            "season": row[0],
            "la_nina": sum(vals[:4]), "neutral": vals[4], "el_nino": sum(vals[5:]),
            "bins": vals,
        })
    p.note("seasons", seasons)
    p.note("row_sums", [round(sum(s["bins"])) for s in seasons])

    r = p.http("cpc_discussion", "GET", CPC_DISC, timeout=60, required=False)
    if r is not None and r.ok:
        m = re.search(r"next ENSO Diagnostics Discussion is scheduled for ([^.<]+)", r.text)
        p.note("cpc_next_discussion", m.group(1).strip() if m else None)

    # IRI plume-based probabilities are published only as an SVG plot. Reachability only.
    y, mo = map(int, (p.record["started_utc"][:4], p.record["started_utc"][5:7]))
    prev = (y, mo - 1) if mo > 1 else (y - 1, 12)
    p.http("iri_fig3_svg", "GET", IRI_PLOT.format(y=prev[0], m=prev[1]), timeout=60, required=False)
    # NMME precipitation probabilities (Phase 8) come from the IRI Data Library.
    p.http("iri_data_library", "GET", IRI_DL, timeout=60, required=False)


if __name__ == "__main__":
    run("enso", body)
