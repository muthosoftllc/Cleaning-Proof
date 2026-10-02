"""Professional PDF proof-of-cleaning report (ReportLab)."""
import io
from datetime import datetime

from django.utils import timezone
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing, Line, PolyLine
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from apps.jobs.models import Photo

OK, WARN, BAD = colors.HexColor("#15803D"), colors.HexColor("#B45309"), colors.HexColor("#B91C1C")


def status_mark(status: str) -> Drawing:
    """Vector check/cross marks: standard PDF fonts have no ✓/✗ glyphs and
    embedding a symbol font isn't worth it."""
    d = Drawing(10, 10)
    if status == "done":
        d.add(PolyLine([1, 5, 4, 2, 9, 9], strokeColor=OK, strokeWidth=1.6))
    elif status == "skipped":
        d.add(Line(2, 5, 8, 5, strokeColor=WARN, strokeWidth=1.6))
    else:
        d.add(Line(2, 2, 8, 8, strokeColor=BAD, strokeWidth=1.6))
        d.add(Line(2, 8, 8, 2, strokeColor=BAD, strokeWidth=1.6))
    return d


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


def _brand(snapshot) -> colors.Color:
    try:
        return colors.HexColor(snapshot["company"].get("brand_color") or "#0F766E")
    except ValueError:
        return colors.HexColor("#0F766E")


def render_report_pdf(report) -> bytes:
    from zoneinfo import ZoneInfo

    with timezone.override(ZoneInfo(report.organization.timezone or "UTC")):
        return _render(report)


def _render(report) -> bytes:
    snap = report.snapshot
    brand = _brand(snap)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=20, alignment=0, spaceAfter=2, textColor=brand)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=4, textColor=brand)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10, textColor=colors.HexColor("#555555"))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
        title=f"Cleaning Proof {report.number}", author=snap["company"]["name"],
    )
    story = []

    # Header: company, title, QR.
    org = report.organization
    logo = None
    if org.logo:
        try:
            logo = Image(org.logo.open("rb"), width=22 * mm, height=22 * mm, kind="proportional")
        except Exception:
            logo = None
    header_text = [
        Paragraph(snap["company"]["name"], ParagraphStyle("co", parent=body, fontSize=11, textColor=colors.grey)),
        Paragraph("Proof of Cleaning", h1),
        Paragraph(f"Report <b>{report.number}</b> · revision {report.revision}", body),
    ]
    header = Table(
        [[logo or "", header_text, _qr(report.verify_url)]],
        colWidths=[26 * mm if logo else 1 * mm, None, 30 * mm],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [header, Spacer(1, 4 * mm)]

    job = snap["job"]
    details = [
        ["Property", snap["property"]["name"], "Cleaner", job["cleaner"] or "—"],
        ["Customer", snap["customer"]["name"] or "—", "Date", _fmt(job["completed_at"], "%d %b %Y")],
        ["Started", _fmt(job["started_at"]), "Finished", _fmt(job["completed_at"])],
        ["Duration", f"{job['duration_minutes']} min" if job["duration_minutes"] is not None else "—",
         "Location", "Recorded on site" if job["location_verified"] else "Not recorded"],
    ]
    table = Table(details, colWidths=[24 * mm, 63 * mm, 24 * mm, 63 * mm])
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.grey),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F6F8F8")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    summary = snap["summary"]
    story += [table, Spacer(1, 3 * mm), Paragraph(
        f"<b>{summary['tasks_done']}/{summary['tasks_total']}</b> tasks completed · "
        f"<b>{summary['photos']}</b> photo(s) · <b>{summary['issues']}</b> issue(s) recorded", body)]

    if snap.get("missing_photo_ids"):
        story.append(Paragraph(
            f"<font color='#B45309'>Note: {len(snap['missing_photo_ids'])} photo(s) captured on the device "
            f"were never uploaded and are not included.</font>", body))

    # Checklist.
    story.append(Paragraph("Checklist", h2))
    for section in snap["checklist"]:
        rows = [[Paragraph(f"<b>{section['section']}</b>", body), ""]]
        for task in section["tasks"]:
            mark = status_mark(task["status"])
            note = f" <font size=8 color='#666666'>— {task['note']}</font>" if task["note"] else ""
            optional = "" if task["required"] else " <font size=8 color='#888888'>(optional)</font>"
            rows.append([mark, Paragraph(f"{task['title']}{optional}{note}", body)])
        t = Table(rows, colWidths=[8 * mm, None])
        t.setStyle(TableStyle([
            ("SPAN", (0, 0), (1, 0)), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#DDDDDD")),
        ]))
        story += [KeepTogether(t), Spacer(1, 2 * mm)]

    # Issues.
    if snap["issues"]:
        story.append(Paragraph("Issues &amp; existing damage", h2))
        rows = [["Room", "Description", "Severity", "Status"]]
        for issue in snap["issues"]:
            rows.append([
                issue["room"] or "—",
                Paragraph(f"{issue['description']}<br/><font size=8 color='#666666'>{issue['phase']} · "
                          f"{_fmt(issue['reported_at'])}</font>", body),
                issue["severity"].title(), issue["resolution"],
            ])
        t = Table(rows, colWidths=[28 * mm, None, 20 * mm, 26 * mm], repeatRows=1)
        t.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F5")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t)

    # Photos (two per row, display copies without EXIF).
    if snap["photos"]:
        story.append(Paragraph("Photo evidence", h2))
        photos = {str(p.id): p for p in Photo.objects.filter(job_id=job["id"])}
        cells = []
        for meta in snap["photos"]:
            photo = photos.get(meta["id"])
            if photo is None or not (photo.thumbnail or photo.file):
                continue
            try:
                img = Image((photo.thumbnail or photo.file).open("rb"), width=82 * mm, height=60 * mm,
                            kind="proportional")
            except Exception:
                continue
            label = " · ".join(x for x in [meta["kind"].title(), meta["room"], _fmt(meta["captured_at"])] if x)
            cells.append([img, Paragraph(label, small)])
        rows = []
        for i in range(0, len(cells), 2):
            pair = cells[i:i + 2] + ([["", ""]] if len(cells[i:i + 2]) == 1 else [])
            rows.append([pair[0][0], pair[1][0]])
            rows.append([pair[0][1], pair[1][1]])
        if rows:
            t = Table(rows, colWidths=[87 * mm, 87 * mm])
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
            story.append(t)

    if job["notes"]:
        story += [Paragraph("Notes", h2), Paragraph(job["notes"].replace("\n", "<br/>"), body)]

    story.append(Paragraph("Customer sign-off", h2))
    if snap["signatures"] or report.approved_at:
        for sig in snap["signatures"]:
            story.append(Paragraph(f"Signed by <b>{sig['signer_name']}</b> ({sig['source']}) on "
                                   f"{_fmt(sig['signed_at'])}", body))
        if report.approved_at and not snap["signatures"]:
            story.append(Paragraph(f"Approved by <b>{report.approved_by_name}</b> on "
                                   f"{timezone.localtime(report.approved_at):%d %b %Y, %H:%M}", body))
    else:
        story.append(Paragraph("Not signed.", body))

    story += [
        Spacer(1, 6 * mm),
        Paragraph(f"Verify this report: {report.verify_url}", small),
        Paragraph(f"Integrity (SHA-256): {report.content_hash or 'pending'}", small),
        Paragraph(f"Generated {_fmt(snap['generated_at'])} · Powered by Cleaning Proof", small),
    ]

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.grey)
        canvas.drawString(16 * mm, 9 * mm, f"{report.number} · {snap['company']['name']}")
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
