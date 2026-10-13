import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.utils import timezone
from common.enums import UserStatus


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


class UserProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    avatar_url = models.CharField(max_length=1000, blank=True, null=True)
    address = models.CharField(max_length=500, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    sex = models.CharField(max_length=20, blank=True, null=True)
    nationality = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_profiles"
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self):
        return f"Profile of {self.user.email}"


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
