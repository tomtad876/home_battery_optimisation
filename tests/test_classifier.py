"""Tests for the v3 classifier and push logic."""
import pytest
import pandas as pd
from datetime import datetime, timezone, timedelta
from app.services.foxess import (
    classify_optimiser_output,
    _merge_groups,
    FOXESS_MODE_SELF_USE,
    FOXESS_MODE_FORCE_CHARGE,
    FOXESS_MODE_FORCE_DISCHARGE,
    FOXESS_MODE_FEEDIN,
)


def _make_schedule(rows):
    """Build a minimal optimiser result DataFrame from a list of (net_battery_kwh, grid_export_kwh) tuples."""
    periods = pd.date_range("2026-09-06 00:00", periods=len(rows), freq="30min", tz="UTC")
    data = []
    for i, (net, export) in enumerate(rows):
        data.append({
            "period_end": periods[i],
            "net_battery_kwh": net,
            "grid_export_kwh": export,
            "soc_pct": 50.0,
            "demand": 0.5,
            "pv_estimate": 0.0,
            "price": 25.0,
        })
    return pd.DataFrame(data)


class TestClassifier:
    """Test suite for the optimiser → FoxESS mode classifier."""

    def test_all_self_use_when_no_activity(self):
        """Near-zero net_battery should classify as SelfUse."""
        schedule = _make_schedule([(0.0, 0.0)] * 48)
        groups = classify_optimiser_output(schedule)
        assert len(groups) > 0
        for g in groups:
            assert g["workMode"] == FOXESS_MODE_SELF_USE

    def test_force_charge_when_positive_net(self):
        """Positive net_battery_kwh should classify as ForceCharge."""
        schedule = _make_schedule([(1.5, 0.0)] * 10 + [(0.0, 0.0)] * 38)
        groups = classify_optimiser_output(schedule)
        charge_groups = [g for g in groups if g["workMode"] == FOXESS_MODE_FORCE_CHARGE]
        assert len(charge_groups) > 0

    def test_force_discharge_when_negative_net_no_export(self):
        """Negative net_battery with no export should be ForceDischarge."""
        schedule = _make_schedule([(-1.5, 0.0)] * 10 + [(0.0, 0.0)] * 38)
        groups = classify_optimiser_output(schedule)
        discharge_groups = [g for g in groups if g["workMode"] == FOXESS_MODE_FORCE_DISCHARGE]
        assert len(discharge_groups) > 0

    def test_feedin_when_negative_net_with_export(self):
        """Negative net_battery with export should be ForceDischarge (battery is discharging)."""
        schedule = _make_schedule([(-1.5, 1.0)] * 10 + [(0.0, 0.0)] * 38)
        groups = classify_optimiser_output(schedule)
        discharge_groups = [g for g in groups if g["workMode"] == FOXESS_MODE_FORCE_DISCHARGE]
        assert len(discharge_groups) > 0

    def test_feedin_when_net_zero_with_export(self):
        """Net near zero with export should be Feedin (solar export, battery idle)."""
        schedule = _make_schedule([(0.0, 1.0)] * 10 + [(0.0, 0.0)] * 38)
        groups = classify_optimiser_output(schedule)
        feedin_groups = [g for g in groups if g["workMode"] == FOXESS_MODE_FEEDIN]
        assert len(feedin_groups) > 0

    def test_force_charge_when_negative_price_with_export(self):
        """During negative prices, net near zero with export should be ForceCharge (not Feedin)."""
        rows = [(0.0, 1.0)] * 10 + [(0.0, 0.0)] * 38
        schedule = _make_schedule(rows)
        # Set price to negative for the first 10 slots
        schedule.loc[schedule.index[:10], "price"] = -3.5
        groups = classify_optimiser_output(schedule)
        charge_groups = [g for g in groups if g["workMode"] == FOXESS_MODE_FORCE_CHARGE]
        assert len(charge_groups) > 0

    def test_groups_consecutive_same_mode(self):
        """Consecutive same-mode slots should be merged into one group."""
        # 10 charge + 10 self-use + 10 discharge + 18 self-use
        rows = [(1.5, 0.0)] * 10 + [(0.0, 0.0)] * 10 + [(-1.5, 0.0)] * 10 + [(0.0, 0.0)] * 18
        schedule = _make_schedule(rows)
        groups = classify_optimiser_output(schedule)
        # Should have at most 4 groups (charge, self-use, discharge, self-use)
        assert len(groups) <= 5

    def test_from_time_filters_past_periods(self):
        """from_time should exclude periods that have already passed."""
        schedule = _make_schedule([(1.5, 0.0)] * 48)
        # Filter to only periods after the 10th slot
        from_time = datetime(2026, 9, 6, 5, 0, tzinfo=timezone.utc)
        groups = classify_optimiser_output(schedule, from_time=from_time)
        # All groups should start at or after 05:00
        for g in groups:
            start_h = g["startHour"]
            assert start_h >= 5

    def test_empty_schedule_returns_empty(self):
        """Empty input should return empty groups."""
        schedule = pd.DataFrame(columns=["period_end", "net_battery_kwh", "grid_export_kwh", "soc_pct", "demand", "pv_estimate", "price"])
        groups = classify_optimiser_output(schedule)
        assert groups == []

    def test_threshold_boundary(self):
        """Values exactly at threshold should stay as SelfUse."""
        schedule = _make_schedule([(0.05, 0.0)] * 48)
        groups = classify_optimiser_output(schedule, threshold=0.05)
        for g in groups:
            assert g["workMode"] == FOXESS_MODE_SELF_USE

    def test_groups_have_correct_time_structure(self):
        """Each group should have startHour, startMinute, endHour, endMinute."""
        schedule = _make_schedule([(1.5, 0.0)] * 4 + [(0.0, 0.0)] * 44)
        groups = classify_optimiser_output(schedule)
        for g in groups:
            assert "startHour" in g
            assert "startMinute" in g
            assert "endHour" in g
            assert "endMinute" in g
            assert "workMode" in g
            assert "extraParam" in g


class TestMergeGroups:
    """Test suite for group merging logic."""

    def test_no_merge_when_under_limit(self):
        """Groups under the limit should not be merged."""
        groups = [
            {"workMode": "ForceCharge", "startHour": 0, "startMinute": 0, "endHour": 6, "endMinute": 0, "extraParam": {}},
            {"workMode": "SelfUse", "startHour": 6, "startMinute": 0, "endHour": 18, "endMinute": 0, "extraParam": {}},
            {"workMode": "ForceDischarge", "startHour": 18, "startMinute": 0, "endHour": 23, "endMinute": 30, "extraParam": {}},
        ]
        merged = _merge_groups(groups, max_groups=8)
        assert len(merged) == 3

    def test_merge_self_use_first(self):
        """SelfUse groups should be merged first when over limit."""
        groups = [
            {"workMode": "ForceCharge", "startHour": 0, "startMinute": 0, "endHour": 4, "endMinute": 0, "extraParam": {}},
            {"workMode": "SelfUse", "startHour": 4, "startMinute": 0, "endHour": 6, "endMinute": 0, "extraParam": {}},
            {"workMode": "ForceCharge", "startHour": 6, "startMinute": 0, "endHour": 10, "endMinute": 0, "extraParam": {}},
            {"workMode": "SelfUse", "startHour": 10, "startMinute": 0, "endHour": 16, "endMinute": 0, "extraParam": {}},
            {"workMode": "ForceDischarge", "startHour": 16, "startMinute": 0, "endHour": 22, "endMinute": 0, "extraParam": {}},
        ]
        merged = _merge_groups(groups, max_groups=3)
        assert len(merged) == 3
