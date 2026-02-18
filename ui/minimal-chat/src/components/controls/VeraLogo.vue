<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';

const props = defineProps({
    status: {
        type: String,
        default: 'idle'
    },
    intensity: {
        type: Number,
        default: 0
    },
    speechPulse: {
        type: Number,
        default: 0
    },
    soundEnabled: {
        type: Boolean,
        default: false
    },
    servoSound: {
        type: String,
        default: '/sounds/servo_actuate.mp3'
    },
    streamSound: {
        type: String,
        default: '/sounds/data_stream_high.mp3'
    },
    width: {
        type: Number,
        default: 200
    },
    height: {
        type: Number,
        default: 60
    }
});

const emit = defineEmits(['ready', 'error']);

const audioRefs = {
    servo: null,
    stream: null
};
const fadeTimers = new Map();
const previousStatus = ref('idle');

const resolvedStatus = computed(() => {
    if (['listening', 'swarm', 'quorum', 'error'].includes(props.status)) {
        return props.status;
    }
    return 'idle';
});

const normalizedIntensity = computed(() => Math.max(0, Math.min(1, props.intensity)));
const normalizedPulse = computed(() => Math.max(0, Math.min(1, props.speechPulse)));

const baseSplit = computed(() => {
    switch (resolvedStatus.value) {
        case 'listening':
            return 3;
        case 'swarm':
            return 7 + normalizedIntensity.value * 4;
        case 'quorum':
            return 9 + normalizedIntensity.value * 3;
        case 'error':
            return 11 + normalizedIntensity.value * 2;
        default:
            return 0;
    }
});

const splitOffset = computed(() => Math.min(9, baseSplit.value + normalizedPulse.value * 6));

const streamOpacity = computed(() => {
    if (resolvedStatus.value === 'idle') {
        return 0;
    }
    const base =
        resolvedStatus.value === 'listening'
            ? 0.35
            : resolvedStatus.value === 'swarm'
              ? 0.85
              : resolvedStatus.value === 'quorum'
                ? 0.65
                : 0.45;
    return Math.min(1, base + normalizedPulse.value * 0.25);
});

const glowStrength = computed(() => {
    if (resolvedStatus.value === 'idle') {
        return 0.3;
    }
    return 0.55 + normalizedIntensity.value * 0.4;
});

const logoStyle = computed(() => ({
    '--logo-width': `${props.width}px`,
    '--logo-height': `${props.height}px`,
    '--split-offset': `${splitOffset.value}px`,
    '--logo-intensity': normalizedIntensity.value,
    '--stream-opacity': streamOpacity.value,
    '--glow-strength': glowStrength.value
}));

const ensureAudio = () => {
    if (!props.soundEnabled) {
        return;
    }
    if (!audioRefs.servo) {
        try {
            audioRefs.servo = new Audio(props.servoSound);
            audioRefs.servo.volume = 0.3;
            audioRefs.servo.addEventListener('error', () => { audioRefs.servo = null; });
        } catch { /* sound file missing — ignore */ }
    }
    if (!audioRefs.stream) {
        try {
            audioRefs.stream = new Audio(props.streamSound);
            audioRefs.stream.loop = true;
            audioRefs.stream.volume = 0;
            audioRefs.stream.addEventListener('error', () => { audioRefs.stream = null; });
        } catch { /* sound file missing — ignore */ }
    }
};

const fadeAudio = (audio, targetVolume, duration = 400) => {
    if (!audio) {
        return;
    }
    const existing = fadeTimers.get(audio);
    if (existing) {
        clearInterval(existing);
    }
    const stepTime = 50;
    const steps = Math.max(1, Math.floor(duration / stepTime));
    const startVolume = audio.volume;
    const volumeStep = (targetVolume - startVolume) / steps;
    if (targetVolume > 0 && audio.paused) {
        audio.play().catch(() => {});
    }
    let currentStep = 0;
    const timer = setInterval(() => {
        currentStep += 1;
        let nextVolume = audio.volume + volumeStep;
        nextVolume = Math.max(0, Math.min(1, nextVolume));
        audio.volume = nextVolume;
        if (currentStep >= steps) {
            audio.volume = targetVolume;
            if (targetVolume === 0) {
                audio.pause();
            }
            clearInterval(timer);
            fadeTimers.delete(audio);
        }
    }, stepTime);
    fadeTimers.set(audio, timer);
};

const handleAudioState = () => {
    if (!props.soundEnabled) {
        fadeAudio(audioRefs.stream, 0, 150);
        previousStatus.value = resolvedStatus.value;
        return;
    }
    ensureAudio();
    if (resolvedStatus.value === 'swarm' || resolvedStatus.value === 'quorum') {
        fadeAudio(audioRefs.stream, 0.15, 600);
    } else {
        fadeAudio(audioRefs.stream, 0, 200);
    }
    if (previousStatus.value !== resolvedStatus.value) {
        audioRefs.servo?.play().catch(() => {});
    }
    previousStatus.value = resolvedStatus.value;
};

onMounted(() => {
    emit('ready');
    handleAudioState();
});

onUnmounted(() => {
    fadeTimers.forEach((timer) => clearInterval(timer));
    fadeTimers.clear();
});

watch([() => props.status, () => props.intensity, () => props.speechPulse], () => {
    handleAudioState();
});

watch(() => props.soundEnabled, () => {
    if (!props.soundEnabled) {
        fadeAudio(audioRefs.stream, 0, 150);
        return;
    }
    handleAudioState();
});
</script>

<template>
    <div class="vera-logo" :class="[`state-${resolvedStatus}`]" :style="logoStyle">
        <div class="vera-aperture-glow" aria-hidden="true"></div>
        <!-- Chromatic aberration layers -->
        <div class="vera-chromatic-layer chromatic-red" aria-hidden="true"></div>
        <div class="vera-chromatic-layer chromatic-blue" aria-hidden="true"></div>
        <!-- Scan line overlay -->
        <div class="vera-scan-lines" aria-hidden="true"></div>
        <!-- Particle container -->
        <div class="vera-particles" aria-hidden="true">
            <span class="particle p1"></span>
            <span class="particle p2"></span>
            <span class="particle p3"></span>
            <span class="particle p4"></span>
            <span class="particle p5"></span>
            <span class="particle p6"></span>
        </div>
        <!-- HUD Frame with corner brackets -->
        <div class="vera-hud-frame" aria-hidden="true">
            <span class="hud-corner corner-tl"></span>
            <span class="hud-corner corner-tr"></span>
            <span class="hud-corner corner-bl"></span>
            <span class="hud-corner corner-br"></span>
            <span class="hud-edge edge-top"></span>
            <span class="hud-edge edge-bottom"></span>
            <span class="hud-edge edge-left"></span>
            <span class="hud-edge edge-right"></span>
        </div>
        <!-- Energy ports at edges - makes transitions intentional -->
        <div class="vera-energy-ports" aria-hidden="true">
            <div class="energy-port port-left">
                <span class="port-line pl-1"></span>
                <span class="port-line pl-2"></span>
                <span class="port-line pl-3"></span>
                <span class="port-glow"></span>
            </div>
            <div class="energy-port port-right">
                <span class="port-line pl-1"></span>
                <span class="port-line pl-2"></span>
                <span class="port-line pl-3"></span>
                <span class="port-glow"></span>
            </div>
        </div>
        <svg class="vera-logo-svg" viewBox="0 0 200 60" role="img" aria-label="VERA">
            <defs>
                <linearGradient id="metal-grad" x1="0" y1="0" x2="0" y2="60">
                    <stop offset="0%" stop-color="var(--vera-text)" />
                    <stop offset="100%" stop-color="var(--vera-accent)" />
                </linearGradient>
            </defs>
            <g class="vera-wordmark" transform="translate(6 7)">
                <g class="vera-top">
                    <g class="vera-top-jitter">
                        <path d="M10 0 L25 30 H35 L50 0 H40 L30 20 L20 0 H10 Z" fill="url(#metal-grad)" />
                        <path d="M60 0 H90 V8 H70 V11 H85 V19 H70 V30 H60 V0 Z" fill="url(#metal-grad)" />
                        <path d="M100 0 H125 C135 0 135 15 125 18 L135 30 H123 L115 20 H110 V30 H100 V0 Z M110 8 V14 H120 C123 14 123 8 120 8 H110 Z" fill="url(#metal-grad)" />
                        <path d="M147 30 L157 0 H167 L177 30 H167 L165 22 H155 V30 H145 L147 30 Z M157 15 H163 L160 5 L157 15 Z" fill="url(#metal-grad)" />
                    </g>
                </g>
                <rect class="vera-stream" x="2" y="26" width="188" height="8" rx="4" />
                <g class="vera-bottom">
                    <g class="vera-bottom-jitter">
                        <path d="M25 30 L30 45 L35 30 H25 Z" fill="url(#metal-grad)" />
                        <path d="M60 30 V45 H90 V37 H70 V30 H60 Z" fill="url(#metal-grad)" />
                        <path d="M100 30 V45 H110 V30 H100 Z M123 30 L128 36 L135 30 H123 Z" fill="url(#metal-grad)" />
                        <path d="M145 30 H155 L152 45 H145 L145 30 Z M169 30 H179 L179 45 H172 L169 30 Z" fill="url(#metal-grad)" />
                    </g>
                </g>
            </g>
        </svg>
    </div>
</template>

<style scoped lang="scss">
.vera-logo {
    --logo-glow-color: rgba(var(--vera-accent-rgb), 0.65);
    --logo-stream-color: rgba(var(--vera-accent-rgb), 0.75);
    width: var(--logo-width);
    height: var(--logo-height);
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
}

.state-quorum {
    --logo-glow-color: rgba(var(--vera-accent-rgb), 0.7);
    --logo-stream-color: var(--vera-accent-80);
}

.state-error {
    --logo-glow-color: rgba(var(--vera-error-rgb), 0.75);
    --logo-stream-color: rgba(var(--vera-error-rgb), 0.8);
}

.vera-aperture-glow {
    position: absolute;
    inset: -20%;
    border-radius: 999px;
    // Softer, more gradual glow that fades naturally
    background: radial-gradient(
        ellipse 120% 100% at center,
        transparent 20%,
        var(--vera-accent-15) 40%,
        var(--logo-glow-color) 70%,
        transparent 100%
    );
    filter: blur(20px);
    opacity: var(--glow-strength);
    pointer-events: none;
}

.vera-logo-svg {
    width: 100%;
    height: 100%;
    z-index: 2;
    filter: drop-shadow(0 0 12px var(--logo-glow-color));
    overflow: visible;
    // Removed hard mask - let logo breathe naturally
}

.vera-top,
.vera-bottom {
    transform-origin: center;
    transition: transform 0.4s ease;
    will-change: transform;
}

.vera-top {
    transform: translateY(calc(var(--split-offset) * -1));
}

.vera-bottom {
    transform: translateY(var(--split-offset));
}

.vera-stream {
    fill: var(--logo-stream-color);
    opacity: var(--stream-opacity);
    filter: drop-shadow(0 0 6px var(--logo-glow-color));
    transition: opacity 0.3s ease;
}

.state-swarm .vera-stream {
    animation: stream-flicker 0.12s steps(2) infinite;
}

.state-quorum .vera-stream {
    animation: stream-scan 1.4s ease-in-out infinite;
}

.state-idle .vera-stream {
    animation: stream-idle 3.8s ease-in-out infinite;
    opacity: 0.35;
}

.state-swarm .vera-top-jitter,
.state-swarm .vera-bottom-jitter {
    animation: logo-shiver 0.18s ease-in-out infinite;
}

.state-error .vera-top-jitter,
.state-error .vera-bottom-jitter {
    animation: logo-error 0.12s steps(2) infinite;
}

@keyframes logo-shiver {
    0% {
        transform: translateY(0);
    }
    50% {
        transform: translateY(1px);
    }
    100% {
        transform: translateY(0);
    }
}

@keyframes logo-error {
    0% {
        transform: translateY(0);
    }
    50% {
        transform: translateY(-1px);
    }
    100% {
        transform: translateY(0);
    }
}

@keyframes stream-flicker {
    0%,
    100% {
        opacity: var(--stream-opacity);
    }
    50% {
        opacity: calc(var(--stream-opacity) * 0.5);
    }
}

@keyframes stream-scan {
    0%,
    100% {
        opacity: calc(var(--stream-opacity) * 0.6);
    }
    50% {
        opacity: var(--stream-opacity);
    }
}

@keyframes stream-idle {
    0%,
    100% {
        opacity: 0.22;
    }
    50% {
        opacity: 0.42;
    }
}

// ==========================================
// CHROMATIC ABERRATION EFFECT
// ==========================================
.vera-chromatic-layer {
    position: absolute;
    inset: -15%;
    pointer-events: none;
    opacity: 0;
    mix-blend-mode: screen;
    z-index: 3;
    transition: opacity 0.3s ease;
    // Ultra-soft vignette fade
    -webkit-mask-image: radial-gradient(
        ellipse 65% 75% at center,
        rgba(var(--vera-shadow-rgb), 1) 0%,
        rgba(var(--vera-shadow-rgb), 1) 15%,
        rgba(var(--vera-shadow-rgb), 0.6) 35%,
        rgba(var(--vera-shadow-rgb), 0.3) 55%,
        transparent 75%
    );
    mask-image: radial-gradient(
        ellipse 65% 75% at center,
        rgba(var(--vera-shadow-rgb), 1) 0%,
        rgba(var(--vera-shadow-rgb), 1) 15%,
        rgba(var(--vera-shadow-rgb), 0.6) 35%,
        rgba(var(--vera-shadow-rgb), 0.3) 55%,
        transparent 75%
    );

    &.chromatic-red {
        background: linear-gradient(
            135deg,
            var(--vera-error-15) 0%,
            transparent 50%,
            var(--vera-error-10) 100%
        );
        transform: translate(-2px, -1px);
    }

    &.chromatic-blue {
        background: linear-gradient(
            -135deg,
            var(--vera-accent-15) 0%,
            transparent 50%,
            var(--vera-accent-10) 100%
        );
        transform: translate(2px, 1px);
    }
}

.state-error .vera-chromatic-layer {
    opacity: 1;
    animation: chromaticGlitch 0.15s steps(2) infinite;
}

.state-swarm .vera-chromatic-layer {
    opacity: 0.6;
    animation: chromaticPulse 0.8s ease-in-out infinite;
}

@keyframes chromaticGlitch {
    0%, 100% {
        opacity: 0.8;
    }
    25% {
        opacity: 0.4;
        transform: translate(-3px, 1px);
    }
    50% {
        opacity: 1;
        transform: translate(2px, -1px);
    }
    75% {
        opacity: 0.5;
        transform: translate(-1px, 2px);
    }
}

@keyframes chromaticPulse {
    0%, 100% {
        opacity: 0.3;
    }
    50% {
        opacity: 0.6;
    }
}

// ==========================================
// SCAN LINES EFFECT
// ==========================================
.vera-scan-lines {
    position: absolute;
    inset: -10%;
    pointer-events: none;
    opacity: 0;
    z-index: 4;
    background: repeating-linear-gradient(
        0deg,
        transparent 0px,
        transparent 2px,
        rgba(var(--vera-accent-rgb), 0.03) 2px,
        rgba(var(--vera-accent-rgb), 0.03) 4px
    );
    transition: opacity 0.3s ease;
    // Ultra-soft vignette fade
    -webkit-mask-image: radial-gradient(
        ellipse 70% 80% at center,
        rgba(var(--vera-shadow-rgb), 1) 0%,
        rgba(var(--vera-shadow-rgb), 1) 20%,
        rgba(var(--vera-shadow-rgb), 0.7) 40%,
        rgba(var(--vera-shadow-rgb), 0.4) 55%,
        rgba(var(--vera-shadow-rgb), 0.15) 70%,
        transparent 85%
    );
    mask-image: radial-gradient(
        ellipse 70% 80% at center,
        rgba(var(--vera-shadow-rgb), 1) 0%,
        rgba(var(--vera-shadow-rgb), 1) 20%,
        rgba(var(--vera-shadow-rgb), 0.7) 40%,
        rgba(var(--vera-shadow-rgb), 0.4) 55%,
        rgba(var(--vera-shadow-rgb), 0.15) 70%,
        transparent 85%
    );

    &::before {
        content: '';
        position: absolute;
        inset: 0;
        background: linear-gradient(
            180deg,
            transparent 0%,
            var(--vera-accent-15) 50%,
            transparent 100%
        );
        height: 30%;
        animation: scanSweep 2s linear infinite;
    }
}

.state-swarm .vera-scan-lines,
.state-quorum .vera-scan-lines {
    opacity: 1;
}

.state-swarm .vera-scan-lines::before {
    animation-duration: 0.8s;
}

@keyframes scanSweep {
    0% {
        transform: translateY(-100%);
    }
    100% {
        transform: translateY(400%);
    }
}

// ==========================================
// FLOATING PARTICLES
// ==========================================
.vera-particles {
    position: absolute;
    inset: -20%;
    pointer-events: none;
    z-index: 1;
    opacity: 0;
    transition: opacity 0.5s ease;
}

.state-swarm .vera-particles,
.state-quorum .vera-particles {
    opacity: 1;
}

.particle {
    position: absolute;
    width: 3px;
    height: 3px;
    background: var(--logo-glow-color);
    border-radius: 50%;
    box-shadow: 0 0 6px var(--logo-glow-color);
    opacity: 0;

    &.p1 {
        top: 20%;
        left: 10%;
        animation: particleFloat1 3s ease-in-out infinite;
    }
    &.p2 {
        top: 60%;
        left: 15%;
        animation: particleFloat2 3.5s ease-in-out infinite 0.5s;
    }
    &.p3 {
        top: 30%;
        right: 10%;
        animation: particleFloat3 2.8s ease-in-out infinite 0.8s;
    }
    &.p4 {
        top: 70%;
        right: 15%;
        animation: particleFloat1 3.2s ease-in-out infinite 1.2s;
    }
    &.p5 {
        top: 45%;
        left: 5%;
        animation: particleFloat2 4s ease-in-out infinite 0.3s;
    }
    &.p6 {
        top: 50%;
        right: 5%;
        animation: particleFloat3 3.6s ease-in-out infinite 0.7s;
    }
}

.state-swarm .particle {
    animation-duration: 1.5s !important;
}

@keyframes particleFloat1 {
    0%, 100% {
        transform: translate(0, 0) scale(0);
        opacity: 0;
    }
    20% {
        opacity: 0.8;
        transform: translate(5px, -10px) scale(1);
    }
    50% {
        opacity: 1;
        transform: translate(15px, -5px) scale(1.2);
    }
    80% {
        opacity: 0.6;
        transform: translate(10px, 5px) scale(0.8);
    }
}

@keyframes particleFloat2 {
    0%, 100% {
        transform: translate(0, 0) scale(0);
        opacity: 0;
    }
    20% {
        opacity: 0.7;
        transform: translate(-8px, 8px) scale(1);
    }
    50% {
        opacity: 1;
        transform: translate(-12px, -5px) scale(1.1);
    }
    80% {
        opacity: 0.5;
        transform: translate(-5px, 10px) scale(0.9);
    }
}

@keyframes particleFloat3 {
    0%, 100% {
        transform: translate(0, 0) scale(0);
        opacity: 0;
    }
    25% {
        opacity: 0.9;
        transform: translate(-10px, -8px) scale(1.1);
    }
    50% {
        opacity: 0.7;
        transform: translate(5px, -12px) scale(1);
    }
    75% {
        opacity: 1;
        transform: translate(-5px, 5px) scale(1.2);
    }
}

// ==========================================
// ENHANCED GLOW EFFECTS
// ==========================================
.state-swarm .vera-aperture-glow {
    animation: aperturePulseIntense 0.4s ease-in-out infinite;
}

.state-quorum .vera-aperture-glow {
    animation: apertureBreath 1.5s ease-in-out infinite;
}

.state-idle .vera-aperture-glow {
    animation: apertureIdle 5.5s ease-in-out infinite;
    opacity: calc(var(--glow-strength) * 0.7);
}

@keyframes aperturePulseIntense {
    0%, 100% {
        opacity: var(--glow-strength);
        transform: scale(1);
        filter: blur(18px);
    }
    50% {
        opacity: calc(var(--glow-strength) * 1.3);
        transform: scale(1.1);
        filter: blur(22px);
    }
}

@keyframes apertureBreath {
    0%, 100% {
        opacity: var(--glow-strength);
        transform: scale(1);
    }
    50% {
        opacity: calc(var(--glow-strength) * 1.15);
        transform: scale(1.05);
    }
}

@keyframes apertureIdle {
    0%,
    100% {
        opacity: calc(var(--glow-strength) * 0.55);
        transform: scale(1);
        filter: blur(20px);
    }
    50% {
        opacity: calc(var(--glow-strength) * 0.85);
        transform: scale(1.04);
        filter: blur(22px);
    }
}

// ==========================================
// HUD FRAME - Sci-Fi Corner Brackets
// ==========================================
.vera-hud-frame {
    position: absolute;
    inset: -4px;
    pointer-events: none;
    z-index: 5;
    opacity: 0;
    transition: opacity 0.4s ease;
}

.state-swarm .vera-hud-frame,
.state-quorum .vera-hud-frame,
.state-error .vera-hud-frame {
    opacity: 1;
}

.state-listening .vera-hud-frame {
    opacity: 0.5;
}

// Corner brackets
.hud-corner {
    position: absolute;
    width: 12px;
    height: 12px;
    border-color: var(--logo-glow-color);
    border-style: solid;
    border-width: 0;
    opacity: 0.8;
    filter: drop-shadow(0 0 3px var(--logo-glow-color));
    transition: all 0.3s ease;

    &.corner-tl {
        top: 0;
        left: 0;
        border-top-width: 2px;
        border-left-width: 2px;
        border-top-left-radius: 3px;
    }

    &.corner-tr {
        top: 0;
        right: 0;
        border-top-width: 2px;
        border-right-width: 2px;
        border-top-right-radius: 3px;
    }

    &.corner-bl {
        bottom: 0;
        left: 0;
        border-bottom-width: 2px;
        border-left-width: 2px;
        border-bottom-left-radius: 3px;
    }

    &.corner-br {
        bottom: 0;
        right: 0;
        border-bottom-width: 2px;
        border-right-width: 2px;
        border-bottom-right-radius: 3px;
    }
}

// Edge lines (subtle connecting lines between corners)
.hud-edge {
    position: absolute;
    background: linear-gradient(
        90deg,
        transparent 0%,
        var(--logo-glow-color) 50%,
        transparent 100%
    );
    opacity: 0.3;
    filter: drop-shadow(0 0 2px var(--logo-glow-color));

    &.edge-top, &.edge-bottom {
        height: 1px;
        left: 20px;
        right: 20px;
    }

    &.edge-top {
        top: 0;
    }

    &.edge-bottom {
        bottom: 0;
    }

    &.edge-left, &.edge-right {
        width: 1px;
        top: 20px;
        bottom: 20px;
        background: linear-gradient(
            180deg,
            transparent 0%,
            var(--logo-glow-color) 50%,
            transparent 100%
        );
    }

    &.edge-left {
        left: 0;
    }

    &.edge-right {
        right: 0;
    }
}

// Animated states
.state-swarm .hud-corner {
    animation: hudCornerPulseSwarm 0.4s ease-in-out infinite;
}

.state-quorum .hud-corner {
    animation: hudCornerPulseQuorum 1.2s ease-in-out infinite;
}

.state-error .hud-corner {
    animation: hudCornerGlitch 0.15s steps(2) infinite;
    border-color: rgba(var(--vera-error-rgb), 0.9);
}

.state-swarm .hud-edge {
    animation: hudEdgePulse 0.3s ease-in-out infinite;
}

.state-quorum .hud-edge {
    animation: hudEdgePulse 1s ease-in-out infinite;
}

// Staggered corner animations
.hud-corner.corner-tr { animation-delay: 0.1s; }
.hud-corner.corner-bl { animation-delay: 0.2s; }
.hud-corner.corner-br { animation-delay: 0.3s; }

@keyframes hudCornerPulseSwarm {
    0%, 100% {
        opacity: 0.7;
        filter: drop-shadow(0 0 3px var(--logo-glow-color));
        transform: scale(1);
    }
    50% {
        opacity: 1;
        filter: drop-shadow(0 0 8px var(--logo-glow-color)) drop-shadow(0 0 12px var(--logo-glow-color));
        transform: scale(1.1);
    }
}

@keyframes hudCornerPulseQuorum {
    0%, 100% {
        opacity: 0.6;
        filter: drop-shadow(0 0 3px var(--logo-glow-color));
    }
    50% {
        opacity: 0.9;
        filter: drop-shadow(0 0 6px var(--logo-glow-color));
    }
}

@keyframes hudCornerGlitch {
    0%, 100% {
        opacity: 0.9;
        transform: translate(0, 0);
    }
    25% {
        opacity: 0.5;
        transform: translate(-1px, 1px);
    }
    50% {
        opacity: 1;
        transform: translate(1px, -1px);
    }
    75% {
        opacity: 0.6;
        transform: translate(-1px, 0);
    }
}

@keyframes hudEdgePulse {
    0%, 100% {
        opacity: 0.2;
    }
    50% {
        opacity: 0.5;
    }
}

// Corner expand on intense activity
.state-swarm .hud-corner {
    width: 16px;
    height: 16px;
}

.state-error .hud-corner {
    width: 14px;
    height: 14px;
}

// ==========================================
// ENERGY PORTS - Edge accent elements
// ==========================================
.vera-energy-ports {
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 1;
    opacity: 0;
    transition: opacity 0.4s ease;
}

.state-swarm .vera-energy-ports,
.state-quorum .vera-energy-ports {
    opacity: 1;
}

.state-listening .vera-energy-ports {
    opacity: 0.4;
}

.energy-port {
    position: absolute;
    top: 15%;
    bottom: 15%;
    width: 8px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 4px;

    &.port-left {
        left: -12px;
    }

    &.port-right {
        right: -12px;
    }
}

.port-line {
    height: 8px;
    width: 100%;
    background: linear-gradient(
        90deg,
        var(--logo-glow-color) 0%,
        transparent 100%
    );
    border-radius: 2px 0 0 2px;
    opacity: 0.6;
    filter: drop-shadow(0 0 3px var(--logo-glow-color));

    .port-right & {
        background: linear-gradient(
            90deg,
            transparent 0%,
            var(--logo-glow-color) 100%
        );
        border-radius: 0 2px 2px 0;
    }

    &.pl-1 {
        height: 6px;
        opacity: 0.4;
    }

    &.pl-2 {
        height: 12px;
        opacity: 0.8;
    }

    &.pl-3 {
        height: 6px;
        opacity: 0.4;
    }
}

.port-glow {
    position: absolute;
    top: 20%;
    bottom: 20%;
    width: 100%;
    background: radial-gradient(
        ellipse 200% 100% at center,
        var(--logo-glow-color) 0%,
        transparent 80%
    );
    filter: blur(6px);
    opacity: 0.5;

    .port-left & {
        left: -4px;
    }

    .port-right & {
        right: -4px;
    }
}

// Animated states for energy ports
.state-swarm .port-line {
    animation: portLinePulse 0.3s ease-in-out infinite;
}

.state-quorum .port-line {
    animation: portLinePulse 0.8s ease-in-out infinite;
}

.state-swarm .port-glow {
    animation: portGlowPulse 0.25s ease-in-out infinite;
}

.state-quorum .port-glow {
    animation: portGlowPulse 1s ease-in-out infinite;
}

.port-line.pl-1 { animation-delay: 0s; }
.port-line.pl-2 { animation-delay: 0.1s; }
.port-line.pl-3 { animation-delay: 0.2s; }

@keyframes portLinePulse {
    0%, 100% {
        opacity: 0.5;
        transform: scaleX(1);
    }
    50% {
        opacity: 1;
        transform: scaleX(1.3);
    }
}

@keyframes portGlowPulse {
    0%, 100% {
        opacity: 0.4;
        filter: blur(6px);
    }
    50% {
        opacity: 0.8;
        filter: blur(10px);
    }
}

// Data flow animation - particles moving through ports
.state-swarm .energy-port::before,
.state-quorum .energy-port::before {
    content: '';
    position: absolute;
    top: 50%;
    width: 3px;
    height: 3px;
    background: var(--logo-glow-color);
    border-radius: 50%;
    box-shadow: 0 0 6px var(--logo-glow-color);
    animation: dataFlowIn 0.6s linear infinite;
}

.state-swarm .energy-port::before {
    animation-duration: 0.3s;
}

.port-left::before {
    left: 0;
    animation-name: dataFlowInLeft;
}

.port-right::before {
    right: 0;
    animation-name: dataFlowInRight;
}

@keyframes dataFlowInLeft {
    0% {
        transform: translateX(-10px) translateY(-50%);
        opacity: 0;
    }
    50% {
        opacity: 1;
    }
    100% {
        transform: translateX(20px) translateY(-50%);
        opacity: 0;
    }
}

@keyframes dataFlowInRight {
    0% {
        transform: translateX(10px) translateY(-50%);
        opacity: 0;
    }
    50% {
        opacity: 1;
    }
    100% {
        transform: translateX(-20px) translateY(-50%);
        opacity: 0;
    }
}

@media (prefers-reduced-motion: reduce) {
    .vera-top,
    .vera-bottom,
    .vera-stream,
    .vera-top-jitter,
    .vera-bottom-jitter,
    .vera-chromatic-layer,
    .vera-scan-lines,
    .particle,
    .hud-corner,
    .hud-edge,
    .port-line,
    .port-glow {
        animation: none;
        transition: none;
    }

    .vera-scan-lines::before,
    .energy-port::before {
        animation: none;
    }
}
</style>
