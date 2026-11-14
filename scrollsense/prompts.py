"""Prompt text for the describing and scoring stages. Pure: no model calls here."""
from .schemas import TextPackage

# Why no inferring a real person's feelings, health or mental state: that would be
# emotion recognition of creators, who can't be informed or consent (EU AI Act
# Art. 50(3)). Naming people is fine when the clip names them or they are famous,
# because a meme's meaning often depends on who is in it.
DESCRIBE_PROMPT = """You are building a content-analysis record for a short video.
A second model reads only your text, never the video, so write down everything a viewer
needs to understand the clip: what is said, written, shown and heard, and what it means.

People:
- Name a person only if the clip itself names them (on-screen text, captions, speech) or
  they are an unmistakable public figure (e.g. a world-famous athlete, musician or
  politician). Otherwise describe them by role and appearance ("a man in a blue shirt").
- Never infer or describe the emotions, health or mental state of any real person shown.
  Describe what they say and do, not what they seem to feel. Mood belongs to the content:
  its music, captions, emoji, colours and editing.

Meaning:
- Explain the clip the way a typical viewer gets it: the joke, irony, sarcasm, subtext,
  meme format or template, and any in-joke or cultural reference it relies on.
- Song lyrics: give their theme in a few words; never reproduce lyrics.

Keep transcript and on-screen text verbatim where possible. Return the fields of the schema."""

# Gemini stops with finish_reason RECITATION when its answer would reproduce copyrighted
# text (typically song lyrics in music edits). The retry asks for paraphrase instead.
PARAPHRASE_PROMPT = DESCRIBE_PROMPT.replace(
    "Keep transcript and on-screen text verbatim where possible.",
    "Do NOT quote anything: paraphrase speech and on-screen text in your own words, prefixed "
    "\"Paraphrased:\". Describe any song only by its theme and mood.")

# The examples are illustrative anchors written for this prompt, not real clips, pending
# the team's own labelled calibration set. Keep them out of the stored data.
__EXAMPLES = """1. Format: talking_to_camera. Transcript: "Depression isn't just being sad. It can be
   sleeping all day, losing interest in things you loved, feeling like a burden."
   Intended meaning: calm psychoeducation that depression has many faces.
   Emotional cues: soft piano, slow pacing, muted colours.
   -> negative 2, positive 1 (valence 2), arousal 2, neutral_or_informational, hopeful false.
      The calm delivery does not make it neutral: the viewer is asked to sit with heavy material.
2. Format: meme. On-screen text: "me at 3am replaying something I said in 2016 🙂 kms".
   Intended meaning: ironic, relatable joke about shame and sleeplessness.
   Emotional cues: slowed-down sad song, dark bedroom, forced-smile emoji.
   -> negative 2, positive 1 (valence 2), arousal 1, dwelling_or_romanticising, hopeful false.
      Bleak humour is still heavy.
3. Format: broll_with_text. On-screen text: "Day 90 of therapy: made my bed, went for a walk,
   called my sister. Small wins count."
   Intended meaning: recovery is slow but real.
   Emotional cues: warm acoustic guitar, morning sunlight.
   -> negative 1, positive 2 (valence 4), arousal 2, coping_or_recovery, hopeful true.
4. Format: tutorial. Transcript: "To reset your router, hold this button for ten seconds."
   Intended meaning: a practical how-to.
   Emotional cues: no music, plain lighting, even pace.
   -> negative 0, positive 0 (valence 3), arousal 2, unrelated, hopeful false.
5. Format: animals_nature. On-screen text: "best friends 🥹". A puppy and a kitten play.
   Intended meaning: wholesome, cute.
   Emotional cues: bouncy ukulele, bright colours, heart emoji.
   -> negative 0, positive 3 (valence 5), arousal 3, unrelated, hopeful true.
6. Format: talking_to_camera. Transcript: "If you're thinking about ending your life, you're
   not alone. Call or text 988, any time."
   Intended meaning: suicide-prevention message pointing to a help line.
   Emotional cues: gentle piano, steady eye-level shot, warm light.
   -> negative 2, positive 2 (valence 3), arousal 1, coping_or_recovery, hopeful true."""

__SCORE_TEMPLATE = """You score the AFFECT of a short video from its text description.
You are not assessing any person, only what the content communicates to a viewer.
Use the intended meaning and emotional cues as well as the literal words: irony and memes
often say the opposite of their surface.

Stance:
- dwelling_or_romanticising: lingers in, validates or aestheticises the feeling without a way forward
- neutral_or_informational: describes or explains (e.g. psychoeducation) without dwelling
- coping_or_recovery: offers coping, help-seeking, recovery or hope
- unrelated: no depressive themes at all

Affect is the emotional experience a typical viewer has while watching, not the speaker's
delivery tone. Score negative_affect and positive_affect separately, each 0-3; mixed content
(bleak humour, hopeful but sad) scores on both. Valence is computed from them, not scored:
- 1 despair, self-hate, grief: negative 3, positive 0
- 2 sad, heavy, melancholic, "relatable" pain, bleak humour: negative one or two above positive
- 3 genuinely neutral (facts, a tutorial with no emotional charge) or evenly mixed: equal
- 4 pleasant, warm, funny: positive one or two above negative
- 5 joyful, awe, uplifting: positive 3, negative 0
Rule: content about sadness or depression has negative_affect above positive_affect
(valence 2 or lower) unless it is purely clinical or explicitly about recovery or coping.

Arousal 1-5: 1 still or sleepy (slow ambient, static shot), 2 calm (conversational, gentle
music), 3 moderate, 4 lively (upbeat music, quick cuts, excitement), 5 frantic or intense
(shouting, rapid cuts, alarm).

Calibration examples (invented):
{examples}

Write the rationale first, then the numbers.

TEXT PACKAGE:
{package}"""


def package_text(package: TextPackage) -> str:
    """The package as plain text, the form scoring reads."""
    return (f"Title: {package.title}\nFormat: {package.format}\n"
            f"Main message: {package.main_message}\nIntended meaning: {package.intended_meaning}\n"
            f"Emotional cues: {package.emotional_cues}\nTranscript: {package.transcript}\n"
            f"On-screen text: {package.on_screen_text}\n"
            f"Visuals: {package.visual_description}\nAudio: {package.audio_description}")


def scoring_prompt(package: TextPackage) -> str:
    """The stage-2 prompt for `package`."""
    return __SCORE_TEMPLATE.format(examples=__EXAMPLES,
                                   package=package_text(package))
