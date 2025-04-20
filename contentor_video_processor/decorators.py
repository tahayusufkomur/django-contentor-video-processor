# utils/decorators.py (or wherever you prefer)
from django.conf import settings
from django.contrib.auth.decorators import login_required

def login_required_if_setting(view_func):
    """
    Conditionally apply login_required based on settings.VIDEO_SIGNED_URL_LOGIN_REQUIRED
    """
    if getattr(settings, "CONTENTOR_VIDEO_SIGNED_URL_LOGIN_REQUIRED", True):
        return login_required(view_func)
    return view_func
