"""Classifier parity — the Python reference must match the golden fixture.

The TypeScript classifier (the cron/auto-push path) asserts the SAME fixture in
supabase/functions/shared/classify-schedule_test.ts. Any drift between the two
implementations fails on one side or the other.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

from app.services.foxess import prepare_schedule_groups
from app.services.foxess import _merge_groups

FIXTURE = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "supabase/functions/shared/__fixtures__/classifier_parity.json"
    ).read_text()
)


def _groups_for_case(case):
    df = pd.DataFrame(case["slots"])
    df["period_end"] = pd.to_datetime(df["period_end"], utc=True)
    cfg = case["config"]
    return prepare_schedule_groups(
        df,
        threshold=cfg["threshold"],
        from_time=pd.Timestamp(case["fromTime"]) if case["fromTime"] else None,
        max_hours=cfg["maxHours"],
        min_soc_pct=cfg["minSocPct"],
        max_soc_pct=cfg["maxSocPct"],
        rated_power_w=cfg["ratedPowerW"],
        local_tz=cfg["localTimezone"],
        remain_mode=case["remainMode"],
        max_groups=cfg["maxGroups"],
    )


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda c: c["name"])
def test_python_matches_golden_fixture(case):
    assert _groups_for_case(case) == case["expectedGroups"]


def _period(start_h, start_m, end_h, end_m, mode):
    return {
        "startHour": start_h, "startMinute": start_m,
        "endHour": end_h, "endMinute": end_m,
        "workMode": mode, "isRemainMode": False,
        "extraParam": {"minSocOnGrid": 20},
    }


def test_merge_index_zero_widens_the_survivor():
    """Regression (review 5f): merging index 0 into index 1 must extend the
    survivor's START, not overwrite its END (which produced end < start)."""
    groups = [
        _period(22, 0, 23, 0, "ForceCharge"),
        _period(23, 0, 23, 30, "ForceDischarge"),
    ]
    merged = _merge_groups(groups, 1)
    assert len(merged) == 1
    g = merged[0]
    assert (g["startHour"], g["startMinute"]) == (22, 0)
    assert (g["endHour"], g["endMinute"]) == (23, 30)
    # survivor keeps its own mode; and the span is valid
    assert g["workMode"] == "ForceDischarge"
