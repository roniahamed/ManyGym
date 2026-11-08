import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gyms", "0011_alter_gymadminlog_action_type_and_more"),
        ("enquiries", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="enquiry",
            name="gym",
            field=models.ForeignKey(
                help_text="Associated gym entity to which this enquiry belongs.",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="enquiries",
                to="gyms.gym",
            ),
        ),
    ]

