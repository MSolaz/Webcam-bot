from webcam_bot.config import Settings


def test_defaults():
    settings = Settings.from_env({})
    assert settings.bot_token == ""
    assert settings.allowed_user_ids == frozenset()
    assert settings.camera_device == "/dev/video0"
    assert settings.warmup_frames == 10
    assert settings.dog_watchdog_enabled is True
    assert settings.reset_settle_seconds == 5.0


def test_parses_user_ids_ignoring_blanks():
    settings = Settings.from_env({"ALLOWED_USER_IDS": " 123, ,456 ,"})
    assert settings.allowed_user_ids == frozenset({123, 456})


def test_parses_watchdog_flag():
    assert Settings.from_env({"DOG_WATCHDOG_ENABLED": "off"}).dog_watchdog_enabled is False
    assert Settings.from_env({"DOG_WATCHDOG_ENABLED": " YES "}).dog_watchdog_enabled is True


def test_model_paths_use_model_dir():
    settings = Settings.from_env({"MODEL_DIR": "/modelos"})
    assert settings.model_prototxt.endswith("MobileNetSSD_deploy.prototxt")
    assert settings.model_prototxt.startswith("/modelos")
    assert settings.model_weights.endswith("MobileNetSSD_deploy.caffemodel")
