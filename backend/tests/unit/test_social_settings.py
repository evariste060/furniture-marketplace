"""The store's social media links (owner, 2026-11-18): https links on each network's own site, ""
to remove one, checked by the request schema and again when a stored value is read."""

import pytest
from pydantic import ValidationError

from app.schemas.settings import SOCIAL_KEYS, SOCIAL_NETWORKS, SettingsUpdateRequest
from app.services.settings_service import PUBLIC_KEYS, SETTINGS


@pytest.mark.parametrize(
    ("key", "url"),
    [
        ("social.facebook", "https://www.facebook.com/3sixtytech"),
        ("social.facebook", "https://fb.com/3sixtytech"),
        ("social.instagram", "https://instagram.com/3sixtytech/"),
        ("social.x", "https://twitter.com/3sixtytech"),
        ("social.youtube", "https://youtu.be/abc"),
        ("social.tiktok", "https://www.tiktok.com/@3sixtytech"),
        ("social.linkedin", "https://rw.linkedin.com/company/3sixtytech?trk=x"),
        ("social.x", ""),  # removes the link
    ],
)
def test_accepts_links_on_the_networks_own_site(key, url):
    assert SettingsUpdateRequest.model_validate({key: url}).changes() == {key: url}
    assert SETTINGS[key].valid(url)


@pytest.mark.parametrize(
    ("key", "url"),
    [
        ("social.facebook", "http://facebook.com/3sixtytech"),
        ("social.facebook", "facebook.com/3sixtytech"),
        ("social.facebook", "https://facebook.com.evil.example/x"),
        ("social.facebook", "https://notfacebook.com/x"),
        ("social.instagram", "https://facebook.com/3sixtytech"),
        ("social.youtube", "javascript:alert(1)"),
        ("social.x", "https://user:pass@x.com/3sixtytech"),
        ("social.x", "https://x.com:8443/3sixtytech"),
        ("social.x", "https://x.com:bad/3sixtytech"),
        ("social.tiktok", "https://www.tiktok.com/@3sixty tech"),
        ("social.tiktok", " https://www.tiktok.com/@3sixtytech"),
        ("social.linkedin", "https://linkedin.com/" + "a" * 300),
    ],
)
def test_refuses_other_links(key, url):
    with pytest.raises(ValidationError):
        SettingsUpdateRequest.model_validate({key: url})
    assert not SETTINGS[key].valid(url)


def test_null_and_unknown_networks_are_refused():
    with pytest.raises(ValidationError):
        SettingsUpdateRequest.model_validate({"social.facebook": None})
    with pytest.raises(ValidationError):
        SettingsUpdateRequest.model_validate({"social.myspace": "https://myspace.com/x"})


def test_every_network_is_a_public_setting():
    assert set(SOCIAL_KEYS) == set(SOCIAL_NETWORKS)
    assert set(SOCIAL_KEYS.values()) <= PUBLIC_KEYS
