from django.db import migrations

DEFAULT_REACTION_ITEMS = [
    {"code": "smile", "emoji": "😊", "label": "Smile", "order": 1},
    {"code": "laugh", "emoji": "😆", "label": "Laugh", "order": 2},
    {"code": "like", "emoji": "👍", "label": "Like", "order": 3},
    {"code": "love", "emoji": "❤️", "label": "Love", "order": 4},
    {"code": "fire", "emoji": "🔥", "label": "Fire", "order": 5},
    {"code": "muscle", "emoji": "💪", "label": "Strong", "order": 6},
    {"code": "care", "emoji": "🥰", "label": "Care", "order": 7},
    {"code": "clap", "emoji": "👏", "label": "Clap", "order": 8},
    {"code": "wow", "emoji": "😮", "label": "Wow", "order": 9},
    {"code": "sad", "emoji": "😢", "label": "Sad", "order": 10},
    {"code": "thinking", "emoji": "🤔", "label": "Thinking", "order": 11},
    {"code": "hundred", "emoji": "💯", "label": "100", "order": 12},
    {"code": "party", "emoji": "🎉", "label": "Celebrate", "order": 13},
]


def seed_reaction_items(apps, schema_editor):
    ReactionItem = apps.get_model("reactions", "ReactionItem")
    for spec in DEFAULT_REACTION_ITEMS:
        ReactionItem.objects.update_or_create(
            code=spec["code"],
            defaults={
                "emoji": spec["emoji"],
                "label": spec["label"],
                "order": spec["order"],
                "is_active": True,
            },
        )


def reverse_seed(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("reactions", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_reaction_items, reverse_code=reverse_seed),
    ]

