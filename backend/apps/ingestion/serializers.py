"""DRF serializers for the ingestion context."""

from __future__ import annotations

from rest_framework import serializers

from .models import IngestionJob


class IngestionJobSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = IngestionJob
        fields = [
            "id",
            "source_channel",
            "original_filename",
            "file_size",
            "file_mime_type",
            "status",
            "upload_timestamp",
            "completed_at",
            "error_message",
            "extracted_text",
            "extraction_engine",
            "extraction_confidence",
            "state_transitions",
            "download_url",
        ]
        read_only_fields = fields

    def get_download_url(self, obj: IngestionJob) -> str | None:
        """Pre-signed URL — only minted when explicitly requested (detail view).
        List view callers re-request the detail to avoid signing many URLs at once."""
        if not self.context.get("include_download_url"):
            return None
        from . import services

        try:
            return services.presigned_download(job=obj)
        except Exception:
            return None
