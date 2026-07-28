import pytest

from engierun.tfrrs import validate_profile_url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tfrrs.org/athletes/8617086/Dartmouth/Ayush_Saran.html",
        "https://tfrrs.org/athletes/8617086/Dartmouth/Ayush_Saran.html",
        "https://www.tfrrs.org/athletes/8620042/Cornell/Matthew_O'Brien.html",
    ],
)
def test_validate_profile_url_accepts_only_real_tfrrs_athlete_pages(url):
    assert validate_profile_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://www.tfrrs.org/athletes/8617086/Dartmouth/Ayush_Saran.html",
        "https://tfrrs.org.evil.example/athletes/8617086/x",
        "https://evil.example/?next=https://www.tfrrs.org/athletes/8617086/x",
        "https://www.tfrrs.org/teams/tf/NH_college_m_Dartmouth.html",
        "file:///etc/passwd",
        "https://user@www.tfrrs.org/athletes/8617086/Dartmouth/Ayush_Saran.html",
        "https://www.tfrrs.org:444/athletes/8617086/Dartmouth/Ayush_Saran.html",
        "https://www.tfrrs.org/athletes/8617086/Dartmouth/Ayush_Saran.html?x=1",
        "https://www.tfrrs.org/athletes/8617086/Dartmouth/Ayush_Saran.html#x",
        "https://www.tfrrs.org/athletes/8617086/Dartmouth/Ayush_Saran.html/extra",
        "https://www.tfrrs.org/athletes/8617086",
        "https://www.tfrrs.org/athletes/8617086/Dartmouth/Ayush%2fSaran.html",
        "https://www.tfrrs.org\\@evil.example/athletes/8617086/Dartmouth/Ayush_Saran.html",
    ],
)
def test_validate_profile_url_rejects_ssrf_and_non_profile_urls(url):
    with pytest.raises(ValueError):
        validate_profile_url(url)
