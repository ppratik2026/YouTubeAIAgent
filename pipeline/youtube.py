"""YouTube Data API upload with a stored refresh token (scripts/get_refresh_token.py makes it once).

Default quota is 10,000 units/day per Google Cloud project and one upload costs ~1,600, so about six
uploads a day. Until Google audits the project, every API upload is locked to private."""
import json
import os

from . import settings
from .util import HTTP, log

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


class QuotaExceeded(RuntimeError):
    pass


def configured():
    return bool(settings.YT_CLIENT_ID and settings.YT_CLIENT_SECRET and settings.YT_REFRESH_TOKEN)


def access_token():
    r = HTTP.post(TOKEN_URL, timeout=30, data={
        "client_id": settings.YT_CLIENT_ID, "client_secret": settings.YT_CLIENT_SECRET,
        "refresh_token": settings.YT_REFRESH_TOKEN, "grant_type": "refresh_token"})
    if r.status_code != 200:
        raise RuntimeError(f"YouTube login failed ({r.status_code}): {r.text[:300]} - "
                           "run scripts/get_refresh_token.py again")
    return r.json()["access_token"]


def _check(r, what):
    if r.status_code in (200, 201):
        return r
    if r.status_code == 403 and ("quotaExceeded" in r.text or "uploadLimitExceeded" in r.text):
        raise QuotaExceeded(r.text[:300])
    raise RuntimeError(f"{what} failed ({r.status_code}): {r.text[:500]}")


def upload(video_path, meta, publish_at=None):
    """meta: title, description, tags, category_id, language. Returns the YouTube video id."""
    token = access_token()
    status = {"privacyStatus": settings.UPLOAD_PRIVACY, "selfDeclaredMadeForKids": False,
              "containsSyntheticMedia": True}
    if publish_at:
        status.update(privacyStatus="private", publishAt=publish_at)
    body = {"snippet": {"title": meta["title"][:100], "description": meta["description"][:5000],
                        "tags": meta.get("tags", []), "categoryId": meta.get("category_id", "22"),
                        "defaultLanguage": meta["language"], "defaultAudioLanguage": meta["language"]},
            "status": status}
    size = os.path.getsize(video_path)
    r = _check(HTTP.post(UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"},
                         headers={"Authorization": f"Bearer {token}",
                                  "Content-Type": "application/json; charset=UTF-8",
                                  "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
                         data=json.dumps(body), timeout=60), "upload start")
    session = r.headers["Location"]
    with open(video_path, "rb") as fh:
        r = _check(HTTP.put(session, data=fh, timeout=3600, headers={
            "Authorization": f"Bearer {token}", "Content-Type": "video/mp4", "Content-Length": str(size)}),
            "upload")
    vid = r.json()["id"]
    log.info("uploaded https://youtu.be/%s", vid)
    return vid


def set_thumbnail(video_id, jpg):
    """Custom thumbnails need a phone-verified channel; failure here never fails the upload."""
    try:
        with open(jpg, "rb") as fh:
            _check(HTTP.post("https://www.googleapis.com/upload/youtube/v3/thumbnails/set",
                             params={"videoId": video_id}, data=fh, timeout=120,
                             headers={"Authorization": f"Bearer {access_token()}", "Content-Type": "image/jpeg"}),
                   "thumbnail")
    except QuotaExceeded:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("thumbnail not set (is the channel phone-verified?): %s", e)
