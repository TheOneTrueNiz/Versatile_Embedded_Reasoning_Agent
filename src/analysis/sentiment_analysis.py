#!/usr/bin/env python3
"""
Sentiment Analysis Integration for NizBot VERA

This module provides sentiment analysis capabilities to detect user emotional
state and adapt assistant responses accordingly.

Features:
1. SentimentAnalyzer - Multi-dimensional sentiment detection
2. EmotionDetector - Specific emotion classification
3. UrgencyDetector - Priority/urgency detection
4. SarcasmDetector - Sarcasm pattern recognition
5. ResponseAdapter - Response style recommendations
6. MoodTracker - Temporal mood tracking

Research basis:
- VADER (Valence Aware Dictionary and Sentiment Reasoner)
- NRC Emotion Lexicon patterns
- Urgency detection from task management research
"""

import re
import json
from enum import Enum
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Set
from collections import defaultdict
import logging
logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================

class Sentiment(Enum):
    """Overall sentiment categories"""
    VERY_NEGATIVE = "very_negative"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"
    VERY_POSITIVE = "very_positive"


class Emotion(Enum):
    """Specific emotion categories"""
    JOY = "joy"
    SADNESS = "sadness"
    ANGER = "anger"
    FEAR = "fear"
    SURPRISE = "surprise"
    DISGUST = "disgust"
    TRUST = "trust"
    ANTICIPATION = "anticipation"
    FRUSTRATION = "frustration"
    EXCITEMENT = "excitement"
    CONFUSION = "confusion"
    GRATITUDE = "gratitude"
    NEUTRAL = "neutral"


class Urgency(Enum):
    """Urgency levels"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class ResponseTone(Enum):
    """Recommended response tones"""
    EMPATHETIC = "empathetic"
    ENCOURAGING = "encouraging"
    PROFESSIONAL = "professional"
    CALM = "calm"
    ENTHUSIASTIC = "enthusiastic"
    PATIENT = "patient"
    DIRECT = "direct"
    SUPPORTIVE = "supportive"


# =============================================================================
# Lexicons
# =============================================================================

# Positive word lexicon with intensity scores (0-1)
POSITIVE_LEXICON: Dict[str, float] = {
    # Strong positive
    "excellent": 0.95, "amazing": 0.95, "fantastic": 0.95, "wonderful": 0.95,
    "outstanding": 0.95, "brilliant": 0.95, "perfect": 0.95, "awesome": 0.90,
    "incredible": 0.90, "superb": 0.90, "magnificent": 0.90, "exceptional": 0.90,

    # Moderate positive
    "great": 0.80, "good": 0.70, "nice": 0.65, "happy": 0.75, "pleased": 0.70,
    "glad": 0.70, "delighted": 0.80, "satisfied": 0.70, "love": 0.85,
    "enjoy": 0.70, "appreciate": 0.70, "thankful": 0.75, "grateful": 0.80,
    "helpful": 0.70, "useful": 0.65, "valuable": 0.70, "impressive": 0.75,

    # Mild positive
    "fine": 0.50, "okay": 0.45, "ok": 0.45, "decent": 0.50, "pleasant": 0.55,
    "fair": 0.45, "acceptable": 0.45, "reasonable": 0.50, "interesting": 0.55,
    "cool": 0.60, "neat": 0.55, "works": 0.50, "thanks": 0.60, "thank": 0.60,
    "yes": 0.40, "sure": 0.45, "please": 0.40, "welcome": 0.55,
}

# Negative word lexicon with intensity scores (0-1)
NEGATIVE_LEXICON: Dict[str, float] = {
    # Strong negative
    "terrible": 0.95, "horrible": 0.95, "awful": 0.95, "dreadful": 0.90,
    "disgusting": 0.90, "hate": 0.90, "despise": 0.90, "loathe": 0.90,
    "worst": 0.95, "disaster": 0.90, "catastrophe": 0.90, "nightmare": 0.85,

    # Moderate negative
    "bad": 0.70, "poor": 0.65, "wrong": 0.65, "broken": 0.70, "failed": 0.75,
    "error": 0.60, "bug": 0.55, "issue": 0.50, "problem": 0.55, "trouble": 0.60,
    "annoying": 0.70, "frustrating": 0.75, "angry": 0.75, "upset": 0.70,
    "disappointed": 0.70, "sad": 0.65, "unhappy": 0.70, "worried": 0.60,
    "confused": 0.55, "stuck": 0.60, "lost": 0.55, "difficult": 0.55,

    # Mild negative
    "unfortunately": 0.50, "sorry": 0.45, "hard": 0.45, "tough": 0.50,
    "complicated": 0.50, "challenging": 0.45, "struggle": 0.55, "slow": 0.45,
    "not": 0.30, "don't": 0.30, "can't": 0.40, "won't": 0.35, "doesn't": 0.30,
    "isn't": 0.30, "never": 0.45, "no": 0.35,
}

# Emotion-specific patterns
EMOTION_PATTERNS: Dict[Emotion, List[str]] = {
    Emotion.JOY: [
        r"\b(happy|joy|delighted|thrilled|excited|elated|pleased)\b",
        r"\b(love|loving|loved)\s+(?:it|this|that)\b",
        r"(?:^|\s)[!]+\s*$",  # Exclamation marks
        r"\b(yay|hooray|woohoo|woo)\b",
    ],
    Emotion.SADNESS: [
        r"\b(sad|unhappy|depressed|down|blue|miserable|heartbroken)\b",
        r"\b(cry|crying|cried|tears)\b",
        r"\b(miss|missing|missed)\s+\w+",
        r"\b(sorry|apologize|regret)\b",
    ],
    Emotion.ANGER: [
        r"\b(angry|furious|mad|rage|livid|outraged|enraged)\b",
        r"\b(hate|hating|hated|despise)\b",
        r"[!]{2,}",  # Multiple exclamation marks
        r"\b(damn|dammit|wtf|ugh)\b",
    ],
    Emotion.FEAR: [
        r"\b(scared|afraid|frightened|terrified|worried|anxious)\b",
        r"\b(panic|panicking|panicked)\b",
        r"\b(danger|dangerous|risky|risk)\b",
        r"\b(what\s+if|might\s+go\s+wrong)\b",
    ],
    Emotion.SURPRISE: [
        r"\b(surprised|shocked|amazed|astonished|stunned)\b",
        r"\b(wow|whoa|omg|oh\s+my)\b",
        r"\b(unexpected|unbelievable)\b",
        r"(?<!\?)[?][!]+",  # ?! mixed but not repeated ?
    ],
    Emotion.FRUSTRATION: [
        r"\b(frustrated|frustrating|annoyed|annoying|irritated)\b",
        r"\b(stuck|blocked|can't\s+figure|doesn't\s+work)\b",
        r"\b(tried\s+everything|nothing\s+works|still\s+not)\b",
        r"\b(why\s+(?:is|does|won't|can't|doesn't))\b",
        r"\b(ugh|argh|grr)\b",  # Frustration interjections
    ],
    Emotion.CONFUSION: [
        r"\b(confused|confusing|unclear|don't\s+understand)\b",
        r"\b(what|how|why)\s+(?:does|is|do|are|should)\b",
        r"\b(lost|puzzled|baffled|perplexed)\b",
        r"[?]{2,}",  # Multiple question marks
    ],
    Emotion.EXCITEMENT: [
        r"\b(excited|exciting|can't\s+wait|looking\s+forward)\b",
        r"\b(awesome|amazing|fantastic|incredible)\b",
        r"[!]{2,}",  # Multiple exclamation marks only
        r"\b(finally|yes|yay|woohoo)\b",
    ],
    Emotion.GRATITUDE: [
        r"\b(thank|thanks|grateful|appreciate|appreciated)\b",
        r"\b(helped|helpful|saved\s+(?:me|my|the))\b",
        r"\b(perfect|exactly\s+what\s+I\s+needed)\b",
    ],
    Emotion.TRUST: [
        r"\b(trust|believe|rely|count\s+on)\b",
        r"\b(confident|sure|certain)\b",
        r"\b(always\s+(?:works|helps|reliable))\b",
    ],
    Emotion.ANTICIPATION: [
        r"\b(waiting|expecting|looking\s+forward|can't\s+wait)\b",
        r"\b(soon|upcoming|next|future)\b",
        r"\b(planning|plan\s+to|going\s+to)\b",
    ],
    Emotion.DISGUST: [
        r"\b(disgusting|disgusted|gross|nasty|repulsive)\b",
        r"\b(ugh|yuck|eww|bleh)\b",
        r"\b(sick|sickening|vile)\b",
    ],
}

# Urgency patterns
URGENCY_PATTERNS: Dict[Urgency, List[str]] = {
    Urgency.CRITICAL: [
        r"\b(urgent|urgently|asap|immediately|emergency|critical)\b",
        r"\b(right\s+now|this\s+instant|can't\s+wait)\b",
        r"\b(crisis|disaster|catastrophe)\b",
        r"\b(deadline\s+(?:is\s+)?(?:now|today|in\s+\d+\s+(?:min|hour)))\b",
    ],
    Urgency.HIGH: [
        r"\b(quickly|fast|hurry|soon|priority)\b",
        r"(?<!no\s)\brush\b",  # "rush" but not "no rush"
        r"\b(need\s+(?:this|it)\s+(?:by|before))\b",
        r"\b(important|crucial|vital)\b",
        r"\b(today|by\s+(?:end\s+of\s+)?(?:day|tonight))\b",
    ],
    Urgency.MEDIUM: [
        r"\b(when\s+you\s+(?:can|get\s+a\s+chance))\b",
        r"\b(this\s+week|by\s+(?:friday|monday|tomorrow))\b",
        r"\b(would\s+be\s+nice|if\s+possible)\b",
        r"\b(sometime|eventually)\b",
    ],
    Urgency.LOW: [
        r"\b(no\s+rush|whenever|no\s+hurry)\b",
        r"\b(when\s+you\s+have\s+time|at\s+your\s+convenience)\b",
        r"\b(low\s+priority|not\s+urgent)\b",
    ],
}

# Sarcasm indicators
SARCASM_PATTERNS: List[str] = [
    r"\b(yeah\s+right|sure\s+thing|oh\s+great|oh\s+wonderful)\b",
    r"\b(obviously|clearly|of\s+course)\b.*[!.]$",
    r"(?:thanks|thank\s+you)\s*[.]{2,}",  # thanks...
    r"\b(wow|great|amazing|fantastic)\b.*(?:not|n't)",  # "wow, that's NOT helpful"
    r"quotation marks around.*(?:good|great|helpful|useful)",  # "helpful"
]

# Intensifiers and diminishers
INTENSIFIERS: Dict[str, float] = {
    "very": 1.5, "extremely": 2.0, "absolutely": 2.0, "completely": 1.8,
    "totally": 1.7, "really": 1.4, "so": 1.3, "incredibly": 1.8,
    "remarkably": 1.6, "particularly": 1.3, "especially": 1.4,
    "quite": 1.2, "pretty": 1.2, "super": 1.5, "ultra": 1.6,
}

DIMINISHERS: Dict[str, float] = {
    "slightly": 0.5, "somewhat": 0.6, "a bit": 0.6, "a little": 0.5,
    "kind of": 0.6, "sort of": 0.6, "barely": 0.3, "hardly": 0.3,
    "only": 0.7, "just": 0.7, "merely": 0.5,
}

# Negation words
NEGATION_WORDS: Set[str] = {
    "not", "no", "never", "neither", "nobody", "nothing", "nowhere",
    "none", "don't", "doesn't", "didn't", "won't", "wouldn't", "couldn't",
    "shouldn't", "can't", "cannot", "isn't", "aren't", "wasn't", "weren't",
    "haven't", "hasn't", "hadn't",
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class SentimentResult:
    """Result of sentiment analysis"""
    text: str
    sentiment: Sentiment
    sentiment_score: float  # -1 to 1
    confidence: float  # 0 to 1

    # Detailed scores
    positive_score: float = 0.0
    negative_score: float = 0.0
    neutral_score: float = 0.0

    # Word-level details
    positive_words: List[Tuple[str, float]] = field(default_factory=list)
    negative_words: List[Tuple[str, float]] = field(default_factory=list)

    # Analysis metadata
    word_count: int = 0
    analyzed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text[:100] + "..." if len(self.text) > 100 else self.text,
            "sentiment": self.sentiment.value,
            "sentiment_score": round(self.sentiment_score, 3),
            "confidence": round(self.confidence, 3),
            "positive_score": round(self.positive_score, 3),
            "negative_score": round(self.negative_score, 3),
            "neutral_score": round(self.neutral_score, 3),
            "positive_words": self.positive_words[:5],
            "negative_words": self.negative_words[:5],
            "word_count": self.word_count,
            "analyzed_at": self.analyzed_at.isoformat(),
        }


@dataclass
class EmotionResult:
    """Result of emotion detection"""
    text: str
    primary_emotion: Emotion
    emotion_scores: Dict[Emotion, float]
    confidence: float
    patterns_matched: List[str] = field(default_factory=list)
    analyzed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text[:100] + "..." if len(self.text) > 100 else self.text,
            "primary_emotion": self.primary_emotion.value,
            "emotion_scores": {e.value: round(s, 3) for e, s in self.emotion_scores.items()},
            "confidence": round(self.confidence, 3),
            "patterns_matched": self.patterns_matched[:5],
            "analyzed_at": self.analyzed_at.isoformat(),
        }

    def top_emotions(self, n: int = 3) -> List[Tuple[Emotion, float]]:
        """Get top N emotions by score"""
        sorted_emotions = sorted(
            self.emotion_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return sorted_emotions[:n]


@dataclass
class UrgencyResult:
    """Result of urgency detection"""
    text: str
    urgency: Urgency
    urgency_score: float  # 0 to 1
    confidence: float
    indicators: List[str] = field(default_factory=list)
    analyzed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text[:100] + "..." if len(self.text) > 100 else self.text,
            "urgency": self.urgency.value,
            "urgency_score": round(self.urgency_score, 3),
            "confidence": round(self.confidence, 3),
            "indicators": self.indicators,
            "analyzed_at": self.analyzed_at.isoformat(),
        }


@dataclass
class SarcasmResult:
    """Result of sarcasm detection"""
    text: str
    is_sarcastic: bool
    sarcasm_score: float  # 0 to 1
    confidence: float
    indicators: List[str] = field(default_factory=list)
    analyzed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text[:100] + "..." if len(self.text) > 100 else self.text,
            "is_sarcastic": self.is_sarcastic,
            "sarcasm_score": round(self.sarcasm_score, 3),
            "confidence": round(self.confidence, 3),
            "indicators": self.indicators,
            "analyzed_at": self.analyzed_at.isoformat(),
        }


@dataclass
class FullAnalysis:
    """Complete sentiment analysis result"""
    text: str
    sentiment: SentimentResult
    emotion: EmotionResult
    urgency: UrgencyResult
    sarcasm: SarcasmResult
    recommended_tone: ResponseTone
    response_suggestions: List[str] = field(default_factory=list)
    analyzed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text[:100] + "..." if len(self.text) > 100 else self.text,
            "sentiment": self.sentiment.to_dict(),
            "emotion": self.emotion.to_dict(),
            "urgency": self.urgency.to_dict(),
            "sarcasm": self.sarcasm.to_dict(),
            "recommended_tone": self.recommended_tone.value,
            "response_suggestions": self.response_suggestions,
            "analyzed_at": self.analyzed_at.isoformat(),
        }


@dataclass
class MoodSnapshot:
    """Single mood measurement"""
    timestamp: datetime
    sentiment_score: float
    primary_emotion: Emotion
    urgency: Urgency

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "sentiment_score": round(self.sentiment_score, 3),
            "primary_emotion": self.primary_emotion.value,
            "urgency": self.urgency.value,
        }


# =============================================================================
# Sentiment Analyzer
# =============================================================================

class SentimentAnalyzer:
    """
    Multi-dimensional sentiment analyzer using lexicon-based approach
    with context awareness.
    """

    def __init__(
        self,
        positive_lexicon: Optional[Dict[str, float]] = None,
        negative_lexicon: Optional[Dict[str, float]] = None,
        intensifiers: Optional[Dict[str, float]] = None,
        diminishers: Optional[Dict[str, float]] = None,
    ):
        self.positive_lexicon = positive_lexicon or POSITIVE_LEXICON
        self.negative_lexicon = negative_lexicon or NEGATIVE_LEXICON
        self.intensifiers = intensifiers or INTENSIFIERS
        self.diminishers = diminishers or DIMINISHERS
        self.negation_words = NEGATION_WORDS

    def analyze(self, text: str) -> SentimentResult:
        """Analyze sentiment of text"""
        if not text or not text.strip():
            return SentimentResult(
                text="",
                sentiment=Sentiment.NEUTRAL,
                sentiment_score=0.0,
                confidence=0.0,
                word_count=0,
            )

        # Tokenize
        words = self._tokenize(text.lower())
        word_count = len(words)

        if word_count == 0:
            return SentimentResult(
                text=text,
                sentiment=Sentiment.NEUTRAL,
                sentiment_score=0.0,
                confidence=0.0,
                word_count=0,
            )

        # Track sentiment words
        positive_words = []
        negative_words = []

        positive_total = 0.0
        negative_total = 0.0

        # Sliding window for context
        window_size = 3

        for i, word in enumerate(words):
            # Check for modifiers in preceding window
            modifier = 1.0
            is_negated = False

            for j in range(max(0, i - window_size), i):
                prev_word = words[j]

                # Check negation
                if prev_word in self.negation_words:
                    is_negated = True

                # Check intensifiers
                if prev_word in self.intensifiers:
                    modifier *= self.intensifiers[prev_word]

                # Check diminishers
                if prev_word in self.diminishers:
                    modifier *= self.diminishers[prev_word]

            # Check positive lexicon
            if word in self.positive_lexicon:
                score = self.positive_lexicon[word] * modifier
                if is_negated:
                    negative_total += score
                    negative_words.append((word, score))
                else:
                    positive_total += score
                    positive_words.append((word, score))

            # Check negative lexicon
            elif word in self.negative_lexicon:
                score = self.negative_lexicon[word] * modifier
                if is_negated:
                    positive_total += score * 0.5  # Partial flip
                    positive_words.append((word, score * 0.5))
                else:
                    negative_total += score
                    negative_words.append((word, score))

        # Calculate normalized scores (consider intensity)
        total = positive_total + negative_total
        if total > 0:
            positive_score = positive_total / total
            negative_score = negative_total / total
        else:
            positive_score = 0.0
            negative_score = 0.0

        # Neutral is inversely related to sentiment words found
        sentiment_words_ratio = len(positive_words) + len(negative_words)
        neutral_score = max(0, 1 - (sentiment_words_ratio / max(word_count, 1)))

        # Overall sentiment score (-1 to 1)
        # Use intensity-weighted approach: normalize by word count with intensity
        # This ensures "extremely good" scores higher than just "good"
        raw_sentiment = positive_total - negative_total
        max_possible = word_count * 1.0  # Assume max intensity per word is 1.0
        sentiment_score = raw_sentiment / max(max_possible, 1.0)
        # Clamp to [-1, 1]
        sentiment_score = max(-1.0, min(1.0, sentiment_score))

        # Determine sentiment category
        if sentiment_score >= 0.5:
            sentiment = Sentiment.VERY_POSITIVE
        elif sentiment_score >= 0.15:
            sentiment = Sentiment.POSITIVE
        elif sentiment_score <= -0.5:
            sentiment = Sentiment.VERY_NEGATIVE
        elif sentiment_score <= -0.15:
            sentiment = Sentiment.NEGATIVE
        else:
            sentiment = Sentiment.NEUTRAL

        # Confidence based on signal strength
        confidence = min(1.0, abs(sentiment_score) + (sentiment_words_ratio / max(word_count, 1)))

        return SentimentResult(
            text=text,
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            confidence=confidence,
            positive_score=positive_score,
            negative_score=negative_score,
            neutral_score=neutral_score,
            positive_words=sorted(positive_words, key=lambda x: x[1], reverse=True),
            negative_words=sorted(negative_words, key=lambda x: x[1], reverse=True),
            word_count=word_count,
        )

    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenizer"""
        # Remove punctuation except apostrophes
        text = re.sub(r"[^\w\s']", " ", text)
        # Split and filter
        words = [w.strip("'") for w in text.split()]
        return [w for w in words if w]


# =============================================================================
# Emotion Detector
# =============================================================================

class EmotionDetector:
    """Detects specific emotions in text using pattern matching"""

    def __init__(self, patterns: Optional[Dict[Emotion, List[str]]] = None) -> None:
        self.patterns = patterns or EMOTION_PATTERNS
        self._compiled_patterns: Dict[Emotion, List[re.Pattern]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns"""
        for emotion, patterns in self.patterns.items():
            self._compiled_patterns[emotion] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]

    def detect(self, text: str) -> EmotionResult:
        """Detect emotions in text"""
        if not text or not text.strip():
            return EmotionResult(
                text="",
                primary_emotion=Emotion.NEUTRAL,
                emotion_scores={e: 0.0 for e in Emotion},
                confidence=0.0,
            )

        emotion_scores: Dict[Emotion, float] = defaultdict(float)
        patterns_matched: List[str] = []

        for emotion, compiled_patterns in self._compiled_patterns.items():
            for pattern in compiled_patterns:
                matches = pattern.findall(text)
                if matches:
                    emotion_scores[emotion] += len(matches) * 0.25
                    patterns_matched.append(f"{emotion.value}: {pattern.pattern[:30]}")

        # Ensure all emotions have a score
        for emotion in Emotion:
            if emotion not in emotion_scores:
                emotion_scores[emotion] = 0.0

        # Find primary emotion
        if any(emotion_scores.values()):
            primary_emotion = max(emotion_scores.items(), key=lambda x: x[1])[0]
            max_score = max(emotion_scores.values())
            confidence = min(1.0, max_score)
        else:
            primary_emotion = Emotion.NEUTRAL
            emotion_scores[Emotion.NEUTRAL] = 1.0
            confidence = 0.5

        # Normalize scores
        total = sum(emotion_scores.values()) or 1.0
        normalized_scores = {e: s / total for e, s in emotion_scores.items()}

        return EmotionResult(
            text=text,
            primary_emotion=primary_emotion,
            emotion_scores=normalized_scores,
            confidence=confidence,
            patterns_matched=patterns_matched,
        )


# =============================================================================
# Urgency Detector
# =============================================================================

class UrgencyDetector:
    """Detects urgency/priority in messages"""

    def __init__(self, patterns: Optional[Dict[Urgency, List[str]]] = None) -> None:
        self.patterns = patterns or URGENCY_PATTERNS
        self._compiled_patterns: Dict[Urgency, List[re.Pattern]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns"""
        for urgency, patterns in self.patterns.items():
            self._compiled_patterns[urgency] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]

    def detect(self, text: str) -> UrgencyResult:
        """Detect urgency in text"""
        if not text or not text.strip():
            return UrgencyResult(
                text="",
                urgency=Urgency.NONE,
                urgency_score=0.0,
                confidence=0.0,
            )

        urgency_scores: Dict[Urgency, float] = {
            Urgency.CRITICAL: 0.0,
            Urgency.HIGH: 0.0,
            Urgency.MEDIUM: 0.0,
            Urgency.LOW: 0.0,
            Urgency.NONE: 0.0,
        }

        indicators: List[str] = []

        # Check each urgency level
        for urgency, compiled_patterns in self._compiled_patterns.items():
            for pattern in compiled_patterns:
                matches = pattern.findall(text)
                if matches:
                    urgency_scores[urgency] += len(matches) * 0.3
                    indicators.extend(matches[:3])

        # Determine urgency level
        if urgency_scores[Urgency.CRITICAL] > 0:
            urgency = Urgency.CRITICAL
            urgency_score = min(1.0, 0.8 + urgency_scores[Urgency.CRITICAL] * 0.1)
        elif urgency_scores[Urgency.HIGH] > 0:
            urgency = Urgency.HIGH
            urgency_score = min(0.8, 0.6 + urgency_scores[Urgency.HIGH] * 0.1)
        elif urgency_scores[Urgency.MEDIUM] > 0:
            urgency = Urgency.MEDIUM
            urgency_score = min(0.6, 0.4 + urgency_scores[Urgency.MEDIUM] * 0.1)
        elif urgency_scores[Urgency.LOW] > 0:
            urgency = Urgency.LOW
            urgency_score = min(0.4, 0.2 + urgency_scores[Urgency.LOW] * 0.1)
        else:
            urgency = Urgency.NONE
            urgency_score = 0.0

        # Confidence based on indicator count
        confidence = min(1.0, len(indicators) * 0.3) if indicators else 0.3

        return UrgencyResult(
            text=text,
            urgency=urgency,
            urgency_score=urgency_score,
            confidence=confidence,
            indicators=indicators,
        )


# =============================================================================
# Sarcasm Detector
# =============================================================================

class SarcasmDetector:
    """Basic sarcasm detection using patterns"""

    def __init__(self, patterns: Optional[List[str]] = None) -> None:
        self.patterns = patterns or SARCASM_PATTERNS
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.patterns
        ]

    def detect(self, text: str) -> SarcasmResult:
        """Detect sarcasm in text"""
        if not text or not text.strip():
            return SarcasmResult(
                text="",
                is_sarcastic=False,
                sarcasm_score=0.0,
                confidence=0.0,
            )

        indicators: List[str] = []

        for pattern in self._compiled_patterns:
            matches = pattern.findall(text)
            if matches:
                if isinstance(matches[0], tuple):
                    indicators.extend([str(m) for m in matches[0]])
                else:
                    indicators.extend([str(m) for m in matches])

        # Check for sentiment contradiction (positive words + negative context)
        has_contradiction = self._check_contradiction(text)
        if has_contradiction:
            indicators.append("sentiment_contradiction")

        # Calculate sarcasm score
        sarcasm_score = min(1.0, len(indicators) * 0.25)
        is_sarcastic = sarcasm_score >= 0.4

        # Confidence is lower for sarcasm detection (it's hard!)
        confidence = min(0.7, sarcasm_score * 0.8) if indicators else 0.2

        return SarcasmResult(
            text=text,
            is_sarcastic=is_sarcastic,
            sarcasm_score=sarcasm_score,
            confidence=confidence,
            indicators=indicators,
        )

    def _check_contradiction(self, text: str) -> bool:
        """Check for sentiment contradiction"""
        text_lower = text.lower()

        # Patterns like "great, just great" or "thanks for nothing"
        patterns = [
            r"\b(great|wonderful|fantastic|amazing),?\s+(just\s+)?\1\b",
            r"thanks\s+for\s+nothing",
            r"oh\s+(how\s+)?(great|wonderful|amazing)",
        ]

        for pattern in patterns:
            if re.search(pattern, text_lower):
                return True

        return False


# =============================================================================
# Response Adapter
# =============================================================================

class ResponseAdapter:
    """Recommends response adaptations based on sentiment analysis"""

    # Mapping from emotion to recommended tone
    EMOTION_TONE_MAP: Dict[Emotion, ResponseTone] = {
        Emotion.JOY: ResponseTone.ENTHUSIASTIC,
        Emotion.SADNESS: ResponseTone.EMPATHETIC,
        Emotion.ANGER: ResponseTone.CALM,
        Emotion.FEAR: ResponseTone.SUPPORTIVE,
        Emotion.FRUSTRATION: ResponseTone.PATIENT,
        Emotion.CONFUSION: ResponseTone.PATIENT,
        Emotion.EXCITEMENT: ResponseTone.ENTHUSIASTIC,
        Emotion.GRATITUDE: ResponseTone.ENCOURAGING,
        Emotion.NEUTRAL: ResponseTone.PROFESSIONAL,
        Emotion.SURPRISE: ResponseTone.PROFESSIONAL,
        Emotion.TRUST: ResponseTone.PROFESSIONAL,
        Emotion.ANTICIPATION: ResponseTone.ENCOURAGING,
        Emotion.DISGUST: ResponseTone.CALM,
    }

    # Response suggestions by context
    SUGGESTIONS: Dict[str, List[str]] = {
        "negative_urgent": [
            "Acknowledge the urgency immediately",
            "Be concise and action-oriented",
            "Offer immediate solutions first, explanations later",
        ],
        "negative_frustrated": [
            "Acknowledge the frustration without being defensive",
            "Break down the problem into smaller steps",
            "Offer alternative approaches",
        ],
        "negative_confused": [
            "Start with a clear, simple explanation",
            "Use concrete examples",
            "Ask clarifying questions before diving deep",
        ],
        "positive_excited": [
            "Match the enthusiasm appropriately",
            "Build on their momentum",
            "Offer ways to expand on their success",
        ],
        "neutral": [
            "Be clear and professional",
            "Focus on the task at hand",
            "Provide relevant context when helpful",
        ],
        "sarcastic": [
            "Address any underlying frustration",
            "Stay professional and helpful",
            "Don't mirror the sarcasm",
        ],
    }

    def recommend_tone(
        self,
        sentiment: SentimentResult,
        emotion: EmotionResult,
        urgency: UrgencyResult,
        sarcasm: SarcasmResult,
    ) -> ResponseTone:
        """Recommend appropriate response tone"""

        # High urgency overrides to direct
        if urgency.urgency in [Urgency.CRITICAL, Urgency.HIGH]:
            if sentiment.sentiment in [Sentiment.NEGATIVE, Sentiment.VERY_NEGATIVE]:
                return ResponseTone.CALM
            return ResponseTone.DIRECT

        # Sarcasm needs careful handling
        if sarcasm.is_sarcastic:
            return ResponseTone.PROFESSIONAL

        # Use emotion-based mapping
        return self.EMOTION_TONE_MAP.get(emotion.primary_emotion, ResponseTone.PROFESSIONAL)

    def get_suggestions(
        self,
        sentiment: SentimentResult,
        emotion: EmotionResult,
        urgency: UrgencyResult,
        sarcasm: SarcasmResult,
    ) -> List[str]:
        """Get response suggestions based on analysis"""

        if sarcasm.is_sarcastic:
            return self.SUGGESTIONS["sarcastic"]

        # Determine context key
        if sentiment.sentiment in [Sentiment.NEGATIVE, Sentiment.VERY_NEGATIVE]:
            if urgency.urgency in [Urgency.CRITICAL, Urgency.HIGH]:
                return self.SUGGESTIONS["negative_urgent"]
            elif emotion.primary_emotion == Emotion.FRUSTRATION:
                return self.SUGGESTIONS["negative_frustrated"]
            elif emotion.primary_emotion == Emotion.CONFUSION:
                return self.SUGGESTIONS["negative_confused"]

        if sentiment.sentiment in [Sentiment.POSITIVE, Sentiment.VERY_POSITIVE]:
            if emotion.primary_emotion in [Emotion.EXCITEMENT, Emotion.JOY]:
                return self.SUGGESTIONS["positive_excited"]

        return self.SUGGESTIONS["neutral"]


# =============================================================================
# Mood Tracker
# =============================================================================

class MoodTracker:
    """Tracks user mood over time"""

    def __init__(
        self,
        history_limit: int = 100,
        decay_hours: float = 24.0,
    ):
        self.history_limit = history_limit
        self.decay_hours = decay_hours
        self.snapshots: List[MoodSnapshot] = []

    def record(self, analysis: FullAnalysis) -> None:
        """Record a mood snapshot from analysis"""
        snapshot = MoodSnapshot(
            timestamp=analysis.analyzed_at,
            sentiment_score=analysis.sentiment.sentiment_score,
            primary_emotion=analysis.emotion.primary_emotion,
            urgency=analysis.urgency.urgency,
        )
        self.snapshots.append(snapshot)

        # Trim history
        if len(self.snapshots) > self.history_limit:
            self.snapshots = self.snapshots[-self.history_limit:]

    def get_recent_mood(self, hours: float = 1.0) -> Optional[Dict[str, Any]]:
        """Get recent mood summary"""
        cutoff = datetime.now() - timedelta(hours=hours)
        recent = [s for s in self.snapshots if s.timestamp > cutoff]

        if not recent:
            return None

        # Average sentiment
        avg_sentiment = sum(s.sentiment_score for s in recent) / len(recent)

        # Most common emotion
        emotion_counts: Dict[Emotion, int] = defaultdict(int)
        for s in recent:
            emotion_counts[s.primary_emotion] += 1
        dominant_emotion = max(emotion_counts.items(), key=lambda x: x[1])[0]

        # Urgency trend
        urgency_scores = {
            Urgency.CRITICAL: 4, Urgency.HIGH: 3,
            Urgency.MEDIUM: 2, Urgency.LOW: 1, Urgency.NONE: 0,
        }
        avg_urgency = sum(urgency_scores[s.urgency] for s in recent) / len(recent)

        return {
            "period_hours": hours,
            "sample_count": len(recent),
            "avg_sentiment": round(avg_sentiment, 3),
            "dominant_emotion": dominant_emotion.value,
            "avg_urgency_score": round(avg_urgency, 2),
            "sentiment_trend": self._calculate_trend([s.sentiment_score for s in recent]),
        }

    def get_mood_history(self) -> List[Dict[str, Any]]:
        """Get full mood history"""
        return [s.to_dict() for s in self.snapshots]

    def _calculate_trend(self, values: List[float]) -> str:
        """Calculate trend direction"""
        if len(values) < 2:
            return "stable"

        first_half = sum(values[:len(values)//2]) / max(1, len(values)//2)
        second_half = sum(values[len(values)//2:]) / max(1, len(values) - len(values)//2)

        diff = second_half - first_half

        if diff > 0.1:
            return "improving"
        elif diff < -0.1:
            return "declining"
        return "stable"


# =============================================================================
# Full Analyzer (Orchestrator)
# =============================================================================

class FullSentimentAnalyzer:
    """
    Complete sentiment analysis orchestrator combining all analyzers.
    """

    def __init__(self) -> None:
        self.sentiment_analyzer = SentimentAnalyzer()
        self.emotion_detector = EmotionDetector()
        self.urgency_detector = UrgencyDetector()
        self.sarcasm_detector = SarcasmDetector()
        self.response_adapter = ResponseAdapter()
        self.mood_tracker = MoodTracker()

    def analyze(self, text: str, track_mood: bool = True) -> FullAnalysis:
        """Perform full analysis of text"""
        # Run all analyzers
        sentiment = self.sentiment_analyzer.analyze(text)
        emotion = self.emotion_detector.detect(text)
        urgency = self.urgency_detector.detect(text)
        sarcasm = self.sarcasm_detector.detect(text)

        # Get recommendations
        recommended_tone = self.response_adapter.recommend_tone(
            sentiment, emotion, urgency, sarcasm
        )
        suggestions = self.response_adapter.get_suggestions(
            sentiment, emotion, urgency, sarcasm
        )

        # Create full analysis
        analysis = FullAnalysis(
            text=text,
            sentiment=sentiment,
            emotion=emotion,
            urgency=urgency,
            sarcasm=sarcasm,
            recommended_tone=recommended_tone,
            response_suggestions=suggestions,
        )

        # Track mood
        if track_mood:
            self.mood_tracker.record(analysis)

        return analysis

    def get_mood_summary(self, hours: float = 1.0) -> Optional[Dict[str, Any]]:
        """Get mood summary for recent period"""
        return self.mood_tracker.get_recent_mood(hours)

    def get_stats(self) -> Dict[str, Any]:
        """Get analyzer statistics"""
        return {
            "mood_history_size": len(self.mood_tracker.snapshots),
            "positive_lexicon_size": len(self.sentiment_analyzer.positive_lexicon),
            "negative_lexicon_size": len(self.sentiment_analyzer.negative_lexicon),
            "emotion_patterns": len(self.emotion_detector.patterns),
        }


# =============================================================================
# Persistent Analyzer
# =============================================================================

class PersistentSentimentAnalyzer:
    """
    Sentiment analyzer with persistence for mood tracking across sessions.
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self.config_path = config_path or Path("sentiment_config.json")
        self.analyzer = FullSentimentAnalyzer()
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration and history"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    data = json.load(f)

                # Restore mood history
                for snapshot_data in data.get("mood_history", []):
                    snapshot = MoodSnapshot(
                        timestamp=datetime.fromisoformat(snapshot_data.get("timestamp", "")),
                        sentiment_score=snapshot_data.get("sentiment_score", ""),
                        primary_emotion=Emotion(snapshot_data.get("primary_emotion", "")),
                        urgency=Urgency(snapshot_data.get("urgency", "")),
                    )
                    self.analyzer.mood_tracker.snapshots.append(snapshot)
            except Exception as exc:
                logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

    def _save_config(self) -> None:
        """Save configuration and history"""
        data = {
            "mood_history": self.analyzer.mood_tracker.get_mood_history(),
            "saved_at": datetime.now().isoformat(),
        }

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(data, f, indent=2)

    def analyze(self, text: str) -> FullAnalysis:
        """Analyze text and persist mood tracking"""
        result = self.analyzer.analyze(text)
        self._save_config()
        return result

    def get_mood_summary(self, hours: float = 1.0) -> Optional[Dict[str, Any]]:
        """Get mood summary"""
        return self.analyzer.get_mood_summary(hours)

    def summarize(self) -> str:
        """Generate human-readable summary"""
        lines = ["Sentiment Analysis Summary", "=" * 40]

        stats = self.analyzer.get_stats()
        lines.append(f"Mood samples tracked: {stats['mood_history_size']}")

        mood = self.get_mood_summary(hours=24)
        if mood:
            lines.append(f"\nLast 24 hours ({mood['sample_count']} samples):")
            lines.append(f"  Avg sentiment: {mood['avg_sentiment']:+.2f}")
            lines.append(f"  Dominant emotion: {mood['dominant_emotion']}")
            lines.append(f"  Trend: {mood['sentiment_trend']}")

        return "\n".join(lines)


# =============================================================================
# CLI Tests
# =============================================================================

def run_cli_tests():
    """Run CLI tests"""
    print("=" * 70)
    print("Sentiment Analysis CLI Tests")
    print("=" * 70)

    tests_passed = 0
    tests_failed = 0

    def test(name: str, condition: bool, detail: str = "") -> None:
        nonlocal tests_passed, tests_failed
        if condition:
            print(f"✓ {name}")
            tests_passed += 1
        else:
            print(f"✗ {name}: {detail}")
            tests_failed += 1

    # Test 1: Basic sentiment analysis
    print("\n--- Test 1: Basic Sentiment Analysis ---")
    analyzer = SentimentAnalyzer()
    result = analyzer.analyze("I love this! It's absolutely amazing!")
    test("Positive sentiment detected", result.sentiment in [Sentiment.POSITIVE, Sentiment.VERY_POSITIVE])
    test("Positive score > 0", result.sentiment_score > 0, f"score={result.sentiment_score}")

    # Test 2: Negative sentiment
    print("\n--- Test 2: Negative Sentiment ---")
    result = analyzer.analyze("This is terrible and I hate it completely.")
    test("Negative sentiment detected", result.sentiment in [Sentiment.NEGATIVE, Sentiment.VERY_NEGATIVE])
    test("Negative score < 0", result.sentiment_score < 0, f"score={result.sentiment_score}")

    # Test 3: Neutral sentiment
    print("\n--- Test 3: Neutral Sentiment ---")
    result = analyzer.analyze("The file is located in the src directory.")
    test("Neutral sentiment detected", result.sentiment == Sentiment.NEUTRAL)

    # Test 4: Intensifiers
    print("\n--- Test 4: Intensifiers ---")
    mild = analyzer.analyze("This is good.")
    intense = analyzer.analyze("This is extremely good.")
    test("Intensifier increases score", intense.sentiment_score > mild.sentiment_score)

    # Test 5: Negation handling
    print("\n--- Test 5: Negation ---")
    result = analyzer.analyze("This is not good at all.")
    test("Negation detected", result.sentiment_score < 0.3, f"score={result.sentiment_score}")

    # Test 6: Emotion detection
    print("\n--- Test 6: Emotion Detection ---")
    detector = EmotionDetector()
    result = detector.detect("I'm so frustrated! Why doesn't this work?")
    test("Frustration detected", result.primary_emotion == Emotion.FRUSTRATION)

    # Test 7: Joy emotion
    print("\n--- Test 7: Joy Emotion ---")
    result = detector.detect("I'm so happy and thrilled about this! Yay!")
    test("Joy detected", result.primary_emotion == Emotion.JOY)

    # Test 8: Urgency detection
    print("\n--- Test 8: Urgency Detection ---")
    urgency_detector = UrgencyDetector()
    result = urgency_detector.detect("URGENT: Need this fixed ASAP!")
    test("Critical urgency detected", result.urgency == Urgency.CRITICAL)

    # Test 9: Low urgency
    print("\n--- Test 9: Low Urgency ---")
    result = urgency_detector.detect("No rush, whenever you have time is fine.")
    test("Low urgency detected", result.urgency in [Urgency.LOW, Urgency.NONE])

    # Test 10: Sarcasm detection
    print("\n--- Test 10: Sarcasm Detection ---")
    sarcasm_detector = SarcasmDetector()
    result = sarcasm_detector.detect("Oh great, another error. Yeah right, that's 'helpful'.")
    test("Sarcasm indicators found", len(result.indicators) > 0)

    # Test 11: Full analysis
    print("\n--- Test 11: Full Analysis ---")
    full_analyzer = FullSentimentAnalyzer()
    result = full_analyzer.analyze("I'm really frustrated, need help urgently!")
    test("Full analysis sentiment", result.sentiment is not None)
    test("Full analysis emotion", result.emotion is not None)
    test("Full analysis urgency", result.urgency is not None)
    test("Recommended tone", result.recommended_tone is not None)

    # Test 12: Response suggestions
    print("\n--- Test 12: Response Suggestions ---")
    test("Has suggestions", len(result.response_suggestions) > 0)

    # Test 13: Mood tracking
    print("\n--- Test 13: Mood Tracking ---")
    full_analyzer.analyze("First message - happy!")
    full_analyzer.analyze("Second message - still good")
    mood = full_analyzer.get_mood_summary(hours=1)
    test("Mood summary available", mood is not None)
    test("Mood sample count", mood and mood["sample_count"] >= 2)

    # Test 14: Persistent analyzer
    print("\n--- Test 14: Persistent Analyzer ---")
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "sentiment.json"
        persistent = PersistentSentimentAnalyzer(config_path)
        result = persistent.analyze("Test message")
        test("Persistent analysis works", result is not None)
        test("Config file created", config_path.exists())

    # Test 15: Serialization
    print("\n--- Test 15: Serialization ---")
    result = full_analyzer.analyze("Test serialization")
    d = result.to_dict()
    test("to_dict works", "sentiment" in d and "emotion" in d)

    # Summary
    print("\n" + "=" * 70)
    print(f"Tests passed: {tests_passed}")
    print(f"Tests failed: {tests_failed}")
    print("=" * 70)

    return tests_failed == 0


if __name__ == "__main__":
    import sys
    success = run_cli_tests()
    sys.exit(0 if success else 1)
