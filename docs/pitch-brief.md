# ScrollSense: brief for a video pitch script

You are writing the script for a short pitch video of a hackathon project (Junction 2026). This
brief is everything you need: what the project is, what it shows, the numbers you may use, and the
claims you must not make. Ask the team for the target length, challenge name and team names if
they are not given; otherwise assume 2 minutes.

## One line

ScrollSense reads the short videos a person scrolls as a passive, early signal of low mood, and
answers with a gentle check-in, not a diagnosis.

## The problem

- Low mood and depression are usually noticed late: by the person, their family or a clinician.
- People spend hours a day in short-video feeds (YouTube Shorts, Reels, TikTok). What a feed
  serves, and what someone lingers on, shifts with mood, and the algorithm amplifies it: a sad
  evening can turn into a feed full of sad content.
- Clinicians see a patient every few weeks and rely on self-report in between.

## What ScrollSense does

1. **Logs what is scrolled.** A small browser userscript on the phone sends the ID of each
   YouTube Short as it opens. Nothing else: no account, comments or messages. The person agrees
   to this first and can pause it any time.
2. **Gemini watches each Short.** Gemini 3.5 Flash-Lite watches the public video directly (only
   its first 30 seconds) and returns, in one call of about 2 seconds, a short text description
   and affect scores: how pleasant the content feels (valence) and how energetic (arousal).
   It scores the **content as a typical viewer would feel it, never the person** watching or
   appearing in it.
3. **Detects drift towards low mood.** The last few analysed Shorts (5 in the demo) are compared
   with a research norm of typical affect (Warriner, Kuperman and Brysbaert 2013). Within 1
   standard deviation is the normal range. When the feed's average points into the low-mood
   corner (lower valence and lower arousal) and is more than 1 SD away, that is a warning.
4. **Sends a gentle check-in.** On the first warning the phone shows a calm card: "How do these
   videos feel right now?" with three equal options: "I'm OK", "I want to take a break" (pauses
   and closes the feed) and "Not now". It never names a diagnosis, a mood or a video.
5. **Keeps the clinician informed.** A dashboard shows the trend, each check-in, what caused it
   (for example "Drift 2.1 SD passed the 1 SD alarm") and how the person answered.

## Why it is different

- **Passive:** no questionnaires, no diaries; it uses something people already do.
- **Fast enough to matter:** about 2 seconds per Short, while people watch a Short for about
  14 to 16 seconds on average. The check-in arrives a few seconds after the warning forms.
- **Gentle by design:** a check-in and a break, not an alarm. No crisis or suicide alerts, because
  a feed signal is not reliable enough for that. No "refresh my feed" option either: steering the
  feed would erase the very signal it reads.
- **Privacy-minded:** pseudonyms instead of names; only public video links go to Gemini, never
  patient data; a viewer's data can be erased on request (GDPR); no emotion recognition of the
  people in the videos (EU AI Act, Art. 50(3)).

## Numbers you may use (and how to phrase them)

- **About 2 seconds** to analyse a Short (measured on 10 Shorts: median 1.9 s, at most 2.3 s).
- **Average Short watch time about 14 to 16 seconds** (industry reports, not peer-reviewed).
- **Slower models did not do better:** on 41 Shorts, Gemini 3.5 Flash-Lite matched the most
  thorough pipeline on the low-mood call for 39 of 41, while 2 to 4 times slower models matched
  36 to 38.
- **On simulated feeds** (300 sessions per scenario, window of 10 Shorts): 0% false warnings on
  ordinary feeds; a switch to a heavy feed was caught in 99% of sessions, after a median of 10
  Shorts. Say "in simulation", never "clinically validated".

## What the demo shows (for shot planning)

**Live web demo** (one screen, three views; a judge can try it in a browser):
- **"User sees":** a phone that scrolls a scripted feed: a few upbeat Shorts, then a run of
  melancholic ones. Scroll, swipe or use the arrow keys.
- **"Only software sees":** the trend strip ("Trend: drift towards low mood") that turns red on a
  warning, the Short's text description ("Analyzing…" for about 2 seconds after it starts), and
  the mood map: dots for the recent Shorts and an arrow that glides from "typical" into the red
  "depressive signal zone".
- **The moment:** around Short 9 the drift passes 1 SD, the strip turns red ("Warning: 2.1 SD,
  past the 1 SD alarm, check-in sent …") and the check-in card slides up on the phone.
- **"Clinician sees":** this session's check-ins with cause and answer, plus a clearly labelled
  example two-week history (invented data) showing how a clinician follows a patient over time.
- **"Want to test your own video?"** Paste any YouTube Short and it plays next, analysed live.

**Floor demo:** a real phone scrolling real YouTube Shorts with the userscript, and the clinician
dashboard updating live on a laptop beside it.

## Tone and wording

- Calm, warm, credible. This is about mental health: no dramatic music cues described as
  "danger", no fear-based framing, no flashing red alarms.
- Say "low-mood drift", "signal", "check-in", "research prototype".
- The person stays in control: they choose the answer, they can pause logging, nothing is sent
  without consent.

## Do not claim

- That it detects, diagnoses or predicts depression, or that it is a medical device.
- That it reads the person's emotions or face. It scores the videos, not the viewer.
- That it is clinically validated. Thresholds were checked on simulated feeds only, and the norm
  is for English words, not videos.
- That it works on TikTok or Instagram today. It works with YouTube Shorts.
- Crisis or emergency features: there are none, on purpose.

## Honest limits (good for a closing line or Q&A)

- Research prototype; the next step is a study with clinicians and consenting patients.
- Short-video feeds reflect mood but also taste and the algorithm; ScrollSense looks for a change
  over time, not a single sad video.

## Under the hood (one line in the video at most)

Python and FastAPI, the Gemini API (3.5 Flash-Lite, one call per Short), a browser userscript on
the phone, a plain HTML dashboard, hosted on Modal.
