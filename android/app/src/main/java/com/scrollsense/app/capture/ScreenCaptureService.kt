package com.scrollsense.app.capture

import android.Manifest
import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.scrollsense.app.data.ClipStore
import com.scrollsense.app.data.GeminiClient
import com.scrollsense.app.ui.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

data class CaptureState(
    val recording: Boolean = false,
    val analyzing: Boolean = false,
    val chunkSeconds: Int = 8,
    val elapsedSeconds: Int = 0,
    val mockMode: Boolean = false,
    val status: String = "Idle",
    val error: String? = null
)

class ScreenCaptureService : Service() {

    companion object {
        const val ACTION_START = "com.scrollsense.app.START"
        const val ACTION_STOP = "com.scrollsense.app.STOP"
        const val ACTION_FLUSH = "com.scrollsense.app.FLUSH"
        const val ACTION_CONFIG = "com.scrollsense.app.CONFIG"

        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_DATA = "data"
        const val EXTRA_CHUNK_SEC = "chunk_sec"
        const val EXTRA_MOCK = "mock"
        const val EXTRA_API_KEY = "api_key"
        const val EXTRA_SOURCE = "source"

        private const val CHANNEL_ID = "scrollsense_capture"
        private const val NOTIF_ID = 1001

        private val _state = MutableStateFlow(CaptureState())
        val state: StateFlow<CaptureState> = _state.asStateFlow()

        fun flush(context: Context, source: String = "manual_flush") {
            if (!_state.value.recording) return
            val intent = Intent(context, ScreenCaptureService::class.java).apply {
                action = ACTION_FLUSH
                putExtra(EXTRA_SOURCE, source)
            }
            context.startService(intent)
        }
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var projection: MediaProjection? = null
    private var recorder: MediaMuxerRecorder? = null
    private var timerJob: Job? = null
    private var customApiKey: String = ""

    private val projectionCallback = object : MediaProjection.Callback() {
        override fun onStop() {
            stopCapture()
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        ClipStore.init(applicationContext)
        ensureChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                val code = intent.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED)
                @Suppress("DEPRECATION")
                val data: Intent? = intent.getParcelableExtra(EXTRA_DATA)
                val chunkSec = intent.getIntExtra(EXTRA_CHUNK_SEC, 8)
                val mock = intent.getBooleanExtra(EXTRA_MOCK, false)
                customApiKey = intent.getStringExtra(EXTRA_API_KEY).orEmpty()
                if (code == Activity.RESULT_OK && data != null) {
                    startCapture(code, data, chunkSec, mock)
                }
            }
            ACTION_FLUSH -> {
                val src = intent.getStringExtra(EXTRA_SOURCE) ?: "manual_flush"
                flushAndAnalyze(src)
            }
            ACTION_CONFIG -> {
                val chunkSec = intent.getIntExtra(EXTRA_CHUNK_SEC, _state.value.chunkSeconds)
                val mock = intent.getBooleanExtra(EXTRA_MOCK, _state.value.mockMode)
                customApiKey = intent.getStringExtra(EXTRA_API_KEY) ?: customApiKey
                _state.value = _state.value.copy(chunkSeconds = chunkSec, mockMode = mock)
            }
            ACTION_STOP -> stopCapture()
        }
        return START_NOT_STICKY
    }

    private fun startCapture(resultCode: Int, data: Intent, chunkSec: Int, mock: Boolean) {
        val notif = buildNotification("Recording screen segments…")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIF_ID, notif, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else {
            startForeground(NOTIF_ID, notif)
        }

        val mgr = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        val proj = mgr.getMediaProjection(resultCode, data) ?: run {
            _state.value = _state.value.copy(error = "MediaProjection denied")
            stopSelf()
            return
        }
        proj.registerCallback(projectionCallback, null)
        projection = proj

        val hasAudio = ContextCompat.checkSelfPermission(
            this, Manifest.permission.RECORD_AUDIO
        ) == PackageManager.PERMISSION_GRANTED
        val density = resources.displayMetrics.densityDpi

        val rec = MediaMuxerRecorder(proj, cacheDir, density, captureAudio = hasAudio)
        rec.start()
        recorder = rec

        _state.value = _state.value.copy(
            recording = true,
            chunkSeconds = chunkSec,
            elapsedSeconds = 0,
            mockMode = mock,
            status = if (hasAudio) "Recording screen + internal audio" else "Recording screen (no audio permission)",
            error = null
        )

        timerJob?.cancel()
        timerJob = scope.launch {
            while (isActive && _state.value.recording) {
                delay(1000)
                val next = _state.value.elapsedSeconds + 1
                val limit = _state.value.chunkSeconds
                if (limit > 0 && next >= limit) {
                    _state.value = _state.value.copy(elapsedSeconds = 0)
                    flushAndAnalyze("auto_chunk_${limit}s")
                } else {
                    _state.value = _state.value.copy(elapsedSeconds = next)
                }
            }
        }
    }

    private fun flushAndAnalyze(source: String) {
        val rec = recorder ?: return
        _state.value = _state.value.copy(elapsedSeconds = 0)
        scope.launch(Dispatchers.IO) {
            val bytes = rec.flushSegment() ?: return@launch
            analyzeBytes(bytes, source)
        }
    }

    private fun stopCapture() {
        timerJob?.cancel()
        timerJob = null
        val rec = recorder
        recorder = null
        val proj = projection
        projection = null

        scope.launch(Dispatchers.IO) {
            val tail = rec?.stop()
            runCatching { proj?.unregisterCallback(projectionCallback) }
            runCatching { proj?.stop() }
            if (tail != null) {
                analyzeBytes(tail, "final_segment")
            }
        }
        _state.value = _state.value.copy(recording = false, elapsedSeconds = 0, status = "Stopped")
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private suspend fun analyzeBytes(bytes: ByteArray, source: String) {
        _state.value = _state.value.copy(analyzing = true, status = "Analyzing ${bytes.size / 1024} KB clip…")
        runCatching {
            val key = customApiKey.ifBlank { com.scrollsense.app.BuildConfig.GEMINI_API_KEY }
            GeminiClient.analyzeClip(
                mp4Bytes = bytes,
                source = source,
                apiKey = key,
                forceMock = _state.value.mockMode
            )
        }.onSuccess { record ->
            ClipStore.add(record)
            _state.value = _state.value.copy(
                analyzing = false,
                status = "Analyzed: ${record.pkg.title}",
                error = null
            )
        }.onFailure { err ->
            _state.value = _state.value.copy(
                analyzing = false,
                status = "Analysis failed",
                error = err.message ?: err::class.java.simpleName
            )
        }
    }

    private fun ensureChannel() {
        val mgr = getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(
            CHANNEL_ID, "ScrollSense Screen Capture", NotificationManager.IMPORTANCE_LOW
        )
        mgr.createNotificationChannel(channel)
    }

    private fun buildNotification(text: String): Notification {
        val openIntent = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE
        )
        val stopIntent = PendingIntent.getService(
            this, 1,
            Intent(this, ScreenCaptureService::class.java).apply { action = ACTION_STOP },
            PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("ScrollSense")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setOngoing(true)
            .setContentIntent(openIntent)
            .addAction(android.R.drawable.ic_media_pause, "Stop", stopIntent)
            .build()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }
}
