import uuid
from django.db import models
from django.utils import timezone

from common.enums import (
    RoutineFormatEnum,
    RoutineLevelEnum,
    FitnessGoalEnum,
)


class RoutineTemplate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        related_name="routine_templates",
    )
    created_by_staff = models.ForeignKey(
        "access_control.GymStaffAssignment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_routine_templates",
    )
    template_name = models.CharField(max_length=255)
    routine_format = models.CharField(
        max_length=50,
        choices=RoutineFormatEnum.choices,
        default=RoutineFormatEnum.WEEKLY,
    )
    level = models.CharField(
        max_length=50,
        choices=RoutineLevelEnum.choices,
        default=RoutineLevelEnum.BEGINNER,
    )
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "routine_templates"
        verbose_name = "Routine Template"
        verbose_name_plural = "Routine Templates"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["gym", "-created_at"], name="idx_rtemp_gym_created"),
            models.Index(fields=["gym", "routine_format"], name="idx_rtemp_gym_format"),
            models.Index(fields=["gym", "level"], name="idx_rtemp_gym_level"),
        ]

    def __str__(self):
        return f"{self.template_name} ({self.get_routine_format_display()})"


class RoutineTemplateGoal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template = models.ForeignKey(
        RoutineTemplate,
        on_delete=models.CASCADE,
        related_name="goals",
    )
    goal = models.CharField(max_length=50, choices=FitnessGoalEnum.choices)

    class Meta:
        db_table = "routine_template_goals"
        verbose_name = "Routine Template Goal"
        verbose_name_plural = "Routine Template Goals"
        unique_together = ("template", "goal")

    def __str__(self):
        return f"{self.template.template_name} - {self.get_goal_display()}"


class RoutineTemplateDay(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template = models.ForeignKey(
        RoutineTemplate,
        on_delete=models.CASCADE,
        related_name="days",
    )
    day_of_week = models.IntegerField(
        null=True,
        blank=True,
        help_text="1=Monday, 2=Tuesday ... 7=Sunday for weekly format",
    )
    session_number = models.IntegerField(
        null=True,
        blank=True,
        help_text="1, 2, 3... for session-based format",
    )
    is_rest_day = models.BooleanField(default=False)
    workout_title = models.CharField(max_length=255, blank=True, null=True)
    workday_note = models.TextField(blank=True, null=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "routine_template_days"
        verbose_name = "Routine Template Day"
        verbose_name_plural = "Routine Template Days"
        ordering = ["sort_order", "day_of_week", "session_number"]
        indexes = [
            models.Index(fields=["template", "sort_order"], name="idx_rtemp_day_tmpl_order"),
            models.Index(fields=["template", "day_of_week"], name="idx_rtemp_day_tmpl_dow"),
            models.Index(fields=["template", "session_number"], name="idx_rtemp_day_tmpl_sess"),
        ]

    def __str__(self):
        if self.template.routine_format == RoutineFormatEnum.WEEKLY:
            return f"Day {self.day_of_week} ({'Rest' if self.is_rest_day else self.workout_title or 'Workout'})"
        return f"Session {self.session_number} ({self.workout_title or 'Session'})"


class RoutineTemplateExercise(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template_day = models.ForeignKey(
        RoutineTemplateDay,
        on_delete=models.CASCADE,
        related_name="exercises",
    )
    exercise_name = models.CharField(max_length=255)
    sets = models.IntegerField(null=True, blank=True, help_text="Nullable for cardio")
    reps_or_duration = models.CharField(max_length=100, help_text="e.g. 10 reps or 15 min")
    rest_seconds = models.IntegerField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "routine_template_exercises"
        verbose_name = "Routine Template Exercise"
        verbose_name_plural = "Routine Template Exercises"
        ordering = ["sort_order", "id"]
        indexes = [
            models.Index(fields=["template_day", "sort_order"], name="idx_rtemp_ex_day_order"),
        ]

    def __str__(self):
        return f"{self.exercise_name} ({self.reps_or_duration})"


class MemberRoutine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    member = models.ForeignKey(
        "members.Member",
        on_delete=models.CASCADE,
        related_name="routines",
    )
    source_template = models.ForeignKey(
        RoutineTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="member_routines",
    )
    prescribed_by_staff = models.ForeignKey(
        "access_control.GymStaffAssignment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prescribed_routines",
    )
    routine_name = models.CharField(max_length=255)
    routine_format = models.CharField(
        max_length=50,
        choices=RoutineFormatEnum.choices,
        default=RoutineFormatEnum.WEEKLY,
    )
    level = models.CharField(
        max_length=50,
        choices=RoutineLevelEnum.choices,
        default=RoutineLevelEnum.BEGINNER,
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True)
    assigned_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "member_routines"
        verbose_name = "Member Routine"
        verbose_name_plural = "Member Routines"
        ordering = ["-is_active", "-assigned_at"]
        indexes = [
            models.Index(fields=["member", "-is_active", "-assigned_at"], name="idx_mrout_mem_act_asgn"),
            models.Index(fields=["member", "is_active"], name="idx_mrout_mem_active"),
        ]

    def __str__(self):
        return f"{self.member.full_name} - {self.routine_name} ({'Active' if self.is_active else 'Inactive'})"


class MemberRoutineDay(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    member_routine = models.ForeignKey(
        MemberRoutine,
        on_delete=models.CASCADE,
        related_name="days",
    )
    day_of_week = models.IntegerField(null=True, blank=True)
    session_number = models.IntegerField(null=True, blank=True)
    is_rest_day = models.BooleanField(default=False)
    workout_title = models.CharField(max_length=255, blank=True, null=True)
    workday_note = models.TextField(blank=True, null=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "member_routine_days"
        verbose_name = "Member Routine Day"
        verbose_name_plural = "Member Routine Days"
        ordering = ["sort_order", "day_of_week", "session_number"]
        indexes = [
            models.Index(fields=["member_routine", "sort_order"], name="idx_mrout_day_rout_order"),
        ]

    def __str__(self):
        if self.member_routine.routine_format == RoutineFormatEnum.WEEKLY:
            return f"Day {self.day_of_week} ({'Rest' if self.is_rest_day else self.workout_title or 'Workout'})"
        return f"Session {self.session_number} ({self.workout_title or 'Session'})"


class MemberRoutineExercise(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    member_routine_day = models.ForeignKey(
        MemberRoutineDay,
        on_delete=models.CASCADE,
        related_name="exercises",
    )
    exercise_name = models.CharField(max_length=255)
    sets = models.IntegerField(null=True, blank=True)
    reps_or_duration = models.CharField(max_length=100)
    rest_seconds = models.IntegerField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "member_routine_exercises"
        verbose_name = "Member Routine Exercise"
        verbose_name_plural = "Member Routine Exercises"
        ordering = ["sort_order", "id"]
        indexes = [
            models.Index(fields=["member_routine_day", "sort_order"], name="idx_mrout_ex_day_order"),
        ]

    def __str__(self):
        return f"{self.exercise_name} ({self.reps_or_duration})"

