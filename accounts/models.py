from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address.")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None
    email = models.EmailField("email address", unique=True)
    is_demo = models.BooleanField(default=False, help_text="Throwaway account created by the 'Try the demo' button.")

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email


class DeletedAccount(models.Model):
    # Lets the admin count deletions without keeping anything about the person.

    deleted_at = models.DateTimeField(auto_now_add=True)
    joined_at = models.DateTimeField()
    application_count = models.PositiveIntegerField()
    signed_up_with = models.CharField(max_length=20)  # "google", "password" or "both"

    class Meta:
        ordering = ["-deleted_at"]

    def __str__(self):
        return f"Account deleted {self.deleted_at:%Y-%m-%d}"
