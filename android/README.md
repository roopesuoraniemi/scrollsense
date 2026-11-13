# ScrollSense Android (Kotlin + Jetpack Compose)

Native Android implementation of the screen-capture spike (`minSdk 29` / Android 10+).

## What it does
1. **Screen + Internal Audio Capture** (`MediaProjection` + `VirtualDisplay` + `MediaCodec` H.264 @ 480x854 5 FPS + `AudioPlaybackCapture` AAC @ 16 kHz) muxed via `MediaMuxer` into short `.mp4` segments in `cacheDir` and deleted immediately after reading.
2. **Optional Swipe Boundary Detection** (`SwipeAccessibilityService`): listens for `TYPE_VIEW_SCROLLED` in TikTok, YouTube, and Instagram to flush the current `.mp4` chunk on each swipe (alongside the configurable 5s/8s/12s auto-chunk timer).
3. **Gemini Multimodal Pipeline** (`GeminiClient.kt`): sends inline `video/mp4` bytes (`fps=3`) to Gemini Stage 1 (`TextPackage`) and Stage 2 (`ClipScores` DSM-5 A1–A9, valence, arousal, stance, evidence).
4. **Offline Mock Mode & Local Persistence** (`ClipStore.kt`): works without an API key in Mock mode and persists clips to `filesDir/scrollsense_clips.json`.

## Build & Run
1. Open `android/` in **Android Studio** (or run `./gradlew assembleDebug` if you have Gradle + Android SDK installed).
2. *(Optional)* Create `android/local.properties` with:
   ```properties
   GEMINI_API_KEY=your_key_here
   ```
   (Or toggle **Mock mode** off in the app and paste your key in the UI.)
3. Install on an Android 10+ device, tap **Start Screen Capture**, grant the system projection prompt, and switch to TikTok / YouTube Shorts / Reels.
4. *(Optional)* Tap **Swipe Detector** in the app to enable the **ScrollSense** Accessibility Service for swipe-boundary chunking.
