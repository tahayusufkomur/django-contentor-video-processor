import os
from urllib.parse import urlparse, urlunparse

import requests
from django.conf import settings
from django.urls import reverse



def replace_file_format(url, new_ext):
    """
    Replaces the file extension in the given URL with `new_ext`.

    Parameters:
        url (str): The original URL.
        new_ext (str): The new file extension (with or without dot, e.g. 'mp4' or '.mp4').

    Returns:
        str: The updated URL with the new file extension.
    """
    if not new_ext.startswith('.'):
        new_ext = '.' + new_ext

    parsed = urlparse(url)
    path = parsed.path
    base, _ = os.path.splitext(path)
    new_path = base + new_ext

    # Return the full URL with updated path
    return urlunparse(parsed._replace(path=new_path))

def get_webhook_url():
    base_url = getattr(settings, "BASE_URL", "")
    if not base_url:
        return None
    return f"{base_url}{reverse('webhook_receiver')}"


def process_video(
    download_url,
    upload_url,
    resolution=None,
):

    headers = {
        "Content-Type": "application/json",
        "X-User-Access-Key": settings.CONTENTOR_VIDEO_PROCESSING_ACCESS_KEY,
        "X-User-Access-Token": settings.CONTENTOR_VIDEO_PROCESSING_ACCESS_TOKEN,
    }

    contentor_config = getattr(settings, "CONTENTOR_VIDEO_PROCESSING_CONFIG", {})

    config = {
        # contentor settings
        "download_provider": contentor_config.get("download_provider", "aws"),
        "upload_provider": contentor_config.get("upload_provider", "aws"),
        "download_url": download_url,
        "upload_url": upload_url,
        "webhook_url": getattr(settings, "CONTENTOR_WEBHOOK_URL", get_webhook_url()),

        # video settings
        "crf": contentor_config.get("crf", "30"),
        "preset": contentor_config.get("preset", "ultrafast"),
        "optimise_for_web": contentor_config.get("optimise_for_web", True),

        # access keys
        "download_access_key": settings.AWS_ACCESS_KEY_ID,
        "download_access_secret": settings.AWS_SECRET_ACCESS_KEY,
        "upload_access_key": settings.AWS_ACCESS_KEY_ID,
        "upload_access_secret": settings.AWS_SECRET_ACCESS_KEY
    }

    if resolution:
        config["resolution"] = resolution

    try:
        response = requests.post(
            contentor_config.get("api_url", "https://process.contentor.app/api/process-video/"), headers=headers, json=config
        )

        if response.status_code == 200:
            result = response.json()
            print(f"✅ Video processing for {resolution} submitted successfully!")
            print(f"Job ID: {result.get('id')}")
            print(f"Status: {result.get('status')}")
            return result.get("id")
        else:
            print(
                f"❌ Error processing {resolution}: {response.status_code} - {response.text}"
            )

    except Exception as e:
        print(f"🔥 Exception while processing video at {resolution}: {str(e)}")