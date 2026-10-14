from django.db import models


class UserStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    SUSPENDED = "suspended", "Suspended"


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
    PROSPECT = "prospect", "Prospect"
    ONBOARDING = "onboarding", "Onboarding"
    ACTIVE = "active", "Active"
    FROZEN = "frozen", "Frozen"
    CANCELLED = "cancelled", "Cancelled"
    EXPIRED = "expired", "Expired"


class MembershipStatusEnum(models.TextChoices):
    ACTIVE = "active", "Active"
    PENDING = "pending", "Pending"
    PAUSED = "paused", "Paused"
    CANCELLED = "cancelled", "Cancelled"
    EXPIRED = "expired", "Expired"


class PaymentStatusEnum(models.TextChoices):
    PENDING = "pending", "Pending"
    PAID = "paid", "Paid"
    FAILED = "failed", "Failed"
    REFUNDED = "refunded", "Refunded"


class PaymentMethodEnum(models.TextChoices):
    CARD = "card", "Credit/Debit Card"
    CASH = "cash", "Cash"
    BANK_TRANSFER = "bank_transfer", "Bank Transfer"
    POS = "pos", "POS Machine"
    ONLINE_GATEWAY = "online_gateway", "Online Payment Gateway"


class LeadStageEnum(models.TextChoices):
    NEW = "new", "New"
    CONTACTED = "contacted", "Contacted"
    TRIAL_BOOKED = "trial_booked", "Trial Booked"
    TRIAL_COMPLETED = "trial_completed", "Trial Completed"
    NEGOTIATION = "negotiation", "Negotiation"
    CONVERTED = "converted", "Converted"
    LOST = "lost", "Lost"


class NotJoiningReasonStandard(models.TextChoices):
    TOO_EXPENSIVE = "too_expensive", "Too Expensive"
    WRONG_LOCATION = "wrong_location", "Wrong Location"
    LACK_OF_TIME = "lack_of_time", "Lack of Time"
    JOINED_COMPETITOR = "joined_competitor", "Joined Competitor"
    MEDICAL_REASONS = "medical_reasons", "Medical Reasons"
    NOT_INTERESTED = "not_interested", "Not Interested"
    OTHER = "other", "Other"


class LeadSourceEnum(models.TextChoices):
    WEBSITE = "website", "Website"
    WALK_IN = "walk_in", "Walk In"
    REFERRAL = "referral", "Referral"
    SOCIAL_MEDIA = "social_media", "Social Media"
    PHONE_INQUIRY = "phone_inquiry", "Phone Inquiry"
    FLYER = "flyer", "Flyer / Banner"
    OTHER = "other", "Other"


class FitnessGoalEnum(models.TextChoices):
    WEIGHT_LOSS = "weight_loss", "Weight Loss"
    MUSCLE_GAIN = "muscle_gain", "Muscle Gain"
    GENERAL_FITNESS = "general_fitness", "General Fitness"
    BODYBUILDING = "bodybuilding", "Bodybuilding"
    ENDURANCE = "endurance", "Endurance"
    REHABILITATION = "rehabilitation", "Rehabilitation"
    STRENGTH_TRAINING = "strength_training", "Strength Training"
    OTHER = "other", "Other"


class RoutineFormatEnum(models.TextChoices):
    STANDARD = "standard", "Standard"
    SUPERSET = "superset", "Superset"
    CIRCUIT = "circuit", "Circuit"
    EMOM = "emom", "EMOM"
    AMRAP = "amrap", "AMRAP"
    FOR_TIME = "for_time", "For Time"
    TABATA = "tabata", "Tabata"


class RoutineLevelEnum(models.TextChoices):
    BEGINNER = "beginner", "Beginner"
    INTERMEDIATE = "intermediate", "Intermediate"
    ADVANCED = "advanced", "Advanced"
    ELITE = "elite", "Elite"


class PostPrivacyEnum(models.TextChoices):
    PUBLIC = "public", "Public"
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
