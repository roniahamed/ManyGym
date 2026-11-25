import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone

from common.models import TimeStampedModel
from common.enums import (
    ConversationTypeEnum,
    MessageSenderTypeEnum,
    MessageDeliveryStatusEnum,
    KeyAlgorithmEnum,
)


class UserDeviceKey(TimeStampedModel):
    """
    Stores E2EE public cryptographic identity and pre-keys for a user's client device.
    Private keys NEVER leave the user's device.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="device_keys",
    )
    device_id = models.CharField(max_length=100, db_index=True)
    device_name = models.CharField(max_length=150, blank=True, default="")
    algorithm = models.CharField(
        max_length=20,
        choices=KeyAlgorithmEnum.choices,
        default=KeyAlgorithmEnum.X25519,
    )
    identity_key = models.TextField(help_text="Public Identity Key (Base64)")
    signed_prekey = models.TextField(help_text="Public Signed Pre-Key (Base64)")
    signed_prekey_signature = models.TextField(blank=True, default="", help_text="Ed25519 signature of the pre-key")
    one_time_prekeys = models.JSONField(
        default=list,
        blank=True,
        help_text="Pool of one-time public pre-keys for asynchronous handshake",
    )
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "messaging_user_device_keys"
        verbose_name = "User Device Key"
        verbose_name_plural = "User Device Keys"
        unique_together = (("user", "device_id"),)
        indexes = [
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self):
        return f"UserDeviceKey({self.user.email} - {self.device_id})"


class GymDeviceKey(TimeStampedModel):
    """
    Stores E2EE public keys for a Gym tenant identity.
    Authorized gym staff hold decrypting capability on behalf of the Gym entity.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        related_name="device_keys",
    )
    device_id = models.CharField(max_length=100, db_index=True)
    device_name = models.CharField(max_length=150, blank=True, default="")
    algorithm = models.CharField(
        max_length=20,
        choices=KeyAlgorithmEnum.choices,
        default=KeyAlgorithmEnum.X25519,
    )
    identity_key = models.TextField(help_text="Gym Public Identity Key (Base64)")
    signed_prekey = models.TextField(help_text="Gym Public Signed Pre-Key (Base64)")
    signed_prekey_signature = models.TextField(blank=True, default="", help_text="Signature of the pre-key")
    one_time_prekeys = models.JSONField(default=list, blank=True)
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registered_gym_keys",
    )
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "messaging_gym_device_keys"
        verbose_name = "Gym Device Key"
        verbose_name_plural = "Gym Device Keys"
        unique_together = (("gym", "device_id"),)
        indexes = [
            models.Index(fields=["gym", "is_active"]),
        ]

    def __str__(self):
        return f"GymDeviceKey({self.gym.name} - {self.device_id})"


class Conversation(TimeStampedModel):
    """
    Conversation room representing a channel between:
    - User <-> User (user_a, user_b)
    - User <-> Gym (user_a, gym_a)
    - Gym <-> Gym (gym_a, gym_b)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation_type = models.CharField(
        max_length=20,
        choices=ConversationTypeEnum.choices,
        db_index=True,
    )
    user_a = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conversations_as_user_a",
    )
    user_b = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conversations_as_user_b",
    )
    gym_a = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conversations_as_gym_a",
    )
    gym_b = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conversations_as_gym_b",
    )
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_message_preview = models.CharField(
        max_length=255,
        default="🔒 Encrypted Message",
        blank=True,
    )

    class Meta:
        db_table = "messaging_conversations"
        verbose_name = "Conversation"
        verbose_name_plural = "Conversations"
        ordering = ["-last_message_at", "-created_at"]
        indexes = [
            models.Index(fields=["conversation_type", "-last_message_at"]),
            models.Index(fields=["user_a", "user_b"]),
            models.Index(fields=["user_a", "gym_a"]),
            models.Index(fields=["gym_a", "gym_b"]),
        ]

    def __str__(self):
        return f"Conversation[{self.conversation_type}] ({self.id})"


class ConversationParticipant(TimeStampedModel):
    """
    Tracks state, membership, read pointer, and unread counts for a participant.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="participants",
    )
    participant_type = models.CharField(
        max_length=20,
        choices=MessageSenderTypeEnum.choices,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="messaging_participations",
    )
    gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="messaging_participations",
    )
    last_read_message_id = models.UUIDField(null=True, blank=True)
    last_read_at = models.DateTimeField(null=True, blank=True)
    unread_count = models.PositiveIntegerField(default=0)
    is_muted = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)

    class Meta:
        db_table = "messaging_participants"
        verbose_name = "Conversation Participant"
        verbose_name_plural = "Conversation Participants"
        indexes = [
            models.Index(fields=["conversation", "user"]),
            models.Index(fields=["conversation", "gym"]),
            models.Index(fields=["user", "-updated_at"]),
            models.Index(fields=["gym", "-updated_at"]),
        ]

    def __str__(self):
        target = self.user.email if self.user else (self.gym.name if self.gym else "Unknown")
        return f"Participant({target} in {self.conversation_id})"


class EncryptedMessage(TimeStampedModel):
    """
    E2EE Encrypted message record.
    The server stores only encrypted ciphertext, cryptographic nonces, and metadata.
    Plaintext content NEVER touches the server.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender_type = models.CharField(
        max_length=20,
        choices=MessageSenderTypeEnum.choices,
    )
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_messages",
    )
    sender_gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_messages",
    )
    sender_device_id = models.CharField(max_length=100, blank=True, default="")

    # End-to-End Encryption payload
    ciphertext = models.TextField(help_text="Base64 ciphertext of the encrypted message")
    nonce = models.CharField(max_length=255, help_text="Base64 initialization vector / nonce")
    ephemeral_public_key = models.TextField(
        blank=True,
        default="",
        help_text="Sender ephemeral X25519 public key (Base64)",
    )
    recipient_key_fingerprint = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Fingerprint of recipient's public key used",
    )
    encrypted_keys = models.JSONField(
        default=dict,
        blank=True,
        help_text="Multi-device or gym staff wrapped session keys: {participant_or_device_id: encrypted_key}",
    )

    delivery_status = models.CharField(
        max_length=20,
        choices=MessageDeliveryStatusEnum.choices,
        default=MessageDeliveryStatusEnum.SENT,
        db_index=True,
    )
    sent_at = models.DateTimeField(default=timezone.now, db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "messaging_messages"
        verbose_name = "Encrypted Message"
        verbose_name_plural = "Encrypted Messages"
        ordering = ["sent_at"]
        indexes = [
            models.Index(fields=["conversation", "sent_at"]),
            models.Index(fields=["conversation", "delivery_status"]),
        ]

    def __str__(self):
        return f"EncryptedMessage({self.id} in {self.conversation_id} [{self.delivery_status}])"


class MessageDeliveryReceipt(TimeStampedModel):
    """
    Per-recipient delivery and read receipt tracking.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        EncryptedMessage,
        on_delete=models.CASCADE,
        related_name="receipts",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="message_receipts",
    )
    gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="message_receipts",
    )
    device_id = models.CharField(max_length=100, blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=MessageDeliveryStatusEnum.choices,
    )
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "messaging_receipts"
        verbose_name = "Message Delivery Receipt"
        verbose_name_plural = "Message Delivery Receipts"
        indexes = [
            models.Index(fields=["message", "status"]),
        ]

    def __str__(self):
        return f"Receipt({self.message_id} -> {self.status})"


class UserE2EEBackup(TimeStampedModel):
    """
    Messenger-style password/PIN-protected encrypted E2EE key backup.
    Enables a user to restore their Master E2EE Identity & Search keys on new devices
    to decrypt historical conversations without exposing plaintext keys or codes to the server.
    """
    SECRET_TYPE_PIN = "pin"
    SECRET_TYPE_PASSPHRASE = "passphrase"
    SECRET_TYPE_CHOICES = [
        (SECRET_TYPE_PIN, "PIN / Numeric Code"),
        (SECRET_TYPE_PASSPHRASE, "Password / Passphrase"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="e2ee_backup",
    )
    backup_public_key = models.TextField(
        help_text="Public X25519 Master/Backup key (Base64) used to wrap history keys for new devices.",
    )
    backup_key_fingerprint = models.CharField(
        max_length=255,
        db_index=True,
        help_text="SHA-256 fingerprint of backup_public_key.",
    )
    encrypted_key_bundle = models.TextField(
        help_text="Base64 AEAD ciphertext of private identity/history/search keys encrypted client-side.",
    )
    nonce = models.CharField(max_length=255, help_text="Base64 AEAD nonce / IV.")
    salt = models.CharField(max_length=255, help_text="Base64 KDF salt.")
    kdf_algorithm = models.CharField(max_length=32, default="pbkdf2_sha256")
    kdf_iterations = models.PositiveIntegerField(default=310000)
    cipher_algorithm = models.CharField(max_length=32, default="chacha20_poly1305")
    secret_type = models.CharField(
        max_length=20,
        choices=SECRET_TYPE_CHOICES,
        default=SECRET_TYPE_PIN,
    )
    pin_length = models.PositiveSmallIntegerField(
        default=5,
        help_text="Expected numeric recovery code length (5 digits by default, Messenger-style).",
    )
    verifier_hash = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Salted hash of client auth_proof (never raw PIN/password or encryption key) for brute-force gated restore.",
    )
    recovery_encrypted_bundle = models.TextField(
        blank=True,
        default="",
        help_text="Optional secondary backup encrypted with a one-time recovery code.",
    )
    recovery_nonce = models.CharField(max_length=255, blank=True, default="")
    recovery_salt = models.CharField(max_length=255, blank=True, default="")
    key_version = models.PositiveIntegerField(default=1)
    failed_attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=10)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_restored_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "messaging_user_e2ee_backups"
        verbose_name = "User E2EE Key Backup"
        verbose_name_plural = "User E2EE Key Backups"
        indexes = [
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self):
        return f"UserE2EEBackup({self.user.email} v{self.key_version})"


class MessageSearchToken(TimeStampedModel):
    """
    Blinded HMAC-SHA256 keyword token index for zero-knowledge WhatsApp-style chat history search.
    Plaintext keywords never touch the server.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        EncryptedMessage,
        on_delete=models.CASCADE,
        related_name="search_tokens",
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="search_tokens",
    )
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="message_search_tokens",
    )
    owner_gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="message_search_tokens",
    )
    token_hash = models.CharField(max_length=128, db_index=True)

    class Meta:
        db_table = "messaging_message_search_tokens"
        verbose_name = "Message Search Token"
        verbose_name_plural = "Message Search Tokens"
        indexes = [
            models.Index(fields=["owner_user", "token_hash", "conversation"], name="idx_mst_user_tok_conv"),
            models.Index(fields=["owner_gym", "token_hash", "conversation"], name="idx_mst_gym_tok_conv"),
            models.Index(fields=["conversation", "token_hash"], name="idx_mst_conv_tok"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["message", "owner_user", "owner_gym", "token_hash"],
                name="unique_msg_owner_search_token",
            ),
        ]

    def __str__(self):
        return f"SearchToken({self.message_id} - {self.token_hash[:12]}...)"
