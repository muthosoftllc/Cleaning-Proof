"""Professional PDF proof-of-cleaning report (ReportLab).

Security note: ReportLab ``Paragraph`` parses a markup language that supports
``<img src=...>`` (local files and URLs) and fails hard on malformed tags.
Every piece of user-controlled text MUST go through :func:`esc` before it is
placed in markup. Images are only ever loaded from our own storage.
"""

import io
from datetime import datetime
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from django.utils import timezone
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing, Line, PolyLine
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.jobs.models import Photo
from apps.organizations.models import HEX_COLOR

DEFAULT_BRAND = "#0F766E"
OK, WARN, BAD = colors.HexColor("#15803D"), colors.HexColor("#B45309"), colors.HexColor("#B91C1C")
GREY_BG, LINE = colors.HexColor("#F6F8F8"), colors.HexColor("#DDDDDD")
CONTENT_WIDTH = A4[0] - 32 * mm


def esc(value) -> str:
    """Escape text for ReportLab paragraph markup."""
    return escape("" if value is None else str(value))


def _fmt(iso: str | None, fmt="%d %b %Y, %H:%M") -> str:
    if not iso:
        return "—"
    return timezone.localtime(datetime.fromisoformat(iso)).strftime(fmt)


def _qr(url: str, size=28 * mm) -> Drawing:
    widget = QrCodeWidget(url)
    x1, y1, x2, y2 = widget.getBounds()
    drawing = Drawing(size, size, transform=[size / (x2 - x1), 0, 0, size / (y2 - y1), 0, 0])
    drawing.add(widget)
    return drawing


def status_mark(status: str) -> Drawing:
    """Vector check/cross marks: standard PDF fonts have no ✓/✗ glyphs."""
    d = Drawing(10, 10)
    if status == "done":
        d.add(PolyLine([1, 5, 4, 2, 9, 9], strokeColor=OK, strokeWidth=1.6))
    elif status == "skipped":
        d.add(Line(2, 5, 8, 5, strokeColor=WARN, strokeWidth=1.6))
    else:
        d.add(Line(2, 2, 8, 8, strokeColor=BAD, strokeWidth=1.6))
        d.add(Line(2, 8, 8, 2, strokeColor=BAD, strokeWidth=1.6))
    return d


def _stored_image(field, width, height) -> Image | None:
    """Load an image from our storage into memory (closing the handle)."""
    if not field:
        return None
    try:
        with field.open("rb") as fh:
            data = io.BytesIO(fh.read())
        return Image(data, width=width, height=height, kind="proportional")
    except (OSError, ValueError):
        return None


class _Styles:
    def __init__(self, brand):
        base = getSampleStyleSheet()
        self.body = ParagraphStyle("body", parent=base["BodyText"], fontSize=9.5, leading=13)
        self.small = ParagraphStyle(
            "small", parent=self.body, fontSize=8, leading=10, textColor=colors.HexColor("#555555")
        )
        self.company = ParagraphStyle("co", parent=self.body, fontSize=11, textColor=colors.grey)
        self.h1 = ParagraphStyle("h1", parent=base["Title"], fontSize=20, alignment=0, spaceAfter=2, textColor=brand)
        self.h2 = ParagraphStyle(
            "h2", parent=base["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=4, textColor=brand
        )


class ReportPdf:
    """Builds the story for one report; each section is a small method."""

    def __init__(self, report):
        self.report = report
        self.snap = report.snapshot
        brand_hex = self.snap["company"].get("brand_color") or DEFAULT_BRAND
        try:
            HEX_COLOR(brand_hex)
        except Exception:
            brand_hex = DEFAULT_BRAND
        self.brand = colors.HexColor(brand_hex)
        self.s = _Styles(self.brand)

    def p(self, markup: str, style=None) -> Paragraph:
        """Paragraph from *trusted* markup. Interpolate user text via esc()."""
        return Paragraph(markup, style or self.s.body)

    def build(self) -> bytes:
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=16 * mm,
            rightMargin=16 * mm,
            topMargin=14 * mm,
            bottomMargin=16 * mm,
            title=f"Cleaning Proof {self.report.number}",
            author=self.snap["company"]["name"],
        )
        story = [
            *self.header(),
            *self.details(),
            *self.checklist(),
            *self.issues(),
            *self.photos(),
            *self.notes(),
            *self.signoff(),
            *self.verification(),
        ]
        doc.build(story, onFirstPage=self.footer, onLaterPages=self.footer)
        return buf.getvalue()

    # --- sections ---------------------------------------------------------
    def header(self):
        report = self.report
        logo = _stored_image(report.organization.logo, 22 * mm, 22 * mm)
        text = [
            self.p(esc(self.snap["company"]["name"]), self.s.company),
            self.p("Proof of Cleaning", self.s.h1),
            self.p(f"Report <b>{esc(report.number)}</b> · revision {report.revision}"),
        ]
        table = Table(
            [[logo or "", text, _qr(report.verify_url)]], colWidths=[26 * mm if logo else 1 * mm, None, 30 * mm]
        )
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        return [table, Spacer(1, 4 * mm)]

    def details(self):
        job, summary = self.snap["job"], self.snap["summary"]
        duration = f"{job['duration_minutes']} min" if job["duration_minutes"] is not None else "—"
        rows = [
            ["Property", self.snap["property"]["name"], "Cleaner", job["cleaner"] or "—"],
            ["Customer", self.snap["customer"]["name"] or "—", "Date", _fmt(job["completed_at"], "%d %b %Y")],
            ["Started", _fmt(job["started_at"]), "Finished", _fmt(job["completed_at"])],
            ["Duration", duration, "Location", "Recorded on site" if job["location_verified"] else "Not recorded"],
        ]
        # Plain strings in table cells are drawn as text, not parsed as markup.
        table = Table(rows, colWidths=[24 * mm, 63 * mm, 24 * mm, 63 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
                    ("TEXTCOLOR", (2, 0), (2, -1), colors.grey),
                    ("BACKGROUND", (0, 0), (-1, -1), GREY_BG),
                    ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story = [
            table,
            Spacer(1, 3 * mm),
            self.p(
                f"<b>{summary['tasks_done']}/{summary['tasks_total']}</b> tasks completed · "
                f"<b>{summary['photos']}</b> photo(s) · <b>{summary['issues']}</b> issue(s) recorded"
            ),
        ]
        missing = len(self.snap.get("missing_photo_ids") or [])
        if missing:
            story.append(
                self.p(
                    f"<font color='#B45309'>Note: {missing} photo(s) captured on the device "
                    "were never uploaded and are not included.</font>"
                )
            )
        return story

    def checklist(self):
        story = [self.p("Checklist", self.s.h2)]
        for section in self.snap["checklist"]:
            rows = [[self.p(f"<b>{esc(section['section'])}</b>"), ""]]
            for task in section["tasks"]:
                optional = "" if task["required"] else " <font size=8 color='#888888'>(optional)</font>"
                note = f" <font size=8 color='#666666'>— {esc(task['note'])}</font>" if task["note"] else ""
                rows.append([status_mark(task["status"]), self.p(f"{esc(task['title'])}{optional}{note}")])
            table = Table(rows, colWidths=[8 * mm, None])
            table.setStyle(
                TableStyle(
                    [
                        ("SPAN", (0, 0), (1, 0)),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE),
                    ]
                )
            )
            story += [KeepTogether(table), Spacer(1, 2 * mm)]
        return story

    def issues(self):
        if not self.snap["issues"]:
            return []
        rows = [["Room", "Description", "Severity", "Status"]] + [
            [
                issue["room"] or "—",
                self.p(
                    f"{esc(issue['description'])}<br/><font size=8 color='#666666'>"
                    f"{esc(issue['phase'])} · {_fmt(issue['reported_at'])}</font>"
                ),
                issue["severity"].title(),
                issue["resolution"],
            ]
            for issue in self.snap["issues"]
        ]
        table = Table(rows, colWidths=[28 * mm, None, 20 * mm, 26 * mm], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F5")),
                    ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return [self.p("Issues &amp; existing damage", self.s.h2), table]

    def photos(self):
        metas = self.snap["photos"]
        if not metas:
            return []
        # Only photos frozen in the snapshot, only from this job, only the
        # EXIF-free display copies.
        stored = Photo.objects.filter(job_id=self.snap["job"]["id"], id__in=[m["id"] for m in metas]).only(
            "id", "thumbnail", "file"
        )
        by_id = {str(p.id): p for p in stored}
        cells = []
        for meta in metas:
            photo = by_id.get(meta["id"])
            img = _stored_image(photo.thumbnail or photo.file, 82 * mm, 60 * mm) if photo else None
            if img is None:
                continue
            label = " · ".join(x for x in [meta["kind"].title(), meta["room"], _fmt(meta["captured_at"])] if x)
            cells.append((img, self.p(esc(label), self.s.small)))
        if not cells:
            return []
        rows = []
        for i in range(0, len(cells), 2):
            left, right = cells[i], cells[i + 1] if i + 1 < len(cells) else ("", "")
            rows += [[left[0], right[0]], [left[1], right[1]]]
        table = Table(rows, colWidths=[CONTENT_WIDTH / 2] * 2)
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
        return [self.p("Photo evidence", self.s.h2), table]

    def notes(self):
        notes = self.snap["job"]["notes"]
        if not notes:
            return []
        return [self.p("Notes", self.s.h2), self.p(esc(notes).replace("\n", "<br/>"))]

    def signoff(self):
        story = [self.p("Customer sign-off", self.s.h2)]
        signatures = self.snap["signatures"]
        story += [
            self.p(f"Signed by <b>{esc(sig['signer_name'])}</b> ({esc(sig['source'])}) on {_fmt(sig['signed_at'])}")
            for sig in signatures
        ]
        if self.report.approved_at and not signatures:
            story.append(
                self.p(
                    f"Approved by <b>{esc(self.report.approved_by_name)}</b> on "
                    f"{timezone.localtime(self.report.approved_at):%d %b %Y, %H:%M}"
                )
            )
        if len(story) == 1:
            story.append(self.p("Not signed."))
        return story

    def verification(self):
        report = self.report
        return [
            Spacer(1, 6 * mm),
            self.p(f"Verify this report: {esc(report.verify_url)}", self.s.small),
            self.p(f"Integrity (SHA-256): {esc(report.content_hash or 'pending')}", self.s.small),
            self.p(f"Generated {_fmt(self.snap['generated_at'])} · Powered by Cleaning Proof", self.s.small),
        ]

    def footer(self, canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.grey)
        # drawString renders literally; no markup parsing here.
        canvas.drawString(16 * mm, 9 * mm, f"{self.report.number} · {self.snap['company']['name']}")
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()


def render_report_pdf(report) -> bytes:
    """Render in the organization's timezone."""
    with timezone.override(ZoneInfo(report.organization.timezone or "UTC")):
        return ReportPdf(report).build()
