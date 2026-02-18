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
    active: {
        type: Boolean,
        default: false
    },
    soundEnabled: {
        type: Boolean,
        default: false
    },
    humSound: {
        type: String,
        default: '/sounds/swarm_hum_loop.mp3'
    },
    lockSound: {
        type: String,
        default: '/sounds/quorum_lock.mp3'
    },
    errorSound: {
        type: String,
        default: '/sounds/system_fail_descend.mp3'
    },
    size: {
        type: Number,
        default: 60
    },
    statusClass: {
        type: String,
        default: 'neutral'
    }
});

const emit = defineEmits(['ready', 'error']);

const audioRefs = {
    hum: null,
    lock: null,
    error: null
};
const fadeTimers = new Map();
const previousStatus = ref('idle');

const resolvedStatus = computed(() => {
    if (props.status === 'swarm' || props.status === 'quorum' || props.status === 'error') {
        return props.status;
    }
    return 'idle';
});

const normalizedIntensity = computed(() => Math.max(0, Math.min(1, props.intensity)));
const sizeScale = computed(() => Math.max(0.6, props.size / 60));

const indicatorStyle = computed(() => ({
    '--indicator-size': `${props.size}px`,
    '--swarm-intensity': normalizedIntensity.value,
    '--consume-duration': `${consumeDuration.value}s`
}));

const statusSpeed = computed(() => {
    if (resolvedStatus.value === 'idle') {
        return 1.7;
    }
    if (resolvedStatus.value === 'quorum') {
        return props.active ? 0.55 : 0.85;
    }
    if (resolvedStatus.value === 'swarm') {
        return props.active ? 0.75 : 1;
    }
    if (resolvedStatus.value === 'error') {
        return 0.7;
    }
    return 1;
});

const consumeDuration = computed(() => {
    if (resolvedStatus.value === 'quorum') {
        return props.active ? 1.5 - normalizedIntensity.value * 0.3 : 2.4;
    }
    if (resolvedStatus.value === 'swarm') {
        return props.active ? 1.9 - normalizedIntensity.value * 0.4 : 2.8;
    }
    return 3.2;
});

const orbitConfigs = [
    { radius: 16, size: 5, duration: 5.4, delay: -1.2, tilt: 0.85, rotation: 0 },
    { radius: 22, size: 4, duration: 6.1, delay: -2.3, tilt: 0.75, rotation: 35 },
    { radius: 28, size: 4.5, duration: 6.8, delay: -0.7, tilt: 0.65, rotation: 70 },
    { radius: 34, size: 3.5, duration: 7.6, delay: -3.0, tilt: 0.9, rotation: 110 },
    { radius: 40, size: 3, duration: 8.4, delay: -1.8, tilt: 0.6, rotation: 150 }
];

const orbitStyle = (orbit) => {
    const scale = sizeScale.value;
    const intensity = normalizedIntensity.value;
    const speedFactor = 1 - intensity * 0.35;
    const duration = Math.max(1.3, orbit.duration * speedFactor * statusSpeed.value);
    const radius = orbit.radius * scale * (1 + intensity * 0.15);
    const size = orbit.size * scale * (1 + intensity * 0.2);
    return {
        '--orbit-radius': `${radius}px`,
        '--orbit-size': `${size}px`,
        '--orbit-duration': `${duration}s`,
        '--orbit-delay': `${orbit.delay}s`,
        '--orbit-tilt': orbit.tilt,
        '--orbit-rotation': `${orbit.rotation}deg`
    };
};

const ensureAudio = () => {
    if (!props.soundEnabled) {
        return;
    }
    if (!audioRefs.hum) {
        try {
            audioRefs.hum = new Audio(props.humSound);
            audioRefs.hum.loop = true;
            audioRefs.hum.volume = 0;
            audioRefs.hum.addEventListener('error', () => { audioRefs.hum = null; });
        } catch { /* sound file missing — ignore */ }
    }
    if (!audioRefs.lock) {
        try {
            audioRefs.lock = new Audio(props.lockSound);
            audioRefs.lock.volume = 0.5;
            audioRefs.lock.addEventListener('error', () => { audioRefs.lock = null; });
        } catch { /* sound file missing — ignore */ }
    }
    if (!audioRefs.error) {
        try {
            audioRefs.error = new Audio(props.errorSound);
            audioRefs.error.volume = 0.4;
            audioRefs.error.addEventListener('error', () => { audioRefs.error = null; });
        } catch { /* sound file missing — ignore */ }
    }
};

const fadeAudio = (audio, targetVolume, duration = 500) => {
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
        fadeAudio(audioRefs.hum, 0, 200);
        previousStatus.value = resolvedStatus.value;
        return;
    }
    ensureAudio();
    if (resolvedStatus.value === 'swarm') {
        fadeAudio(audioRefs.hum, 0.3, 800);
    } else {
        fadeAudio(audioRefs.hum, 0, 300);
    }
    if (previousStatus.value !== resolvedStatus.value) {
        if (resolvedStatus.value === 'quorum') {
            audioRefs.lock?.play().catch(() => {});
        }
        if (resolvedStatus.value === 'error') {
            audioRefs.error?.play().catch(() => {});
        }
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

watch([() => props.status, () => props.intensity], () => {
    handleAudioState();
});

watch(() => props.soundEnabled, () => {
    if (!props.soundEnabled) {
        fadeAudio(audioRefs.hum, 0, 150);
        return;
    }
    handleAudioState();
});
</script>

<template>
    <div
        class="swarm-indicator"
        :class="[`state-${resolvedStatus}`, statusClass, { 'is-active': active }]"
        :style="indicatorStyle"
    >
        <div class="swarm-glow" aria-hidden="true"></div>
        <div class="swarm-status-ring" aria-hidden="true"></div>
        <svg class="swarm-core" viewBox="0 0 100 100" aria-hidden="true">
            <path d="M50 5L93.3 25V75L50 95L6.7 75V25L50 5Z" stroke="currentColor" stroke-width="2" fill="none" />
            <path d="M50 5L50 95" stroke="currentColor" stroke-width="1" stroke-opacity="0.5" />
            <path d="M6.7 25L93.3 25" stroke="currentColor" stroke-width="1" stroke-opacity="0.5" />
            <path d="M6.7 75L93.3 75" stroke="currentColor" stroke-width="1" stroke-opacity="0.5" />
            <path d="M50 50L6.7 25" stroke="currentColor" stroke-width="1" stroke-opacity="0.3" />
            <path d="M50 50L93.3 25" stroke="currentColor" stroke-width="1" stroke-opacity="0.3" />
            <path d="M50 50L50 95" stroke="currentColor" stroke-width="1" stroke-opacity="0.3" />
        </svg>
        <!-- Connection lines from satellites to core -->
        <svg class="swarm-connections" viewBox="0 0 100 100" aria-hidden="true">
            <line v-for="(orbit, index) in orbitConfigs" :key="`line-${index}`"
                class="connection-line"
                :class="`line-${index}`"
                x1="50" y1="50"
                :x2="50 + orbit.radius * 0.8" :y2="50"
                :style="{ '--line-delay': `${index * 0.2}s` }"
            />
        </svg>
        <div class="swarm-orbits" aria-hidden="true">
            <div v-for="(orbit, index) in orbitConfigs" :key="index" class="swarm-orbit" :style="orbitStyle(orbit)">
                <span class="swarm-satellite">
                    <span class="swarm-satellite-trail"></span>
                    <span class="swarm-satellite-core"></span>
                    <span class="swarm-satellite-glow"></span>
                </span>
            </div>
        </div>
        <!-- Pulse rings -->
        <div class="swarm-pulse-rings" aria-hidden="true">
            <span class="pulse-ring ring-1"></span>
            <span class="pulse-ring ring-2"></span>
            <span class="pulse-ring ring-3"></span>
        </div>
        <!-- Constellation lines connecting satellites -->
        <svg class="swarm-constellation" viewBox="0 0 100 100" aria-hidden="true">
            <line class="constellation-line cl-1" x1="50" y1="34" x2="72" y2="28" />
            <line class="constellation-line cl-2" x1="72" y1="28" x2="78" y2="22" />
            <line class="constellation-line cl-3" x1="78" y1="22" x2="84" y2="16" />
            <line class="constellation-line cl-4" x1="50" y1="34" x2="28" y2="28" />
            <line class="constellation-line cl-5" x1="28" y1="28" x2="22" y2="22" />
            <line class="constellation-line cl-6" x1="50" y1="66" x2="65" y2="75" />
            <line class="constellation-line cl-7" x1="65" y1="75" x2="35" y2="75" />
            <line class="constellation-line cl-8" x1="35" y1="75" x2="50" y2="66" />
        </svg>
        <!-- Energy vortex spiral -->
        <div class="energy-vortex" aria-hidden="true">
            <span v-for="n in 12" :key="`vortex-${n}`" class="vortex-particle" :class="`vp-${n}`"></span>
        </div>
        <!-- Lightning web between satellites -->
        <svg class="lightning-web" viewBox="0 0 100 100" aria-hidden="true">
            <path class="lightning-bolt lb-1" d="M 50 35 L 48 38 L 52 40 L 50 50" />
            <path class="lightning-bolt lb-2" d="M 65 42 L 60 44 L 62 48 L 55 50" />
            <path class="lightning-bolt lb-3" d="M 35 42 L 40 44 L 38 48 L 45 50" />
            <path class="lightning-bolt lb-4" d="M 60 65 L 58 60 L 54 58 L 50 55" />
            <path class="lightning-bolt lb-5" d="M 40 65 L 42 60 L 46 58 L 50 55" />
        </svg>
        <!-- Core reactor rotation ring -->
        <svg class="reactor-ring" viewBox="0 0 100 100" aria-hidden="true">
            <circle class="reactor-orbit" cx="50" cy="50" r="20" />
            <circle class="reactor-dot rd-1" cx="50" cy="30" r="2" />
            <circle class="reactor-dot rd-2" cx="70" cy="50" r="1.5" />
            <circle class="reactor-dot rd-3" cx="50" cy="70" r="2" />
            <circle class="reactor-dot rd-4" cx="30" cy="50" r="1.5" />
        </svg>
    </div>
</template>

<style scoped lang="scss">
.swarm-indicator {
    --swarm-accent: var(--vera-accent);
    --swarm-accent-soft: rgba(var(--vera-accent-rgb), 0.35);
    --swarm-status-color: color-mix(in srgb, var(--vera-text-muted) 40%, transparent);
    width: var(--indicator-size);
    height: var(--indicator-size);
    display: grid;
    place-items: center;
    position: relative;
    border-radius: 999px;
}

.swarm-indicator.ok {
    --swarm-status-color: rgba(var(--vera-success-rgb), 0.65);
}

.swarm-indicator.warn {
    --swarm-status-color: rgba(var(--vera-warning-rgb), 0.65);
}

.swarm-indicator.danger {
    --swarm-status-color: rgba(var(--vera-error-rgb), 0.7);
}

.swarm-indicator.neutral {
    --swarm-status-color: color-mix(in srgb, var(--vera-text-muted) 40%, transparent);
}

.state-swarm {
    --swarm-accent: var(--vera-accent);
    --swarm-accent-soft: rgba(var(--vera-accent-rgb), 0.4);
}

.state-quorum {
    --swarm-accent: var(--vera-success);
    --swarm-accent-soft: var(--vera-success-40);
}

.state-error {
    --swarm-accent: var(--vera-danger);
    --swarm-accent-soft: rgba(var(--vera-error-rgb), 0.45);
}

.swarm-glow {
    position: absolute;
    inset: 8%;
    border-radius: 50%;
    background: radial-gradient(circle, var(--swarm-accent-soft) 0%, transparent 70%);
    filter: blur(10px);
    opacity: 0.6;
    z-index: 1;
    pointer-events: none;
    animation: glow-breathe 3.8s ease-in-out infinite;
}

.swarm-status-ring {
    position: absolute;
    inset: 5%;
    border-radius: 50%;
    border: 1px solid var(--swarm-status-color);
    box-shadow: 0 0 12px var(--swarm-status-color);
    opacity: 0.6;
    pointer-events: none;
}

.swarm-core {
    width: 70%;
    height: 70%;
    color: var(--swarm-accent);
    z-index: 2;
    filter: drop-shadow(0 0 8px rgba(var(--vera-shadow-rgb), 0.25)) drop-shadow(0 0 8px var(--swarm-accent-soft));
}

.swarm-orbits {
    position: absolute;
    inset: 0;
    pointer-events: none;
}

.swarm-orbit {
    position: absolute;
    inset: 0;
    opacity: 0.85;
    animation: orbit-spin var(--orbit-duration) linear infinite;
    animation-delay: var(--orbit-delay);
}

.swarm-satellite {
    position: absolute;
    left: 50%;
    top: 50%;
    width: var(--orbit-size);
    height: var(--orbit-size);
    margin-left: calc(var(--orbit-size) * -0.5);
    margin-top: calc(var(--orbit-size) * -0.5);
    transform: translateX(var(--orbit-radius));
    opacity: 0.85;
}

.swarm-satellite-core {
    width: 100%;
    height: 100%;
    background: var(--swarm-accent);
    clip-path: polygon(50% 0%, 100% 70%, 50% 100%, 0% 70%);
    box-shadow: 0 0 6px var(--swarm-accent);
    display: block;
}

.state-idle .swarm-orbit {
    opacity: 0.35;
    animation-duration: calc(var(--orbit-duration) * 1.5);
}

.state-quorum .swarm-orbit {
    opacity: 0.65;
}

.state-swarm .swarm-orbit {
    opacity: 0.95;
}

.state-error .swarm-orbit {
    opacity: 0.95;
    animation: orbit-spin 2.2s linear infinite, orbit-jitter 0.16s steps(2) infinite;
}

.is-active.state-swarm .swarm-satellite,
.is-active.state-quorum .swarm-satellite {
    animation: satellite-consume var(--consume-duration) ease-in-out infinite;
    animation-delay: calc(var(--orbit-delay) * 0.6);
}

.is-active.state-swarm .swarm-core,
.is-active.state-quorum .swarm-core {
    animation: core-absorb calc(var(--consume-duration) * 0.8) ease-in-out infinite;
}

.is-active .swarm-status-ring {
    opacity: 0.9;
}

.is-active .swarm-glow {
    opacity: 0.8;
}

@keyframes orbit-spin {
    from {
        transform: rotate(var(--orbit-rotation)) scaleY(var(--orbit-tilt));
    }
    to {
        transform: rotate(calc(var(--orbit-rotation) + 360deg)) scaleY(var(--orbit-tilt));
    }
}

@keyframes orbit-jitter {
    0% {
        filter: brightness(1);
    }
    50% {
        filter: brightness(1.4);
    }
    100% {
        filter: brightness(1);
    }
}

@keyframes satellite-consume {
    0% {
        transform: translateX(var(--orbit-radius)) scale(0.6);
        opacity: 0;
    }
    18% {
        transform: translateX(var(--orbit-radius)) scale(1);
        opacity: 0.9;
    }
    55% {
        transform: translateX(calc(var(--orbit-radius) * 0.35)) scale(0.8);
        opacity: 0.7;
    }
    78% {
        transform: translateX(0px) scale(0.2);
        opacity: 0;
    }
    100% {
        transform: translateX(0px) scale(0.2);
        opacity: 0;
    }
}

@keyframes core-absorb {
    0%, 100% {
        transform: scale(1);
        filter: drop-shadow(0 0 8px rgba(var(--vera-shadow-rgb), 0.25)) drop-shadow(0 0 8px var(--swarm-accent-soft));
    }
    50% {
        transform: scale(1.06);
        filter: drop-shadow(0 0 10px rgba(var(--vera-shadow-rgb), 0.3)) drop-shadow(0 0 16px var(--swarm-accent-soft));
    }
}

@keyframes glow-breathe {
    0%,
    100% {
        transform: scale(0.96);
        opacity: 0.5;
    }
    50% {
        transform: scale(1.05);
        opacity: 0.75;
    }
}

// ==========================================
// CONNECTION LINES
// ==========================================
.swarm-connections {
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 1;
    opacity: 0;
    transition: opacity 0.5s ease;
}

.connection-line {
    stroke: var(--swarm-accent);
    stroke-width: 0.5;
    stroke-opacity: 0.3;
    stroke-dasharray: 2 4;
    transform-origin: 50px 50px;
    animation: connectionRotate 8s linear infinite;
    animation-delay: var(--line-delay);
}

.is-active .swarm-connections {
    opacity: 1;
}

.is-active .connection-line {
    stroke-opacity: 0.5;
    animation: connectionRotate 4s linear infinite, connectionPulse 1.5s ease-in-out infinite;
    animation-delay: var(--line-delay), var(--line-delay);
}

@keyframes connectionRotate {
    from {
        transform: rotate(0deg);
    }
    to {
        transform: rotate(360deg);
    }
}

@keyframes connectionPulse {
    0%, 100% {
        stroke-opacity: 0.3;
        stroke-width: 0.5;
    }
    50% {
        stroke-opacity: 0.7;
        stroke-width: 1;
    }
}

// ==========================================
// SATELLITE TRAILS
// ==========================================
.swarm-satellite-trail {
    position: absolute;
    width: 200%;
    height: 100%;
    right: 100%;
    top: 0;
    background: linear-gradient(
        90deg,
        transparent 0%,
        var(--swarm-accent-soft) 60%,
        var(--swarm-accent) 100%
    );
    opacity: 0;
    border-radius: 50% 0 0 50%;
    filter: blur(1px);
    transform-origin: right center;
    transition: opacity 0.3s ease;
}

.state-swarm .swarm-satellite-trail,
.state-quorum .swarm-satellite-trail {
    opacity: 0.6;
}

.is-active .swarm-satellite-trail {
    opacity: 0.8;
    width: 300%;
    animation: trailPulse 0.8s ease-in-out infinite;
}

@keyframes trailPulse {
    0%, 100% {
        opacity: 0.6;
        width: 200%;
    }
    50% {
        opacity: 0.9;
        width: 350%;
    }
}

// ==========================================
// SATELLITE OUTER GLOW
// ==========================================
.swarm-satellite-glow {
    position: absolute;
    inset: -50%;
    background: radial-gradient(
        circle,
        var(--swarm-accent) 0%,
        transparent 70%
    );
    opacity: 0;
    filter: blur(3px);
    transition: opacity 0.3s ease;
    animation: glowPulse 1.2s ease-in-out infinite;
}

.is-active .swarm-satellite-glow {
    opacity: 0.7;
}

@keyframes glowPulse {
    0%, 100% {
        transform: scale(1);
        opacity: 0.5;
    }
    50% {
        transform: scale(1.3);
        opacity: 0.8;
    }
}

// ==========================================
// PULSE RINGS
// ==========================================
.swarm-pulse-rings {
    position: absolute;
    inset: 0;
    pointer-events: none;
    display: grid;
    place-items: center;
    z-index: 0;
    opacity: 0;
    transition: opacity 0.3s ease;
}

.is-active .swarm-pulse-rings {
    opacity: 1;
}

.pulse-ring {
    position: absolute;
    border-radius: 50%;
    border: 1px solid var(--swarm-accent);
    opacity: 0;
    animation: pulseRingExpand 2s ease-out infinite;

    &.ring-1 {
        width: 30%;
        height: 30%;
        animation-delay: 0s;
    }

    &.ring-2 {
        width: 30%;
        height: 30%;
        animation-delay: 0.66s;
    }

    &.ring-3 {
        width: 30%;
        height: 30%;
        animation-delay: 1.33s;
    }
}

.state-swarm .pulse-ring {
    animation-duration: 1s;
}

@keyframes pulseRingExpand {
    0% {
        transform: scale(1);
        opacity: 0.8;
        border-width: 2px;
    }
    100% {
        transform: scale(3);
        opacity: 0;
        border-width: 0.5px;
    }
}

// ==========================================
// ENHANCED CORE EFFECTS
// ==========================================
.is-active.state-swarm .swarm-core,
.is-active.state-quorum .swarm-core {
    filter:
        drop-shadow(0 0 8px rgba(var(--vera-shadow-rgb), 0.25))
        drop-shadow(0 0 12px var(--swarm-accent-soft))
        drop-shadow(0 0 20px var(--swarm-accent-soft));
}

.state-swarm .swarm-status-ring {
    animation: statusRingPulse 0.6s ease-in-out infinite;
}

.state-quorum .swarm-status-ring {
    animation: statusRingPulse 1.2s ease-in-out infinite;
}

@keyframes statusRingPulse {
    0%, 100% {
        box-shadow: 0 0 12px var(--swarm-status-color);
        opacity: 0.6;
    }
    50% {
        box-shadow: 0 0 20px var(--swarm-status-color), 0 0 30px var(--swarm-status-color);
        opacity: 0.9;
    }
}

// ==========================================
// IDLE STATE ENHANCEMENTS
// ==========================================
.state-idle .swarm-glow {
    animation: idleGlow 4s ease-in-out infinite;
}

.state-idle .swarm-status-ring {
    animation: idleRingBreath 3s ease-in-out infinite;
}

@keyframes idleGlow {
    0%, 100% {
        opacity: 0.3;
        transform: scale(0.95);
    }
    50% {
        opacity: 0.5;
        transform: scale(1);
    }
}

@keyframes idleRingBreath {
    0%, 100% {
        opacity: 0.4;
    }
    50% {
        opacity: 0.6;
    }
}

// ==========================================
// CONSTELLATION LINES
// ==========================================
.swarm-constellation {
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 1;
    opacity: 0;
    transition: opacity 0.5s ease;
}

.constellation-line {
    stroke: var(--swarm-accent);
    stroke-width: 0.5;
    stroke-opacity: 0;
    stroke-linecap: round;
    filter: drop-shadow(0 0 2px var(--swarm-accent));
}

.state-quorum .swarm-constellation,
.state-swarm .swarm-constellation {
    opacity: 1;
}

.state-quorum .constellation-line,
.state-swarm .constellation-line {
    stroke-opacity: 0.4;
    animation: constellationPulse 2s ease-in-out infinite;
}

.is-active .constellation-line {
    stroke-opacity: 0.7;
    stroke-width: 1;
    animation: constellationFlow 1s ease-in-out infinite;
}

.constellation-line.cl-1 { animation-delay: 0.15s; }
.constellation-line.cl-2 { animation-delay: 0.3s; }
.constellation-line.cl-3 { animation-delay: 0.45s; }
.constellation-line.cl-4 { animation-delay: 0.6s; }
.constellation-line.cl-5 { animation-delay: 0.75s; }
.constellation-line.cl-6 { animation-delay: 0.9s; }
.constellation-line.cl-7 { animation-delay: 1.05s; }
.constellation-line.cl-8 { animation-delay: 1.2s; }

@keyframes constellationPulse {
    0%, 100% {
        stroke-opacity: 0.3;
        filter: drop-shadow(0 0 2px var(--swarm-accent));
    }
    50% {
        stroke-opacity: 0.6;
        filter: drop-shadow(0 0 4px var(--swarm-accent));
    }
}

@keyframes constellationFlow {
    0%, 100% {
        stroke-opacity: 0.5;
        stroke-dasharray: none;
    }
    50% {
        stroke-opacity: 0.9;
        stroke-dasharray: 4 2;
    }
}

// ==========================================
// ENERGY VORTEX
// ==========================================
.energy-vortex {
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 2;
    opacity: 0;
    transition: opacity 0.3s ease;
}

.vortex-particle {
    position: absolute;
    left: 50%;
    top: 50%;
    width: 3px;
    height: 3px;
    margin: -1.5px;
    background: var(--swarm-accent);
    border-radius: 50%;
    opacity: 0;
    box-shadow: 0 0 4px var(--swarm-accent);
}

.vortex-particle.vp-1 { animation: vortexSpiral1 1.5s ease-in infinite; animation-delay: 0.12s; }
.vortex-particle.vp-2 { animation: vortexSpiral2 1.8s ease-in infinite; animation-delay: 0.24s; }
.vortex-particle.vp-3 { animation: vortexSpiral3 2.1s ease-in infinite; animation-delay: 0.36s; }
.vortex-particle.vp-4 { animation: vortexSpiral1 1.5s ease-in infinite; animation-delay: 0.48s; }
.vortex-particle.vp-5 { animation: vortexSpiral2 1.8s ease-in infinite; animation-delay: 0.6s; }
.vortex-particle.vp-6 { animation: vortexSpiral3 2.1s ease-in infinite; animation-delay: 0.72s; }
.vortex-particle.vp-7 { animation: vortexSpiral1 1.5s ease-in infinite; animation-delay: 0.84s; }
.vortex-particle.vp-8 { animation: vortexSpiral2 1.8s ease-in infinite; animation-delay: 0.96s; }
.vortex-particle.vp-9 { animation: vortexSpiral3 2.1s ease-in infinite; animation-delay: 1.08s; }
.vortex-particle.vp-10 { animation: vortexSpiral1 1.5s ease-in infinite; animation-delay: 1.2s; }
.vortex-particle.vp-11 { animation: vortexSpiral2 1.8s ease-in infinite; animation-delay: 1.32s; }
.vortex-particle.vp-12 { animation: vortexSpiral3 2.1s ease-in infinite; animation-delay: 1.44s; }

@keyframes vortexSpiral1 {
    0% {
        transform: rotate(0deg) translateX(45px) scale(1.2);
        opacity: 0;
    }
    20% {
        opacity: 0.8;
    }
    80% {
        opacity: 0.6;
    }
    100% {
        transform: rotate(540deg) translateX(0px) scale(0);
        opacity: 0;
    }
}

@keyframes vortexSpiral2 {
    0% {
        transform: rotate(120deg) translateX(40px) scale(1);
        opacity: 0;
    }
    15% {
        opacity: 0.7;
    }
    85% {
        opacity: 0.5;
    }
    100% {
        transform: rotate(600deg) translateX(0px) scale(0);
        opacity: 0;
    }
}

@keyframes vortexSpiral3 {
    0% {
        transform: rotate(240deg) translateX(50px) scale(0.8);
        opacity: 0;
    }
    25% {
        opacity: 0.9;
    }
    75% {
        opacity: 0.4;
    }
    100% {
        transform: rotate(720deg) translateX(0px) scale(0);
        opacity: 0;
    }
}

.is-active.state-swarm .energy-vortex,
.is-active.state-quorum .energy-vortex {
    opacity: 1;
}

.state-swarm .vortex-particle {
    animation-duration: 0.8s;
    box-shadow: 0 0 6px var(--swarm-accent), 0 0 10px var(--swarm-accent-soft);
}

.state-quorum .vortex-particle {
    animation-duration: 1.2s;
}

// ==========================================
// LIGHTNING WEB
// ==========================================
.lightning-web {
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 3;
    opacity: 0;
    transition: opacity 0.2s ease;
}

.lightning-bolt {
    fill: none;
    stroke: var(--swarm-accent);
    stroke-width: 1.5;
    stroke-linecap: round;
    stroke-linejoin: round;
    filter: drop-shadow(0 0 3px var(--swarm-accent));
    stroke-dasharray: 50;
    stroke-dashoffset: 50;
    opacity: 0;
}

.state-swarm .lightning-web {
    opacity: 1;
}

.state-swarm .lightning-bolt {
    animation: lightningStrike 0.4s ease-out infinite;
}

.lightning-bolt.lb-1 { animation-delay: 0.08s; }
.lightning-bolt.lb-2 { animation-delay: 0.16s; }
.lightning-bolt.lb-3 { animation-delay: 0.24s; }
.lightning-bolt.lb-4 { animation-delay: 0.32s; }
.lightning-bolt.lb-5 { animation-delay: 0.4s; }

@keyframes lightningStrike {
    0% {
        stroke-dashoffset: 50;
        opacity: 0;
    }
    15% {
        stroke-dashoffset: 0;
        opacity: 1;
    }
    30% {
        stroke-dashoffset: 0;
        opacity: 0.9;
        filter: drop-shadow(0 0 6px var(--swarm-accent)) brightness(1.5);
    }
    50% {
        stroke-dashoffset: -50;
        opacity: 0.3;
    }
    100% {
        stroke-dashoffset: -50;
        opacity: 0;
    }
}

.is-active.state-swarm .lightning-bolt {
    animation-duration: 0.25s;
    stroke-width: 2;
}

.state-error .lightning-web {
    opacity: 1;
}

.state-error .lightning-bolt {
    stroke: var(--swarm-accent);
    animation: lightningStrike 0.15s ease-out infinite;
}

// ==========================================
// REACTOR RING
// ==========================================
.reactor-ring {
    position: absolute;
    inset: 15%;
    pointer-events: none;
    z-index: 1;
    opacity: 0;
    transition: opacity 0.3s ease;
    animation: reactorSpin 8s linear infinite;
}

.reactor-orbit {
    fill: none;
    stroke: var(--swarm-accent);
    stroke-width: 0.5;
    stroke-opacity: 0.3;
    stroke-dasharray: 3 6;
}

.reactor-dot {
    fill: var(--swarm-accent);
    filter: drop-shadow(0 0 3px var(--swarm-accent));
    opacity: 0.7;
}

.state-quorum .reactor-ring,
.state-swarm .reactor-ring {
    opacity: 1;
}

.is-active .reactor-ring {
    animation-duration: 3s;
}

.is-active .reactor-orbit {
    stroke-opacity: 0.6;
    stroke-width: 1;
    animation: reactorOrbitPulse 0.8s ease-in-out infinite;
}

.is-active .reactor-dot {
    opacity: 1;
    animation: reactorDotPulse 0.5s ease-in-out infinite;
}

@keyframes reactorSpin {
    from {
        transform: rotate(0deg);
    }
    to {
        transform: rotate(360deg);
    }
}

@keyframes reactorOrbitPulse {
    0%, 100% {
        stroke-opacity: 0.4;
        stroke-dasharray: 3 6;
    }
    50% {
        stroke-opacity: 0.8;
        stroke-dasharray: 6 3;
    }
}

@keyframes reactorDotPulse {
    0%, 100% {
        transform: scale(1);
        filter: drop-shadow(0 0 3px var(--swarm-accent));
    }
    50% {
        transform: scale(1.5);
        filter: drop-shadow(0 0 6px var(--swarm-accent)) drop-shadow(0 0 10px var(--swarm-accent-soft));
    }
}

.state-swarm .reactor-ring {
    animation-duration: 2s;
}

.state-swarm.is-active .reactor-ring {
    animation-duration: 1s;
}

.state-swarm .reactor-dot {
    animation: reactorDotPulse 0.3s ease-in-out infinite;
}

// ==========================================
// ENHANCED SATELLITE TRAILS
// ==========================================
.swarm-satellite-trail {
    position: absolute;
    width: 200%;
    height: 100%;
    right: 100%;
    top: 0;
    background: linear-gradient(
        90deg,
        transparent 0%,
        var(--swarm-accent-soft) 60%,
        var(--swarm-accent) 100%
    );
    opacity: 0;
    border-radius: 50% 0 0 50%;
    filter: blur(1px);
    transform-origin: right center;
    transition: opacity 0.3s ease;
}

// Trail particle breakup effect
.swarm-satellite::after {
    content: '';
    position: absolute;
    right: 100%;
    top: 50%;
    width: 30px;
    height: 2px;
    transform: translateY(-50%);
    background: linear-gradient(
        90deg,
        transparent 0%,
        var(--swarm-accent) 20%,
        transparent 40%,
        var(--swarm-accent) 50%,
        transparent 70%,
        var(--swarm-accent) 80%,
        transparent 100%
    );
    opacity: 0;
    filter: blur(0.5px);
    transition: opacity 0.3s ease;
}

.is-active .swarm-satellite::after {
    opacity: 0.6;
    animation: trailBreakup 0.4s ease-in-out infinite;
}

@keyframes trailBreakup {
    0%, 100% {
        opacity: 0.4;
        width: 25px;
    }
    50% {
        opacity: 0.8;
        width: 40px;
    }
}

.state-swarm .swarm-satellite::after {
    background: linear-gradient(
        90deg,
        transparent 0%,
        var(--swarm-accent) 15%,
        transparent 30%,
        var(--swarm-accent) 40%,
        transparent 55%,
        var(--swarm-accent) 65%,
        transparent 80%,
        var(--swarm-accent) 90%,
        transparent 100%
    );
    width: 50px;
}

// ==========================================
// ENHANCED CORE EFFECTS
// ==========================================
.swarm-core {
    transition: filter 0.3s ease;
}

.is-active.state-swarm .swarm-core {
    animation: coreReactorPulse 0.5s ease-in-out infinite;
}

.is-active.state-quorum .swarm-core {
    animation: coreReactorPulse 0.8s ease-in-out infinite;
}

@keyframes coreReactorPulse {
    0%, 100% {
        transform: scale(1) rotate(0deg);
        filter:
            drop-shadow(0 0 8px rgba(var(--vera-shadow-rgb), 0.25))
            drop-shadow(0 0 12px var(--swarm-accent-soft));
    }
    25% {
        transform: scale(1.02) rotate(0.5deg);
    }
    50% {
        transform: scale(1.05) rotate(0deg);
        filter:
            drop-shadow(0 0 10px rgba(var(--vera-shadow-rgb), 0.3))
            drop-shadow(0 0 20px var(--swarm-accent-soft))
            drop-shadow(0 0 30px var(--swarm-accent-soft));
    }
    75% {
        transform: scale(1.02) rotate(-0.5deg);
    }
}

// Core inner glow effect
.swarm-core::after {
    content: '';
    position: absolute;
    inset: 30%;
    background: radial-gradient(
        circle,
        var(--swarm-accent) 0%,
        transparent 70%
    );
    opacity: 0;
    filter: blur(5px);
    transition: opacity 0.3s ease;
    animation: coreInnerGlow 1.5s ease-in-out infinite;
}

.is-active .swarm-core::after {
    opacity: 0.5;
}

@keyframes coreInnerGlow {
    0%, 100% {
        opacity: 0.3;
        transform: scale(0.8);
    }
    50% {
        opacity: 0.6;
        transform: scale(1.2);
    }
}

@media (prefers-reduced-motion: reduce) {
    .swarm-glow,
    .swarm-orbit,
    .swarm-satellite,
    .swarm-core,
    .connection-line,
    .swarm-satellite-trail,
    .swarm-satellite-glow,
    .pulse-ring,
    .swarm-status-ring,
    .constellation-line,
    .vortex-particle,
    .lightning-bolt,
    .reactor-ring,
    .reactor-dot {
        animation: none;
    }
}
</style>
