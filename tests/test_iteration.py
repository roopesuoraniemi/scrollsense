"""Tests for the YT-wrapper design iteration: priority queueing, live arrival,
circumplex/semantic/dwell signals, closed-loop guidance, and mock scenario coherence.
"""
import time
from pathlib import Path
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scrollsense.analysis_queue import AnalysisQueue, Pacer
from scrollsense.domain import ClipAnalysis, Embedding, VideoId
from scrollsense.feed import (Composition, Shift, composition, evidence_items, readout,
                              trajectory)
from scrollsense.intake import ACTIVE_TTL_S, LiveWatchers, ViewIntake
from scrollsense.loop import guidance
from scrollsense.mock import MOCK_SAFETY_ID
from scrollsense.ports import ContentAnalyser
from scrollsense.schemas import CRITERIA, ClipScores, Format, Stance, TextPackage
from scrollsense.service import AnalysisService
from scrollsense.store import JsonFileStore
from scrollsense.viewlog import JsonlViewLog
from scrollsense.views import EVER, ViewEvent
from scrollsense.views_api import ViewerReports, ViewsApi

from .fakes import MemoryStore, instant_mock, label, no_wait

HOUR = 3600.0
NOW = 1_763_100_000.0


def make_pkg(fmt: Format = "other", title: str = "Clip") -> TextPackage:
    return TextPackage(
        title=title, transcript="", on_screen_text="", visual_description="",
        audio_description="", emotional_cues="", intended_meaning="",
        main_message="", format=fmt, people_present=False, language="en")


def make_scores(stance: Stance = "unrelated", neg: int = 0, pos: int = 0, arousal: int = 3,
                themes: dict[str, int] | None = None) -> ClipScores:
    return ClipScores(
        rationale="r", evidence="quoted evidence", negative_affect=neg, positive_affect=pos,
        arousal=arousal, stance=stance, hopeful=(stance == "coping_or_recovery"),
        **({c.key: 0 for c in CRITERIA} | (themes or {})))


def make_analysis(vid: str, clip_scores: ClipScores, vector: tuple[float, ...] | None = None,
                  fmt: Format = "other") -> ClipAnalysis:
    return ClipAnalysis(
        video_id=vid, analyser=label(), created=0.0, package=make_pkg(fmt, f"Title {vid}"),
        scores=clip_scores, embedding=Embedding(vector=vector))


def make_view(vid: str, seen_at: float, dwell: float | None = None, duration: float | None = None,
              loops: int | None = None, tz: int = 0) -> ViewEvent:
    return ViewEvent(
        event_id=f"ev-{vid}-{seen_at}", viewer="patient-01", video_id=vid,
        seen_at=seen_at, tz_offset_min=tz, dwell_s=dwell, duration_s=duration, loops=loops)


def vid(prefix: str, i: int) -> str:
    return f"{prefix}{i:02d}".ljust(11, "x")


# ---------------------------------------------------------------- semantic dispersion & circumplex

def test_semantic_dispersion_is_sample_size_invariant_and_bounded() -> None:
    s = make_scores()
    # Orthogonal unit basis vectors in R^8 -> pairwise cosine 0 -> dispersion 1.0 for k=2 and k=8
    ortho = [
        make_analysis(vid("o", i), s, tuple(1.0 if j == i else 0.0 for j in range(8)))
        for i in range(8)
    ]
    two = composition([make_view(a.video_id, float(i)) for i, a in enumerate(ortho[:2])],
                      {a.video_id: a for a in ortho[:2]}, EVER)
    eight = composition([make_view(a.video_id, float(i)) for i, a in enumerate(ortho)],
                        {a.video_id: a for a in ortho}, EVER)
    assert two.semantic_dispersion == pytest.approx(1.0)
    assert eight.semantic_dispersion == pytest.approx(1.0)

    # Identical vectors -> dispersion 0.0
    same = [make_analysis(vid("s", i), s, (0.6, 0.8, 0.0)) for i in range(5)]
    collapsed = composition([make_view(a.video_id, float(i)) for i, a in enumerate(same)],
                            {a.video_id: a for a in same}, EVER)
    assert collapsed.semantic_dispersion == pytest.approx(0.0)

    # Antipodal + zero-norm + missing vectors stay safe and clamped to [0, 1]
    edge = [
        make_analysis(vid("e", 0), s, (1.0, 0.0)),
        make_analysis(vid("e", 1), s, (-1.0, 0.0)),
        make_analysis(vid("e", 2), s, (0.0, 0.0)),
        make_analysis(vid("e", 3), s, None),
    ]
    res = composition([make_view(a.video_id, float(i)) for i, a in enumerate(edge)],
                      {a.video_id: a for a in edge}, EVER)
    assert res.semantic_dispersion == pytest.approx(1.0)


def test_low_arousal_negative_separates_withdrawal_from_high_arousal_outrage() -> None:
    outrage = make_analysis(vid("hi", 1), make_scores("unrelated", neg=3, pos=0, arousal=5))
    withdrawal = make_analysis(vid("lo", 1), make_scores("dwelling_or_romanticising", neg=2, pos=0, arousal=1))

    c_outrage = composition([make_view(outrage.video_id, 10.0)], {outrage.video_id: outrage}, EVER)
    c_withdraw = composition([make_view(withdrawal.video_id, 10.0)], {withdrawal.video_id: withdrawal}, EVER)

    assert c_outrage.negative_share == 1.0 and c_outrage.low_arousal_negative_share == 0.0
    assert c_withdraw.negative_share == 1.0 and c_withdraw.low_arousal_negative_share == 1.0


def test_dwell_weighted_negative_catches_selective_lingering_and_handles_edge_durations() -> None:
    heavy = make_analysis(vid("hv", 1), make_scores("dwelling_or_romanticising", neg=3, arousal=1))
    light_clips = [make_analysis(vid("lt", i), make_scores("unrelated", pos=2, arousal=3)) for i in range(3)]
    analyses = {a.video_id: a for a in [heavy, *light_clips]}

    events = [
        make_view(heavy.video_id, 1.0, dwell=18.0, duration=12.0, loops=2),
        make_view(light_clips[0].video_id, 2.0, dwell=1.0, duration=15.0, loops=0),
        make_view(light_clips[1].video_id, 3.0, dwell=1.0, duration=0.0, loops=0),
        make_view(light_clips[2].video_id, 4.0, dwell=1.0, duration=None, loops=None),
    ]
    comp = composition(events, analyses, EVER)
    assert comp.negative_share == pytest.approx(0.25)
    assert comp.dwell_negative_share == pytest.approx(18.0 / 21.0)
    # Completion caps at 1.0 (18/12 -> 1.0) and skips duration=0/None; median of [1.0, 1/15]
    assert comp.completion_rate == pytest.approx((1.0 + 1.0 / 15.0) / 2.0)
    assert comp.loop_share == pytest.approx(1.0 / 3.0)


def test_evidence_and_trajectory_handle_empty_single_and_large_histories() -> None:
    assert evidence_items([], {}, EVER) == ()
    assert trajectory([], {}) == ()

    s_sad = make_scores("dwelling_or_romanticising", neg=3, arousal=1,
                        themes={"a1_depressed_mood": 3, "a4_sleep": 2})
    s_ok = make_scores("unrelated", pos=2, arousal=3)
    analyses = {
        vid("p", i): make_analysis(vid("p", i), s_ok if i < 10 else s_sad,
                                   (1.0, 0.0) if i >= 10 else (float(i % 3 == 0), float(i % 3 == 1), float(i % 3 == 2)))
        for i in range(20)
    }
    single = trajectory([make_view(vid("p", 0), 10.0)], analyses)
    assert len(single) == 1 and single[0].mean_valence == 4.0

    events = [make_view(vid("p", i), 2 * HOUR + i * 30, dwell=12.0 if i >= 10 else 3.0) for i in range(20)]
    series = trajectory(events, analyses)
    assert len(series) == 12
    assert series[0].mean_valence > series[-1].mean_valence
    assert series[-1].low_arousal_negative_share == pytest.approx(1.0)

    ev = evidence_items(events, analyses, EVER)
    assert len(ev) > 0
    assert {"a1_depressed_mood", "a4_sleep", "low_arousal_negative_share", "dwell_negative_share", "night_share"} <= set(ev[0].metrics)


# ---------------------------------------------------------------- closed-loop guidance

def test_loop_guidance_silent_when_stable_and_overrides_on_a9() -> None:
    ok_clip = make_analysis(vid("ok", 1), make_scores("unrelated", pos=2, arousal=3), (1.0, 0.0))
    ok_clip2 = make_analysis(vid("ok", 2), make_scores("unrelated", pos=2, arousal=3), (0.0, 1.0))
    analyses = {ok_clip.video_id: ok_clip, ok_clip2.video_id: ok_clip2}
    events = [make_view(ok_clip.video_id, 14 * HOUR, dwell=6.0),
              make_view(ok_clip2.video_id, 14 * HOUR + 20, dwell=5.0)]
    comp = composition(events, analyses, EVER)
    stable_readout = readout(comp, comp, Shift(current=comp, baseline=comp))
    stable_loop = guidance(comp, stable_readout)
    assert stable_loop.safety_active is False
    assert stable_loop.triage_level == "stable"
    assert stable_loop.resets == ()

    a9_clip = make_analysis(vid("a9", 1), make_scores("dwelling_or_romanticising", neg=3, arousal=1,
                                                      themes={"a9_death_suicide": 2}))
    a9_comp = composition([make_view(a9_clip.video_id, 2 * HOUR, dwell=10.0)],
                          {a9_clip.video_id: a9_clip}, EVER)
    a9_loop = guidance(a9_comp, readout(a9_comp, comp, None))
    assert a9_loop.safety_active is True
    assert a9_loop.triage_level == "flag"
    assert a9_loop.resets == ()
    assert any("09 2525 0111" in r.contact for r in a9_loop.crisis_resources)
    assert any(r.contact == "988" for r in a9_loop.crisis_resources)


# ---------------------------------------------------------------- dwell-aware priority queue

class RecordingAnalyser(ContentAnalyser):
    def __init__(self, gate: Event) -> None:
        self.__gate = gate
        self.order: list[str] = []
        self.__mock = instant_mock()

    @property
    def label(self):
        return self.__mock.label

    def describe(self, video: VideoId) -> TextPackage:
        self.__gate.wait(timeout=2.0)
        self.order.append(video.value)
        return self.__mock.describe(video)

    def score(self, package: TextPackage) -> ClipScores:
        return self.__mock.score(package)

    def embed(self, package: TextPackage) -> tuple[float, ...]:
        return self.__mock.embed(package)


def test_priority_queue_runs_watched_ahead_of_skips_and_promotes_in_place() -> None:
    gate = Event()
    rec = RecordingAnalyser(gate)
    store = MemoryStore()
    queue = AnalysisQueue(AnalysisService(rec, store, time.time), store,
                          Pacer(0.0, time.monotonic, no_wait))
    skip1, skip2, watched = VideoId(vid("sk", 1)), VideoId(vid("sk", 2)), VideoId(vid("wt", 1))

    assert queue.enqueue_if_new(skip1, priority=False) is True
    assert queue.enqueue_if_new(skip2, priority=False) is True
    assert queue.enqueue_if_new(watched, priority=True) is True
    # Promote skip2 ahead of skip1 without double-counting queue depth
    assert queue.enqueue_if_new(skip2, priority=True) is False
    assert queue.status().depth == 3

    gate.set()
    queue.start(1)
    for _ in range(200):
        if queue.status().done == 3:
            break
        time.sleep(0.01)
    assert rec.order == [watched.value, skip2.value, skip1.value]


# ---------------------------------------------------------------- live arrival, TTL, mock readout API

def build_live_app(tmp_path: Path, clock_ref: list[float]) -> TestClient:
    store = JsonFileStore(tmp_path / "clips")
    log = JsonlViewLog(tmp_path / "views")
    queue = AnalysisQueue(AnalysisService(instant_mock(), store, lambda: clock_ref[0]), store,
                          Pacer(0.0, time.monotonic, no_wait))
    queue.start(2)
    live = LiveWatchers()
    reports = ViewerReports(log, store, queue).tracking(live)
    api = ViewsApi(ViewIntake(log, queue, live), reports, lambda: clock_ref[0])
    app = FastAPI()
    app.include_router(api.router())
    return TestClient(app)


def wait_idle(client: TestClient) -> None:
    for _ in range(200):
        q = client.get("/api/queue").json()
        if q["depth"] == 0 and q["in_flight"] == 0:
            return
        time.sleep(0.01)
    raise AssertionError("queue did not finish")


def test_live_watching_lifecycle_ttl_pause_and_erase(tmp_path: Path) -> None:
    clock = [NOW]
    client = build_live_app(tmp_path, clock)

    # 1. Viewer lands on first Short before swiping away: appears in /viewers & /feed immediately
    res = client.post("/api/views", json={
        "viewer": "patient-01",
        "events": [],
        "watching": {"video_id": "Qo4PLQXRmUw", "started_at": NOW - 3.0, "tz_offset_min": 120},
    })
    assert res.status_code == 202 and res.json()["queued"] == 1
    wait_idle(client)

    viewers = client.get("/api/viewers").json()
    assert viewers == [{"viewer": "patient-01", "events": 0, "last_seen": NOW - 3.0, "watching": "Qo4PLQXRmUw"}]

    feed = client.get("/api/viewers/patient-01/feed").json()
    assert len(feed) == 1 and feed[0]["live"] is True and feed[0]["state"] == "scored"
    assert feed[0]["event"]["dwell_s"] == pytest.approx(3.0)

    # 2. Swipe to Short 2 closes Short 1 without duplicating it, and starts Short 2 live
    clock[0] = NOW + 6.0
    client.post("/api/views", json={
        "viewer": "patient-01",
        "events": [{
            "event_id": "e1", "video_id": "Qo4PLQXRmUw", "seen_at": NOW - 3.0,
            "tz_offset_min": 120, "dwell_s": 9.0, "duration_s": 15.0, "loops": 0,
        }],
        "watching": {"video_id": "RWD9TXXf1_A", "started_at": NOW + 6.0, "tz_offset_min": 120},
    })
    wait_idle(client)
    feed2 = client.get("/api/viewers/patient-01/feed").json()
    assert [(f["event"]["video_id"], f["live"]) for f in feed2] == [
        ("RWD9TXXf1_A", True), ("Qo4PLQXRmUw", False)
    ]
    # Viewer-scoped semantic PCA coordinates are populated directly on FeedItem.clip
    assert feed2[0]["clip"]["semantic"] is not None and feed2[1]["clip"]["semantic"] is not None

    # 3. Stale active watch expires cleanly after ACTIVE_TTL_S if phone disconnects
    clock[0] = NOW + 6.0 + ACTIVE_TTL_S + 5.0
    feed_expired = client.get("/api/viewers/patient-01/feed").json()
    assert [(f["event"]["video_id"], f["live"]) for f in feed_expired] == [("Qo4PLQXRmUw", False)]

    # 4. Explicit pause clears active watch immediately
    clock[0] = NOW + 500.0
    client.post("/api/views", json={
        "viewer": "patient-01",
        "watching": {"video_id": "KOiWuuzGzOw", "started_at": NOW + 500.0},
    })
    assert client.get("/api/viewers/patient-01/feed").json()[0]["live"] is True
    client.post("/api/views", json={"viewer": "patient-01", "paused": True})
    assert all(not f["live"] for f in client.get("/api/viewers/patient-01/feed").json())

    # 5. GDPR erase clears both log and live state
    assert client.delete("/api/viewers/patient-01").status_code == 204
    assert client.get("/api/viewers").json() == []


def test_mock_end_to_end_drift_readout_stance_and_safety_override(tmp_path: Path) -> None:
    clock = [NOW]
    client = build_live_app(tmp_path, clock)
    old_day = NOW - 2 * 86400
    # 02:00 UTC with tz_offset_min=0 is nocturnal; 14:00 UTC is daytime
    day_base = old_day - (old_day % 86400) + 14 * 3600
    night_now = NOW - (NOW % 86400) + 2 * 3600
    if night_now > NOW - 60:
        night_now -= 86400

    light = ["Qo4PLQXRmUw", "RWD9TXXf1_A", "KOiWuuzGzOw", "jNQXAC9IVRw", "cRftRest001"]
    heavy = ["lMQJ2bHeP4c", "wZF2PLGsksI", "bPnRMwahAMA"]

    client.post("/api/views", json={
        "viewer": "patient-01",
        "events": [
            *[{"event_id": f"pb-{i}", "video_id": v, "seen_at": day_base + i * 30, "dwell_s": 9.0}
              for i, v in enumerate(light)],
            *[{"event_id": f"pn-{i}", "video_id": v, "seen_at": night_now + i * 30, "dwell_s": 17.0}
              for i, v in enumerate(heavy)],
            {"event_id": "pn-skip", "video_id": light[0], "seen_at": night_now + 120, "dwell_s": 1.0},
            {"event_id": "pn-rec", "video_id": "recovWin001", "seen_at": night_now + 150, "dwell_s": 10.0},
        ],
    })
    client.post("/api/views", json={
        "viewer": "control-01",
        "events": [
            *[{"event_id": f"cb-{i}", "video_id": v, "seen_at": day_base + i * 30, "dwell_s": 8.0}
              for i, v in enumerate(light[:3])],
            *[{"event_id": f"cn-{i}", "video_id": v, "seen_at": NOW - 900 + i * 30, "dwell_s": 8.0}
              for i, v in enumerate(light[2:])],
        ],
    })
    wait_idle(client)

    rv = client.get("/api/viewers/patient-01/readout?control=control-01").json()
    flags = set(rv["readout"]["flags"])
    assert {"a1_depressed_mood", "a4_sleep", "low_arousal_negative_share",
            "dwell_negative_share", "semantic_dispersion", "night_share"} <= flags
    levels = {c["name"]: c["level"] for c in rv["readout"]["clusters"]}
    assert levels["sleep_fatigue"] == "flag"
    assert levels["anhedonia_hopelessness"] == "flag"
    assert rv["guidance"]["triage_level"] == "flag"
    assert len(rv["guidance"]["resets"]) >= 3
    assert len(rv["evidence"]) >= 3 and len(rv["trajectory"]) >= 5

    # Explicit mock safety ID activates deterministic A9 override
    client.post("/api/views", json={
        "viewer": "patient-01",
        "events": [{"event_id": "p-a9", "video_id": MOCK_SAFETY_ID, "seen_at": NOW - 30, "dwell_s": 6.0}],
    })
    wait_idle(client)
    rv_a9 = client.get("/api/viewers/patient-01/readout?control=control-01").json()
    assert rv_a9["guidance"]["safety_active"] is True
    assert len(rv_a9["readout"]["safety_hits"]) == 1
