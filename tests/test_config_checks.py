from pathlib import Path

from subtitle_info_collection.config import (
    ENV_FIELD_META,
    AppSettings,
    bootstrap_env_file,
    evaluate_config,
    upsert_env_values,
)


ENV_KEYS = [
    "TMDB_TOKEN",
    "ASSRT_TOKEN",
    "ASSRT_API_BASE_URL",
    "SUBDL_API_KEY",
    "SUBDL_BASE_URL",
    "SUBDL_DOWNLOAD_BASE_URL",
    "SUBDL_LANGUAGES",
    "SUBDL_INCLUDE_TRADITIONAL",
    "OPENSUBTITLES_API_KEY",
    "OPENSUBTITLES_USERNAME",
    "OPENSUBTITLES_PASSWORD",
    "OPENSUBTITLES_BASE_URL",
    "OPENSUBTITLES_USER_AGENT",
    "TODAYS_LINES_USERNAME",
    "TODAYS_LINES_PASSWORD",
    "TODAYS_LINES_TOKEN",
    "TODAYS_LINES_TOKEN_TIME",
    "BAIDU_TRANSLATE_APP_ID",
    "BAIDU_TRANSLATE_SECRET",
    "SUBTITLE_PROVIDER_PRIORITY",
    "SUBTITLE_PROVIDER_DISABLED",
    "SUBTITLE_REQUEST_INTERVAL_MS",
    "SUBTITLE_MOVIE_CONCURRENCY",
    "SUBTITLE_MIN_BILINGUAL_RATIO",
    "SUBHD_CAPTCHA_OCR_ENABLED",
    "SUBHD_CAPTCHA_AUTO_SUBMIT_MIN_CONFIDENCE",
    "SUBHD_CAPTCHA_OCR_MAX_ATTEMPTS",
    "SUBHD_SEARCH_TIMEOUT",
    "PROVIDER_SEARCH_TIMEOUT",
    "CAPTCHA_SOUND_ENABLED",
    "SUBTITLE_COLLECTION_PACKAGE_DIST_DIR",
    "SUBTITLE_COLLECTION_DATA_DIR",
    "HTTP_PROXY",
    "HTTPS_PROXY",
]


def test_bootstrap_env_file_copies_example_without_overwriting(tmp_path):
    example = tmp_path / ".env.example"
    env = tmp_path / ".env"
    example.write_text("TMDB_TOKEN=\nSUBTITLE_COLLECTION_DATA_DIR=\n", encoding="utf-8")

    first = bootstrap_env_file(tmp_path)
    second = bootstrap_env_file(tmp_path)

    assert first.created is True
    assert second.created is False
    assert env.read_text(encoding="utf-8") == example.read_text(encoding="utf-8")


def test_bootstrap_env_file_uses_pyinstaller_internal_template(tmp_path):
    internal = tmp_path / "_internal"
    internal.mkdir()
    example = internal / ".env.example"
    env = tmp_path / ".env"
    example.write_text("TMDB_TOKEN=packaged\n", encoding="utf-8")

    result = bootstrap_env_file(tmp_path)

    assert result.created is True
    assert result.env_path == env
    assert env.read_text(encoding="utf-8") == "TMDB_TOKEN=packaged\n"


def test_evaluate_config_reports_missing_tokens_and_provider_readiness(tmp_path):
    settings = AppSettings(
        data_dir=tmp_path,
        tmdb_token="",
        assrt_token="",
        opensubtitles_api_key="",
        opensubtitles_username="",
        opensubtitles_password="",
        provider_disabled=["opensubtitles"],
    )

    result = evaluate_config(settings, tmp_path / ".env")

    assert result.ready is False
    assert result.env_exists is False
    assert result.tmdb_configured is False
    assert result.data_dir_exists is True
    assert result.enabled_provider_count == 3
    assert result.configured_provider_count == 1
    assert [provider.id for provider in result.providers] == ["subhd", "subdl", "assrt", "opensubtitles"]
    assert result.providers[0].configured is True
    assert result.providers[1].configured is False
    assert result.providers[2].configured is False
    assert result.providers[3].enabled is False
    assert any("TMDb" in warning for warning in result.warnings)


def test_env_example_documents_each_config_item_in_chinese():
    env_example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    lines = env_example.splitlines()

    for key in ENV_KEYS:
        key_index = next(index for index, line in enumerate(lines) if line.startswith(f"{key}="))
        previous = lines[key_index - 1] if key_index > 0 else ""
        assert previous.startswith("#")
        assert any("\u4e00" <= char <= "\u9fff" for char in previous)


def test_app_settings_reads_and_clamps_subtitle_min_bilingual_ratio(tmp_path):
    env = tmp_path / ".env"

    env.write_text("SUBTITLE_MIN_BILINGUAL_RATIO=0.55\n", encoding="utf-8")
    assert AppSettings.from_env(env).subtitle_min_bilingual_ratio == 0.55

    env.write_text("SUBTITLE_MIN_BILINGUAL_RATIO=\n", encoding="utf-8")
    assert AppSettings.from_env(env).subtitle_min_bilingual_ratio == 0.70

    env.write_text("SUBTITLE_MIN_BILINGUAL_RATIO=not-a-number\n", encoding="utf-8")
    assert AppSettings.from_env(env).subtitle_min_bilingual_ratio == 0.70

    env.write_text("SUBTITLE_MIN_BILINGUAL_RATIO=1.25\n", encoding="utf-8")
    assert AppSettings.from_env(env).subtitle_min_bilingual_ratio == 1.0

    env.write_text("SUBTITLE_MIN_BILINGUAL_RATIO=-0.25\n", encoding="utf-8")
    assert AppSettings.from_env(env).subtitle_min_bilingual_ratio == 0.0


def test_upsert_env_values_preserves_comments_and_updates_secrets(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# TMDB_TOKEN：测试注释\n"
        "TMDB_TOKEN=old-token\n"
        "\n"
        "# ASSRT_TOKEN：另一注释\n"
        "ASSRT_TOKEN=\n",
        encoding="utf-8",
    )

    upsert_env_values(
        env,
        {
            "TMDB_TOKEN": "new-token",
            "ASSRT_TOKEN": "assrt-secret",
            "HTTP_PROXY": "http://127.0.0.1:7890",
        },
    )

    text = env.read_text(encoding="utf-8")
    assert "# TMDB_TOKEN：测试注释" in text
    assert "TMDB_TOKEN=new-token" in text
    assert "# ASSRT_TOKEN：另一注释" in text
    assert "ASSRT_TOKEN=assrt-secret" in text
    assert "HTTP_PROXY=http://127.0.0.1:7890" in text


def test_app_settings_reads_automation_and_package_fields(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "TODAYS_LINES_USERNAME=user@example.com\n"
        "TODAYS_LINES_PASSWORD=secret\n"
        "TODAYS_LINES_TOKEN=cached-token\n"
        "TODAYS_LINES_TOKEN_TIME=123456\n"
        "BAIDU_TRANSLATE_APP_ID=app-id\n"
        "BAIDU_TRANSLATE_SECRET=app-secret\n"
        "SUBTITLE_COLLECTION_PACKAGE_DIST_DIR=D:\\dist\\app\n"
        "SUBHD_CAPTCHA_OCR_MAX_ATTEMPTS=12\n"
        "SUBHD_SEARCH_TIMEOUT=\n"
        "PROVIDER_SEARCH_TIMEOUT=\n",
        encoding="utf-8",
    )

    settings = AppSettings.from_env(env)
    assert settings.todays_lines_username == "user@example.com"
    assert settings.todays_lines_password == "secret"
    assert settings.todays_lines_token == "cached-token"
    assert settings.todays_lines_token_time == "123456"
    assert settings.baidu_translate_app_id == "app-id"
    assert settings.baidu_translate_secret == "app-secret"
    assert settings.package_dist_dir == r"D:\dist\app"
    assert settings.subhd_captcha_ocr_max_attempts == 12
    assert settings.subhd_search_timeout == 120
    assert settings.provider_search_timeout == 90


def test_env_field_meta_covers_all_env_keys():
    meta_keys = {item.key for item in ENV_FIELD_META}
    assert meta_keys == set(ENV_KEYS)


def test_app_settings_to_env_values_roundtrip_keys(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TMDB_TOKEN=abc\nSUBTITLE_MOVIE_CONCURRENCY=3\n", encoding="utf-8")
    settings = AppSettings.from_env(env)
    values = settings.to_env_values()
    assert set(ENV_KEYS).issubset(set(values))
    assert values["TMDB_TOKEN"] == "abc"
    assert values["SUBTITLE_MOVIE_CONCURRENCY"] == "3"
