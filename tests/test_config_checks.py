from subtitle_info_collection.config import AppSettings, bootstrap_env_file, evaluate_config


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
    assert result.enabled_provider_count == 2
    assert result.configured_provider_count == 1
    assert [provider.id for provider in result.providers] == ["subhd", "assrt", "opensubtitles"]
    assert result.providers[0].configured is True
    assert result.providers[1].configured is False
    assert result.providers[2].enabled is False
    assert any("TMDb" in warning for warning in result.warnings)
