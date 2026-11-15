from django.contrib import admin
from apps.reactions.models import Reaction, ReactionItem


@admin.register(ReactionItem)
class ReactionItemAdmin(admin.ModelAdmin):
    list_display = ("emoji", "label", "code", "order", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("label", "code", "emoji")
    ordering = ("order", "created_at")


@admin.register(Reaction)
class ReactionAdmin(admin.ModelAdmin):
    list_display = ("id", "reaction_item", "user", "owner_type", "gym", "target_type", "target_id", "created_at")
    list_filter = ("owner_type", "reaction_item__code", "created_at")
    search_fields = ("user__email", "gym__name", "reaction_item__label", "reaction_item__code")
    readonly_fields = ("created_at", "updated_at")

