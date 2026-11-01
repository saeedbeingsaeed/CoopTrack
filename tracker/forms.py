from django import forms

from .models import Application, ResumeVersion


class DateInput(forms.DateInput):
    input_type = "date"  # the browser's native date picker, which works well on phones

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class ApplicationForm(forms.ModelForm):
    new_resume = forms.CharField(
        label="Or add a new resume version",
        max_length=80,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "e.g. SWE v3 (backend focus)"}),
    )

    class Meta:
        model = Application
        fields = [
            "company",
            "role",
            "stage",
            "date_applied",
            "deadline",
            "location",
            "pay",
            "posting_url",
            "resume_version",
            "notes",
        ]
        widgets = {
            "company": forms.TextInput(attrs={"autofocus": True, "placeholder": "Shopify"}),
            "role": forms.TextInput(attrs={"placeholder": "Backend Developer Intern"}),
            "date_applied": DateInput(),
            "deadline": DateInput(),
            "location": forms.TextInput(attrs={"placeholder": "Toronto, ON · Hybrid"}),
            "pay": forms.TextInput(attrs={"placeholder": "$28/hr"}),
            "posting_url": forms.URLInput(attrs={"placeholder": "https://"}),
            "notes": forms.Textarea(attrs={"rows": 5, "placeholder": "Recruiter's name, interview prep, referral…"}),
        }
        help_texts = {"pay": "", "date_applied": "Filled in with today's date when you move past Saved."}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        # Only this user's resumes can be picked. Posting another user's id fails
        # validation ("Select a valid choice"), so it can't be linked.
        self.fields["resume_version"].queryset = ResumeVersion.objects.for_user(user)
        self.fields["resume_version"].empty_label = "Not tracked"

    def save(self, commit=True):
        application = super().save(commit=False)
        application.user = self.user
        name = self.cleaned_data.get("new_resume", "").strip()
        if name:
            # Reuse a version with the same name (ignoring case) rather than duplicate it.
            resume = ResumeVersion.objects.for_user(self.user).filter(name__iexact=name).first()
            application.resume_version = resume or ResumeVersion.objects.create(user=self.user, name=name)
        if commit:
            application.save()
        return application


class ResumeVersionForm(forms.ModelForm):
    class Meta:
        model = ResumeVersion
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"placeholder": "e.g. SWE v3 (backend focus)"})}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if ResumeVersion.objects.for_user(self.user).filter(name__iexact=name).exists():
            raise forms.ValidationError("You already have a resume version with this name.")
        return name

    def save(self, commit=True):
        resume = super().save(commit=False)
        resume.user = self.user
        if commit:
            resume.save()
        return resume


class ImportForm(forms.Form):
    file = forms.FileField(
        label="CSV file",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )
