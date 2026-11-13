package com.scrollsense.app.capture

import android.accessibilityservice.AccessibilityService
import android.view.accessibility.AccessibilityEvent

/**
 * Optional AccessibilityService that listens for feed scroll events in TikTok, YouTube,
 * and Instagram and flushes the current MP4 segment on each swipe.
 */
class SwipeAccessibilityService : AccessibilityService() {
    private var lastFlushMs = 0L

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event?.eventType != AccessibilityEvent.TYPE_VIEW_SCROLLED) return
        val now = System.currentTimeMillis()
        if (now - lastFlushMs < 2_000L) return
        lastFlushMs = now
        ScreenCaptureService.flush(applicationContext, source = "swipe_${event.packageName ?: "app"}")
    }

    override fun onInterrupt() = Unit
}
