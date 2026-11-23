"""My Agentic: a model group shares the work between all its cloud models by default."""

from collections import Counter
from types import SimpleNamespace

from agentic.engine import rotation

DS = {"provider_id": "ap_ds", "model_id": "deepseek-chat"}
OA = {"provider_id": "ap_oa", "model_id": "gpt-4.1"}
LOCAL = {"provider_id": "ap_local", "model_id": "qwen3:0.6b"}
PROVIDERS = {
    "ap_ds": SimpleNamespace(tier="paid"),
    "ap_oa": SimpleNamespace(tier="paid"),
    "ap_local": SimpleNamespace(tier="local"),
}


def test_unmarked_cloud_members_share_and_local_stays_last():
    got = rotation.share_by_default([LOCAL, DS, OA], PROVIDERS)
    assert [m["model_id"] for m in got] == ["deepseek-chat", "gpt-4.1", "qwen3:0.6b"]
    assert [m.get("shared") for m in got] == [True, True, None]
    firsts = Counter(rotation.plan(got, {}, turn)[0]["model_id"] for turn in range(200))
    assert set(firsts) == {"deepseek-chat", "gpt-4.1"}  # both providers get work
    assert min(firsts.values()) > 70  # about evenly, while both are healthy


def test_an_explicit_choice_and_a_lone_model_are_left_alone():
    marked = [{**DS, "shared": True}, OA]
    assert rotation.share_by_default(marked, PROVIDERS) == marked  # the owner chose
    assert rotation.share_by_default([DS, LOCAL], PROVIDERS) == [DS, LOCAL]
