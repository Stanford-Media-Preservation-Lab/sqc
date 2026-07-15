import pytest

from sqc.policy import load_profile, resolve_profile_path

VALID_PROFILE = """
[profile]
name = "test_profile"
description = "A test profile"
container_extensions = [".mov"]
mediaconch_policy = "test_profile.xml"

[video]
codec = "v210"
width = 720
height = 486

[audio]
codec_prefix = "pcm"

[thresholds]
spin_down_zone = 0.95
"""


class TestResolveProfilePath:
    def test_resolves_bare_name_in_profiles_dir(self, tmp_path):
        (tmp_path / "myprofile.toml").write_text(VALID_PROFILE)
        resolved = resolve_profile_path("myprofile", tmp_path)
        assert resolved == tmp_path / "myprofile.toml"

    def test_resolves_direct_path(self, tmp_path):
        direct = tmp_path / "somewhere.toml"
        direct.write_text(VALID_PROFILE)
        resolved = resolve_profile_path(str(direct), tmp_path / "unrelated")
        assert resolved == direct

    def test_missing_profile_raises_with_helpful_message(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="not found"):
            resolve_profile_path("nonexistent", tmp_path)


class TestLoadProfile:
    def test_loads_valid_profile(self, tmp_path):
        (tmp_path / "test_profile.toml").write_text(VALID_PROFILE)
        profile = load_profile("test_profile", tmp_path, tmp_path / "MediaConch")
        assert profile.name == "test_profile"
        assert profile.video["codec"] == "v210"
        assert profile.thresholds["spin_down_zone"] == 0.95

    def test_mediaconch_policy_resolved_against_mediaconch_dir(self, tmp_path):
        (tmp_path / "test_profile.toml").write_text(VALID_PROFILE)
        mc_dir = tmp_path / "MediaConch"
        profile = load_profile("test_profile", tmp_path, mc_dir)
        assert profile.mediaconch_policy == mc_dir / "test_profile.xml"

    def test_missing_required_section_raises(self, tmp_path):
        bad = """
[profile]
name = "bad"
description = "missing sections"
container_extensions = [".mov"]
mediaconch_policy = "bad.xml"
"""
        (tmp_path / "bad.toml").write_text(bad)
        with pytest.raises(ValueError, match="missing section"):
            load_profile("bad", tmp_path, tmp_path / "MediaConch")

    def test_missing_required_profile_key_raises(self, tmp_path):
        bad = """
[profile]
name = "bad"

[video]
[audio]
[thresholds]
"""
        (tmp_path / "bad.toml").write_text(bad)
        with pytest.raises(ValueError, match="missing key"):
            load_profile("bad", tmp_path, tmp_path / "MediaConch")

    def test_frame_timing_thresholds_falls_back_to_defaults(self, tmp_path):
        (tmp_path / "test_profile.toml").write_text(VALID_PROFILE)
        profile = load_profile("test_profile", tmp_path, tmp_path / "MediaConch")
        thresholds = profile.frame_timing_thresholds()
        assert thresholds["spin_down_zone"] == 0.95  # from profile
        assert thresholds["frame_anomaly_low_ratio"] == 0.5  # default, not in profile
