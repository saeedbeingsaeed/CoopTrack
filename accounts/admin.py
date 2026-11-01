from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import DeletedAccount, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["-date_joined"]
    list_display = ["email", "first_name", "is_demo", "is_staff", "date_joined", "last_login"]
    list_filter = ["is_demo", "is_staff", "is_active"]
    search_fields = ["email", "first_name", "last_name"]
    fieldsets = [
        (None, {"fields": ["email", "password"]}),
        ("Profile", {"fields": ["first_name", "last_name", "reminders_enabled", "is_demo"]}),
        ("Permissions", {"fields": ["is_active", "is_staff", "is_superuser", "groups", "user_permissions"]}),
        ("Dates", {"fields": ["last_login", "date_joined"]}),
    ]
    add_fieldsets = [(None, {"classes": ["wide"], "fields": ["email", "password1", "password2"]})]


@admin.register(DeletedAccount)
class DeletedAccountAdmin(admin.ModelAdmin):
    list_display = ["deleted_at", "joined_at", "application_count", "signed_up_with"]
    list_filter = ["signed_up_with"]

    # A record of what happened: it can be looked at, not edited.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
