"""
End-to-end: a real browser drives the real app, JavaScript included.

    pytest -m e2e        (needs `playwright install chromium` once, and the CSS built)
"""

import datetime

import pytest
from playwright.sync_api import Page, expect

from accounts.models import User
from tracker.models import Application, Stage

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def column(page: Page, stage):
    return page.locator(f"[data-board-list][data-stage='{stage.value}']")


def test_sign_up_add_drag_and_review(page: Page, live_server):
    # Sign up from the landing page.
    page.goto(live_server.url)
    page.get_by_role("link", name="Create a free account").click()
    page.get_by_label("Email").fill("ada@example.com")
    page.get_by_label("Password").fill("a-long-passphrase-9")
    page.get_by_role("button", name="Create account").click()
    expect(page.get_by_text("Your board is empty")).to_be_visible()

    # Add an application.
    page.get_by_role("link", name="Add your first application").click()
    page.get_by_label("Company").fill("Shopify")
    page.get_by_label("Role").fill("Backend Developer Intern")
    page.get_by_label("Stage").select_option(label="Applied")
    deadline = datetime.date.today() + datetime.timedelta(days=2)
    page.get_by_label("Deadline").fill(deadline.isoformat())
    page.get_by_role("button", name="Add application").click()
    expect(page.get_by_text("Added as Applied")).to_be_visible()

    # It's on the board in Applied. Drag it to Interview; it saves in the background.
    page.get_by_role("link", name="Board", exact=True).click()
    card = page.locator(".board-card", has_text="Shopify")
    expect(column(page, Stage.APPLIED).locator(".board-card")).to_have_count(1)
    card.drag_to(column(page, Stage.INTERVIEW))
    expect(page.get_by_text("Shopify moved to Interview.")).to_be_visible()
    expect(column(page, Stage.INTERVIEW).locator(".board-card", has_text="Shopify")).to_be_visible()
    page.wait_for_load_state("networkidle")  # the board refreshes itself after a move

    # Keyboard: open the card's Move menu and move it to Offer without the mouse.
    application = Application.objects.get(company="Shopify")
    page.locator(f"#move-{application.pk}").focus()
    page.keyboard.press("Enter")
    page.get_by_role("button", name="Offer").focus()
    page.keyboard.press("Enter")
    expect(column(page, Stage.OFFER).locator(".board-card", has_text="Shopify")).to_be_visible()
    expect(page.locator(f"#move-{application.pk}")).to_be_focused()

    application.refresh_from_db()
    assert application.stage == Stage.OFFER
    assert [c.to_stage for c in application.history.order_by("changed_at")] == [
        Stage.APPLIED,
        Stage.INTERVIEW,
        Stage.OFFER,
    ]

    # The table finds it, and says so when nothing matches.
    page.get_by_role("link", name="Table", exact=True).click()
    page.get_by_label("Search applications").fill("shop")
    expect(page.locator("#results tbody tr")).to_have_count(1)
    page.get_by_label("Search applications").fill("zzz")
    expect(page.get_by_text("No applications match")).to_be_visible()

    # Stats count it.
    page.get_by_role("link", name="Stats", exact=True).click()
    expect(page.get_by_text("1 of 1 applications heard back")).to_be_visible()


def test_failed_drag_puts_the_card_back(page: Page, live_server, django_user_model):
    user = django_user_model.objects.create_user(email="bo@example.com", password="a-long-passphrase-9")
    Application.objects.create(user=user, company="RBC", role="Analyst", stage=Stage.APPLIED)
    page.goto(f"{live_server.url}/accounts/login/")
    page.get_by_label("Email").fill(user.email)
    page.get_by_label("Password").fill("a-long-passphrase-9")
    page.get_by_role("button", name="Sign in").click()

    page.route("**/stage/", lambda route: route.fulfill(status=500))
    page.locator(".board-card", has_text="RBC").drag_to(column(page, Stage.OFFER))

    expect(page.get_by_text("Couldn't move RBC")).to_be_visible()
    expect(column(page, Stage.APPLIED).locator(".board-card", has_text="RBC")).to_be_visible()
    assert Application.objects.get(company="RBC").stage == Stage.APPLIED


def test_try_the_demo(page: Page, live_server):
    page.goto(live_server.url)
    page.get_by_role("button", name="Try the demo").click()

    expect(page.get_by_text("You're exploring a demo")).to_be_visible()
    expect(page.locator(".board-card")).not_to_have_count(0)
    assert User.objects.get().is_demo
