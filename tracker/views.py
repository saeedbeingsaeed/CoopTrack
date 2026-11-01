import json

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Max, Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, FormView, ListView, TemplateView, UpdateView
from django.views.generic.detail import SingleObjectMixin

from . import csv_io, stats
from .domain.errors import CoopTrackError, InvalidMove, JobSearchError, NotFound
from .domain.ranking import DEFAULT_RANKING, RANKINGS
from .forms import ApplicationForm, ImportForm, ResumeVersionForm
from .models import Application, ResumeVersion, Stage, Via
from .scoping import OwnedObjectMixin
from .services import ApplicationService


def service_for(request):
    return ApplicationService(request.user, via=Via.WEB)


def refused(problem):
    # 409 = we said no on purpose; app.js and board.js show the text and undo the change on screen.
    return HttpResponse(str(problem), status=409, content_type="text/plain; charset=utf-8")


def is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def with_events(response, **events):
    """Fire client-side events after an HTMX request (handled in static/js/app.js)."""
    response["HX-Trigger"] = json.dumps(events)
    return response


# --- Board view ----------------------------------------------------------------


class BoardView(OwnedObjectMixin, ListView):
    model = Application
    template_name = "tracker/board.html"

    def get_queryset(self):
        # stage_since: when the card last entered its current stage, from its history.
        # The database works it out in the same single query (no query per card).
        return (
            super()
            .get_queryset()
            .annotate(stage_since=Max("history__changed_at", filter=Q(history__to_stage=F("stage"))))
            .order_by(F("deadline").asc(nulls_last=True), "-updated_at")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        columns = {stage: [] for stage in Stage}
        for application in context["object_list"]:
            columns[application.stage].append(application)
        context["columns"] = list(columns.items())
        context["stages"] = Stage.choices
        return context

    def get_template_names(self):
        # After a move, the board refreshes itself with an HTMX request for just the board.
        if is_htmx(self.request):
            return [f"{self.template_name}#board"]
        return [self.template_name]


# --- Table view ----------------------------------------------------------------

# Allowed ?sort= values and the ordering each one means. Anything else falls back
# to the default, so the query string can't order by arbitrary fields.
SORTS = {
    "company": [F("company").asc(), F("role").asc()],
    "role": [F("role").asc(), F("company").asc()],
    "stage": [F("stage").asc(), F("updated_at").desc()],
    "applied": [F("date_applied").desc(nulls_last=True)],
    "deadline": [F("deadline").asc(nulls_last=True)],
    "updated": [F("updated_at").desc()],
}
DEFAULT_SORT = "updated"


class ApplicationListView(OwnedObjectMixin, ListView):
    model = Application
    template_name = "tracker/application_list.html"
    paginate_by = 50

    def get_queryset(self):
        params = self.request.GET
        self.query = params.get("q", "").strip()
        self.sort = params.get("sort") if params.get("sort") in SORTS else DEFAULT_SORT
        self.stage = params.get("stage", "")
        if self.stage not in {str(value) for value in Stage.values}:
            self.stage = ""

        queryset = super().get_queryset()
        if self.query:
            queryset = queryset.filter(
                Q(company__icontains=self.query)
                | Q(role__icontains=self.query)
                | Q(location__icontains=self.query)
                | Q(notes__icontains=self.query)
            )
        # The stage chips show counts for the current search but ignore the stage
        # filter, so each chip says how many rows clicking it would give.
        self.searched = queryset
        if self.stage:
            queryset = queryset.filter(stage=int(self.stage))
        # select_related: each row shows its resume name, which would otherwise
        # cost one extra query per row (the N+1 problem).
        return queryset.select_related("resume_version").order_by(*SORTS[self.sort], "-id")

    def paginate_queryset(self, queryset, page_size):
        # get_page() turns a bad or out-of-range ?page= into a valid page instead of a 404.
        paginator = Paginator(queryset, page_size)
        page = paginator.get_page(self.request.GET.get("page"))
        return paginator, page, page.object_list, page.has_other_pages()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        counts = dict(self.searched.order_by().values_list("stage").annotate(n=Count("id")))
        searched_total = sum(counts.values())
        context.update(
            query=self.query,
            sort=self.sort,
            stage_filter=self.stage,
            stage_counts=[(stage, counts.get(stage.value, 0)) for stage in Stage],
            searched_total=searched_total,
            has_any=bool(searched_total) or Application.objects.for_user(self.request.user).exists(),
            stages=Stage.choices,
        )
        return context

    def get_template_names(self):
        # HTMX filter/sort/page requests only need the results, not the whole page.
        if is_htmx(self.request):
            return [f"{self.template_name}#results"]
        return [self.template_name]


# --- Create, read, update, delete -----------------------------------------------


class ApplicationFormMixin:
    model = Application
    form_class = ApplicationForm
    template_name = "tracker/application_form.html"

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def get_success_url(self):
        return reverse("tracker:detail", args=[self.object.pk])


class ApplicationCreateView(ApplicationFormMixin, CreateView):
    def get_initial(self):
        # Links like "Add to Applied" pass ?stage=1 to preselect the stage.
        stage = self.request.GET.get("stage", "")
        return {"stage": int(stage)} if stage.isdigit() and int(stage) in Stage.values else {}

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Added {self.object.company}.")
        return response


class ApplicationUpdateView(ApplicationFormMixin, OwnedObjectMixin, UpdateView):
    def form_valid(self, form):
        # Changing the stage here should be undoable too, so snapshot it first.
        before = Application.objects.get(pk=self.object.pk)
        with transaction.atomic():
            if before.stage != form.instance.stage:
                before.undo_history.push(before.create_memento())
            response = super().form_valid(form)
        messages.success(self.request, "Changes saved.")
        return response


class ApplicationDetailView(OwnedObjectMixin, DetailView):
    model = Application
    template_name = "tracker/application_detail.html"

    def get_queryset(self):
        return super().get_queryset().select_related("resume_version").prefetch_related("history")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(stages=Stage.choices, **kwargs)
        context["can_undo"] = self.object.undo_history.can_undo()
        # Pair each history row with the next one, so the page can say how long the
        # application spent in each stage. The latest row is still ongoing (until=None).
        changes = list(self.object.history.all())
        context["timeline"] = [
            (change, changes[i + 1].changed_at if i + 1 < len(changes) else None) for i, change in enumerate(changes)
        ][::-1]
        return context


class ApplicationDeleteView(OwnedObjectMixin, DeleteView):
    model = Application
    template_name = "tracker/application_confirm_delete.html"
    success_url = reverse_lazy("tracker:board")

    def form_valid(self, form):
        name = str(self.object)
        response = super().form_valid(form)
        messages.success(self.request, f"Deleted {name}.")
        return response


class ApplicationStageView(OwnedObjectMixin, SingleObjectMixin, View):
    """
    POST to=<stage number>, from drag and drop, the Move menus and the table dropdown.
    HTMX gets 204 + events (refresh, toast with Undo); a refused move gets 409.
    """

    model = Application
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        application = self.get_object()  # 404 if it isn't this user's
        try:
            stage = Stage(int(request.POST.get("to", "")))
        except ValueError:
            return HttpResponseBadRequest("Unknown stage.")
        try:
            application, moved = service_for(request).move(application, stage)
        except InvalidMove as problem:
            if is_htmx(request):
                return refused(problem)
            messages.error(request, str(problem))
            return redirect("tracker:detail", application.pk)
        message = f"{application.company} moved to {stage.label}."
        if not is_htmx(request):
            messages.success(request, message)
            return redirect("tracker:detail", application.pk)
        toast = {"message": message}
        if moved:
            toast["undo_url"] = reverse("tracker:undo", args=[application.pk])
        return with_events(HttpResponse(status=204), **{"applications-changed": None, "toast": toast})


class ApplicationUndoView(OwnedObjectMixin, SingleObjectMixin, View):
    model = Application
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        application = self.get_object()
        try:
            application = service_for(request).undo(application)
        except CoopTrackError as problem:
            if is_htmx(request):
                return refused(problem)
            messages.error(request, str(problem))
            return redirect("tracker:detail", application.pk)
        message = f"Undone: {application.company} is back in {application.get_stage_display()}."
        if not is_htmx(request):
            messages.success(request, message)
            return redirect("tracker:detail", application.pk)
        return with_events(HttpResponse(status=204), **{"applications-changed": None, "toast": {"message": message}})


# --- Find jobs (Adzuna) -------------------------------------------------------------


class JobSearchView(TemplateView):
    template_name = "tracker/jobs.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        query, where = params.get("q", "").strip(), params.get("where", "").strip()
        rank = params.get("rank") if params.get("rank") in RANKINGS else DEFAULT_RANKING
        context.update(query=query, where=where, rank=rank, rankings=RANKINGS.values(), searched=bool(query))
        if query:
            service = service_for(self.request)
            try:
                results = service.search_jobs(query, where, rank)
            except JobSearchError as problem:
                context["search_error"] = str(problem)
            else:
                context.update(
                    postings=results.postings,
                    is_sample=results.is_sample,
                    saved_urls=service.saved_posting_urls(results.postings),
                )
        return context

    def get_template_names(self):
        if is_htmx(self.request):
            return [f"{self.template_name}#results"]
        return [self.template_name]


class SavePostingView(View):
    http_method_names = ["post"]

    def post(self, request, posting_id):
        try:
            application, created = service_for(request).save_posting(posting_id)
        except NotFound as problem:
            if is_htmx(request):
                return refused(problem)
            messages.error(request, str(problem))
            return redirect("tracker:jobs")
        if is_htmx(request):
            response = TemplateResponse(request, "tracker/jobs.html#saved", {"application": application})
            message = f"Saved {application.company} to your board." if created else "Already on your board."
            return with_events(response, toast={"message": message})
        messages.success(request, f"Saved {application.company} to your board.")
        return redirect("tracker:detail", application.pk)


# --- Resume versions -------------------------------------------------------------


class ResumeVersionListView(OwnedObjectMixin, ListView):
    """Lists resume versions and handles the "add" form on the same page."""

    model = ResumeVersion
    template_name = "tracker/resume_list.html"

    def get_queryset(self):
        return super().get_queryset().annotate(application_count=Count("applications"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("form", ResumeVersionForm(user=self.request.user))
        return context

    def post(self, request, *args, **kwargs):
        form = ResumeVersionForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, f"Added {form.instance.name}.")
            return redirect("tracker:resumes")
        self.object_list = self.get_queryset()
        return self.render_to_response(self.get_context_data(form=form))


class ResumeVersionDeleteView(OwnedObjectMixin, DeleteView):
    model = ResumeVersion
    success_url = reverse_lazy("tracker:resumes")
    http_method_names = ["post"]

    def form_valid(self, form):
        name = self.object.name
        response = super().form_valid(form)
        messages.success(self.request, f"Deleted {name}. Applications that used it now show “Not tracked”.")
        return response


# --- Stats -----------------------------------------------------------------------


class StatsView(TemplateView):
    template_name = "tracker/stats.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        weeks = stats.per_week(user)
        resumes = stats.per_resume(user)
        context.update(
            summary=stats.summary(user),
            weeks=weeks,
            week_max=max([w["count"] for w in weeks] + [1]),
            weeks_total=sum(w["count"] for w in weeks),
            resumes=resumes,
        )
        return context


# --- CSV ---------------------------------------------------------------------------


class ExportView(View):
    def get(self, request):
        filename = f"cooptrack-{timezone.localdate().isoformat()}.csv"
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.write("\ufeff")  # byte-order mark, so Excel opens accented characters correctly
        csv_io.write_csv(request.user, response)
        return response


class ImportView(FormView):
    template_name = "tracker/import.html"
    form_class = ImportForm

    def get_context_data(self, **kwargs):
        return super().get_context_data(columns=csv_io.COLUMNS, stages=Stage.labels, max_rows=csv_io.MAX_ROWS, **kwargs)

    def form_valid(self, form):
        try:
            imported, skipped, errors = csv_io.import_csv(self.request.user, form.cleaned_data["file"])
        except csv_io.CSVImportError as problem:
            form.add_error("file", str(problem))
            return self.form_invalid(form)
        if errors:
            return self.render_to_response(
                self.get_context_data(form=form, row_errors=errors[:25], error_count=len(errors))
            )
        message = f"Imported {imported} application{'s' if imported != 1 else ''}."
        if skipped:
            message += f" Skipped {skipped} already on your board."
        messages.success(self.request, message)
        return redirect("tracker:board")
