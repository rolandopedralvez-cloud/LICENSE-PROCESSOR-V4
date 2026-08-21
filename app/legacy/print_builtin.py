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


def fetch_record(lic_id):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM licenses WHERE id = ?", (lic_id,)).fetchone()
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
    return str(value)


def formatted_fields(record):
    """Every DB column on this record, formatted for display -- the Live
    Preview page (JS) drops these straight into the template's boxes by
    field name, no client-side date-formatting logic to keep in sync."""
    return {k: format_value(k, v) for k, v in record.items()}


# ---------------------------------------------------------------- PDF export
def build_pdf(lic_id):
    """Renders the certificate to a PDF using the SAME template positions
    as the Live Preview, via reportlab (pure Python -- no Chrome/Word/Excel
    needed on the machine running this). Returns PDF bytes, or None if the
    record doesn't exist."""
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

    for box in tpl.get("boxes", []):
        cursor_y_top = page_h - box["y"]  # reportlab's origin is bottom-left; the template's is top-left
        for para in box.get("paragraphs", []):
            markup_parts = []
            base_size = 10
            for run in para.get("runs", []):
                if run.get("type") == "br":
                    markup_parts.append("<br/>")
                    continue
                if run.get("type") == "field":
                    text = values.get(run.get("field"), "")
                else:
                    text = run.get("text", "")
                if not text:
                    continue
                base_size = run.get("size", base_size)
                base_font = run.get("font", "Helvetica") or "Helvetica"
                if base_font not in ("Helvetica", "Times-Roman", "Courier"):
                    base_font = "Helvetica"  # unknown/legacy font name -- fall back rather than error
                escaped = saxutils.escape(text)
                if run.get("bold"):
                    escaped = f"<b>{escaped}</b>"
                markup_parts.append(f'<font face="{base_font}" size="{run.get("size", base_size)}">{escaped}</font>')
            markup = "".join(markup_parts)
            if not markup.strip():
                continue
            style = ParagraphStyle(
                "box", fontName=base_font, fontSize=base_size, leading=base_size * 1.2,
                alignment=ALIGN.get(para.get("align", "left"), TA_LEFT),
            )
            p = Paragraph(markup, style)
            w, h = p.wrap(box["w"], box["h"])
            cursor_y_top -= h
            p.drawOn(c, box["x"], cursor_y_top)

    c.showPage()
    c.save()
    return buf.getvalue()
