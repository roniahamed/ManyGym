from django.db import models


class UserStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    SUSPENDED = "suspended", "Suspended"
    DEACTIVATED = "deactivated", "Deactivated"
    DELETED = "deleted", "Deleted"


class UserAudienceMessagingEnum(models.TextChoices):
    """User audience setting: Who can send direct messages to the user profile."""
    EVERYONE = "everyone", "Everyone"
    FOLLOWERS = "followers", "Followers"
    NO_ONE = "no_one", "No one"


class UserAudienceVisibilityEnum(models.TextChoices):
    """User audience setting: Who can see followers or following lists of the user profile."""
    EVERYONE = "everyone", "Everyone"
    FOLLOWERS = "followers", "Followers"
    PRIVATE = "private", "Private"


class TokenContextType(models.TextChoices):
    PERSONAL = "personal", "Personal"
    GYM = "gym", "Gym"


class StaffStatus(models.TextChoices):
    INVITED = "invited", "Invited"
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


class GymGenderRequired(models.TextChoices):
    EVERYONE = "everyone", "Everyone"
    WOMEN_ONLY = "women_only", "Women Only"
    MEN_ONLY = "men_only", "Men Only"


class GymTypeEnum(models.TextChoices):
    GENERAL_FITNESS = "general_fitness_gym", "General Fitness Gym"
    STRENGTH_BODYBUILDING = "strength_bodybuilding_gym", "Strength & Bodybuilding Gym"
    FUNCTIONAL_FITNESS = "functional_fitness_gym", "Functional Fitness Gym"
    PERSONAL_TRAINING_STUDIO = "personal_training_studio", "Personal Training Studio"
    BOUTIQUE_FITNESS_STUDIO = "boutique_fitness_studio", "Boutique Fitness Studio"
    BOXING_MARTIAL_ARTS = "boxing_martial_arts_gym", "Boxing & Martial Arts Gym"
    YOGA_PILATES_STUDIO = "yoga_pilates_studio", "Yoga & Pilates Studio"
    INDOOR_CYCLING_STUDIO = "indoor_cycling_studio", "Indoor Cycling Studio"
    SPORTS_PERFORMANCE_CENTRE = "sports_performance_centre", "Sports Performance Centre"
    OTHER = "other", "Other"


class GalleryCategoryEnum(models.TextChoices):
    GENERAL = "general", "General"
    EQUIPMENT = "equipment", "Equipment"
    WORKOUT_AREAS = "workout_areas", "Workout Areas"
    STUDIOS_CLASS_SPACES = "studios_class_spaces", "Studios & Class Spaces"
    CHANGING_ROOMS_SHOWERS = "changing_rooms_showers", "Changing Rooms & Showers"
    WELLNESS_FACILITIES = "wellness_facilities", "Wellness Facilities"
    RECEPTION_LOUNGE = "reception_lounge", "Reception & Lounge"
    INTERIOR_DECOR = "interior_decor", "Interior & Decor"
    EXTERIOR_ENTRANCE = "exterior_entrance", "Exterior & Entrance"
    OTHER = "other", "Other"


class AmenityGroupEnum(models.TextChoices):
    CHANGING_AND_STORAGE = "changing_and_storage", "Changing & Storage"
    WELLNESS_AND_RECOVERY = "wellness_and_recovery", "Wellness & Recovery"
    COMFORT_AND_CONVENIENCE = "comfort_and_convenience", "Comfort & Convenience"
    FOOD_AND_DRINK = "food_and_drink", "Food & Drink"
    PARKING_AND_TRANSPORT = "parking_and_transport", "Parking & Transport"
    ACCESSIBILITY = "accessibility", "Accessibility"
    FAMILY_FACILITIES = "family_facilities", "Family Facilities"


class PlanStatusEnum(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    ARCHIVED = "archived", "Archived"


class PlanTypeEnum(models.TextChoices):
    TIME_BASED = "time_based", "Time Based"
    SESSION_BASED = "session_based", "Session Based"


class DurationUnitEnum(models.TextChoices):
    DAY = "day", "Day"
    WEEK = "week", "Week"
    MONTH = "month", "Month"
    SESSION = "session", "Session"


class PaymentScheduleEnum(models.TextChoices):
    FULL_PAYMENT = "full_payment", "Full Payment"
    INSTALMENTS = "instalments", "Instalments"


class MemberJoiningStatus(models.TextChoices):
    SENT_INVITATION = "sent_invitation", "Sent Invitation"
    JOINED = "joined", "Joined"


class MembershipStatusEnum(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled"
    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"


class PaymentStatusEnum(models.TextChoices):
    FULLY_PAID = "fully_paid", "Fully Paid"
    PARTIALLY_PAID = "partially_paid", "Partially Paid"
    UNPAID = "unpaid", "Unpaid"


class PaymentMethodEnum(models.TextChoices):
    CASH = "cash", "Cash"
    CREDIT_CARD = "credit_card", "Credit Card"
    DEBIT_CARD = "debit_card", "Debit Card"
    BANK_TRANSFER = "bank_transfer", "Bank Transfer"
    MOBILE_PAY = "mobile_pay", "Mobile Pay"
    OTHER = "other", "Other"


class LeadStageEnum(models.TextChoices):
    NEW = "new", "New"
    CONTACTED = "contacted", "Contacted"
    VISIT_TRIAL_BOOKED = "visit_trial_booked", "Visit / Trial Booked"
    JOINED = "joined", "Joined"
    NOT_JOINING = "not_joining", "Not Joining"


class NotJoiningReasonStandard(models.TextChoices):
    PRICE = "price", "Price"
    LOCATION = "location", "Location"
    TIMING = "timing", "Timing"
    CHOSE_ANOTHER_GYM = "chose_another_gym", "Chose Another Gym"
    OTHER = "other", "Other"


class LeadSourceEnum(models.TextChoices):
    WALK_IN = "walk_in", "Walk In"
    PHONE = "phone", "Phone"
    SOCIAL_MEDIA = "social_media", "Social Media"
    REFERRAL = "referral", "Referral"
    WEBSITE = "website", "Website"
    OTHER = "other", "Other"


class FitnessGoalEnum(models.TextChoices):
    GENERAL_FITNESS = "general_fitness", "General Fitness"
    STRENGTH = "strength", "Strength"
    MUSCLE_GAIN = "muscle_gain", "Muscle Gain"
    WEIGHT_LOSS = "weight_loss", "Weight Loss"
    OTHER = "other", "Other"


class RoutineFormatEnum(models.TextChoices):
    WEEKLY = "weekly", "Weekly"
    SESSION_BASED = "session_based", "Session-Based"


class RoutineLevelEnum(models.TextChoices):
    BEGINNER = "beginner", "Beginner"
    INTERMEDIATE = "intermediate", "Intermediate"
    ADVANCED = "advanced", "Advanced"


class PostPrivacyEnum(models.TextChoices):
    PUBLIC = "public", "Public"
    MEMBERS_ONLY = "members_only", "Gym Members Only"
    GYM_MEMBERS_ONLY = "gym_members_only", "Gym Members Only"
    PRIVATE = "private", "Private"


class MediaTypeEnum(models.TextChoices):
    PICTURE = "picture", "Picture"
    VIDEO = "video", "Video"


class ProcessingStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class AudienceMessagingEnum(models.TextChoices):
    """Audience visibility setting: Who can send direct messages to the gym."""
    EVERYONE = "everyone", "Everyone"
    FOLLOWERS_AND_MEMBERS = "followers_and_members", "Followers & Members"
    MEMBERS_ONLY = "members_only", "Members only"


class AudienceJoiningRequestEnum(models.TextChoices):
    """Audience visibility setting: Who can submit member joining requests to the gym."""
    EVERYONE = "everyone", "Everyone"
    NO_ONE = "no_one", "No one"


class AudienceMembersVisibilityEnum(models.TextChoices):
    """Audience visibility setting: Who can see the gym's member list."""
    EVERYONE = "everyone", "Everyone"
    ONLY_MEMBERS = "only_members", "Only Members"


class AudienceFollowingVisibilityEnum(models.TextChoices):
    """Audience visibility setting: Who can see the pages and people the gym follows."""
    EVERYONE = "everyone", "Everyone"
    ONLY_MEMBERS = "only_members", "Only members"
    PRIVATE = "private", "Private"


class PostsAgeRestrictionEnum(models.TextChoices):
    """Content filtering setting: Minimum age threshold required to view gym community posts."""
    ANY_AGE = "any_age", "Any age"
    AGE_17_PLUS = "17_plus", "17 and + age"
    AGE_18_PLUS = "18_plus", "18 and + age"
    AGE_19_PLUS = "19_plus", "19 and + age"
    AGE_20_PLUS = "20_plus", "20 and + age"


class ConversationTypeEnum(models.TextChoices):
    """Supported end-to-end messaging conversation channels."""
    USER_TO_USER = "user_to_user", "User to User"
    USER_TO_GYM = "user_to_gym", "User to Gym"
    GYM_TO_GYM = "gym_to_gym", "Gym to Gym"


class MessageSenderTypeEnum(models.TextChoices):
    """Identifies whether a message was authored as an individual user or under a gym identity."""
    USER = "user", "User"
    GYM = "gym", "Gym"


class MessageDeliveryStatusEnum(models.TextChoices):
    """Message lifecycle status for privacy and delivery tracking."""
    SENT = "sent", "Sent"
    DELIVERED = "delivered", "Delivered"
    READ = "read", "Read"


class KeyAlgorithmEnum(models.TextChoices):
    """Asymmetric cryptography key algorithms supported for E2EE."""
    X25519 = "x25519", "Curve25519 / X25519 (ECDH)"
    ED25519 = "ed25519", "Ed25519 (Digital Signatures)"


class AdminLogCategory(models.TextChoices):
    """Categories / modules for gym administration logs."""
    GYM_PROFILE = "gym_profile", "Gym Profile"
    POSTS = "posts", "Posts"
    ACCESS_CONTROL = "access_control", "People & Roles"
    VISIBILITY = "visibility", "Page Visibility"
    SETTINGS = "settings", "Settings & Alerts"
    MEMBERS = "members", "Members"
    MEMBER_REQUESTS = "member_requests", "Member Requests"
    MEMBERSHIP_PLANS = "membership_plans", "Membership Plans"
    ROUTINES = "routines", "Routine Templates"
    LEADS = "leads", "Leads"
    GENERAL = "general", "General"


class AdminLogActionType(models.TextChoices):
    """Machine-readable action types for gym administration logs."""
    # Gym Profile
    UPDATE_PAGE_INFO = "update_page_info", "Updated page information"
    UPDATE_GYM_PROFILE = "update_gym_profile", "Update Gym profile"
    UPDATE_GYM_LOCATION = "update_gym_location", "Updated gym location"
    UPDATE_OPENING_HOURS = "update_opening_hours", "Updated opening hours"
    ADD_GALLERY_MEDIA = "add_gallery_media", "Added gallery media"
    DELETE_GALLERY_MEDIA = "delete_gallery_media", "Deleted gallery media"

    # Community Posts
    PUBLISH_POST = "publish_post", "Publish a post"
    UPDATE_POST = "update_post", "Update a post"
    DELETE_POST = "delete_post", "Delete a post"

    # Staff & Access Control
    ADD_ADMIN = "add_admin", "Added an admin"
    UPDATE_STAFF_ROLE = "update_staff_role", "Update staff role"
    REMOVE_STAFF = "remove_staff", "Remove staff member"
    CREATE_ROLE = "create_role", "Create a role"
    UPDATE_ROLE = "update_role", "Update a role"
    DELETE_ROLE = "delete_role", "Delete a role"

    # Visibility & Lifecycle
    CHANGE_PAGE_VISIBILITY = "change_page_visibility", "Changed page visibility"

    # Settings & Privacy
    UPDATE_SETTINGS = "update_settings", "Update gym settings"
    BLOCK_USER = "block_user", "Block user"
    UNBLOCK_USER = "unblock_user", "Unblock user"

    # Member Requests
    CREATE_MEMBER_REQUEST = "create_member_request", "Create a member request"
    UPDATE_MEMBER_REQUEST = "update_member_request", "Update a member request"
    DELETE_MEMBER_REQUEST = "delete_member_request", "Delete a member request"

    # Members
    CREATE_MEMBER = "create_member", "Create a member"
    UPDATE_MEMBER = "update_member", "Update a member"
    DELETE_MEMBER = "delete_member", "Delete a member"

    # Custom Membership Plans
    CREATE_MEMBERSHIP_PLAN = "create_membership_plan", "Create a custom membership plan"
    UPDATE_MEMBERSHIP_PLAN = "update_membership_plan", "Update a custom membership plan"
    DELETE_MEMBERSHIP_PLAN = "delete_membership_plan", "Delete a custom membership plan"

    # Routine Templates
    CREATE_ROUTINE = "create_routine", "Create a routine template"
    UPDATE_ROUTINE = "update_routine", "Update a routine template"
    DELETE_ROUTINE = "delete_routine", "Delete a routine template"

    # Leads CRM
    CREATE_LEAD = "create_lead", "Create a lead"
    UPDATE_LEAD = "update_lead", "Update a lead"
    DELETE_LEAD = "delete_lead", "Delete a lead"

    # Custom / General
    CUSTOM_ACTION = "custom_action", "Custom Action"

