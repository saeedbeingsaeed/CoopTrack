"""
CSV export and import.

Import is all-or-nothing: every row is validated first, using the same form as
the "Add application" page, and nothing is saved unless every row is valid.
"""

import csv
import datetime
import io

from django.db import transaction
from django.utils import timezone

from .forms import ApplicationForm
from .models import Application, Stage

COLUMNS = [
    ("company", "Company"),
    ("role", "Role"),
    ("stage", "Stage"),
    ("date_applied", "Date applied"),
    ("deadline", "Deadline"),
    ("location", "Location"),
    ("pay", "Pay"),
    ("posting_url", "Link to posting"),
    ("resume_version", "Resume version"),
    ("notes", "Notes"),
]
MAX_ROWS = 1000
MAX_BYTES = 1024 * 1024  # 1 MB is roughly 5,000 rows; plenty for one job search


# --- Export ----------------------------------------------------------------------


def safe_cell(value):
    """
    Spreadsheet apps run cells that start with = + - @ as formulas (CSV injection),
    so prefix those with an apostrophe. Spreadsheets hide the apostrophe.
    """
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def write_csv(user, out):
    writer = csv.writer(out)
    writer.writerow([label for _, label in COLUMNS])
    applications = Application.objects.for_user(user).select_related("resume_version").order_by("created_at")
    for app in applications:
        writer.writerow(
            [
                safe_cell(app.company),
                safe_cell(app.role),
                app.get_stage_display(),
                app.date_applied.isoformat() if app.date_applied else "",
                app.deadline.isoformat() if app.deadline else "",
                safe_cell(app.location),
                safe_cell(app.pay),
                safe_cell(app.posting_url),
                safe_cell(app.resume_version.name if app.resume_version else ""),
                safe_cell(app.notes),
            ]
        )


# --- Import ----------------------------------------------------------------------


class CSVImportError(Exception):
    """A problem with the whole file (not a single row)."""


def _normalise(header):
    return " ".join(header.replace("_", " ").strip().lower().split())


# Accept our own headers, the field names, and a few obvious synonyms.
HEADER_ALIASES = {_normalise(label): field for field, label in COLUMNS}
HEADER_ALIASES |= {_normalise(field): field for field, _ in COLUMNS}
HEADER_ALIASES |= {
    "position": "role",
    "job title": "role",
    "title": "role",
    "url": "posting_url",
    "link": "posting_url",
}
HEADER_ALIASES |= {"applied": "date_applied", "resume": "resume_version", "status": "stage"}

STAGE_NAMES = {label.lower(): value for value, label in Stage.choices}
STAGE_NAMES |= {str(value): value for value in Stage.values} | {"oa": Stage.ONLINE_ASSESSMENT, "": Stage.SAVED}


def parse_stage(text):
    return STAGE_NAMES.get(text.strip().lower())


def read_rows(uploaded_file):
    """Decode the upload and return (rows as dicts keyed by field name)."""
    if uploaded_file.size > MAX_BYTES:
        raise CSVImportError("That file is over 1 MB. Split it into smaller files.")
    raw = uploaded_file.read()
    try:
        text = raw.decode("utf-8-sig")  # -sig strips the byte-order mark Excel adds
    except UnicodeDecodeError:
        raise CSVImportError("That file isn't UTF-8 text. In Excel, use Save As → “CSV UTF-8”.") from None

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise CSVImportError("That file is empty.")
    mapping = {header: HEADER_ALIASES.get(_normalise(header)) for header in reader.fieldnames if header}
    found = set(mapping.values())
    if not {"company", "role"} <= found:
        raise CSVImportError("The first row must contain column headers, including “Company” and “Role”.")

    rows = []
    for row in reader:
        values = {field: (row.get(header) or "").strip() for header, field in mapping.items() if field}
        if any(values.values()):  # skip blank lines
            rows.append(values)
        if len(rows) > MAX_ROWS:
            raise CSVImportError(f"That file has more than {MAX_ROWS} applications. Split it into smaller files.")
    if not rows:
        raise CSVImportError("That file has headers but no applications.")
    return rows


def import_csv(user, uploaded_file):
    """
    Returns (imported_count, skipped_count, errors). If errors is non-empty,
    nothing was saved. Raises CSVImportError for problems with the whole file.
    """
    rows = read_rows(uploaded_file)
    forms, errors = [], []
    for number, row in enumerate(rows, start=2):  # row 1 is the header
        stage = parse_stage(row.get("stage", ""))
        if stage is None:
            errors.append((number, "Stage", f"“{row['stage']}” isn't a stage. Use one of: {', '.join(Stage.labels)}."))
            continue
        data = {**row, "stage": stage, "new_resume": row.get("resume_version", "")}
        data.pop("resume_version", None)
        form = ApplicationForm(data=data, user=user)
        if form.is_valid():
            forms.append(form)
        else:
            for field, messages in form.errors.items():
                label = form.fields[field].label if field in form.fields else "Row"
                errors.extend((number, label, message) for message in messages)
    if errors:
        return 0, 0, errors

    # Skip rows that already exist, so importing the same file twice doesn't duplicate.
    existing = {
        (c.lower(), r.lower(), d)
        for c, r, d in Application.objects.for_user(user).values_list("company", "role", "date_applied")
    }
    imported = skipped = 0
    with transaction.atomic():
        for form in forms:
            key = _dedupe_key(form.cleaned_data)
            if key in existing:
                skipped += 1
                continue
            existing.add(key)
            application = form.save()
            _backdate_history(application)
            imported += 1
    return imported, skipped, []


def _dedupe_key(data):
    # Mirror Application.save(): past Saved with no date means "applied today".
    date = data["date_applied"]
    if date is None and data["stage"] != Stage.SAVED:
        date = timezone.localdate()
    return (data["company"].lower(), data["role"].lower(), date)


def _backdate_history(application):
    """
    An imported application wasn't really created today. Date its first history
    row to the day it was applied to, so time-in-stage and stats make sense.
    """
    if application.date_applied:
        when = timezone.make_aware(datetime.datetime.combine(application.date_applied, datetime.time(12)))
        application.history.update(changed_at=min(when, timezone.now()))
