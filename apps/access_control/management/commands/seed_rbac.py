from django.core.management.base import BaseCommand
from apps.access_control.services import seed_default_permissions_and_roles


class Command(BaseCommand):
    help = "Seeds default permissions grouped across the 9 core topics and standard roles (Administrator, Staff, Trainer)."

    def handle(self, *args, **options):
        self.stdout.write("==> Seeding system permissions and standard roles...")
        seed_default_permissions_and_roles()
        self.stdout.write(self.style.SUCCESS("==> System permissions and roles successfully seeded!"))
