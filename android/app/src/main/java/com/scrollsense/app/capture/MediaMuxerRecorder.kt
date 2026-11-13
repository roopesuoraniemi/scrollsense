package com.scrollsense.app.capture

import android.annotation.SuppressLint
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioPlaybackCaptureConfiguration
import android.media.AudioRecord
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.MediaMuxer
import android.media.projection.MediaProjection
import android.view.Surface
import java.io.File
import java.nio.ByteBuffer
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Encodes low-res screen video (480x854 @ 5 FPS H.264) and internal playback audio
 * (16 kHz mono AAC) into short, self-contained .mp4 segments in [cacheDir].
 *
 * Keeps a single VirtualDisplay alive across segments (swapping its Surface per segment)
 * so Android 14+ does not invalidate the MediaProjection token between clips.
 */
class MediaMuxerRecorder(
    private val projection: MediaProjection,
    private val cacheDir: File,
    private val densityDpi: Int,
    private val captureAudio: Boolean
) {
    companion object {
        private const val WIDTH = 480
        private const val HEIGHT = 854
        private const val FPS = 5
        private const val VIDEO_BITRATE = 400_000
        private const val SAMPLE_RATE = 16_000
        private const val AUDIO_BITRATE = 32_000
    }

    private val running = AtomicBoolean(false)
    private val segmentLock = Any()

    private var virtualDisplay: VirtualDisplay? = null
    private var videoCodec: MediaCodec? = null
    private var audioCodec: MediaCodec? = null
    private var audioRecord: AudioRecord? = null
    private var inputSurface: Surface? = null
    private var muxer: MediaMuxer? = null
    private var currentFile: File? = null

    private var videoTrack = -1
    private var audioTrack = -1
    private var muxerStarted = false
    private var hasAudioTrack = false
    private var segmentStartNs = 0L

    private var videoThread: Thread? = null
    private var audioThread: Thread? = null

    fun start() {
        if (!running.compareAndSet(false, true)) return
        startSegmentLocked()
    }

    fun flushSegment(): ByteArray? {
        if (!running.get()) return null
        synchronized(segmentLock) {
            val bytes = stopSegmentLocked()
            if (running.get()) {
                startSegmentLocked()
            }
            return bytes
        }
    }

    fun stop(): ByteArray? {
        if (!running.compareAndSet(true, false)) return null
        synchronized(segmentLock) {
            val bytes = stopSegmentLocked()
            virtualDisplay?.release()
            virtualDisplay = null
            return bytes
        }
    }

    @SuppressLint("MissingPermission")
    private fun startSegmentLocked() {
        segmentStartNs = System.nanoTime()
        videoTrack = -1
        audioTrack = -1
        muxerStarted = false

        val outFile = File(cacheDir, "seg_${System.currentTimeMillis()}.mp4")
        currentFile = outFile
        muxer = MediaMuxer(outFile.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)

        val vFormat = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, WIDTH, HEIGHT).apply {
            setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
            setInteger(MediaFormat.KEY_BIT_RATE, VIDEO_BITRATE)
            setInteger(MediaFormat.KEY_FRAME_RATE, FPS)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1)
        }
        val vCodec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)
        vCodec.configure(vFormat, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        val surface = vCodec.createInputSurface()
        vCodec.start()
        videoCodec = vCodec
        inputSurface = surface

        if (virtualDisplay == null) {
            virtualDisplay = projection.createVirtualDisplay(
                "ScrollSenseCapture",
                WIDTH,
                HEIGHT,
                densityDpi,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                surface,
                null,
                null
            )
        } else {
            virtualDisplay?.surface = surface
        }

        hasAudioTrack = false
        if (captureAudio) {
            runCatching {
                val aFormat = MediaFormat.createAudioFormat(
                    MediaFormat.MIMETYPE_AUDIO_AAC, SAMPLE_RATE, 1
                ).apply {
                    setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC)
                    setInteger(MediaFormat.KEY_BIT_RATE, AUDIO_BITRATE)
                }
                val aCodec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_AAC)
                aCodec.configure(aFormat, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
                aCodec.start()

                val playbackConfig = AudioPlaybackCaptureConfiguration.Builder(projection)
                    .addMatchingUsage(AudioAttributes.USAGE_MEDIA)
                    .build()
                val bufSize = AudioRecord.getMinBufferSize(
                    SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT
                ).coerceAtLeast(2048)
                val record = AudioRecord.Builder()
                    .setAudioPlaybackCaptureConfig(playbackConfig)
                    .setAudioFormat(
                        AudioFormat.Builder()
                            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                            .setSampleRate(SAMPLE_RATE)
                            .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                            .build()
                    )
                    .setBufferSizeInBytes(bufSize * 2)
                    .build()
                if (record.state == AudioRecord.STATE_INITIALIZED) {
                    record.startRecording()
                    audioCodec = aCodec
                    audioRecord = record
                    hasAudioTrack = true
                } else {
                    record.release()
                    aCodec.stop()
                    aCodec.release()
                }
            }
        }

        val segmentActive = AtomicBoolean(true)
        videoThread = Thread { drainVideo(vCodec, segmentActive) }.apply { start() }
        if (hasAudioTrack) {
            audioThread = Thread { drainAudio(audioCodec!!, audioRecord!!, segmentActive) }.apply { start() }
        }
        currentSegmentActive = segmentActive
    }

    private var currentSegmentActive: AtomicBoolean? = null

    private fun stopSegmentLocked(): ByteArray? {
        currentSegmentActive?.set(false)
        runCatching { videoCodec?.signalEndOfInputStream() }
        runCatching { audioRecord?.stop() }

        runCatching { videoThread?.join(1500) }
        runCatching { audioThread?.join(1500) }
        videoThread = null
        audioThread = null

        runCatching { videoCodec?.stop() }
        runCatching { videoCodec?.release() }
        videoCodec = null

        runCatching { inputSurface?.release() }
        inputSurface = null

        runCatching { audioRecord?.release() }
        audioRecord = null

        runCatching { audioCodec?.stop() }
        runCatching { audioCodec?.release() }
        audioCodec = null

        if (muxerStarted) {
            runCatching { muxer?.stop() }
        }
        runCatching { muxer?.release() }
        muxer = null
        muxerStarted = false

        val file = currentFile
        currentFile = null
        return if (file != null && file.exists()) {
            val bytes = file.readBytes()
            file.delete()
            if (bytes.size > 1024) bytes else null
        } else {
            null
        }
    }

    private fun maybeStartMuxer() {
        val m = muxer ?: return
        if (muxerStarted) return
        val videoReady = videoTrack >= 0
        val audioReady = !hasAudioTrack || audioTrack >= 0
        if (videoReady && audioReady) {
            m.start()
            muxerStarted = true
        }
    }

    private fun drainVideo(codec: MediaCodec, active: AtomicBoolean) {
        val info = MediaCodec.BufferInfo()
        while (active.get()) {
            val idx = codec.dequeueOutputBuffer(info, 10_000)
            when {
                idx == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> synchronized(this) {
                    if (videoTrack < 0) {
                        videoTrack = muxer?.addTrack(codec.outputFormat) ?: -1
                        maybeStartMuxer()
                    }
                }
                idx >= 0 -> {
                    val buf = codec.getOutputBuffer(idx)
                    if (buf != null && info.size > 0 && (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0) {
                        synchronized(this) {
                            if (muxerStarted) {
                                info.presentationTimeUs = (System.nanoTime() - segmentStartNs) / 1000L
                                buf.position(info.offset)
                                buf.limit(info.offset + info.size)
                                muxer?.writeSampleData(videoTrack, buf, info)
                            }
                        }
                    }
                    codec.releaseOutputBuffer(idx, false)
                    if ((info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) break
                }
            }
        }
    }

    private fun drainAudio(codec: MediaCodec, record: AudioRecord, active: AtomicBoolean) {
        val pcm = ByteArray(2048)
        val info = MediaCodec.BufferInfo()
        while (active.get()) {
            val read = record.read(pcm, 0, pcm.size)
            if (read > 0) {
                val inIdx = codec.dequeueInputBuffer(10_000)
                if (inIdx >= 0) {
                    val inBuf: ByteBuffer? = codec.getInputBuffer(inIdx)
                    inBuf?.clear()
                    inBuf?.put(pcm, 0, read)
                    val pts = (System.nanoTime() - segmentStartNs) / 1000L
                    codec.queueInputBuffer(inIdx, 0, read, pts, 0)
                }
            }
            while (true) {
                val outIdx = codec.dequeueOutputBuffer(info, 0)
                when {
                    outIdx == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> synchronized(this) {
                        if (audioTrack < 0) {
                            audioTrack = muxer?.addTrack(codec.outputFormat) ?: -1
                            maybeStartMuxer()
                        }
                    }
                    outIdx >= 0 -> {
                        val outBuf = codec.getOutputBuffer(outIdx)
                        if (outBuf != null && info.size > 0 && (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0) {
                            synchronized(this) {
                                if (muxerStarted) {
                                    outBuf.position(info.offset)
                                    outBuf.limit(info.offset + info.size)
                                    muxer?.writeSampleData(audioTrack, outBuf, info)
                                }
                            }
                        }
                        codec.releaseOutputBuffer(outIdx, false)
                    }
                    else -> break
                }
            }
        }
    }
}
