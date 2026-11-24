from django.contrib import admin
from apps.stories.models import Story, StoryView, StoryReply


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "owner_type",
        "user",
        "gym",
        "media_type",
        "privacy",
        "lifetime_hours",
        "views_count",
        "reactions_count",
        "replies_count",
        "published_at",
        "expires_at",
        "is_archived",
    )
    list_filter = ("owner_type", "media_type", "privacy", "lifetime_hours", "is_archived")
    search_fields = ("user__email", "gym__name", "caption")
    readonly_fields = ("id", "created_at", "updated_at", "views_count", "reactions_count", "replies_count")


@admin.register(StoryView)
class StoryViewAdmin(admin.ModelAdmin):
    list_display = ("id", "story", "viewer_user", "viewed_at")
    readonly_fields = ("id", "viewed_at")


@admin.register(StoryReply)
class StoryReplyAdmin(admin.ModelAdmin):
    list_display = ("id", "story", "user", "owner_type", "gym", "message", "created_at")
    list_filter = ("owner_type", "created_at")
    search_fields = ("user__email", "gym__name", "message")
    readonly_fields = ("id", "created_at", "updated_at")


