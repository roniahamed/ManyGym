import uuid
from rest_framework import serializers


class StrictCharField(serializers.CharField):
    """Enforces strict string types, preventing silent type coercion."""
    def to_internal_value(self, data):
        if not isinstance(data, str):
            raise serializers.ValidationError("This field must be a valid string.")
        return super().to_internal_value(data)


# ==============================================================================
# 1. DASHBOARD SUMMARY SERIALIZERS
# ==============================================================================

class HeadlineMetricsSerializer(serializers.Serializer):
    total_members = serializers.IntegerField()
    total_active_members = serializers.IntegerField()
    expiring_memberships_next_7_days = serializers.IntegerField()
    expiring_memberships_next_30_days = serializers.IntegerField()
    new_leads_this_week = serializers.IntegerField()
    pending_next_moves_today = serializers.IntegerField()
    overdue_next_moves = serializers.IntegerField()
    todays_scheduled_trials = serializers.IntegerField()
    todays_revenue = serializers.FloatField()
    current_month_revenue = serializers.FloatField()


class DashboardSummarySerializer(serializers.Serializer):
    gym_id = serializers.UUIDField()
    gym_name = serializers.CharField()
    generated_at = serializers.DateTimeField()
    headline_metrics = HeadlineMetricsSerializer()


# ==============================================================================
# 2. REVENUE REPORT SERIALIZERS
# ==============================================================================

class PaymentMethodBreakdownSerializer(serializers.Serializer):
    payment_method = serializers.CharField()
    total_amount = serializers.FloatField()
    transaction_count = serializers.IntegerField()
    percentage = serializers.FloatField()


class PlanRevenueDistributionSerializer(serializers.Serializer):
    plan_id = serializers.UUIDField(allow_null=True)
    plan_name = serializers.CharField()
    total_amount = serializers.FloatField()
    subscription_count = serializers.IntegerField()
    transaction_count = serializers.IntegerField()


class DailyRevenueBreakdownSerializer(serializers.Serializer):
    date = serializers.CharField()
    amount = serializers.FloatField()
    transaction_count = serializers.IntegerField()


class RevenueReportSerializer(serializers.Serializer):
    gym_id = serializers.UUIDField()
    start_date = serializers.CharField()
    end_date = serializers.CharField()
    total_revenue = serializers.FloatField()
    total_transactions = serializers.IntegerField()
    average_transaction_value = serializers.FloatField()
    payment_method_breakdown = PaymentMethodBreakdownSerializer(many=True)
    plan_distribution = PlanRevenueDistributionSerializer(many=True)
    daily_breakdown = DailyRevenueBreakdownSerializer(many=True)


# ==============================================================================
# 3. MEMBERSHIP GROWTH SERIALIZERS
# ==============================================================================

class SubscriptionStatusBreakdownSerializer(serializers.Serializer):
    status = serializers.CharField()
    count = serializers.IntegerField()


class PlanActiveSubscriptionSerializer(serializers.Serializer):
    plan_id = serializers.UUIDField(allow_null=True)
    plan_name = serializers.CharField()
    active_subscriptions = serializers.IntegerField()


class MembershipGrowthReportSerializer(serializers.Serializer):
    gym_id = serializers.UUIDField()
    start_date = serializers.CharField()
    end_date = serializers.CharField()
    total_members = serializers.IntegerField()
    active_subscriptions = serializers.IntegerField()
    new_members_in_period = serializers.IntegerField()
    new_subscriptions_in_period = serializers.IntegerField()
    cancelled_subscriptions_in_period = serializers.IntegerField()
    net_growth = serializers.IntegerField()
    churn_rate_percentage = serializers.FloatField()
    status_breakdown = SubscriptionStatusBreakdownSerializer(many=True)
    plan_breakdown = PlanActiveSubscriptionSerializer(many=True)


# ==============================================================================
# 4. LEAD FUNNEL SERIALIZERS
# ==============================================================================

class FunnelStagesSerializer(serializers.Serializer):
    new = serializers.IntegerField()
    contacted = serializers.IntegerField()
    trial_booked = serializers.IntegerField()
    joined = serializers.IntegerField()
    lost = serializers.IntegerField()


class ConversionRatesSerializer(serializers.Serializer):
    trial_booking_rate_percentage = serializers.FloatField()
    trial_to_join_rate_percentage = serializers.FloatField()
    overall_conversion_rate_percentage = serializers.FloatField()
    drop_off_rate_percentage = serializers.FloatField()


class LeadStageCountSerializer(serializers.Serializer):
    stage = serializers.CharField()
    count = serializers.IntegerField()


class LostReasonCountSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_null=True)
    type = serializers.CharField()
    count = serializers.IntegerField()


class SourceCountSerializer(serializers.Serializer):
    source = serializers.CharField()
    count = serializers.IntegerField()
    percentage = serializers.FloatField()


class LeadFunnelReportSerializer(serializers.Serializer):
    gym_id = serializers.UUIDField()
    start_date = serializers.CharField()
    end_date = serializers.CharField()
    total_leads = serializers.IntegerField()
    funnel_stages = FunnelStagesSerializer()
    conversion_rates = ConversionRatesSerializer()
    stage_breakdown = LeadStageCountSerializer(many=True)
    lost_reason_distribution = LostReasonCountSerializer(many=True)
    source_breakdown = SourceCountSerializer(many=True)


# ==============================================================================
# 5. TRAINER WORKLOAD SERIALIZERS
# ==============================================================================

class TrainerWorkloadItemSerializer(serializers.Serializer):
    staff_assignment_id = serializers.UUIDField()
    user_id = serializers.UUIDField()
    name = serializers.CharField()
    email = serializers.EmailField()
    role_name = serializers.CharField()
    role_slug = serializers.CharField(allow_null=True)
    assigned_members_count = serializers.IntegerField()
    active_routines_count = serializers.IntegerField()
    total_routines_prescribed = serializers.IntegerField()


class TrainerWorkloadReportSerializer(serializers.Serializer):
    gym_id = serializers.UUIDField()
    gym_name = serializers.CharField()
    total_active_staff = serializers.IntegerField()
    total_assigned_members = serializers.IntegerField()
    total_active_routines = serializers.IntegerField()
    average_members_per_trainer = serializers.FloatField()
    trainers = TrainerWorkloadItemSerializer(many=True)
