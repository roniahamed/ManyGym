from django.core.management.base import BaseCommand
from apps.gyms.services.geo_services import warm_gym_geo_cache


class Command(BaseCommand):
    help = "Warms the Redis Geospatial index (gyms:geo:locations) with all published, active gyms from PostgreSQL."

    def handle(self, *args, **options):
        self.stdout.write("Warming Redis GEO cache with active gym locations...")
        count = warm_gym_geo_cache()
        self.stdout.write(
            self.style.SUCCESS(f"Successfully cached {count} gym locations in Redis GEO index.")
        )

