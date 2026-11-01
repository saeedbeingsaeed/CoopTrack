from django import forms

from .models import User


class ReminderSettingsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["reminders_enabled"]
        labels = {"reminders_enabled": "Email me a daily reminder"}
