from django.core.exceptions import ValidationError
from django.forms import fields

from contentor_video_processor.widgets import ResumableAdminWidget


class FormResumableFileField(fields.FileField):
    widget = ResumableAdminWidget

    def to_python(self, data):
        if self.required:
            if not data or data == "None":
                raise ValidationError(self.error_messages["empty"])
        return data
