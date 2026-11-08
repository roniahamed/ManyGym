import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.utils import timezone
from common.enums import (
    UserStatus,
    UserAudienceMessagingEnum,
    UserAudienceVisibilityEnum,
    GenderEnum,
    SocialPlatformEnum,
)


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("is_verified", True)
        extra_fields.setdefault("status", UserStatus.ACTIVE)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(max_length=255, unique=True, db_index=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=50, blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=UserStatus.choices,
        default=UserStatus.ACTIVE,
    )
    is_verified = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        db_table = "users"
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email} ({self.first_name} {self.last_name})"

    def get_settings(self) -> "UserSetting":
        """Retrieves or provisions the user configuration and privacy settings record."""
        setting, _ = UserSetting.objects.get_or_create(user=self)
        return setting


class UserProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    avatar_url = models.CharField(max_length=1000, blank=True, null=True)
    address = models.CharField(max_length=500, blank=True, null=True)
    home_town = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    sex = models.CharField(max_length=20, blank=True, null=True)
    gender = models.CharField(
        max_length=50,
        choices=GenderEnum.choices,
        blank=True,
        null=True,
        help_text="User gender identity selection.",
    )
    nationality = models.CharField(max_length=100, blank=True, null=True)
    hobbies = models.JSONField(
        default=list,
        blank=True,
        help_text="List of user hobbies as free text items.",
    )
    about_you = models.CharField(
        max_length=320,
        blank=True,
        null=True,
        help_text="Short bio/description about user (maximum 320 characters).",
    )
    favourite_quote = models.CharField(
        max_length=160,
        blank=True,
        null=True,
        help_text="User favourite quote (maximum 160 characters).",
    )
    is_private = models.BooleanField(
        default=False,
        help_text="If True, this user's profile is private and cannot be followed by other users.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_profiles"
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self):
        return f"Profile of {self.user.email}"

    @property
    def current_address(self):
        return self.address

    @current_address.setter
    def current_address(self, value):
        self.address = value


class UserEducation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="educations",
    )
    university_name = models.CharField(max_length=255)
    from_year = models.DateField(help_text="Start date / year of education")
    till_year = models.DateField(
        null=True,
        blank=True,
        help_text="End date / year of education (optional if still continuing)",
    )
    subject = models.CharField(max_length=255)
    graduated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_educations"
        verbose_name = "User Education"
        verbose_name_plural = "User Educations"
        ordering = ["-from_year", "-created_at"]
        indexes = [
            models.Index(fields=["user", "-from_year"]),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.university_name} ({self.subject})"


class UserSocialLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="social_links",
    )
    platform = models.CharField(max_length=50, choices=SocialPlatformEnum.choices)
    link = models.CharField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_social_links"
        verbose_name = "User Social Link"
        verbose_name_plural = "User Social Links"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["user", "platform"]),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.platform}: {self.link}"


_raw_otp_cache = {}


class OTPCodeDescriptor:
    def __init__(self, field_name="otp_code"):
        self.field_name = field_name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        raw = getattr(instance, "_raw_otp", None)
        if raw is not None:
            return raw
        record_id = instance.__dict__.get("id")
        if record_id:
            cached = _raw_otp_cache.get(str(record_id))
            if cached is not None:
                return cached
        return instance.__dict__.get(self.field_name)

    def __set__(self, instance, value):
        instance.__dict__[self.field_name] = value
        if value and len(str(value)) < 64:
            instance._raw_otp = str(value)


class HashedOTPField(models.CharField):
    """
    Field that ensures the OTP is cryptographically hashed before being written to PostgreSQL.
    """

    def pre_save(self, model_instance, add):
        from common.security import hash_otp
        raw = getattr(model_instance, "_raw_otp", None)
        if raw and len(str(raw).strip()) < 64:
            raw_str = str(raw).strip()
            if model_instance.id:
                _raw_otp_cache[str(model_instance.id)] = raw_str
            return hash_otp(model_instance.email, raw_str)
        val = model_instance.__dict__.get(self.attname)
        if val and len(str(val).strip()) < 64:
            raw_val = str(val).strip()
            model_instance._raw_otp = raw_val
            if model_instance.id:
                _raw_otp_cache[str(model_instance.id)] = raw_val
            return hash_otp(model_instance.email, raw_val)
        return val


class OTPVerification(models.Model):
    class Purpose(models.TextChoices):
        SIGNUP_VERIFICATION = "signup_verification", "Signup Verification"
        PASSWORD_RESET = "password_reset", "Password Reset"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(db_index=True)
    otp_code = HashedOTPField(max_length=255)
    purpose = models.CharField(max_length=30, choices=Purpose.choices)
    is_used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "otp_verifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email", "purpose", "is_used"]),
        ]

    def save(self, *args, **kwargs):
        from common.security import hash_otp
        raw = getattr(self, "_raw_otp", None)
        current_val = self.__dict__.get("otp_code")
        if not raw and current_val and len(str(current_val).strip()) < 64:
            raw = str(current_val).strip()
            self._raw_otp = raw
        if raw and self.id:
            if len(_raw_otp_cache) >= 5000:
                for k in list(_raw_otp_cache.keys())[:500]:
                    _raw_otp_cache.pop(k, None)
            _raw_otp_cache[str(self.id)] = raw
        super().save(*args, **kwargs)

    @property
    def otp_hash(self) -> str:
        """Returns the cryptographic hash stored in the database."""
        return self.__dict__.get("otp_code", "")

    def check_otp(self, raw_otp_code: str) -> bool:
        """Cryptographically validates raw_otp_code in constant time."""
        import hmac
        from common.security import hash_otp
        if not raw_otp_code:
            return False
        expected = hash_otp(self.email, str(raw_otp_code).strip())
        current_hash = self.otp_hash
        return hmac.compare_digest(current_hash, expected) or hmac.compare_digest(current_hash, str(raw_otp_code).strip())

    def is_valid(self):
        return not self.is_used and timezone.now() <= self.expires_at

    def __str__(self):
        masked = f"{self.otp_hash[:8]}..." if self.otp_hash else "None"
        return f"OTP for {self.email} ({self.purpose}) [hash: {masked}]"


OTPVerification.otp_code = OTPCodeDescriptor("otp_code")


class UserFollow(models.Model):
    """
    Represents an intentional follow relationship from one user to another public user.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    follower = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="following_relations",
    )
    followed_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="follower_relations",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_follows"
        verbose_name = "User Follow"
        verbose_name_plural = "User Follows"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["follower", "followed_user"],
                name="unique_user_follow",
            ),
            models.CheckConstraint(
                check=~models.Q(follower=models.F("followed_user")),
                name="prevent_self_user_follow",
            ),
        ]
        indexes = [
            models.Index(fields=["follower", "-created_at"], name="idx_ufollow_flwr_created"),
            models.Index(fields=["followed_user", "-created_at"], name="idx_ufollow_trgt_created"),
        ]

    def __str__(self):
        return f"{self.follower.email} follows {self.followed_user.email}"


class FollowRequestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


class UserFollowRequest(models.Model):
    """
    Represents an intentional follow request from one user to another public user
    who requires confirmation/approval before followers are accepted.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requester = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="sent_follow_requests",
    )
    target_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="received_follow_requests",
    )
    status = models.CharField(
        max_length=20,
        choices=FollowRequestStatus.choices,
        default=FollowRequestStatus.PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_follow_requests"
        verbose_name = "User Follow Request"
        verbose_name_plural = "User Follow Requests"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["requester", "target_user"],
                condition=models.Q(status="pending"),
                name="unique_pending_follow_request",
            ),
            models.CheckConstraint(
                check=~models.Q(requester=models.F("target_user")),
                name="prevent_self_follow_request",
            ),
        ]
        indexes = [
            models.Index(fields=["target_user", "status", "-created_at"], name="idx_freq_target_status"),
            models.Index(fields=["requester", "status", "-created_at"], name="idx_freq_req_status"),
        ]

    def __str__(self):
        return f"{self.requester.email} -> {self.target_user.email} ({self.status})"

    @property
    def followed_user(self):
        """Convenience alias matching UserFollow interface."""
        return self.target_user


class UserSetting(models.Model):
    """
    Configuration and administrative settings for an individual user profile.
    Encompasses Display Preferences, Audience & Messaging Privacy, and Account Lifecycle (Access & Control).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="settings",
    )

    # --- Preference -> Display ---
    language = models.CharField(
        max_length=20,
        default="en",
        help_text="Display language (e.g. en, bn).",
    )
    dark_mode = models.BooleanField(
        default=False,
        help_text="Dark Mode (ON/OFF).",
    )

    # --- Privacy and Sharing -> Audience ---
    who_can_message = models.CharField(
        max_length=50,
        choices=UserAudienceMessagingEnum.choices,
        default=UserAudienceMessagingEnum.EVERYONE,
        help_text="Who can send you messages? (Everyone, Followers, No one)",
    )
    who_can_see_followers = models.CharField(
        max_length=50,
        choices=UserAudienceVisibilityEnum.choices,
        default=UserAudienceVisibilityEnum.EVERYONE,
        help_text="Who can see your followers? (Everyone, Followers, Private)",
    )
    who_can_see_following = models.CharField(
        max_length=50,
        choices=UserAudienceVisibilityEnum.choices,
        default=UserAudienceVisibilityEnum.EVERYONE,
        help_text="Who can see people and gyms you follow? (Everyone, Followers, Private)",
    )
    require_follow_approval = models.BooleanField(
        default=False,
        help_text="If True, followers must be confirmed before they can follow this user.",
    )

    # --- Visibility -> Access & Control ---
    is_deactivated = models.BooleanField(
        default=False,
        help_text="Whether the user profile is deactivated.",
    )
    deactivated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the user account was deactivated.",
    )
    is_deleted = models.BooleanField(
        default=False,
        help_text="Soft-delete flag for user account.",
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the user account was soft-deleted.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_settings"
        verbose_name = "User Setting"
        verbose_name_plural = "User Settings"

    def __str__(self):
        return f"Settings of {self.user.email}"

    def deactivate(self) -> None:
        """Transitions user profile to deactivated state and records timestamp."""
        self.is_deactivated = True
        self.deactivated_at = timezone.now()

    def reactivate(self) -> None:
        """Reactivates user profile and resets deactivated timestamp."""
        self.is_deactivated = False
        self.deactivated_at = None

    def soft_delete(self) -> None:
        """Marks user account as soft-deleted and records timestamp."""
        self.is_deleted = True
        self.deleted_at = timezone.now()

    def restore(self) -> None:
        """Restores soft-deleted user account and resets deleted timestamp."""
        self.is_deleted = False
        self.deleted_at = None


class UserBlockedUser(models.Model):
    """
    Represents an intentional block relationship where blocker blocks blocked_user.
    Blocked users cannot view the blocker's profile, follow them, or send messages.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    blocker = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="blocked_users_relations",
    )
    blocked_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="blocked_by_relations",
    )
    reason = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_blocked_users"
        verbose_name = "User Blocked User"
        verbose_name_plural = "User Blocked Users"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["blocker", "blocked_user"],
                name="unique_user_block",
            ),
            models.CheckConstraint(
                check=~models.Q(blocker=models.F("blocked_user")),
                name="prevent_self_user_block",
            ),
        ]
        indexes = [
            models.Index(fields=["blocker", "-created_at"], name="idx_ublk_blkr_created"),
            models.Index(fields=["blocked_user", "-created_at"], name="idx_ublk_trgt_created"),
        ]

    def __str__(self):
        return f"{self.blocker.email} blocked {self.blocked_user.email}"
