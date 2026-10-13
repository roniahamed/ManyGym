from django.core.management.base import BaseCommand
from apps.amenities.services import seed_amenity_catalog


class Command(BaseCommand):
    help = "Seeds the master amenity catalog across the 7 categories."

    def handle(self, *args, **options):
        self.stdout.write("==> Seeding master amenity catalog...")
        seed_amenity_catalog()
        self.stdout.write(self.style.SUCCESS("==> Master amenity catalog successfully seeded!"))
