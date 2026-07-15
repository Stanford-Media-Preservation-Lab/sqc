"""Unit tests for analysis/frame_timing.py's classify_frame_timing().

Pure function, no subprocess involved — real ffprobe integration (packet
extraction) is validated manually against real/synthetic media files, not
unit-tested, matching srw/vdg's convention.
"""

from sqc.analysis.frame_timing import classify_frame_timing

NORMAL = 1001 / 30000  # ~0.033367s, standard 29.97fps frame duration
DOUBLE = 2002 / 30000  # ~0.066733s, spin-down/dropped-frame double duration


class TestClassifyFrameTiming:
    def test_empty_durations_returns_none(self):
        assert classify_frame_timing([]) is None

    def test_all_nominal_classifies_none(self):
        stats = classify_frame_timing([NORMAL] * 100)
        assert stats.classification == "NONE"
        assert stats.anomalous_count == 0

    def test_tail_anomalies_classify_spin_down(self):
        durations = [NORMAL] * 98 + [DOUBLE, DOUBLE]
        stats = classify_frame_timing(durations)
        assert stats.classification == "SPIN_DOWN"
        assert stats.anomalous_count == 2
        assert stats.trim_duration_s == NORMAL * 98

    def test_distributed_anomalies_classify_dropped_frames(self):
        durations = [NORMAL] * 100
        durations[10] = DOUBLE
        durations[50] = DOUBLE
        stats = classify_frame_timing(durations)
        assert stats.classification == "DROPPED_FRAMES"
        assert stats.anomalous_count == 2
        assert stats.trim_duration_s is None

    def test_timebase_rounding_detected_when_no_large_anomalies(self):
        # Alternating 1001/1002-tick-equivalent durations, tiny difference,
        # no duration exceeds the anomaly ratio thresholds.
        tick_a = 1001 / 30000
        tick_b = 1002 / 30000
        durations = [tick_a, tick_b] * 50
        stats = classify_frame_timing(durations)
        assert stats.classification == "TIMEBASE_ROUNDING"
        assert stats.anomalous_count == 0

    def test_spin_down_zone_threshold_is_respected(self):
        # Anomalies must be at or after spin_down_zone fraction through the
        # file to count as SPIN_DOWN; here they sit just before the zone.
        durations = [NORMAL] * 100
        durations[80] = DOUBLE  # 80% through, below the 0.97 default zone
        stats = classify_frame_timing(durations)
        assert stats.classification == "DROPPED_FRAMES"

    def test_custom_thresholds_are_applied(self):
        durations = [NORMAL] * 100
        durations[85] = DOUBLE  # 85% through
        stats = classify_frame_timing(durations, {"spin_down_zone": 0.8})
        assert stats.classification == "SPIN_DOWN"

    def test_anomalous_positions_capped_at_50(self):
        durations = [NORMAL] * 200
        for i in range(0, 200, 2):
            durations[i] = DOUBLE
        stats = classify_frame_timing(durations)
        assert len(stats.anomalous_positions) <= 50
