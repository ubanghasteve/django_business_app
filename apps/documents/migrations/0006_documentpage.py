from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0005_document_cleaned_tables_json_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='DocumentPage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('page_number', models.PositiveIntegerField(db_index=True)),
                ('text', models.TextField(blank=True)),
                ('tables_json', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('document', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pages', to='documents.document')),
            ],
            options={
                'verbose_name': 'Document page',
                'verbose_name_plural': 'Document pages',
                'ordering': ['page_number'],
                'unique_together': {('document', 'page_number')},
            },
        ),
    ]

