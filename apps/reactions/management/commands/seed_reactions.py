from django.core.management.base import BaseCommand
from apps.reactions.services import seed_default_reaction_items


class Command(BaseCommand):
    help = "Seeds the default social reaction items (10+ emojis including Smile 😊 and Laugh 😆)"

    def handle(self, *args, **options):
        items = seed_default_reaction_items()
        self.stdout.write(
            self.style.SUCCESS(f"Successfully seeded {len(items)} default reaction items.")
        )

