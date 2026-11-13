package com.scrollsense.app.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

data class CriterionMeta(
    val key: String,
    val code: String,
    val label: String,
    val theme: String,
    val get: (ClipScores) -> Int
)

@Serializable
data class TextPackage(
    val title: String,
    val transcript: String = "",
    @SerialName("on_screen_text") val onScreenText: String = "",
    @SerialName("visual_description") val visualDescription: String = "",
    @SerialName("audio_description") val audioDescription: String = "",
    @SerialName("main_message") val mainMessage: String = "",
    val format: String = "other",
    @SerialName("people_present") val peoplePresent: Boolean = false,
    val language: String = "en"
)

@Serializable
data class ClipScores(
    val valence: Int,
    val arousal: Int,
    val stance: String,
    @SerialName("a1_depressed_mood") val a1DepressedMood: Int = 0,
    @SerialName("a2_anhedonia") val a2Anhedonia: Int = 0,
    @SerialName("a3_appetite_weight") val a3AppetiteWeight: Int = 0,
    @SerialName("a4_sleep") val a4Sleep: Int = 0,
    @SerialName("a5_psychomotor") val a5Psychomotor: Int = 0,
    @SerialName("a6_fatigue") val a6Fatigue: Int = 0,
    @SerialName("a7_worthlessness_guilt") val a7WorthlessnessGuilt: Int = 0,
    @SerialName("a8_concentration") val a8Concentration: Int = 0,
    @SerialName("a9_death_suicide") val a9DeathSuicide: Int = 0,
    val hopeful: Boolean = false,
    val evidence: String = ""
) {
    fun clamped(): ClipScores = copy(
        valence = valence.coerceIn(1, 5),
        arousal = arousal.coerceIn(1, 5),
        a1DepressedMood = a1DepressedMood.coerceIn(0, 3),
        a2Anhedonia = a2Anhedonia.coerceIn(0, 3),
        a3AppetiteWeight = a3AppetiteWeight.coerceIn(0, 3),
        a4Sleep = a4Sleep.coerceIn(0, 3),
        a5Psychomotor = a5Psychomotor.coerceIn(0, 3),
        a6Fatigue = a6Fatigue.coerceIn(0, 3),
        a7WorthlessnessGuilt = a7WorthlessnessGuilt.coerceIn(0, 3),
        a8Concentration = a8Concentration.coerceIn(0, 3),
        a9DeathSuicide = a9DeathSuicide.coerceIn(0, 3)
    )

    val themeLoad: Int
        get() = DSM_CRITERIA.sumOf { it.get(this) }
}

@Serializable
data class ClipRecord(
    val id: String,
    val createdMs: Long,
    val source: String,
    val bytesLen: Int,
    val mock: Boolean,
    val model: String,
    val pkg: TextPackage,
    val scores: ClipScores
)

val DSM_CRITERIA = listOf(
    CriterionMeta("a1_depressed_mood", "A1", "Depressed mood", "sadness, emptiness, hopelessness, crying") { it.a1DepressedMood },
    CriterionMeta("a2_anhedonia", "A2", "Anhedonia", "numbness, nothing matters, loss of interest") { it.a2Anhedonia },
    CriterionMeta("a3_appetite_weight", "A3", "Appetite / weight", "not eating, overeating, weight change") { it.a3AppetiteWeight },
    CriterionMeta("a4_sleep", "A4", "Sleep", "insomnia, can't sleep, oversleeping") { it.a4Sleep },
    CriterionMeta("a5_psychomotor", "A5", "Psychomotor", "slowed down, unable to move, agitated") { it.a5Psychomotor },
    CriterionMeta("a6_fatigue", "A6", "Fatigue", "exhaustion, no energy, everything takes effort") { it.a6Fatigue },
    CriterionMeta("a7_worthlessness_guilt", "A7", "Worthlessness / guilt", "self-blame, being a burden, failure") { it.a7WorthlessnessGuilt },
    CriterionMeta("a8_concentration", "A8", "Concentration", "brain fog, can't focus, indecisive") { it.a8Concentration },
    CriterionMeta("a9_death_suicide", "A9", "Death / suicide", "death wishes, suicide, self-harm") { it.a9DeathSuicide },
)

fun stanceLabel(stance: String): String = when (stance) {
    "dwelling_or_romanticising" -> "Dwelling / romanticising"
    "neutral_or_informational" -> "Neutral / informational"
    "coping_or_recovery" -> "Coping / recovery"
    "unrelated" -> "Unrelated"
    else -> stance
}
