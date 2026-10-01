// BMO Web App Logic
const chatHistory = document.getElementById('chat-history');
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const micBtn = document.getElementById('mic-btn');
const faceCanvas = document.getElementById('bmo-face-canvas');
const audioToggle = document.getElementById('audio-toggle');
const handsFreeToggle = document.getElementById('hands-free-toggle');
const bmoTranscript = document.getElementById('bmo-transcript');
const bmoDisplayImage = document.getElementById('bmo-display-image');

// Face: live rig (static/face/bmo-face.js) that morphs BMO's own artwork and
// reads mouth shapes from the voice. Same interface as the old renderer:
// bmoRenderer.state and setFaceState().
const RIG_EXPRESSIONS = {
    idle: 'idle', listening: 'listening', thinking: 'thinking', speaking: 'idle',
    happy: 'happy', sad: 'sad', angry: 'angry', surprised: 'surprised', sleepy: 'sleepy',
    daydream: 'daydream', football: 'football', heart: 'heart', starry_eyed: 'starry',
    error: 'error', detective: 'detective', sir_mano: 'sir_mano', bee: 'bee',
    dizzy: 'dizzy', cheeky: 'cheeky', confused: 'confused', shhh: 'shhh', jamming: 'jamming',
    low_battery: 'low_battery', bored: 'bored', curious: 'curious', capturing: 'capturing',
    ladybug: 'ladybug', worm: 'worm',
};
const SILENT = { viseme: 'X', intensity: 0, active: false, onset: false };

class BMOFaceRenderer {
    constructor(canvas) {
        this.canvas = canvas;
        this.state = 'idle';
        this.rig = null;
        this.lip = null; // BMOFace.AudioLipSync, created with the AudioContext
        Promise.all(['/static/face/shapes.json', '/static/face/expressions.json'].map((u) => fetch(u).then((r) => r.json())))
            .then(([shapes, presets]) => {
                this.rig = new BMOFace.FaceRig(shapes, presets);
                this.renderer = new BMOFace.CanvasRenderer(canvas, shapes, 'stretch');
                this.setState(this.state);
                this.rig.playIntro();
                let last = performance.now();
                const loop = (now) => {
                    this.tick(Math.min(0.1, (now - last) / 1000));
                    last = now;
                    requestAnimationFrame(loop);
                };
                requestAnimationFrame(loop);
            })
            .catch((err) => console.error('BMO face failed to load:', err));
    }
    setState(s) {
        this.state = s;
        if (this.rig) this.rig.setExpression(RIG_EXPRESSIONS[s] || 'idle');
    }
    tick(dt) {
        const talking = this.state === 'speaking' && this.lip;
        this.rig.setSpeech(talking ? this.lip.tick(dt) : SILENT);
        this.rig.update(dt);
        this.renderer.draw(this.rig.frame());
    }
}

const bmoRenderer = new BMOFaceRenderer(faceCanvas);

let conversationHistory = []; let currentAudio = null; let soundFiles = {}; let isRecording = false;
let screensaverActive = false; let currentMood = 'neutral'; let lastMoodChange = 0;
const MOOD_DURATION = 300000;
const EXPRESSIONS = { happy: ['happy', 'heart', 'football'], neutral: ['idle', 'detective', 'sir_mano', 'bee'], sad: ['sad'], sleepy: ['sleepy', 'daydream'] };

function setFaceState(s) {
    bmoRenderer.setState(s);
}

// Audio Recording Logic
let mediaRecorder;
let audioChunks = [];

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];
        mediaRecorder.ondataavailable = (event) => audioChunks.push(event.data);
        mediaRecorder.onstop = async () => {
            const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
            sendAudioToBMO(audioBlob);
        };
        mediaRecorder.start();
        isRecording = true;
        micBtn.classList.add('recording');
        setFaceState('listening');
    } catch (err) {
        console.error("Error accessing microphone:", err);
        addMessage("I can't hear you! Please check microphone permissions.", 'system');
    }
}

function stopRecording() {
    if (mediaRecorder && isRecording) {
        mediaRecorder.stop();
        isRecording = false;
        micBtn.classList.remove('recording');
        setFaceState('thinking');
    }
}

async function sendAudioToBMO(blob) {
    const formData = new FormData();
    formData.append('audio', blob);
    try {
        const response = await fetch('/api/transcribe', { method: 'POST', body: formData });
        const data = await response.json();
        if (data.text) {
            userInput.value = data.text;
            sendMessage();
        } else {
            setFaceState('idle');
        }
    } catch (err) {
        console.error("Transcription error:", err);
        setFaceState('error');
    }
}

// Chat Logic
async function sendMessage() {
    const text = userInput.value.trim();
    if (!text) return;

    userInput.value = '';
    addMessage(text, 'user');
    setFaceState('thinking');

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: text,
                history: conversationHistory,
                play_on_hardware: audioToggle.checked
            })
        });

        const data = await response.json();
        if (data.response) {
            addMessage(marked.parse(data.response), 'bmo', true);
            conversationHistory = data.history;

            if (data.audio_url && !audioToggle.checked) {
                setFaceState('speaking');
                if (currentAudio) currentAudio.pause();
                currentAudio = new Audio(data.audio_url);
                setupVisualizer(currentAudio);
                currentAudio.onended = () => {
                    setFaceState('idle');
                    if (handsFreeToggle.checked) {
                        setTimeout(startRecording, 500);
                    }
                };
                currentAudio.play();
            } else {
                setFaceState('idle');
            }
        }
    } catch (err) {
        console.error("Chat error:", err);
        setFaceState('error');
    }
}

function addMessage(text, sender, html = false) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${sender}-message`;
    if (html) {
        msgDiv.innerHTML = text;
    } else {
        msgDiv.textContent = text;
    }
    chatHistory.appendChild(msgDiv);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

// Lip-sync: route BMO's reply audio through the rig's analyser.
let audioContext;
function setupVisualizer(audioElement) {
    if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        bmoRenderer.lip = new BMOFace.AudioLipSync(audioContext);
        bmoRenderer.lip.node.connect(audioContext.destination);
    }
    if (audioElement._v) return;
    audioElement._v = true;
    audioContext.resume();
    audioContext.createMediaElementSource(audioElement).connect(bmoRenderer.lip.node);
}

// Screensaver Logic
let screensaverTimer;
function resetScreensaverTimer() {
    clearTimeout(screensaverTimer);
    if (screensaverActive) {
        screensaverActive = false;
        stopScreensaverThoughts();
        setFaceState('idle');
    }
    screensaverTimer = setTimeout(startScreensaver, 60000);
}

function startScreensaver() {
    screensaverActive = true;
    playScreensaverSequence();
    startScreensaverThoughts();
}

let screensaverThoughtInterval;
async function startScreensaverThoughts() {
    if (screensaverThoughtInterval) clearInterval(screensaverThoughtInterval);
    const fetchThought = async () => {
        if (!screensaverActive) return;
        try {
            const r = await fetch('/api/screensaver-thought');
            const d = await r.json();
            if (d.thought && screensaverActive) {
                bmoTranscript.textContent = d.thought;
                if (d.image_url) {
                    bmoDisplayImage.src = d.image_url;
                    bmoDisplayImage.style.display = 'block';
                    setTimeout(() => { if (screensaverActive) bmoDisplayImage.style.display = 'none'; }, 15000);
                }
                setTimeout(() => { if (screensaverActive) bmoTranscript.textContent = ''; }, 12000);
            }
        } catch (e) { }
    };
    fetchThought();
    screensaverThoughtInterval = setInterval(fetchThought, 45000);
}

function stopScreensaverThoughts() {
    clearInterval(screensaverThoughtInterval);
    bmoTranscript.textContent = '';
    bmoDisplayImage.style.display = 'none';
}

function playScreensaverSequence() {
    if (!screensaverActive) return;
    const now = Date.now();
    if (now - lastMoodChange > MOOD_DURATION) {
        currentMood = Object.keys(EXPRESSIONS)[Math.floor(Math.random() * Object.keys(EXPRESSIONS).length)];
        lastMoodChange = now;
    }
    const possible = EXPRESSIONS[currentMood] || EXPRESSIONS.neutral;
    setFaceState(possible[Math.floor(Math.random() * possible.length)]);
    setTimeout(playScreensaverSequence, 8000 + Math.random() * 4000);
}

// Status Checking
async function checkStatus() {
    try {
        const r = await fetch('/api/status');
        const d = await r.json();
        const dot = document.getElementById('status-dot');
        const text = document.getElementById('status-text');
        if (d.status === 'online') {
            dot.style.backgroundColor = '#58d68d';
            text.textContent = 'LLM: Online';
        } else {
            dot.style.backgroundColor = '#e74c3c';
            text.textContent = 'LLM: Offline';
        }
    } catch (e) { }
}

// Pronunciation Modal
window.openPronunciationModal = () => document.getElementById('pronunciation-modal').style.display = 'flex';
window.closePronunciationModal = () => document.getElementById('pronunciation-modal').style.display = 'none';
window.savePronunciation = async () => {
    const word = document.getElementById('pronounce-word').value;
    const phonetic = document.getElementById('pronounce-phonetic').value;
    if (!word || !phonetic) return;
    await fetch('/api/pronunciation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ word, phonetic })
    });
    window.closePronunciationModal();
};

// Initialization
function init() {
    micBtn.addEventListener('mousedown', startRecording);
    micBtn.addEventListener('mouseup', stopRecording);
    micBtn.addEventListener('touchstart', (e) => { e.preventDefault(); startRecording(); });
    micBtn.addEventListener('touchend', (e) => { e.preventDefault(); stopRecording(); });

    sendBtn.addEventListener('click', sendMessage);
    userInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendMessage(); });

    document.addEventListener('mousemove', resetScreensaverTimer);
    document.addEventListener('keypress', resetScreensaverTimer);
    document.addEventListener('touchstart', resetScreensaverTimer);

    checkStatus();
    setInterval(checkStatus, 30000);
    resetScreensaverTimer();
}

window.addEventListener('DOMContentLoaded', init);
