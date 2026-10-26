import pytest

from app.errors import InvalidURL
from app.urls import extract_video_id, timestamp_link

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VID}",
    f"https://youtube.com/watch?v={VID}&t=42s",
    f"http://m.youtube.com/watch?feature=share&v={VID}",
    f"https://youtu.be/{VID}",
    f"https://youtu.be/{VID}?si=abc&t=10",
    f"https://www.youtube.com/shorts/{VID}",
    f"https://www.youtube.com/embed/{VID}",
    f"https://www.youtube.com/live/{VID}?feature=share",
    f"https://music.youtube.com/watch?v={VID}",
    f"www.youtube.com/watch?v={VID}",
    VID,
])
def test_valid_urls(url):
    assert extract_video_id(url) == VID


@pytest.mark.parametrize("url", [
    "",
    "https://vimeo.com/123456",
    f"https://evil.com/watch?v={VID}",
    f"https://youtube.com.evil.com/watch?v={VID}",
    f"https://user:pass@youtube.com/watch?v={VID}",
    f"https://youtube.com:8080/watch?v={VID}",
    "https://www.youtube.com/watch?v=short",
    "https://www.youtube.com/channel/UC123",
    f"ftp://youtube.com/watch?v={VID}",
    f"file:///etc/passwd?v={VID}",
    "http://169.254.169.254/latest/meta-data",
    "https://youtu.be/" + "a" * 3000,
])
def test_invalid_urls(url):
    with pytest.raises(InvalidURL):
        extract_video_id(url)


def test_timestamp_link():
    assert timestamp_link(VID, 125.9) == f"https://youtu.be/{VID}?t=125"
