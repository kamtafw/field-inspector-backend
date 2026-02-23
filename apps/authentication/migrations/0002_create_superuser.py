from django.db import migrations
import os


def create_superuser(apps, schema_editor):
    from django.contrib.auth import get_user_model

    User = get_user_model()

    email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "admin@vantage.com")
    password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
    first_name = os.environ.get("DJANGO_SUPERUSER_FIRST_NAME", "vantage")
    last_name = os.environ.get("DJANGO_SUPERUSER_LAST_NAME", "admin")

    if not password:
        return  # skip silently if no password set

    if not User.objects.filter(email=email).exists():
        User.objects.create(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role="manager",
        )


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_superuser, migrations.RunPython.noop),
    ]
