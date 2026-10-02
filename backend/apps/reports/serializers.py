from rest_framework import serializers

from apps.core.signed_urls import file_url

from .models import CustomerFeedback, Report


class ReportBriefSerializer(serializers.ModelSerializer):
    share_url = serializers.CharField(read_only=True)
    verify_url = serializers.CharField(read_only=True)
    pdf_url = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = [
            "id", "number", "status", "revision", "content_hash", "share_url", "verify_url", "pdf_url",
            "generated_at", "finalized_at", "approved_at", "approved_by_name", "view_count",
        ]

    def get_pdf_url(self, report):
        return file_url("report_pdf", report.id, self.context.get("request")) if report.pdf else None


class CustomerFeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerFeedback
        fields = ["id", "kind", "name", "message", "created_at", "resolved_at"]


class ReportSerializer(ReportBriefSerializer):
    job = serializers.UUIDField(source="job_id", read_only=True)
    feedback = CustomerFeedbackSerializer(many=True, read_only=True)

    class Meta(ReportBriefSerializer.Meta):
        fields = ReportBriefSerializer.Meta.fields + ["job", "snapshot", "feedback"]


class FinalizeSerializer(serializers.Serializer):
    force = serializers.BooleanField(default=False)
