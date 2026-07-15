"""Unit tests for tools/*.py subprocess wrappers.

subprocess.run is mocked throughout — no real ffmpeg/ffprobe/mediainfo/
mediaconch/exiftool invocation happens here, matching srw/vdg's explicit
testing convention. Real tool integration is validated manually.
"""

import subprocess

import pytest

from sqc.tools import ffprobe, mediaconch, mediainfo


class FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestFfprobeProbeFile(object):
    def test_parses_valid_json(self, monkeypatch, tmp_path):
        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(returncode=0, stdout='{"format": {}, "streams": []}', stderr="")

        monkeypatch.setattr(ffprobe.subprocess, "run", fake_run)
        data, stderr = ffprobe.probe_file(tmp_path / "f.mov")
        assert data == {"format": {}, "streams": []}
        assert stderr == ""

    def test_raises_on_nonzero_exit(self, monkeypatch, tmp_path):
        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(returncode=1, stdout="", stderr="moov atom not found")

        monkeypatch.setattr(ffprobe.subprocess, "run", fake_run)
        with pytest.raises(RuntimeError, match="moov atom not found"):
            ffprobe.probe_file(tmp_path / "f.mov")

    def test_raises_on_unparseable_json(self, monkeypatch, tmp_path):
        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(returncode=0, stdout="not json", stderr="")

        monkeypatch.setattr(ffprobe.subprocess, "run", fake_run)
        with pytest.raises(RuntimeError, match="JSON parse error"):
            ffprobe.probe_file(tmp_path / "f.mov")


class TestFfprobeGetPacketDurations:
    def test_extracts_durations(self, monkeypatch, tmp_path):
        payload = '{"packets": [{"duration_time": "0.033367"}, {"duration_time": "0.033367"}]}'

        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(returncode=0, stdout=payload, stderr="")

        monkeypatch.setattr(ffprobe.subprocess, "run", fake_run)
        durations = ffprobe.get_packet_durations(tmp_path / "f.mov")
        assert durations == [0.033367, 0.033367]

    def test_skips_missing_duration_time(self, monkeypatch, tmp_path):
        payload = '{"packets": [{"duration_time": "N/A"}, {"duration_time": "0.033367"}]}'

        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(returncode=0, stdout=payload, stderr="")

        monkeypatch.setattr(ffprobe.subprocess, "run", fake_run)
        durations = ffprobe.get_packet_durations(tmp_path / "f.mov")
        assert durations == [0.033367]


class TestMediaInfoRun:
    def test_parses_valid_json(self, monkeypatch, tmp_path):
        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(returncode=0, stdout='{"media": {}}', stderr="")

        monkeypatch.setattr(mediainfo.subprocess, "run", fake_run)
        data = mediainfo.run_mediainfo(tmp_path / "f.mov")
        assert data == {"media": {}}

    def test_raises_on_nonzero_exit(self, monkeypatch, tmp_path):
        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(returncode=1, stdout="", stderr="oops")

        monkeypatch.setattr(mediainfo.subprocess, "run", fake_run)
        with pytest.raises(RuntimeError, match="oops"):
            mediainfo.run_mediainfo(tmp_path / "f.mov")


class TestMediaconchValidateFilesAgainstPolicy:
    def test_yields_pass_fail_per_file(self, monkeypatch, tmp_path):
        # MediaConch's real CSV `filename` column echoes back the exact path
        # string it was invoked with, not a bare basename.
        file1, file2 = tmp_path / "file1.mov", tmp_path / "file2.mov"
        csv_output = f"filename,overall\n{file1},pass\n{file2},fail\n"

        def fake_run(args, **kwargs):
            return FakeCompletedProcess(returncode=0, stdout=csv_output, stderr="")

        monkeypatch.setattr(mediaconch.subprocess, "run", fake_run)
        results = dict(
            (str(f), ok)
            for f, ok in mediaconch.validate_files_against_policy([file1, file2], tmp_path / "policy.xml")
        )
        assert results[str(file1)] is True
        assert results[str(file2)] is False

    def test_batches_respect_batch_size(self, monkeypatch, tmp_path):
        call_count = {"n": 0}

        def fake_run(args, **kwargs):
            call_count["n"] += 1
            return FakeCompletedProcess(returncode=0, stdout="filename,overall\n", stderr="")

        monkeypatch.setattr(mediaconch.subprocess, "run", fake_run)
        files = [tmp_path / f"file{i}.mov" for i in range(5)]
        list(mediaconch.validate_files_against_policy(files, tmp_path / "policy.xml", batch_size=2))
        assert call_count["n"] == 3  # 2 + 2 + 1
