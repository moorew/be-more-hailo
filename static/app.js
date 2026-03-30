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

class BMOFaceRenderer {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.width = canvas.width;
        this.height = canvas.height;
        this.ctx.imageSmoothingEnabled = true;
        this.ctx.imageSmoothingQuality = 'high';
        this.colors = { bg: '#bdffcb', line: '#000000', mouthDark: '#298339', tongue: '#70c370', teeth: '#ffffff', pink: '#ff8cbc' };
        this.eyeY = 195; this.leftEyeX = 217; this.rightEyeX = 581; this.eyeR = 18; this.mouthY = 302; this.mouthW = 97;
        this.state = 'idle'; this.frame = 0; this.blink = 0; this.eyeOffsetX = 0; this.eyeOffsetY = 0; this.mouthOpen = 0;
        this.speakingShapes = [[0, 97], [20, 80], [35, 70], [50, 60], [25, 85], [45, 65], [0, 97], [30, 75], [55, 55], [20, 90], [40, 70], [25, 80], [0, 97], [30, 80], [45, 60], [35, 75], [0, 97]];
    }
    clear() { this.ctx.fillStyle = this.colors.bg; this.ctx.fillRect(0, 0, this.width, this.height); }
    drawArc(cx, cy, r, s, e, w = 12) { this.ctx.beginPath(); this.ctx.arc(cx, cy, r, s, e); this.ctx.strokeStyle = this.colors.line; this.ctx.lineWidth = w; this.ctx.lineCap = 'round'; this.ctx.stroke(); }
    drawCircle(cx, cy, r, f = true) { this.ctx.beginPath(); this.ctx.arc(cx, cy, r, 0, Math.PI * 2); if (f) { this.ctx.fillStyle = this.colors.line; this.ctx.fill(); } else { this.ctx.strokeStyle = this.colors.line; this.ctx.lineWidth = 12; this.ctx.stroke(); } }
    drawLine(x1, y1, x2, y2, w = 12) { this.ctx.beginPath(); this.ctx.moveTo(x1, y1); this.ctx.lineTo(x2, y2); this.ctx.strokeStyle = this.colors.line; this.ctx.lineWidth = w; this.ctx.lineCap = 'round'; this.ctx.stroke(); }
    drawMouth(type, h = 0, w = this.mouthW) {
        const cx = this.width / 2, cy = this.mouthY, hw = w / 2;
        this.ctx.lineWidth = 12; this.ctx.strokeStyle = this.colors.line; this.ctx.lineCap = 'round';
        if (type === 'straight' || (type === 'speaking' && h === 0)) { this.drawLine(cx - hw, cy, cx + hw, cy); }
        else if (type === 'smile') { this.ctx.beginPath(); this.ctx.arc(cx, cy - 25, hw, Math.PI * 0.15, Math.PI * 0.85); this.ctx.stroke(); }
        else if (type === 'frown') { this.ctx.beginPath(); this.ctx.arc(cx, cy + 15, hw, Math.PI * 1.15, Math.PI * 1.85); this.ctx.stroke(); }
        else if (type === 'speaking') {
            const r = h / 2; this.ctx.beginPath(); this.ctx.roundRect(cx - hw, cy - r, w, h, r);
            this.ctx.fillStyle = this.colors.mouthDark; this.ctx.fill(); this.ctx.stroke();
            if (h > 25) { this.ctx.fillStyle = this.colors.teeth; this.ctx.beginPath(); this.ctx.roundRect(cx - hw + 10, cy - r + 5, w - 20, h / 4, 4); this.ctx.fill(); }
            if (h > 40) { this.ctx.fillStyle = this.colors.tongue; this.ctx.beginPath(); this.ctx.ellipse(cx, cy + r - 8, hw - 15, h / 4, 0, 0, Math.PI * 2); this.ctx.fill(); }
        }
    }
    render() {
        this.clear(); const frame = this.frame++;
        let eyeType = 'regular', mouthType = 'straight', curH = 0, curW = this.mouthW;
        if (!['sleepy', 'thinking', 'listening'].includes(this.state)) {
            if (frame % 150 < 5) this.blink = 1; else if (frame % 150 < 8) this.blink = 0.5; else this.blink = 0;
        } else if (this.state === 'sleepy') this.blink = 1;
        if (this.state === 'idle') {
            const m = frame % 300; if (m < 50) this.eyeOffsetX = -10; else if (m < 100) this.eyeOffsetX = 0; else if (m < 150) this.eyeOffsetX = 10; else this.eyeOffsetX = 0;
        } else if (this.state === 'thinking') { this.eyeOffsetX = Math.sin(frame * 0.4) * 15; }
        else if (this.state === 'listening') { this.eyePulseR = Math.sin(frame * 0.2) * 2; eyeType = 'circle'; }
        else if (this.state === 'speaking') {
            eyeType = 'circle'; mouthType = 'speaking';
            // True lip-sync mapping: Map mouthOpen intensity to physical height/width
            // Scale the mouth up/down based on instantaneous volume
            if (this.mouthOpen > 0.5) {
                curH = Math.min(65, this.mouthOpen * 1.5);
                curW = Math.min(105, 80 + (this.mouthOpen * 0.5));
            } else {
                curH = 0; curW = this.mouthW;
            }
        }
        switch (this.state) {
            case 'happy': eyeType = 'happy'; mouthType = 'smile'; break;
            case 'sad': eyeType = 'sad'; mouthType = 'frown'; break;
            case 'angry': eyeType = 'angry'; mouthType = 'straight'; break;
            case 'surprised': eyeType = 'circle'; mouthType = 'speaking'; curH = 40; curW = 60; break;
            case 'heart': eyeType = 'heart'; mouthType = 'smile'; break;
            case 'starry_eyed': eyeType = 'star'; mouthType = 'smile'; break;
            case 'sleepy': eyeType = 'closed'; break;
            case 'daydream': eyeType = 'regular'; this.eyeOffsetY = -10; break;
            case 'football': eyeType = 'happy'; mouthType = 'smile'; break;
            case 'bee': eyeType = 'circle'; mouthType = 'speaking'; curH = 20; break;
        }
        const drawE = (x, y) => {
            let r = this.eyeR; if (this.state === 'listening') r += this.eyePulseR;
            if (this.blink >= 0.9 || eyeType === 'closed') this.drawLine(x - r, y, x + r, y);
            else if (this.blink > 0) this.drawArc(x, y, r, -0.2, Math.PI + 0.2);
            else if (eyeType === 'happy') this.drawArc(x, y + 10, r, Math.PI, Math.PI * 2);
            else if (eyeType === 'circle') this.drawCircle(x, y, r - 2);
            else if (eyeType === 'sad') this.drawLine(x - 15, y + 10, x + 15, y - 5);
            else if (eyeType === 'angry') this.drawLine(x - 15, y - 5, x + 15, y + 10);
            else this.drawArc(x, y, r, -0.4, Math.PI + 0.4);
        };
        drawE(this.leftEyeX + this.eyeOffsetX, this.eyeY + this.eyeOffsetY);
        drawE(this.rightEyeX + this.eyeOffsetX, this.eyeY + this.eyeOffsetY);
        this.drawMouth(mouthType, curH, curW);
        requestAnimationFrame(() => this.render());
    }
}

const bmoRenderer = new BMOFaceRenderer(faceCanvas);
bmoRenderer.render();

let conversationHistory = []; let currentAudio = null; let soundFiles = {}; let isRecording = false;
let screensaverActive = false; let currentMood = 'neutral'; let lastMoodChange = 0;
const MOOD_DURATION = 300000;
const EXPRESSIONS = { happy: ['happy', 'heart', 'football'], neutral: ['idle', 'detective', 'sir_mano', 'bee'], sad: ['sad'], sleepy: ['sleepy', 'daydream'] };

function setFaceState(s) {
    bmoRenderer.state = s;
    if (s !== 'speaking') bmoRenderer.mouthOpen = 0;
    if (s !== 'bee') bmoRenderer.eyeOffsetX = 0;
    bmoRenderer.eyeOffsetY = 0;
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

// Audio Visualizer for Mouth Sync
let audioContext, analyser, dataArray;
function setupVisualizer(audioElement) {
    if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioElement._v) return;
    audioElement._v = true;

    const source = audioContext.createMediaElementSource(audioElement);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    analyser.connect(audioContext.destination);
    dataArray = new Uint8Array(analyser.frequencyBinCount);

    function syncMouth() {
        if (bmoRenderer.state === 'speaking' && !audioElement.paused) {
            analyser.getByteTimeDomainData(dataArray);
            let sum = 0;
            for (let i = 0; i < dataArray.length; i++) {
                sum += Math.abs(dataArray[i] - 128);
            }
            bmoRenderer.mouthOpen = (sum / dataArray.length) * 4;
            requestAnimationFrame(syncMouth);
        }
    }
    syncMouth();
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
