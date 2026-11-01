from django.contrib import admin
from django.urls import include, path

from accounts import views as account_views

urlpatterns = [
    path("", account_views.landing, name="landing"),
    path("healthz", account_views.healthz, name="healthz"),
    path("privacy/", account_views.privacy, name="privacy"),
    path("demo/", account_views.start_demo, name="demo"),
    path("metrics/", account_views.metrics_page, name="metrics"),
    path("settings/", account_views.settings_page, name="settings"),
    path("settings/delete/", account_views.delete_account, name="delete_account"),
    path("settings/reminder-preview/", account_views.reminder_preview, name="reminder_preview"),
    path("unsubscribe/<str:token>/", account_views.unsubscribe, name="unsubscribe"),
    path("accounts/", include("allauth.urls")),
    path("app/", include("tracker.urls")),
    path("admin/", admin.site.urls),
]
