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


def test_bark_guard_defaults():
    settings = Settings.from_env({})
    assert settings.bark_guard_enabled is True
    assert settings.audio_input_device == "default"
    assert settings.bark_threshold is None
    assert settings.bark_sound_file.endswith("ladrido.wav")
    assert settings.bark_model.endswith("ladridos.tflite")
    assert settings.bark_model_info.endswith("ladridos_info.json")


def test_bark_threshold_override():
    assert Settings.from_env({"BARK_THRESHOLD": "0.7"}).bark_threshold == 0.7
    assert Settings.from_env({"BARK_THRESHOLD": " "}).bark_threshold is None
