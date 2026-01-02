from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    ROLE_CHOICES = [
        ("inspector", "Inspector"),
        ("manager", "Manager"),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="inspector")

    class Meta:
        db_table = "users"
