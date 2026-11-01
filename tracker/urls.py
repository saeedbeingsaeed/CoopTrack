from django.urls import path

from . import views

app_name = "tracker"

urlpatterns = [
    path("", views.BoardView.as_view(), name="board"),
    path("table/", views.ApplicationListView.as_view(), name="table"),
    path("applications/new/", views.ApplicationCreateView.as_view(), name="create"),
    path("applications/<int:pk>/", views.ApplicationDetailView.as_view(), name="detail"),
    path("applications/<int:pk>/edit/", views.ApplicationUpdateView.as_view(), name="edit"),
    path("applications/<int:pk>/delete/", views.ApplicationDeleteView.as_view(), name="delete"),
    path("applications/<int:pk>/stage/", views.ApplicationStageView.as_view(), name="stage"),
    path("stats/", views.StatsView.as_view(), name="stats"),
    path("export.csv", views.ExportView.as_view(), name="export"),
    path("import/", views.ImportView.as_view(), name="import"),
    path("resumes/", views.ResumeVersionListView.as_view(), name="resumes"),
    path("resumes/<int:pk>/delete/", views.ResumeVersionDeleteView.as_view(), name="resume_delete"),
]
