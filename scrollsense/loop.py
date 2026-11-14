"""Closed-loop home companion guidance, derived purely from feed composition and readout.

Grounded in ScrollSense's post-TMS maintenance design (`research/evidence-and-sources.md`):
1. Deterministic A9 safety path always overrides wellness nudges and shows crisis contacts.
2. When stable, zero unnecessary nudges are emitted (avoiding reminder-induced attrition).
3. When acute or baseline drift emerges, gentle state-matched resets and 2-minute Comfort
   Anchor feed re-seeding options are surfaced alongside a non-diagnostic triage summary.
"""
from typing import Literal, Sequence

from .feed import LEVELS, ClusterLevel, Composition, Readout
from .schemas import Frozen

ResetKind = Literal["arousal_bridge", "circadian_wind_down",
                    "comfort_anchor_reseed", "cognitive_activation"]


class CrisisResource(Frozen):
    """Immediate human crisis contact shown deterministically on any A9 safety hit."""

    label: str
    contact: str
    detail: str


class AnchorSeed(Frozen):
    """A pre-chosen restorative or curiosity topic used to re-seed the Shorts recommender."""

    topic: str
    url: str


class ResetAction(Frozen):
    """One low-effort home micro-intervention matched to the active feed drift signals."""

    kind: ResetKind
    title: str
    summary: str
    basis: str
    triggered_by: tuple[str, ...]


class LoopGuidance(Frozen):
    """Non-diagnostic closed-loop actions for the viewer and baseline-drift triage summary."""

    safety_active: bool
    triage_level: ClusterLevel
    headline: str
    clinical_note: str
    crisis_resources: tuple[CrisisResource, ...]
    resets: tuple[ResetAction, ...]
    anchors: tuple[AnchorSeed, ...]


CRISIS_RESOURCES: tuple[CrisisResource, ...] = (
    CrisisResource(label="MIELI Crisis Helpline (Finland, 24/7)", contact="09 2525 0111",
                   detail="Confidential crisis support in Finnish, Swedish and English."),
    CrisisResource(label="Suicide & Crisis Lifeline (US / Canada)", contact="988",
                   detail="Call or text 988 any time, free and confidential."),
    CrisisResource(label="Emergency Services (EU)", contact="112",
                   detail="Immediate emergency assistance if someone is in danger."),
)

DEFAULT_ANCHORS: tuple[AnchorSeed, ...] = (
    AnchorSeed(topic="Hand-tool woodworking",
               url="https://www.youtube.com/results?search_query=calm+hand+tool+woodworking+shorts"),
    AnchorSeed(topic="Golden retriever puppies",
               url="https://www.youtube.com/results?search_query=golden+retriever+puppies+wholesome+shorts"),
    AnchorSeed(topic="Slow Nordic nature",
               url="https://www.youtube.com/results?search_query=nordic+forest+morning+calm+shorts"),
    AnchorSeed(topic="Deep space & astronomy",
               url="https://www.youtube.com/results?search_query=james+webb+astronomy+discoveries+shorts"),
)


def guidance(current: Composition, result: Readout) -> LoopGuidance:
    """Pure closed-loop summary for `current` exposure and longitudinal `result`."""
    if current.safety_hits:
        return __safety_guidance(len(current.safety_hits))
    level = __overall_level(result)
    resets = __select_resets(current, set(result.flags))
    return LoopGuidance(safety_active=False, triage_level=level,
                        headline=__headline(level, len(resets)),
                        clinical_note=__clinical_note(level, result.flags),
                        crisis_resources=(), resets=resets, anchors=DEFAULT_ANCHORS)


def __safety_guidance(hit_count: int) -> LoopGuidance:
    noun = "clip" if hit_count == 1 else "clips"
    return LoopGuidance(
        safety_active=True, triage_level="flag",
        headline=f"Safety protocol active ({hit_count} A9 {noun} in current window)",
        clinical_note=("Deterministic safety rule: A9 death or self-harm content exposure is "
                       "never aggregated as a wellness trend. Route to human safety protocol."),
        crisis_resources=CRISIS_RESOURCES, resets=(), anchors=DEFAULT_ANCHORS)


def __overall_level(result: Readout) -> ClusterLevel:
    indices = [LEVELS.index(c.level) for c in result.clusters]
    if not indices:
        return "stable"
    highest = max(indices)
    if highest == 0 and result.flags:
        return "watch"
    return LEVELS[highest]


def __headline(level: ClusterLevel, reset_count: int) -> str:
    if level == "flag":
        return "Multi-signal feed drift vs personal baseline"
    if level == "watch" or reset_count > 0:
        return "Early feed shift noted — gentle reset options ready"
    return "Feed exposure aligned with baseline — no prompt needed"


def __clinical_note(level: ClusterLevel, flags: Sequence[str]) -> str:
    if level == "flag":
        joined = ", ".join(flags[:4])
        return (f"Sustained baseline deviation ({joined}) not shared by control. "
                "Non-diagnostic triage signal: consider brief check-in or booster review.")
    if level == "watch":
        return ("Single-dimension shift from baseline. Continue passive observation before "
                "interrupting the patient.")
    return "Within baseline bounds. Zero surveys or notifications sent."


def __select_resets(current: Composition, flags: set[str]) -> tuple[ResetAction, ...]:
    candidates = (
        __circadian_reset(current, flags),
        __reseed_reset(current, flags),
        __arousal_bridge(current, flags),
        __cognitive_reset(flags),
    )
    return tuple(action for action in candidates if action is not None)


def __circadian_reset(current: Composition, flags: set[str]) -> ResetAction | None:
    hits = tuple(sorted(flags & {"night_share", "a4_sleep", "a6_fatigue"}))
    acute_night = (current.night_share or 0.0) >= 0.35 and current.n_shown >= 3
    if not hits and not acute_night:
        return None
    triggers = hits or ("night_share",)
    return ResetAction(
        kind="circadian_wind_down",
        title="Nocturnal circadian wind-down",
        summary="Switch from vertical scrolling to warm screen-off audio rest.",
        basis="Galanis et al. (2025) & Yao et al. (2023): nocturnal feed bursts track sleep disruption.",
        triggered_by=triggers)


def __reseed_reset(current: Composition, flags: set[str]) -> ResetAction | None:
    keys = {"semantic_dispersion", "format_entropy", "dwell_negative_share",
            "a1_depressed_mood", "a2_anhedonia", "a7_worthlessness_guilt"}
    hits = tuple(sorted(flags & keys))
    narrow = current.semantic_dispersion is not None and current.semantic_dispersion <= 0.16
    if not hits and not narrow:
        return None
    return ResetAction(
        kind="comfort_anchor_reseed",
        title="2-minute Comfort-Anchor feed re-seed",
        summary="Watch 3–4 pre-chosen curiosity Shorts to re-weight the platform's session ranker.",
        basis="Liu et al. (2022, Monolith) & Leung et al. (2026): minute-level embeddings adapt to deliberate dwell.",
        triggered_by=hits or ("semantic_dispersion",))


def __arousal_bridge(current: Composition, flags: set[str]) -> ResetAction | None:
    hits = tuple(sorted(flags & {"low_arousal_negative_share", "mean_valence", "negative_share"}))
    acute_low = (current.low_arousal_negative_share or 0.0) >= 0.5 and current.n_scored >= 2
    if not hits and not acute_low:
        return None
    return ResetAction(
        kind="arousal_bridge",
        title="Arousal-matched calm audio bridge",
        summary="Start with calm, low-arousal ambient sound before gently lifting warmth — never jarring upbeat pop.",
        basis="Yoon & Rottenberg (2020) & Millgram et al. (2015): match low arousal floor first in low mood.",
        triggered_by=hits or ("low_arousal_negative_share",))


def __cognitive_reset(flags: set[str]) -> ResetAction | None:
    hits = tuple(sorted(flags & {"a2_anhedonia", "a6_fatigue", "a8_concentration"}))
    if not hits:
        return None
    return ResetAction(
        kind="cognitive_activation",
        title="60-second paced breathing or brief cognitive play",
        summary="Interrupt passive low-reward scrolling with 6 cycles/min HRV breathing or a short active game module.",
        basis="Nahum-Shani et al. (2018) JITAI routing toward active DTx (e.g. Meru HRV / Soihtu Meliora).",
        triggered_by=hits)
