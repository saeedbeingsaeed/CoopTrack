import json

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from tracker import reminders

from . import deletion, demo, metrics
from .context_processors import email_sending_enabled
from .forms import ReminderSettingsForm


@login_not_required
def landing(request):
    if request.user.is_authenticated:
        return redirect("tracker:board")
    return render(request, "landing.html")


@login_not_required
@require_POST  # creating an account is a state change, so it's a POST with a CSRF token
def start_demo(request):
    """The landing page's "Try the demo" button."""
    if request.user.is_authenticated:
        # Never swap a signed-in user (real or demo) for a new demo account.
        return redirect("tracker:board")
    if demo.too_many_recent_demos():
        messages.error(request, "Lots of people are trying the demo right now. Please try again in a few minutes.")
        return redirect("landing")
    user = demo.create_demo_user()
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect("tracker:board")


@staff_member_required
def metrics_page(request):
    return render(request, "accounts/metrics.html", {"metrics": metrics.collect()})


@login_not_required
def privacy(request):
    return render(request, "privacy.html", {"contact_email": settings.CONTACT_EMAIL})


@login_not_required
def healthz(request):
    # Render pings this to decide the service is up. It deliberately skips the
    # database so a slow or paused database can't make the deploy look broken.
    return HttpResponse("ok", content_type="text/plain")


# --- Settings and reminders -----------------------------------------------------


def settings_page(request):
    # Not `request.POST or None`: an unticked checkbox sends nothing, and an empty
    # POST must still count as a submitted form (it means "turn reminders off").
    form = ReminderSettingsForm(request.POST if request.method == "POST" else None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        state = "on" if form.instance.reminders_enabled else "off"
        message = f"Email reminders turned {state}."
        if request.headers.get("HX-Request") == "true":
            response = HttpResponse(status=204)
            response["HX-Trigger"] = json.dumps({"toast": {"message": message}})
            return response
        messages.success(request, message)
        return redirect("settings")
    return render(
        request,
        "accounts/settings.html",
        {
            "form": form,
            "email_enabled": email_sending_enabled(),
            "email_verified": reminders.has_verified_email(request.user),
        },
    )


def delete_account(request):
    """Users delete their own account. GET asks; POST with the confirmation word does it."""
    user = request.user
    if user.is_demo:
        return redirect("settings")  # demo accounts are deleted when they sign out
    error = None
    if request.method == "POST":
        if request.POST.get("confirm", "").strip().lower() == "delete":
            deletion.delete_account(request, user)
            messages.success(request, "Your account and everything in it have been deleted.")
            return redirect("landing")
        error = "Type delete to confirm."
    return render(request, "accounts/delete_account.html", {"error": error})


def reminder_preview(request):
    """Shows today's reminder email for the signed-in user, exactly as it would be sent."""
    today = timezone.localdate()
    digests = reminders.build_digests([request.user], today)
    if not digests:
        return render(request, "accounts/reminder_preview_empty.html")
    return render(request, "email/reminder.html", reminders.email_context(digests[0], today))


# Mail apps' one-click "Unsubscribe" buttons POST here without cookies, so there's
# no CSRF token. That's safe: the signed token in the URL is the proof of identity,
# and the only thing this can do is turn reminders off.
@csrf_exempt
@login_not_required
def unsubscribe(request, token):
    user = reminders.user_from_unsubscribe_token(token)
    if user is None:
        return render(request, "accounts/unsubscribe.html", {"invalid": True}, status=404)
    if request.method == "POST":
        user.reminders_enabled = False
        user.save(update_fields=["reminders_enabled"])
        return render(request, "accounts/unsubscribe.html", {"done": True, "email": user.email})
    # GET only asks. Link scanners in mail apps open links automatically, and
    # that alone mustn't unsubscribe anyone.
    return render(request, "accounts/unsubscribe.html", {"email": user.email})
