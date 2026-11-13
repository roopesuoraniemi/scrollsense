package com.scrollsense.app.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.scrollsense.app.BuildConfig
import com.scrollsense.app.capture.CaptureState
import com.scrollsense.app.capture.ScreenCaptureService
import com.scrollsense.app.data.ClipStore
import com.scrollsense.app.model.ClipRecord
import com.scrollsense.app.model.DSM_CRITERIA
import com.scrollsense.app.model.stanceLabel

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ScrollSenseScreen(
    onStartCapture: (chunkSec: Int, mock: Boolean, apiKey: String) -> Unit,
    onStopCapture: () -> Unit,
    onFlushNow: () -> Unit,
    onOpenAccessibilitySettings: () -> Unit
) {
    val clips by ClipStore.clips.collectAsState()
    val capState by ScreenCaptureService.state.collectAsState()

    var selectedId by remember { mutableStateOf<String?>(null) }
    var chunkSec by remember { mutableIntStateOf(8) }
    var apiKey by remember { mutableStateOf(BuildConfig.GEMINI_API_KEY) }
    var mockMode by remember { mutableStateOf(BuildConfig.GEMINI_API_KEY.isBlank()) }

    val selected = clips.find { it.id == selectedId } ?: clips.lastOrNull()

    Scaffold { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            HeaderBar(mockMode = mockMode)

            CaptureControlsCard(
                capState = capState,
                chunkSec = chunkSec,
                onChunkSecChange = { chunkSec = it },
                mockMode = mockMode,
                onMockChange = { mockMode = it },
                apiKey = apiKey,
                onApiKeyChange = { apiKey = it },
                onStart = { onStartCapture(chunkSec, mockMode, apiKey.trim()) },
                onStop = onStopCapture,
                onFlush = onFlushNow,
                onOpenAccessibility = onOpenAccessibilitySettings
            )

            if (clips.isNotEmpty()) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    clips.reversed().forEach { c ->
                        FilterChip(
                            selected = selected?.id == c.id,
                            onClick = { selectedId = c.id },
                            label = { Text(c.pkg.title.take(28)) }
                        )
                    }
                    TextButton(onClick = { ClipStore.clear(); selectedId = null }) {
                        Text("Clear")
                    }
                }
            }

            AffectSpaceCard(clips = clips, selected = selected)

            if (selected != null) {
                DsmScoresCard(clip = selected)
                TextPackageCard(clip = selected)
            } else {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Text(
                        text = "Tap Start Screen Capture, then switch to TikTok, YouTube Shorts, or Reels. Clips are analysed every ${if (chunkSec > 0) "${chunkSec}s" else "swipe"}.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(16.dp)
                    )
                }
            }
        }
    }
}

@Composable
private fun HeaderBar(mockMode: Boolean) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Text("ScrollSense", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
        Surface(
            color = if (mockMode) Color(0xFFFAEEDA) else MaterialTheme.colorScheme.primaryContainer,
            shape = RoundedCornerShape(6.dp)
        ) {
            Text(
                text = if (mockMode) "MOCK mode" else "Gemini Live",
                style = MaterialTheme.typography.labelSmall,
                color = if (mockMode) Color(0xFF854F0B) else MaterialTheme.colorScheme.onPrimaryContainer,
                modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp)
            )
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CaptureControlsCard(
    capState: CaptureState,
    chunkSec: Int,
    onChunkSecChange: (Int) -> Unit,
    mockMode: Boolean,
    onMockChange: (Boolean) -> Unit,
    apiKey: String,
    onApiKeyChange: (String) -> Unit,
    onStart: () -> Unit,
    onStop: () -> Unit,
    onFlush: () -> Unit,
    onOpenAccessibility: () -> Unit
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (!capState.recording) {
                    Button(onClick = onStart) { Text("Start Screen Capture") }
                } else {
                    Button(
                        onClick = onStop,
                        colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
                    ) { Text("Stop (${capState.elapsedSeconds}s)") }
                    OutlinedButton(onClick = onFlush) { Text("Flush Clip") }
                }
            }

            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf(5 to "5s", 8 to "8s", 12 to "12s", 0 to "Swipe only").forEach { (sec, label) ->
                    FilterChip(
                        selected = chunkSec == sec,
                        onClick = { onChunkSecChange(sec) },
                        enabled = !capState.recording,
                        label = { Text(label) }
                    )
                }
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text("Mock mode (no API key)", style = MaterialTheme.typography.bodyMedium)
                Switch(checked = mockMode, onCheckedChange = onMockChange, enabled = !capState.recording)
            }

            if (!mockMode) {
                OutlinedTextField(
                    value = apiKey,
                    onValueChange = onApiKeyChange,
                    label = { Text("Gemini API Key") },
                    singleLine = true,
                    enabled = !capState.recording,
                    modifier = Modifier.fillMaxWidth()
                )
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = capState.error ?: capState.status,
                    style = MaterialTheme.typography.bodySmall,
                    color = if (capState.error != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f)
                )
                TextButton(onClick = onOpenAccessibility) {
                    Text("Swipe Detector")
                }
            }
        }
    }
}

@Composable
private fun AffectSpaceCard(clips: List<ClipRecord>, selected: ClipRecord?) {
    val lineColor = MaterialTheme.colorScheme.outlineVariant
    val accentColor = MaterialTheme.colorScheme.primary
    val cool = Color(0xFF378ADD)
    val warm = Color(0xFFD85A30)
    val danger = Color(0xFFA32D2D)

    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Affect Space (Valence × Arousal)", style = MaterialTheme.typography.titleSmall)
            Canvas(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(170.dp)
                    .border(1.dp, lineColor, RoundedCornerShape(8.dp))
            ) {
                val pad = 28f
                val pw = size.width - pad * 2
                val ph = size.height - pad * 2
                fun xFor(v: Int) = pad + ((v - 0.5f) / 5f) * pw
                fun yFor(a: Int) = pad + ph - ((a - 0.5f) / 5f) * ph

                drawLine(lineColor, Offset(xFor(3), pad), Offset(xFor(3), pad + ph), strokeWidth = 2f)
                drawLine(lineColor, Offset(pad, yFor(3)), Offset(pad + pw, yFor(3)), strokeWidth = 2f)

                clips.forEach { c ->
                    val s = c.scores
                    val h = (c.id.hashCode() and 0x7fffffff)
                    val dx = ((h % 11) - 5) * 4f
                    val dy = (((h shr 4) % 11) - 5) * 4f
                    val center = Offset(
                        (xFor(s.valence) + dx).coerceIn(pad + 8f, pad + pw - 8f),
                        (yFor(s.arousal) + dy).coerceIn(pad + 8f, pad + ph - 8f)
                    )
                    val dotColor = if (s.a9DeathSuicide > 0) danger
                    else lerp(cool, warm, (s.themeLoad.coerceAtMost(18)) / 18f)
                    val isCur = selected?.id == c.id
                    if (isCur) {
                        drawCircle(accentColor, radius = 18f, center = center, alpha = 0.25f)
                    }
                    drawCircle(dotColor, radius = if (isCur) 11f else 7f, center = center)
                }
            }
            Text(
                text = "X: Valence (1–5) · Y: Arousal (1–5) · Color: DSM-5 load (blue → orange, red = A9)",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DsmScoresCard(clip: ClipRecord) {
    val s = clip.scores
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (s.a9DeathSuicide > 0) {
                Surface(color = MaterialTheme.colorScheme.errorContainer, shape = RoundedCornerShape(8.dp)) {
                    Text(
                        text = "Safety path: death or suicide themes detected (A9 = ${s.a9DeathSuicide}). Triggers clinician protocol & crisis resources.",
                        color = MaterialTheme.colorScheme.onErrorContainer,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(10.dp)
                    )
                }
            }
            Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("${s.themeLoad}", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                Text("/ 27 theme load", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                ChipTag(stanceLabel(s.stance))
                ChipTag("Valence ${s.valence}/5")
                ChipTag("Arousal ${s.arousal}/5")
                ChipTag(if (s.hopeful) "Hopeful" else "Not hopeful")
            }
            HorizontalDivider()
            DSM_CRITERIA.forEach { c ->
                val v = c.get(s)
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Text(c.code, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.width(26.dp))
                    Text(c.label, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                    Row(horizontalArrangement = Arrangement.spacedBy(3.dp)) {
                        for (i in 1..3) {
                            Box(
                                modifier = Modifier
                                    .size(width = 24.dp, height = 8.dp)
                                    .background(
                                        color = when {
                                            v < i -> MaterialTheme.colorScheme.surfaceVariant
                                            c.code == "A9" -> MaterialTheme.colorScheme.error
                                            else -> MaterialTheme.colorScheme.primary
                                        },
                                        shape = RoundedCornerShape(3.dp)
                                    )
                            )
                        }
                    }
                    Text("$v", style = MaterialTheme.typography.labelSmall, modifier = Modifier.width(14.dp))
                }
            }
            if (s.evidence.isNotBlank()) {
                Text(
                    text = "“${s.evidence}”",
                    style = MaterialTheme.typography.bodySmall,
                    fontStyle = FontStyle.Italic,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
private fun TextPackageCard(clip: ClipRecord) {
    val p = clip.pkg
    Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors()) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(p.title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            Text("${clip.source} · ${(clip.bytesLen / 1024).coerceAtLeast(1)} KB · ${clip.model}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (p.mainMessage.isNotBlank()) LabeledLine("Main message", p.mainMessage)
            if (p.transcript.isNotBlank()) LabeledLine("Transcript", p.transcript)
            if (p.onScreenText.isNotBlank()) LabeledLine("On-screen text", p.onScreenText)
            if (p.visualDescription.isNotBlank()) LabeledLine("Visuals", p.visualDescription)
            if (p.audioDescription.isNotBlank()) LabeledLine("Audio", p.audioDescription)
        }
    }
}

@Composable
private fun LabeledLine(label: String, value: String) {
    Column {
        Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun ChipTag(text: String) {
    Surface(
        shape = RoundedCornerShape(6.dp),
        color = MaterialTheme.colorScheme.surfaceVariant
    ) {
        Text(text, style = MaterialTheme.typography.labelSmall, modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp))
    }
}
