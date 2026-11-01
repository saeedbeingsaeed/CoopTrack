from django.contrib import admin

from .models import Application, ResumeVersion, StageChange


class StageChangeInline(admin.TabularInline):
    model = StageChange
    extra = 0
    readonly_fields = ["from_stage", "to_stage", "changed_at"]
    can_delete = False


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ["company", "role", "stage", "user", "deadline", "updated_at"]
    list_filter = ["stage"]
    search_fields = ["company", "role", "user__email"]
    list_select_related = ["user"]
    raw_id_fields = ["user", "resume_version"]
    inlines = [StageChangeInline]


@admin.register(ResumeVersion)
class ResumeVersionAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "created_at"]
    list_select_related = ["user"]
    raw_id_fields = ["user"]
