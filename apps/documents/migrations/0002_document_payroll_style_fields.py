# Generated migration for Document model enhancements

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_account_owner_set_null'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='document',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, help_text='Unique identifier for the document', unique=True),
        ),
        migrations.AddField(
            model_name='document',
            name='is_deleted',
            field=models.BooleanField(default=False, help_text='Soft delete flag'),
        ),
        migrations.AddField(
            model_name='document',
            name='original_filename',
            field=models.CharField(blank=True, default='', help_text='Original filename when uploaded', max_length=255),
        ),
        migrations.AddField(
            model_name='document',
            name='mime_type',
            field=models.CharField(blank=True, default='', help_text='MIME type of the file', max_length=100),
        ),
        migrations.AddField(
            model_name='document',
            name='file_size',
            field=models.BigIntegerField(default=0, help_text='File size in bytes'),
        ),
        migrations.AddField(
            model_name='document',
            name='file_hash',
            field=models.CharField(blank=True, default='', help_text='SHA256 hash for integrity verification', max_length=64),
        ),
        migrations.AddField(
            model_name='document',
            name='title',
            field=models.CharField(blank=True, default='', help_text='Title/description of the document', max_length=255),
        ),
        migrations.AddField(
            model_name='document',
            name='description',
            field=models.TextField(blank=True, default='', help_text='Additional description or notes'),
        ),
        migrations.AddField(
            model_name='document',
            name='tags',
            field=models.CharField(blank=True, default='', help_text='Comma-separated tags for easy searching', max_length=500),
        ),
        migrations.AddField(
            model_name='document',
            name='is_starred',
            field=models.BooleanField(default=False, help_text='Mark as starred for quick access'),
        ),
        migrations.AddField(
            model_name='document',
            name='is_archived',
            field=models.BooleanField(default=False, help_text='Archive old documents'),
        ),
        migrations.AddField(
            model_name='document',
            name='is_public',
            field=models.BooleanField(default=False, help_text='Make visible to other users'),
        ),
        migrations.AddField(
            model_name='document',
            name='view_count',
            field=models.PositiveIntegerField(default=0, help_text='Number of times this document has been viewed'),
        ),
        migrations.AddField(
            model_name='document',
            name='download_count',
            field=models.PositiveIntegerField(default=0, help_text='Number of times this document has been downloaded'),
        ),
        migrations.AddField(
            model_name='document',
            name='last_viewed_at',
            field=models.DateTimeField(blank=True, help_text='Last time this document was viewed', null=True),
        ),
        migrations.AddField(
            model_name='document',
            name='last_downloaded_at',
            field=models.DateTimeField(blank=True, help_text='Last time this document was downloaded', null=True),
        ),
        migrations.AddField(
            model_name='document',
            name='verified_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='documents_verified', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='document',
            name='verified_at',
            field=models.DateTimeField(blank=True, help_text='When the document was verified', null=True),
        ),
        migrations.AddField(
            model_name='document',
            name='approved_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='documents_approved', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='document',
            name='approved_at',
            field=models.DateTimeField(blank=True, help_text='When the document was approved', null=True),
        ),
        migrations.AddIndex(
            model_name='document',
            index=models.Index(fields=['company', 'is_deleted', '-created_at'], name='documents_d_compan_7e8a4d_idx'),
        ),
        migrations.AddIndex(
            model_name='document',
            index=models.Index(fields=['company', 'processing_status'], name='documents_d_compan_5c1e1a_idx'),
        ),
        migrations.AddIndex(
            model_name='document',
            index=models.Index(fields=['company', 'document_type'], name='documents_d_compan_3b2f8c_idx'),
        ),
        migrations.AddIndex(
            model_name='document',
            index=models.Index(fields=['is_starred', 'is_archived'], name='documents_d_is_star_f8a2e1_idx'),
        ),
    ]
