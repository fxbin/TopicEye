"""
Table-driven tests for the URL → SourceType recognizer (T1-3b).
"""

import pytest

from app.models.source import SourceType
from app.services.scrapers.recognizer import recognize_source_type


@pytest.mark.parametrize(
    "url, expected_type",
    [
        # RSS — explicit feed hints
        ("https://feeds.example.com/blog", SourceType.RSS),
        ("https://example.com/feed.xml", SourceType.RSS),
        ("https://example.com/blog/index.rss", SourceType.RSS),
        ("https://example.com/posts.atom", SourceType.RSS),
        ("https://example.com/feed", SourceType.RSS),
        ("https://example.com/rss", SourceType.RSS),
        # Plain URL — default RSS
        ("https://example.com/some/page", SourceType.RSS),
        ("https://blog.example.com/post-1", SourceType.RSS),
    ],
)
def test_recognize_rss(url, expected_type):
    st, normalized, config = recognize_source_type(url)
    assert st is expected_type
    assert normalized == url
    assert config is None


@pytest.mark.parametrize(
    "url, name, expected_type, expect_screen_name",
    [
        # xgo.ing with handle in name
        (
            "https://xgo.ing/openai",
            "OpenAI (@OpenAI)",
            SourceType.TWITTER_RSS,
            "OpenAI",
        ),
        # xgo.ing with handle in URL path
        ("https://xgo.ing/elonmusk", None, SourceType.TWITTER_RSS, "elonmusk"),
        # xgo.ing rss endpoint — no usable handle
        ("https://xgo.ing/rss", None, SourceType.TWITTER_RSS, None),
    ],
)
def test_recognize_xgo_ing(url, name, expected_type, expect_screen_name):
    st, normalized, config = recognize_source_type(url, name=name)
    assert st is expected_type
    assert normalized == url
    if expect_screen_name:
        assert config == {"screen_name": expect_screen_name}
    else:
        assert config is None


@pytest.mark.parametrize(
    "url, expected_type, expect_config_key",
    [
        # /channel/UCxxxx — channel_id extracted
        (
            "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv",
            SourceType.YOUTUBE,
            "channel_id",
        ),
        # @handle — scraper resolves channel_id later
        ("https://www.youtube.com/@OpenAI", SourceType.YOUTUBE, None),
        # /user/name — scraper resolves channel_id later
        ("https://www.youtube.com/user/Google", SourceType.YOUTUBE, None),
        # already an RSS feed URL with channel_id
        (
            "https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuv",
            SourceType.YOUTUBE,
            "channel_id",
        ),
    ],
)
def test_recognize_youtube(url, expected_type, expect_config_key):
    st, normalized, config = recognize_source_type(url)
    assert st is expected_type
    assert normalized == url
    if expect_config_key:
        assert config is not None
        assert expect_config_key in config
    else:
        assert config is None


@pytest.mark.parametrize(
    "url, expected_type, expect_config_key",
    [
        # Apple Podcast
        (
            "https://podcasts.apple.com/us/podcast/some-show/id1234567890",
            SourceType.PODCAST,
            "itunes_id",
        ),
        # 小宇宙
        ("https://xiaoyuzhoufm.com/podcast/abc123", SourceType.PODCAST, None),
        # Buzzsprout
        ("https://www.buzzsprout.com/12345", SourceType.PODCAST, None),
        # Podbean
        ("https://shows.podbean.com/some-show", SourceType.PODCAST, None),
        # Anchor
        ("https://anchor.fm/some-show", SourceType.PODCAST, None),
        # Spotify show
        ("https://open.spotify.com/show/abc123", SourceType.PODCAST, None),
    ],
)
def test_recognize_podcast(url, expected_type, expect_config_key):
    st, normalized, config = recognize_source_type(url)
    assert st is expected_type
    assert normalized == url
    if expect_config_key:
        assert config is not None
        assert expect_config_key in config
    else:
        assert config is None


@pytest.mark.parametrize(
    "url, expected_type",
    [
        # Substack
        ("https://stratechery.substack.com", SourceType.NEWSLETTER),
        ("https://www.lennysnewsletter.com", SourceType.RSS),  # not a substack host — falls to RSS
        # Beehiiv
        ("https://example.beehiiv.com", SourceType.NEWSLETTER),
        # Buttondown
        ("https://buttondown.email/example", SourceType.NEWSLETTER),
        # Tinyletter
        ("https://tinyletter.com/example", SourceType.NEWSLETTER),
    ],
)
def test_recognize_newsletter(url, expected_type):
    st, normalized, config = recognize_source_type(url)
    assert st is expected_type
    assert normalized == url


def test_recognize_empty_url():
    st, normalized, config = recognize_source_type("")
    assert st is SourceType.RSS
    assert normalized == ""
    assert config is None


def test_recognizer_importable():
    """Sanity: the module loads cleanly and is registered in scrapers."""
    from app.services.scrapers import recognizer  # noqa: F401

    assert callable(recognizer.recognize_source_type)
