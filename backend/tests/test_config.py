from marquee.config import Config, load_config


def test_defaults():
    c = load_config({"TMDB_TOKEN": "tok"})
    assert isinstance(c, Config)
    assert c.tmdb_token == "tok"
    assert c.sources == ["upcoming", "now_playing"]
    assert c.count == 50
    assert c.region == "US"
    assert c.language == "en-US"
    assert c.container == "mkv"
    assert c.max_height == 1080
    assert c.grace_days == 0
    assert c.tz == "UTC"
    assert c.max_size_gb == 0.0
    assert c.jellyfin_url is None


def test_env_override_with_coercion():
    c = load_config(
        {
            "TMDB_TOKEN": "tok",
            "COUNT": "25",
            "REGION": "GB",
            "GRACE_DAYS": "3",
            "MAX_HEIGHT": "720",
            "MAX_SIZE_GB": "12.5",
            "JELLYFIN_URL": "http://jf:8096",
        }
    )
    assert c.count == 25
    assert c.region == "GB"
    assert c.grace_days == 3
    assert c.max_height == 720
    assert c.max_size_gb == 12.5
    assert c.jellyfin_url == "http://jf:8096"


def test_sources_parsing_trims_and_splits():
    c = load_config({"TMDB_TOKEN": "tok", "SOURCES": "upcoming, popular ,trending_week"})
    assert c.sources == ["upcoming", "popular", "trending_week"]


def test_empty_string_falls_back_to_default():
    c = load_config({"TMDB_TOKEN": "tok", "REGION": "", "SOURCES": ""})
    assert c.region == "US"
    assert c.sources == ["upcoming", "now_playing"]


def test_overrides_win_over_env():
    c = load_config({"TMDB_TOKEN": "tok", "COUNT": "25"}, overrides={"COUNT": "99"})
    assert c.count == 99


def test_apply_setting_overrides_coerces_by_field_type():
    from marquee.config import apply_setting_overrides

    base = load_config({"TMDB_TOKEN": "tok"})
    out = apply_setting_overrides(
        base,
        {"count": "25", "max_size_gb": "5.5", "sources": "upcoming, popular", "region": "GB"},
    )
    assert out.count == 25
    assert out.max_size_gb == 5.5
    assert out.sources == ["upcoming", "popular"]
    assert out.region == "GB"
    assert out.tmdb_token == "tok"  # untouched fields preserved


def test_apply_setting_overrides_ignores_unknown_and_bad():
    from marquee.config import apply_setting_overrides

    base = load_config({"TMDB_TOKEN": "tok"})
    out = apply_setting_overrides(base, {"nope": "x", "count": "notanint"})
    assert out.count == 50  # unknown key ignored; uncoercible value leaves default
