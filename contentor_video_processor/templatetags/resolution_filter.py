from django import template

register = template.Library()

@register.filter
def has_resolution(video, resolution):
    """Check if video has a specific resolution"""
    if resolution == 'original':
        return bool(video.video)
    else:
        field_name = f'video_{resolution}'
        return bool(getattr(video, field_name, None))