"""
report.py - where test results go, and the human-readable report that goes with them.

Every measurement script writes one folder per run:

    results/<test>/<label>_<YYYYMMDD-HHMMSS>/
        report.html      tables + graphs, one self-contained file (open in any browser)
        summary.txt      everything the script printed, as it printed it
        *.csv / *.json   the raw data, unchanged -- for Excel, scripts, diffing
        plots/*.png      each graph as a separate image
        run.json         what ran, when, with which command line (used by the index)

and results/index.html lists every run, newest first. results/ is git-ignored.

Usage from a script:

    from report import Run
    with Run("dcx_thdn", label=args.label, outdir=args.outdir) as rep:
        rep.info("DCX output", args.out_ch)
        ...measure, printing as usual (it's captured into summary.txt)...
        rep.csv("freq_sweep.csv", ["freq_Hz", "thdn_dB"], rows)
        rep.table(["Frequency (Hz)", "THD+N (dB)"], rows, title="THD+N vs frequency")
        rep.plot("thdn_vs_freq", [("THD+N", xs, ys)], xlabel="Frequency (Hz)",
                 ylabel="THD+N (dB)", logx=True)

The report is written even if the run fails part-way (it says so at the top), so
whatever was measured before the failure is never lost. Graphs need matplotlib
(`pip install matplotlib`); without it the run still writes its CSVs, tables and
summary, and the report notes that graphs were skipped.

Every script takes the same two options (see add_output_args):
    --label NAME     names the run folder (DUT, cable, setting); each script has a default
    --outdir DIR     write exactly here instead of results/<test>/<label>_<timestamp>/
"""
import base64
import csv
import html
import io
import json
import math
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(ROOT, "results")

# categorical order, fixed (never cycled): blue, orange, aqua, yellow, magenta,
# green, violet, red. Left channel is always blue and right always orange.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def slug(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(s)).strip("_") or "run"


def add_output_args(p, default_label=None):
    """The two output options every script shares."""
    p.add_argument("--label", default=default_label,
                   help="name for this run's results folder (e.g. the DUT or the setting)"
                        + (f"; default {default_label}" if default_label else ""))
    p.add_argument("--outdir", help="write into this folder instead of "
                                    "results/<test>/<label>_<timestamp>/")


def is_na(v):
    """UPL 'no value' sentinels: 9.93e37, and -240 dB (THD with the harmonics out of band)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return True
    return math.isnan(v) or math.isinf(v) or abs(v) > 9e36 or v <= -200


def fmt(v, spec=None):
    """A table cell. Numbers get sensible precision; sentinels read 'n/a'."""
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if isinstance(v, float) and is_na(v):
            return "n/a"
        if spec:
            return format(v, spec)
        if isinstance(v, int):
            return str(v)
        a = abs(v)
        if a == 0:
            return "0"
        if a >= 1e5 or a < 1e-3:
            return f"{v:.4g}"
        if a >= 100:
            return f"{v:.1f}"
        if a >= 1:
            return f"{v:.3f}".rstrip("0").rstrip(".") if a >= 10 else f"{v:.4f}".rstrip("0").rstrip(".")
        return f"{v:.5f}".rstrip("0").rstrip(".")
    if isinstance(v, str):
        try:
            return fmt(float(v), spec) if re.fullmatch(r"\s*[-+]?[\d.]+(e[-+]?\d+)?\s*", v, re.I) else v
        except ValueError:
            return v
    return str(v)


class _Tee:
    """Copies a stream into summary.txt without changing what the console shows."""
    def __init__(self, stream, fp):
        self.stream, self.fp = stream, fp

    def write(self, s):
        self.stream.write(s)
        try:
            self.fp.write(s)
            self.fp.flush()
        except ValueError:
            pass
        return len(s)

    def flush(self):
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


class Run:
    def __init__(self, test, label=None, outdir=None, title=None, argv=None, console=True,
                 started=None):
        """test: the script/test name (results/<test>/). label: names the folder.
        console=True copies stdout/stderr into summary.txt; pass False if the
        script already writes its own summary.txt. started: override the
        timestamp (time.struct_time), used when re-filing old results."""
        self.test = test
        self.label = label or test
        t = started or time.localtime()
        self.stamp = time.strftime("%Y%m%d-%H%M%S", t)
        self.started = time.strftime("%Y-%m-%d %H:%M:%S", t)
        self.dir = os.path.abspath(outdir or os.path.join(RESULTS, slug(test),
                                                          f"{slug(self.label)}_{self.stamp}"))
        os.makedirs(self.dir, exist_ok=True)
        self.title = title or test
        self.meta = [("Test", test), ("Label", self.label), ("Started", self.started)]
        argv = sys.argv if argv is None else argv
        if argv:
            self.meta.append(("Command", " ".join(_q(a) for a in argv)))
        self.headline = None
        self.status = "complete"
        self.body = []           # html fragments, in order
        self.files = []          # (name, description)
        self._warned_mpl = False
        self._fp = self._out = self._err = None
        self._done = False
        if console:
            self._fp = open(self.path("summary.txt"), "a", encoding="utf-8")
            self._out, self._err = sys.stdout, sys.stderr
            sys.stdout, sys.stderr = _Tee(sys.stdout, self._fp), _Tee(sys.stderr, self._fp)

    # ------------------------------------------------------------ plumbing
    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        if et is KeyboardInterrupt:
            self.status = "interrupted"
        elif et is not None:
            self.status = "failed"
            self.note(f"The run stopped with an error: {et.__name__}: {ev}. "
                      "Everything above was measured before that.", warn=True)
        self.finish()
        return False

    def path(self, name):
        p = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def info(self, key, value):
        """A line in the report's 'Run details' block (instrument, DUT, settings)."""
        self.meta.append((key, value))

    # ------------------------------------------------------------ content
    def heading(self, text):
        self.body.append(f"<h2>{html.escape(str(text))}</h2>")

    def note(self, text, warn=False):
        cls = "note warn" if warn else "note"
        self.body.append(f'<p class="{cls}">{html.escape(str(text))}</p>')

    def text(self, text, title=None):
        """A block of preformatted text (e.g. a script's own verdict)."""
        t = f"<h3>{html.escape(title)}</h3>" if title else ""
        self.body.append(f"{t}<pre>{html.escape(str(text))}</pre>")

    def csv(self, name, header, rows, comments=(), describe=None):
        """Write raw data. Returns the path. Nothing is rounded."""
        p = self.path(name)
        with open(p, "w", newline="", encoding="utf-8") as fp:
            for c in comments:
                fp.write(f"# {c}\n")
            w = csv.writer(fp)
            if header:
                w.writerow(header)
            w.writerows(rows)
        self.files.append((name, describe or f"{len(rows)} rows"))
        print(f"  -> {p}")
        return p

    def json(self, name, obj, describe=None):
        p = self.path(name)
        with open(p, "w", encoding="utf-8") as fp:
            json.dump(obj, fp, indent=2, default=str)
        self.files.append((name, describe or "raw data"))
        return p

    def add_file(self, name, describe):
        """List a file the script wrote itself."""
        self.files.append((name, describe))

    def table(self, header, rows, title=None, formats=None, status=None, max_rows=300):
        """A readable table. formats: per-column format specs (None = automatic).
        status: per-row 'ok' / 'fail' / None, shown as a coloured marker plus the word."""
        out = [f"<h3>{html.escape(title)}</h3>"] if title else []
        rows = list(rows)
        shown = rows[:max_rows]
        out.append('<div class="tw"><table><thead><tr>')
        out += [f"<th>{html.escape(str(h))}</th>" for h in header]
        if status:
            out.append("<th>Result</th>")
        out.append("</tr></thead><tbody>")
        for i, r in enumerate(shown):
            st = status[i] if status else None
            out.append(f'<tr class="{st}">' if st else "<tr>")
            for j, v in enumerate(r):
                spec = formats[j] if formats and j < len(formats) else None
                s = fmt(v, spec)
                num = isinstance(v, (int, float)) or re.fullmatch(r"[-+]?[\d.]+(e[-+]?\d+)?", str(v) or "x", re.I)
                out.append(f'<td class="n">{html.escape(s)}</td>' if num else f"<td>{html.escape(s)}</td>")
            if status:
                word = {"ok": "pass", "fail": "FAIL"}.get(st, st or "")
                out.append(f'<td><span class="badge {st or ""}">{word}</span></td>')
            out.append("</tr>")
        out.append("</tbody></table></div>")
        if len(rows) > max_rows:
            out.append(f'<p class="note">First {max_rows} of {len(rows)} rows; all of them are in the CSV.</p>')
        self.body.append("".join(out))

    def plot(self, name, series, title=None, xlabel="", ylabel="", logx=False, logy=False,
             ylim=None, xlim=None, hlines=(), markers=None, steps=False, height=4.2):
        """A line graph. series: [(label, xs, ys), ...] -- or (label, xs, ys, style)
        where style is a dict of matplotlib kwargs. UPL 'no value' sentinels are
        left out (a gap in the line). hlines: [(y, label)] reference lines."""
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            if not self._warned_mpl:
                self.note("Graphs skipped: matplotlib is not installed (pip install matplotlib). "
                          "The data is all in the CSVs.", warn=True)
                self._warned_mpl = True
            return None
        fig, ax = plt.subplots(figsize=(8.6, height), dpi=110)
        drawn = 0
        for i, s in enumerate(series):
            lab, xs, ys = s[0], list(s[1]), list(s[2])
            style = dict(s[3]) if len(s) > 3 else {}
            pts = []
            for x, y in zip(xs, ys):
                try:
                    x, y = float(x), float(y)
                except (TypeError, ValueError):
                    pts.append((math.nan, math.nan)); continue
                if is_na(y) or (logx and x <= 0) or (logy and y <= 0):
                    pts.append((x, math.nan))
                else:
                    pts.append((x, y))
            if not any(not math.isnan(y) for _, y in pts):
                continue
            xs2, ys2 = zip(*pts)
            style.setdefault("color", SERIES[i % len(SERIES)])
            style.setdefault("linewidth", 1.6 if steps is False else 1.0)
            many = len(xs2) > 60
            mk = markers if markers is not None else not many
            if mk:
                style.setdefault("marker", "o")
                style.setdefault("markersize", 3.5)
            if steps:
                style.setdefault("drawstyle", "steps-mid")
            ax.plot(xs2, ys2, label=lab, **style)
            drawn += 1
        if not drawn:
            plt.close(fig)
            self.note(f"{title or name}: nothing to plot (every value was 'n/a').", warn=True)
            return None
        for y, lab in hlines:
            ax.axhline(y, color=INK2, linewidth=0.9, linestyle="--")
            if lab:
                ax.annotate(lab, xy=(1, y), xycoords=("axes fraction", "data"), xytext=(-4, 3),
                            textcoords="offset points", ha="right", va="bottom",
                            fontsize=8, color=INK2)
        if logx:
            ax.set_xscale("log")
            ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(_hz))
        if logy:
            ax.set_yscale("log")
        if ylim:
            ax.set_ylim(*ylim)
        if xlim:
            ax.set_xlim(*xlim)
        ax.set_xlabel(xlabel, color=INK2)
        ax.set_ylabel(ylabel, color=INK2)
        if title:
            ax.set_title(title, color=INK, fontsize=11, loc="left")
        ax.grid(True, which="major", color=GRID, linewidth=0.8)
        if logx:
            ax.grid(True, which="minor", color=GRID, linewidth=0.4)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        for sp in ("left", "bottom"):
            ax.spines[sp].set_color("#b9b8b2")
        ax.tick_params(colors=INK2, labelsize=8.5)
        if drawn > 1:
            ax.legend(frameon=False, fontsize=8.5)
        fig.tight_layout()
        rel = f"plots/{slug(name)}.png"
        fig.savefig(self.path(rel))
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        plt.close(fig)
        b64 = base64.b64encode(buf.getvalue()).decode()
        alt = html.escape(title or name)
        self.body.append(f'<figure><img src="data:image/png;base64,{b64}" alt="{alt}">'
                         f'<figcaption><a href="{rel}">{html.escape(rel)}</a></figcaption></figure>')
        return rel

    # ------------------------------------------------------------ output
    def finish(self):
        if self._done:
            return
        self._done = True
        if self._out is not None:
            sys.stdout, sys.stderr = self._out, self._err
            self._out = self._err = None
        if self._fp:
            self._fp.close()
            self._fp = None
        if os.path.exists(os.path.join(self.dir, "summary.txt")) and                 not any(f == "summary.txt" for f, _ in self.files):
            self.files.insert(0, ("summary.txt", "everything the script printed"))
        with open(self.path("report.html"), "w", encoding="utf-8") as fp:
            fp.write(self._html())
        with open(self.path("run.json"), "w", encoding="utf-8") as fp:
            json.dump({"test": self.test, "label": self.label, "started": self.started,
                       "status": self.status, "headline": self.headline, "title": self.title,
                       "meta": self.meta}, fp, indent=2, default=str)
        try:
            write_index()
        except Exception as e:                       # never let the index break a run
            print(f"(results index not updated: {e})")
        print(f"\nReport: {self.path('report.html')}")

    def _html(self):
        meta = ('<div class="tw"><table class="meta">'
                + "".join(f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>"
                          for k, v in self.meta) + "</table></div>")
        files = "".join(f'<li><a href="{html.escape(n)}">{html.escape(n)}</a>'
                        f' <span class="muted">&mdash; {html.escape(str(d))}</span></li>'
                        for n, d in self.files)
        banner = ""
        if self.status != "complete":
            banner = f'<p class="note warn">This run is <b>{self.status}</b>: the results are partial.</p>'
        head = f'<p class="headline">{html.escape(self.headline)}</p>' if self.headline else ""
        return PAGE.format(title=html.escape(f"{self.title} — {self.label}"),
                           h1=html.escape(self.title), label=html.escape(self.label),
                           started=html.escape(self.started), banner=banner, headline=head,
                           meta=meta, body="\n".join(self.body) or '<p class="muted">No results.</p>',
                           files=files or "<li>none</li>", css=CSS)


def _q(a):
    return f'"{a}"' if (" " in a or not a) else a


def _hz(x, _pos=None):
    if x >= 1000:
        return f"{x / 1000:g}k"
    return f"{x:g}"


def write_index():
    """results/index.html: every run that has a run.json, newest first."""
    runs = []
    for dirpath, _dirs, fnames in os.walk(RESULTS):
        if "run.json" in fnames:
            try:
                with open(os.path.join(dirpath, "run.json"), encoding="utf-8") as fp:
                    r = json.load(fp)
            except (OSError, ValueError):
                continue
            r["href"] = os.path.relpath(os.path.join(dirpath, "report.html"), RESULTS).replace(os.sep, "/")
            runs.append(r)
    runs.sort(key=lambda r: r.get("started", ""), reverse=True)
    rows = []
    for r in runs:
        st = r.get("status", "")
        badge = "" if st == "complete" else f' <span class="badge fail">{html.escape(st)}</span>'
        rows.append(f'<tr><td class="n">{html.escape(r.get("started", ""))}</td>'
                    f'<td>{html.escape(r.get("test", ""))}</td>'
                    f'<td><a href="{html.escape(r["href"])}">{html.escape(r.get("label", ""))}</a>{badge}</td>'
                    f'<td>{html.escape(r.get("headline") or "")}</td></tr>')
    body = ('<div class="tw"><table><thead><tr><th>Started</th><th>Test</th><th>Run</th>'
            '<th>Result</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>")
    page = PAGE.format(title="UPL results", h1="UPL results", label=f"{len(runs)} runs",
                       started=time.strftime("updated %Y-%m-%d %H:%M"), banner="", headline="",
                       meta="", body=body, files="", css=CSS)
    page = page.replace('<section class="files">', '<section class="files" hidden>')
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "index.html"), "w", encoding="utf-8") as fp:
        fp.write(page)


CSS = """
:root{--bg:#f6f6f4;--card:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#7a7973;--line:#e4e3df;
--ok:#008300;--bad:#c62f2e;--warnbg:#fff4de;--warnink:#6b4a00;--link:#1f63b8}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#121211;--card:#1a1a19;
--ink:#fff;--ink2:#c3c2b7;--muted:#96958d;--line:#33332f;--ok:#4cb84c;--bad:#e66767;
--warnbg:#3a2e12;--warnink:#f3d38a;--link:#7fb2f0}}
:root[data-theme="dark"]{--bg:#121211;--card:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#96958d;
--line:#33332f;--ok:#4cb84c;--bad:#e66767;--warnbg:#3a2e12;--warnink:#f3d38a;--link:#7fb2f0}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:24px;margin:0}h2{font-size:19px;margin:36px 0 8px;padding-top:12px;border-top:1px solid var(--line)}
h3{font-size:15px;margin:20px 0 6px;color:var(--ink2)}
.sub{color:var(--ink2);margin:2px 0 16px}.muted{color:var(--muted)}
a{color:var(--link)}
.headline{font-size:17px;font-weight:600;margin:8px 0 16px}
.note{background:var(--card);border-left:3px solid var(--line);padding:8px 12px;margin:10px 0;color:var(--ink2)}
.note.warn{background:var(--warnbg);border-left-color:#eda100;color:var(--warnink)}
.tw{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:6px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{padding:5px 10px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
thead th{background:var(--card);color:var(--ink2);font-weight:600;position:sticky;top:0}
tbody tr:last-child td{border-bottom:0}
td.n{text-align:right;font-variant-numeric:tabular-nums}
.meta th{width:140px;color:var(--ink2);font-weight:500;vertical-align:top}
.meta td{white-space:normal;word-break:break-word}
.badge{display:inline-block;font-size:12px;font-weight:600;padding:0 7px;border-radius:9px;border:1px solid}
.badge.ok{color:var(--ok)}.badge.fail{color:var(--bad)}
tr.fail td{color:var(--bad)}
figure{margin:14px 0;background:#fff;border:1px solid var(--line);border-radius:6px;padding:6px}
figure img{width:100%;height:auto;display:block}
figcaption{font-size:12px;color:#52514e;padding:2px 4px}
figcaption a{color:#1f63b8}
pre{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:10px;overflow-x:auto;font-size:12.5px}
.files ul{padding-left:18px}
"""

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>{css}</style></head>
<body><main>
<h1>{h1}</h1>
<p class="sub">{label} &middot; {started}</p>
{banner}{headline}
{meta}
{body}
<section class="files"><h2>Files in this run</h2><ul>{files}</ul></section>
</main></body></html>
"""


if __name__ == "__main__":
    write_index()
    print(os.path.join(RESULTS, "index.html"))
