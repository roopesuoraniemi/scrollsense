package com.scrollsense.app.ui

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.core.content.ContextCompat
import com.scrollsense.app.BuildConfig
import com.scrollsense.app.capture.ScreenCaptureService
import com.scrollsense.app.data.ClipStore

class MainActivity : ComponentActivity() {

    private var pendingChunkSec = 8
    private var pendingMock = BuildConfig.GEMINI_API_KEY.isBlank()
    private var pendingApiKey = ""

    private val projectionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            val intent = Intent(this, ScreenCaptureService::class.java).apply {
                action = ScreenCaptureService.ACTION_START
                putExtra(ScreenCaptureService.EXTRA_RESULT_CODE, result.resultCode)
                putExtra(ScreenCaptureService.EXTRA_DATA, result.data)
                putExtra(ScreenCaptureService.EXTRA_CHUNK_SEC, pendingChunkSec)
                putExtra(ScreenCaptureService.EXTRA_MOCK, pendingMock)
                putExtra(ScreenCaptureService.EXTRA_API_KEY, pendingApiKey)
            }
            ContextCompat.startForegroundService(this, intent)
        }
    }

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) {
        launchScreenCapturePrompt()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        ClipStore.init(applicationContext)

        setContent {
            val colors = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme()
            MaterialTheme(colorScheme = colors) {
                ScrollSenseScreen(
                    onStartCapture = { chunkSec, mock, apiKey ->
                        pendingChunkSec = chunkSec
                        pendingMock = mock
                        pendingApiKey = apiKey
                        requestPermissionsAndCapture()
                    },
                    onStopCapture = {
                        startService(Intent(this, ScreenCaptureService::class.java).apply {
                            action = ScreenCaptureService.ACTION_STOP
                        })
                    },
                    onFlushNow = {
                        ScreenCaptureService.flush(this, source = "manual_flush")
                    },
                    onOpenAccessibilitySettings = {
                        startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
                    }
                )
            }
        }
    }

    private fun requestPermissionsAndCapture() {
        val needed = buildList {
            add(Manifest.permission.RECORD_AUDIO)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                add(Manifest.permission.POST_NOTIFICATIONS)
            }
        }.toTypedArray()
        permissionLauncher.launch(needed)
    }

    private fun launchScreenCapturePrompt() {
        val mgr = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        projectionLauncher.launch(mgr.createScreenCaptureIntent())
    }
}
