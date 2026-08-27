"""app/legacy/print_builtin.py — the NEW built-in print preview / PDF export
feature. This is ADDITIVE: the existing Excel/Word-based print_engine*.py
files are untouched and still work exactly as before (Print / Preview /
Open File via Excel or Word, needs those programs installed on the PC).
This module is a second, independent way to get the same RSL certificate
that works entirely inside the browser -- no Excel, no Word, no pywin32,
nothing extra to install.

How it works:
  - print_template.json (project root, same folder as telco.db/settings.json)
    holds the certificate's layout: one entry per text box, each with its
    on-page position/size and the mix of static text + database fields it
    shows. It was generated once from the site's actual RSL_Format_2025
    Word template (see the MERGEFIELD names it used) so the built-in
    version starts out matching the real certificate. Users can then drag
    boxes around / resize them / change font size from the Design mode on
    the Live Preview page (app/templates/app/print_preview.html) --
    PUT /api/print-template saves their changes back into this same file.
  - The Live Preview page (HTML) and the PDF export (this module's
    build_pdf) both read the SAME template file and the SAME
    format_value() below, so what you see on screen is what prints.
"""
import os
import io
import re
import json
import base64
import datetime
import sqlite3
import xml.sax.saxutils as saxutils

from app.config import DB

TEMPLATE_FILE = "print_template.json"
# Untouched factory layout (a copy of print_template.json made the moment
# this feature shipped) -- what "Reset to Default" on the Live Preview
# page's Design mode restores, in case someone drags things into a mess.
DEFAULT_TEMPLATE_FILE = "print_template.default.json"

DATE_FIELDS = {"rsl_date", "old_date", "validity_from", "validity_to", "or_date"}

# freq1-4 often carry a "TX (MHz)"/"RX (MHz)" label baked right into the
# stored text, and/or the same number typed several times in a row --
# leftovers from how the original data was imported. _clean_freq_display()
# below pulls out just the distinct frequency values (in the order they
# first appear) so the certificate shows each real value once instead of a
# label plus duplicates. This only changes what's DISPLAYED (Live Preview
# and PDF) -- the raw stored value is never touched, so the edit form still
# shows exactly what was typed.
FREQ_FIELDS = {"freq1", "freq2", "freq3", "freq4"}
_FREQ_TOKEN_RE = re.compile(r'\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?')


def _clean_freq_display(v):
    """Tidy a stored frequency value for printing WITHOUT rewriting it.

    This used to pull number-like tokens out with a regex and re-join them,
    throwing away everything else. On a real certificate that produced:

        "2400-2483.5 MHz"         -> "2400-2483.5"     (unit silently dropped)
        "Freq 1: 900 MHz (Band 8)" -> "1 / 900 / 8"    (nonsense)
        "TX 450.500 RX 455.500"   -> "450.500 / 455.500"  (TX/RX labels lost)

    ...and nothing flagged it, so a wrong document went out to the licensee.

    The only transformation actually wanted was collapsing a value that
    repeats the same entry ("900 / 900" -> "900"). That is all this does now:
    split on the separators people actually type, drop blanks, remove exact
    repeats, and print everything else through untouched -- units, labels,
    ranges and all.
    """
    if not v:
        return ""
    s = str(v).replace("\r", "\n")
    parts = [p.strip() for p in re.split(r"[\n;,/]+", s)]
    parts = [re.sub(r"\s+", " ", p) for p in parts if p.strip()]
    if not parts:
        return re.sub(r"\s+", " ", str(v)).strip()
    seen = set()
    out = []
    for p in parts:
        key = p.casefold()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return " / ".join(out)


# ---------------------------------------------------------------- Fonts
# The PDF is drawn by reportlab, which only knows three fonts out of the box
# (Helvetica / Times-Roman / Courier). Anything else has to be registered from
# a real font file first -- and if it isn't, reportlab silently falls back to
# Helvetica, so the Live Preview would show one font and the printed licence
# would come out in another.
#
# So instead of hard-coding a longer list and hoping, this looks for the fonts
# already installed on this PC (C:\Windows\Fonts on the office machines) and
# offers ONLY the ones it actually found and registered. The Design-mode
# dropdown is built from this list, which means every font you can pick is a
# font that will really print.
#
# Nothing is bundled with the app -- these are the machine's own fonts, so
# there is no font licensing question and nothing extra to install.
_FONT_DIRS = [
    r"C:\Windows\Fonts",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
    "/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"),
]

# display name -> (regular, bold, italic, bold-italic) file names to look for.
# Several spellings per family because the files differ between Windows
# versions and between Windows and Linux.
_FONT_FILES = {
    "Arial":           ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "Calibri":         ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
    "Cambria":         ("cambria.ttc", "cambriab.ttf", "cambriai.ttf", "cambriaz.ttf"),
    "Courier New":     ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
    "Georgia":         ("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf"),
    "Segoe UI":        ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    "Tahoma":          ("tahoma.ttf", "tahomabd.ttf", "tahoma.ttf", "tahomabd.ttf"),
    "Times New Roman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "Trebuchet MS":    ("trebuc.ttf", "trebucbd.ttf", "trebucit.ttf", "trebucbi.ttf"),
    "Verdana":         ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
    # Linux equivalents, so this works on a non-Windows machine too
    "Liberation Sans":  ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf",
                         "LiberationSans-Italic.ttf", "LiberationSans-BoldItalic.ttf"),
    "Liberation Serif": ("LiberationSerif-Regular.ttf", "LiberationSerif-Bold.ttf",
                         "LiberationSerif-Italic.ttf", "LiberationSerif-BoldItalic.ttf"),
    "DejaVu Sans":      ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf",
                         "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf"),
}

# What the browser should use to show the same font on screen.
_FONT_CSS = {
    "Helvetica":   "Arial, Helvetica, sans-serif",
    "Times-Roman": "'Times New Roman', Times, serif",
    "Courier":     "'Courier New', Courier, monospace",
}

# The three that need no font file and are always available.
_BUILTIN_FONTS = [
    {"name": "Helvetica",   "label": "Helvetica (built-in)"},
    {"name": "Times-Roman", "label": "Times Roman (built-in)"},
    {"name": "Courier",     "label": "Courier (built-in)"},
]

_FONT_CACHE = None


def _find_font_file(filename):
    for d in _FONT_DIRS:
        if not d or not os.path.isdir(d):
            continue
        direct = os.path.join(d, filename)
        if os.path.exists(direct):
            return direct
        # Linux keeps fonts in per-family subfolders
        for root, _dirs, files in os.walk(d):
            for f in files:
                if f.lower() == filename.lower():
                    return os.path.join(root, f)
    return None


def available_fonts():
    """Every font this machine can actually put in the PDF.

    Registers each family it finds (with its bold/italic variants so <b> keeps
    working) and returns [{name, label, css}] for the Design-mode dropdown.
    Cached -- scanning the font folders is slow and the answer can't change
    while the app is running.
    """
    global _FONT_CACHE
    if _FONT_CACHE is not None:
        return _FONT_CACHE

    fonts = [dict(f, css=_FONT_CSS.get(f["name"], "sans-serif")) for f in _BUILTIN_FONTS]
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except Exception:
        _FONT_CACHE = fonts
        return fonts

    for family, files in _FONT_FILES.items():
        reg = _find_font_file(files[0])
        if not reg:
            continue
        try:
            pdfmetrics.registerFont(TTFont(family, reg))
        except Exception:
            continue      # a .ttc or an unreadable file -- just skip this family
        variants = {"normal": family, "bold": family, "italic": family, "boldItalic": family}
        for key, idx, suffix in (("bold", 1, "-Bold"), ("italic", 2, "-Italic"), ("boldItalic", 3, "-BoldItalic")):
            path = _find_font_file(files[idx]) if idx < len(files) else None
            if not path or path == reg:
                continue
            try:
                pdfmetrics.registerFont(TTFont(family + suffix, path))
                variants[key] = family + suffix
            except Exception:
                pass
        try:
            pdfmetrics.registerFontFamily(
                family, normal=variants["normal"], bold=variants["bold"],
                italic=variants["italic"], boldItalic=variants["boldItalic"])
        except Exception:
            pass
        fonts.append({"name": family, "label": family,
                      "css": "'" + family + "', sans-serif"})

    _FONT_CACHE = fonts
    return fonts


def font_is_available(name):
    return any(f["name"] == name for f in available_fonts())


def _project_root():
    # this file lives in app/legacy/ -- the template/db files live two
    # levels up, next to start.bat (same convention as every other
    # project-root file lookup in this app, see app/routers/settings.py)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _template_path():
    return os.path.join(_project_root(), TEMPLATE_FILE)


_DEFAULT_TEMPLATE = {"page": {"width_pt": 612, "height_pt": 792}, "image": None, "boxes": []}


def load_template():
    path = _template_path()
    if not os.path.exists(path):
        return dict(_DEFAULT_TEMPLATE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return dict(_DEFAULT_TEMPLATE)


def save_template(data):
    with open(_template_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)


def load_default_template():
    path = os.path.join(_project_root(), DEFAULT_TEMPLATE_FILE)
    if not os.path.exists(path):
        return load_template()  # no factory copy shipped -- fall back to whatever's current
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return load_template()


def save_as_default(data):
    """'Set as My Default' -- overwrites the factory copy with whatever the
    current layout is, so 'Reset to Default' recalls this instead of the
    original Word-doc-extracted layout."""
    path = os.path.join(_project_root(), DEFAULT_TEMPLATE_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)


# ---------------------------------------------------------- layout history
# A simple named/versioned save history so a certain layout can be recalled
# later -- e.g. save "Long bond paper" before experimenting, or keep a
# handful of named layouts around for different document types. Stored as
# one JSON file (a list of {id, name, saved_at, data}) next to the template
# files; not meant for hundreds of entries, just a practical undo-across-
# sessions net plus a few named presets.
HISTORY_FILE = "print_template_history.json"


def _history_path():
    return os.path.join(_project_root(), HISTORY_FILE)


def load_history():
    path = _history_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_history(entries):
    with open(_history_path(), "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=1)


def add_history_entry(name, data):
    entries = load_history()
    entry_id = (max((e["id"] for e in entries), default=0)) + 1
    entry = {"id": entry_id, "name": (name or "Untitled layout").strip()[:80], "saved_at": datetime.datetime.now().isoformat(timespec="seconds")}
    entries.append(dict(entry, data=data))
    # keep the newest 30 -- this is a practical recall list, not an archive
    entries = entries[-30:]
    _save_history(entries)
    return entry


def get_history_entry(entry_id):
    for e in load_history():
        if e["id"] == entry_id:
            return e
    return None


def delete_history_entry(entry_id):
    entries = load_history()
    kept = [e for e in entries if e["id"] != entry_id]
    if len(kept) == len(entries):
        return False
    _save_history(kept)
    return True


def fetch_record(lic_id, include_deleted=False):
    """Load one record for printing.

    Deleted (trashed) records are NOT printable by default. Without the
    deleted_at filter a record that had been deleted could still be pulled up
    by id and printed as a perfectly valid-looking RSL certificate -- the
    printed document gave no hint that the record no longer exists.
    """
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    if include_deleted:
        row = conn.execute("SELECT * FROM licenses WHERE id = ?", (lic_id,)).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM licenses WHERE id = ? AND deleted_at IS NULL", (lic_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _format_date(v):
    if not v:
        return ""
    s = str(v)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            d = datetime.date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
            return d.strftime("%B %-d, %Y") if os.name != "nt" else d.strftime("%B %d, %Y").replace(" 0", " ")
        except ValueError:
            return s
    return s


def format_value(field, value):
    """Same formatting used for both the HTML Live Preview and the PDF
    export -- one place, so the two never drift apart."""
    if value in (None, ""):
        return ""
    if field in DATE_FIELDS:
        return _format_date(value)
    if field in FREQ_FIELDS:
        return _clean_freq_display(value)
    return str(value)


def formatted_fields(record):
    """Every DB column on this record, formatted for display -- the Live
    Preview page (JS) drops these straight into the template's boxes by
    field name, no client-side date-formatting logic to keep in sync."""
    return {k: format_value(k, v) for k, v in record.items()}


# ---------------------------------------------------------------- PDF export
def build_pdf(lic_id, batch_index=1, batch_total=1):
    """Renders the certificate to a PDF using the SAME template positions
    as the Live Preview, via reportlab (pure Python -- no Chrome/Word/Excel
    needed on the machine running this). Returns PDF bytes, or None if the
    record doesn't exist.

    batch_index/batch_total feed any "pagenum" box on the layout (e.g. a
    "(2/8)" marker placed via Design Mode) -- a single ad-hoc PDF export
    defaults to "(1/1)"; Mass Print (get_print_pdf_batch) passes this
    record's real position in the batch."""
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Paragraph
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

    record = fetch_record(lic_id)
    if not record:
        return None
    values = formatted_fields(record)
    tpl = load_template()
    page_w = tpl.get("page", {}).get("width_pt", 612)
    page_h = tpl.get("page", {}).get("height_pt", 792)

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(page_w, page_h))

    img_cfg = tpl.get("image")
    if img_cfg and img_cfg.get("data"):
        try:
            header, b64data = img_cfg["data"].split(",", 1)
            img_bytes = base64.b64decode(b64data)
            img = ImageReader(io.BytesIO(img_bytes))
            c.drawImage(
                img, img_cfg["x"], page_h - img_cfg["y"] - img_cfg["h"],
                width=img_cfg["w"], height=img_cfg["h"], mask="auto",
            )
        except Exception:
            pass  # a broken/missing stamp image should never block the whole PDF

    ALIGN = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT}
    _HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

    for box in tpl.get("boxes", []):
        cursor_y_top = page_h - box["y"]  # reportlab's origin is bottom-left; the template's is top-left
        # Line spacing -- how far apart wrapped/stacked lines sit, e.g.
        # compressed for a box packed with many frequency lines. 1.2 (20%
        # extra breathing room over the font size) is the same default
        # every box used before this was configurable.
        leading_mult = box.get("leading") or 1.2
        for para in box.get("paragraphs", []):
            markup_parts = []
            base_size = 10
            for run in para.get("runs", []):
                if run.get("type") == "br":
                    markup_parts.append("<br/>")
                    continue
                if run.get("type") == "field":
                    text = values.get(run.get("field"), "")
                elif run.get("type") == "pagenum":
                    # Batch page numbering ("(2/8)" etc.) -- batch_index/
                    # batch_total are only set when this PDF is one page of
                    # a Mass Print batch (see get_print_pdf_batch); a single
                    # ad-hoc PDF export just shows "(1/1)".
                    text = f"({batch_index}/{batch_total})"
                else:
                    text = run.get("text", "")
                if not text:
                    continue
                base_size = run.get("size", base_size)
                base_font = run.get("font", "Helvetica") or "Helvetica"
                if not font_is_available(base_font):
                    # A font saved into the layout on a PC that had it, opened
                    # on a PC that doesn't. Fall back rather than error -- the
                    # licence still prints, just in the default face.
                    base_font = "Helvetica"
                # A field like Frequency often has several TX/RX lines typed
                # with line breaks -- reportlab's markup only respects <br/>,
                # not a literal newline, so convert after escaping.
                escaped = saxutils.escape(text).replace("\n", "<br/>")
                if run.get("bold"):
                    escaped = f"<b>{escaped}</b>"
                color = run.get("color")
                color_attr = f' color="{color}"' if color and _HEX_RE.match(color) else ""
                markup_parts.append(f'<font face="{base_font}" size="{run.get("size", base_size)}"{color_attr}>{escaped}</font>')
            markup = "".join(markup_parts)
            if not markup.strip():
                continue
            style = ParagraphStyle(
                "box", fontName=base_font, fontSize=base_size, leading=base_size * leading_mult,
                alignment=ALIGN.get(para.get("align", "left"), TA_LEFT),
            )
            p = Paragraph(markup, style)
            w, h = p.wrap(box["w"], box["h"])
            cursor_y_top -= h
            p.drawOn(c, box["x"], cursor_y_top)

    c.showPage()
    c.save()
    return buf.getvalue()
