import pytest

from app.errors import classify_ytdlp_error
from app.sources.official import check_playable


@pytest.mark.parametrize("msg,code", [
    ("ERROR: [youtube] abcdefghijk: Private video. Sign in if you've been granted access to this video. Use --cookies-from-browser", "video_private"),
    ("ERROR: [youtube] abcdefghijk: Video unavailable. This video is private", "video_private"),
    ("ERROR: [youtube] abcdefghijk: Join this channel to get access to members-only content like this video, and other exclusive perks.", "video_members_only"),
    ("ERROR: [youtube] abcdefghijk: This video is available to this channel's members on level: Tier 1 (or any higher level).", "video_members_only"),
    ("ERROR: [youtube] abcdefghijk: This video is only available to Music Premium members", "video_premium_only"),
    ("ERROR: [youtube] abcdefghijk: Sign in to confirm your age. This video may be inappropriate for some users.", "video_age_restricted"),
    ("ERROR: [youtube] abcdefghijk: Sign in to confirm you're not a bot.", "upstream_blocked"),
    ("ERROR: [youtube] abcdefghijk: Video unavailable. This video has been removed by the uploader", "video_unavailable"),
    ("ERROR: [youtube] abcdefghijk: Something new and strange. Use --cookies for the authentication.", "upstream_blocked"),
])
def test_classify(msg, code):
    assert classify_ytdlp_error(msg).code == code


def test_unknown_error_message_is_clean():
    e = classify_ytdlp_error("ERROR: [youtube] abcdefghijk: Something new and strange. Use --cookies for the authentication.")
    assert e.message == "YouTube returned an error: Something new and strange."


@pytest.mark.parametrize("availability,code", [
    ("private", "video_private"), ("subscriber_only", "video_members_only"), ("premium_only", "video_premium_only"),
])
def test_check_playable_blocks(availability, code):
    from app.errors import APIError
    with pytest.raises(APIError) as ei:
        check_playable({"id": "x", "availability": availability, "formats": [{}]})
    assert ei.value.code == code


def test_unlisted_is_allowed():
    check_playable({"id": "x", "availability": "unlisted", "formats": [{}], "duration": 60})


