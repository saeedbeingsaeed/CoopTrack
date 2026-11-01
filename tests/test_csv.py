import csv
import datetime
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from tracker.models import Application, ResumeVersion, Stage

pytestmark = pytest.mark.django_db


@pytest.fixture
def signed_in(client, user):
    client.force_login(user)
    return client


def upload(client, text, name="apps.csv"):
    data = text.encode("utf-8") if isinstance(text, str) else text
    return client.post(reverse("tracker:import"), {"file": SimpleUploadedFile(name, data, content_type="text/csv")})


def read_export(client):
    response = client.get(reverse("tracker:export"))
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"]
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))


# --- Export ----------------------------------------------------------------------


def test_export_has_headers_and_my_rows_only(signed_in, user, other_user, make_application):
    resume = ResumeVersion.objects.create(user=user, name="SWE v1")
    make_application(
        user, company="Shopify", stage=Stage.INTERVIEW, deadline=datetime.date(2026, 11, 1), resume_version=resume
    )
    make_application(other_user, company="Theirs")

    rows = read_export(signed_in)

    assert rows[0][:3] == ["Company", "Role", "Stage"]
    assert len(rows) == 2
    assert rows[1][0] == "Shopify"
    assert rows[1][2] == "Interview"
    assert "2026-11-01" in rows[1]
    assert "SWE v1" in rows[1]


def test_export_neutralises_spreadsheet_formulas(signed_in, user, make_application):
    make_application(user, company='=HYPERLINK("http://evil")', notes="+1 referral")

    row = read_export(signed_in)[1]

    assert row[0] == '\'=HYPERLINK("http://evil")'
    assert row[-1] == "'+1 referral"


# --- Import ----------------------------------------------------------------------

GOOD = """Company,Role,Stage,Date applied,Deadline,Resume version,Notes
Shopify,Backend Intern,Interview,2026-09-01,,SWE v3,Referral
RBC,Data Analyst,applied,09/15/2026,2026-11-01,swe V3,
Kinaxis,Developer,,,,,
"""


def test_import_creates_applications(signed_in, user):
    response = upload(signed_in, GOOD)

    assert response.url == reverse("tracker:board")
    apps = {a.company: a for a in Application.objects.filter(user=user)}
    assert set(apps) == {"Shopify", "RBC", "Kinaxis"}
    assert apps["Shopify"].stage == Stage.INTERVIEW
    assert apps["RBC"].date_applied == datetime.date(2026, 9, 15)
    assert apps["Kinaxis"].stage == Stage.SAVED
    # "SWE v3" and "swe V3" are one resume version.
    assert ResumeVersion.objects.filter(user=user).count() == 1
    assert apps["RBC"].resume_version == apps["Shopify"].resume_version


def test_imported_history_is_dated_to_the_application_date(signed_in, user):
    upload(signed_in, GOOD)

    change = Application.objects.get(company="Shopify").history.get()
    assert change.changed_at.date() == datetime.date(2026, 9, 1)
    assert change.to_stage == Stage.INTERVIEW


def test_import_is_all_or_nothing(signed_in, user):
    text = (
        "Company,Role,Stage,Link to posting\nGood,Role,Applied,\n,Missing company,,\nBad,Stage,Maybe,\nBad,Link,,nope\n"
    )

    response = upload(signed_in, text)

    assert not Application.objects.exists()
    errors = response.context["row_errors"]
    assert {row for row, _, _ in errors} == {3, 4, 5}
    content = response.content.decode()
    assert "Nothing was imported" in content
    assert "Row 4, Stage" in content


def test_importing_the_same_file_twice_skips_duplicates(signed_in, user):
    upload(signed_in, GOOD)
    response = upload(signed_in, GOOD)

    assert Application.objects.filter(user=user).count() == 3
    assert "Skipped 3" in str(list(response.wsgi_request._messages))


def test_export_then_import_round_trips(signed_in, client, user, other_user, make_application):
    make_application(user, company="Shopify", role="Intern", stage=Stage.OFFER, location="Toronto", pay="$30/hr")
    exported = signed_in.get(reverse("tracker:export")).content

    client.force_login(other_user)
    upload(client, exported)

    copy = Application.objects.get(user=other_user)
    assert (copy.company, copy.role, copy.stage, copy.location, copy.pay) == (
        "Shopify",
        "Intern",
        Stage.OFFER,
        "Toronto",
        "$30/hr",
    )


def test_import_accepts_header_variations_and_excel_bom(signed_in, user):
    text = "﻿company , Job Title,STATUS\nAcme,Intern,OA\n"

    upload(signed_in, text)

    application = Application.objects.get(user=user)
    assert (application.role, application.stage) == ("Intern", Stage.ONLINE_ASSESSMENT)


@pytest.mark.parametrize(
    "content, message",
    [
        ("", "empty"),
        ("Name,Title\nAcme,Intern\n", "must contain column headers"),
        ("Company,Role\n", "no applications"),
        ("Company,Role\nCaf\xe9,Barista\n".encode("latin-1"), "UTF-8"),
    ],
)
def test_import_explains_file_problems(signed_in, content, message):
    response = upload(signed_in, content)

    assert message in str(response.context["form"].errors["file"])
    assert not Application.objects.exists()


def test_import_rejects_big_files(signed_in):
    response = upload(signed_in, "Company,Role\n" + "Acme,Intern\n" * 100_000)
    assert "over 1 MB" in str(response.context["form"].errors["file"])


def test_import_cannot_link_to_another_users_resume(signed_in, user, other_user):
    theirs = ResumeVersion.objects.create(user=other_user, name="Secret")

    upload(signed_in, "Company,Role,Resume version\nAcme,Intern,Secret\n")

    mine = Application.objects.get(user=user).resume_version
    assert mine != theirs
    assert mine.user == user
