from sqc.analysis.patterns import PATTERN_REGISTRY, get_pattern, patterns_for_mode


class TestPatternRegistry:
    def test_all_ids_unique(self):
        ids = [p.pattern_id for p in PATTERN_REGISTRY]
        assert len(ids) == len(set(ids))

    def test_get_pattern_returns_expected(self):
        pattern = get_pattern("VFR_TAIL_ARTIFACT")
        assert pattern.default_severity == "WARN"
        assert pattern.mode_scope == "both"

    def test_patterns_for_mode_donor_triage_excludes_vendor_only(self):
        donor = patterns_for_mode("donor_triage")
        assert all(p.mode_scope in ("both", "donor_triage") for p in donor)
        assert "FAKE_10BIT_LSHIFT" not in [p.pattern_id for p in donor]

    def test_patterns_for_mode_vendor_qc_includes_vendor_only(self):
        vendor = patterns_for_mode("vendor_qc")
        assert "FAKE_10BIT_LSHIFT" in [p.pattern_id for p in vendor]


class TestSeverityForMode:
    def test_default_severity_used_when_no_triage_override(self):
        pattern = get_pattern("VFR_TAIL_ARTIFACT")
        assert pattern.triage_severity is None
        assert pattern.severity_for_mode("vendor_qc") == "WARN"
        assert pattern.severity_for_mode("donor_triage") == "WARN"

    def test_triage_override_applied_only_for_donor_triage(self):
        pattern = get_pattern("VFR_GENUINE_DROPS")
        assert pattern.default_severity == "FAIL"
        assert pattern.triage_severity == "WARN"
        assert pattern.severity_for_mode("vendor_qc") == "FAIL"
        assert pattern.severity_for_mode("donor_triage") == "WARN"
