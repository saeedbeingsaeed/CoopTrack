from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import deletion, demo, metrics


@login_not_required
def landing(request):
    if request.user.is_authenticated:
        return redirect("tracker:board")
    return render(request, "landing.html")


@login_not_required
@require_POST
def start_demo(request):
    if request.user.is_authenticated:
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


def settings_page(request):
    return render(request, "accounts/settings.html")


def delete_account(request):
    # GET asks to confirm, POST with "delete" does it.
    user = request.user
    if user.is_demo:
        return redirect("settings")
    error = None
    if request.method == "POST":
        if request.POST.get("confirm", "").strip().lower() == "delete":
            deletion.delete_account(request, user)
            messages.success(request, "Your account and everything in it have been deleted.")
            return redirect("landing")
        error = "Type delete to confirm."
    return render(request, "accounts/delete_account.html", {"error": error})
