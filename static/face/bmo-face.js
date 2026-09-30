/*!
 * bmo-face.js - procedural face rig for BMO (be-more-hailo).
 *
 * Instead of swapping between pre-rendered frames, every mouth and eye pose
 * from the artwork is stored as a morph-compatible contour (shapes.json) and
 * the rig blends between them with springs. On top of that sit small
 * "behaviour" layers: blinks, glances, breathing, and speech-driven head bob,
 * so BMO feels alive between words as well as during them.
 *
 * The lip-sync analyser looks at the audio spectrum (not just loudness) to
 * pick Rhubarb-style mouth shapes: A/X closed, B teeth, C/D open, E/F round.
 *
 * python/bmo_face/ mirrors this file 1:1 for the Raspberry Pi build.
 */
(function (global) {
  'use strict';

  // ---------------------------------------------------------------- helpers
  const clamp = (v, lo = 0, hi = 1) => (v < lo ? lo : v > hi ? hi : v);
  const lerp = (a, b, t) => a + (b - a) * t;
  const rand = (a, b) => a + Math.random() * (b - a);
  const easeInQuad = (t) => t * t;
  const easeInOutSine = (t) => 0.5 - 0.5 * Math.cos(Math.PI * t);

  /** Damped spring. freq in Hz, damping 1 = critical (no overshoot). */
  class Spring {
    constructor(value = 0, freq = 5, damping = 0.9) {
      this.value = value;
      this.target = value;
      this.velocity = 0;
      this.freq = freq;
      this.damping = damping;
    }
    step(dt) {
      const w = 2 * Math.PI * this.freq;
      const n = Math.max(1, Math.ceil((dt * w) / 0.3)); // keep semi-implicit Euler stable
      const h = dt / n;
      for (let i = 0; i < n; i++) {
        const a = w * w * (this.target - this.value) - 2 * this.damping * w * this.velocity;
        this.velocity += a * h;
        this.value += this.velocity * h;
      }
      return this.value;
    }
    snap(v = this.target) {
      this.value = this.target = v;
      this.velocity = 0;
    }
  }

  // ------------------------------------------------------------ expressions
  // Presets live in expressions.json (shared with the Python rig).
  const NO_LID_Y = -95;

  function resolveExpression(presets, name) {
    const e = presets.expressions[name] || presets.expressions.idle || {};
    const d = presets.default;
    const pick = (k) => (e[k] !== undefined ? e[k] : d[k]);
    return {
      name,
      mouth: pick('mouth'),
      mouthMods: { ...d.mouthMods, ...(e.mouthMods || {}) },
      talk: { ...d.talk, ...(e.talk || {}) },
      eye: pick('eye'),
      eyeScale: pick('eyeScale'),
      eyeOffset: pick('eyeOffset'),
      lid: { ...d.lid, ...(e.lid || {}) },
      brows: pick('brows'),
      blush: pick('blush'),
      gaze: pick('gaze'),
      blink: pick('blink'),
      motion: pick('motion'),
      head: { ...d.head, ...(e.head || {}) },
      breathe: pick('breathe'),
      enter: pick('enter'),
    };
  }

  // ------------------------------------------------------------- behaviours
  const BLINK_MODES = {
    //          interval range   close  hold  open   double-blink chance
    normal:    { every: [2.2, 5.5], c: 0.06, h: 0.04, o: 0.12, dbl: 0.18 },
    attentive: { every: [3.0, 6.5], c: 0.055, h: 0.03, o: 0.11, dbl: 0.1 },
    slow:      { every: [3.0, 6.0], c: 0.1, h: 0.08, o: 0.22, dbl: 0.05 },
    sleepy:    { every: [1.4, 3.2], c: 0.16, h: 0.25, o: 0.45, dbl: 0.25 },
  };

  class Blinker {
    constructor() {
      this.phase = -1;
      this.next = rand(1.2, 3);
      this.queued = 0;
      this.value = 0;
      this.cfg = BLINK_MODES.normal;
    }
    trigger(double = false) {
      if (this.phase >= 0) return;
      this.phase = 0;
      this.queued = double ? 1 : 0;
    }
    update(dt, mode) {
      this.cfg = BLINK_MODES[mode] || BLINK_MODES.normal;
      const { c, h, o } = this.cfg;
      if (this.phase >= 0) {
        this.phase += dt;
        const p = this.phase;
        if (p < c) this.value = easeInQuad(p / c);
        else if (p < c + h) this.value = 1;
        else if (p < c + h + o) this.value = 1 - easeInOutSine((p - c - h) / o);
        else {
          this.value = 0;
          this.phase = -1;
          if (this.queued > 0) {
            this.queued--;
            this.next = 0.07;
          } else {
            this.next = rand(...this.cfg.every);
          }
        }
      } else {
        this.next -= dt;
        if (this.next <= 0) this.trigger(Math.random() < this.cfg.dbl);
      }
      return this.value;
    }
  }

  class Gaze {
    constructor() {
      this.x = new Spring(0, 7, 0.72); // saccades: quick, tiny overshoot
      this.y = new Spring(0, 7, 0.72);
      this.hold = 0.5;
      this.mode = 'wander';
      this.thinkSide = 1;
    }
    pick(mode) {
      let x = 0, y = 0, hold = 1.5;
      switch (mode) {
        case 'wander':
          if (Math.random() < 0.3) {
            x = rand(14, 24) * (Math.random() < 0.5 ? -1 : 1);
            y = rand(-12, 10);
            hold = rand(0.5, 1.3);
          } else {
            x = rand(-5, 5);
            y = rand(-3, 3);
            hold = rand(1.0, 3.2);
          }
          break;
        case 'attentive':
          x = rand(-3, 3);
          y = rand(-2, 2);
          hold = rand(1.2, 3.5);
          break;
        case 'think': {
          const r = Math.random();
          if (r < 0.75) this.thinkSide = -this.thinkSide;
          x = r < 0.85 ? 20 * this.thinkSide + rand(-4, 4) : rand(-4, 4);
          y = rand(-20, -13);
          hold = rand(0.9, 2.2);
          break;
        }
        case 'talk':
          if (Math.random() < 0.2) {
            x = rand(9, 15) * (Math.random() < 0.5 ? -1 : 1);
            y = rand(-6, 4);
            hold = rand(0.4, 0.9);
          } else {
            x = rand(-4, 4);
            y = rand(-3, 2);
            hold = rand(0.8, 2.2);
          }
          break;
        case 'down':
          x = rand(-9, 9);
          y = rand(9, 14);
          hold = rand(1.5, 3.5);
          break;
        default: // fixed
          hold = 1;
      }
      this.x.target = x;
      this.y.target = y;
      this.hold = hold;
    }
    update(dt, mode) {
      if (mode !== this.mode) {
        this.mode = mode;
        this.hold = 0;
      }
      this.hold -= dt;
      if (this.hold <= 0) this.pick(mode);
      this.x.step(dt);
      this.y.step(dt);
    }
  }

  // Visemes whose jaw opening should follow loudness.
  const JAW_VISEMES = new Set(['C', 'D', 'E']);

  // -------------------------------------------------------------------- rig
  class FaceRig {
    /** shapes: shapes.json, presets: expressions.json */
    constructor(shapes, presets) {
      this.shapes = shapes;
      this.presets = presets;
      this.t = 0;
      this.springs = [];
      const S = (v, f, d) => {
        const s = new Spring(v, f, d);
        this.springs.push(s);
        return s;
      };

      this.mouthW = {};
      for (const k of shapes.mouthOrder) this.mouthW[k] = S(k === 'smile' ? 1 : 0, 5, 0.9);
      this.eyeW = {};
      for (const k of shapes.eyeOrder) if (k !== 'closed') this.eyeW[k] = S(k === 'open' ? 1 : 0, 4.5, 0.85);

      this.p = {
        smile: S(0, 5, 0.85), jaw: S(1, 9, 0.55), width: S(1, 5, 0.8),
        mdx: S(0, 4, 0.85), mdy: S(0, 4, 0.85), mtilt: S(0, 4, 0.85),
        esx: S(1, 4.5, 0.55), esy: S(1, 4.5, 0.55), eox: S(0, 4, 0.85), eoy: S(0, 4, 0.85),
        lidY: S(NO_LID_Y, 4, 0.9), lidSlope: S(0, 4, 0.9), lidLine: S(0, 4, 0.9),
        blush: S(0, 1.5, 1), tilt: S(0, 2.5, 0.8), headDy: S(0, 2.5, 0.8),
        bob: S(0, 5, 0.38), squash: S(0, 6, 0.4), talkMix: S(0, 5, 1),
        motion: S(0, 1.5, 1), breathe: S(1, 1, 1),
      };
      this.brows = [0, 1].map(() => ({
        ox: S(0, 5, 0.8), oy: S(-100, 5, 0.8), ix: S(0, 5, 0.8), iy: S(-100, 5, 0.8), w: S(0, 5, 0.9),
      }));

      this.blinker = new Blinker();
      this.gaze = new Gaze();
      this.speech = { viseme: 'X', intensity: 0, active: false, onset: false };
      this._wasTalking = false;
      this._intro = -1;
      this._motionKind = null;
      this.blink = 0;
      this.setExpression('idle', true);
    }

    /** Switch expression. Springs carry the transition. */
    setExpression(name, instant = false) {
      const e = resolveExpression(this.presets, name);
      this.expr = e;
      const p = this.p;
      for (const k in this.mouthW) this.mouthW[k].target = e.mouth[k] || 0;
      for (const k in this.eyeW) this.eyeW[k].target = e.eye[k] || 0;
      p.smile.target = e.mouthMods.smile;
      p.jaw.target = e.mouthMods.jaw;
      p.width.target = e.mouthMods.width;
      p.mdx.target = e.mouthMods.dx;
      p.mdy.target = e.mouthMods.dy;
      p.mtilt.target = e.mouthMods.tilt;
      p.esx.target = e.eyeScale[0];
      p.esy.target = e.eyeScale[1];
      p.eox.target = e.eyeOffset[0];
      p.eoy.target = e.eyeOffset[1];
      p.lidY.target = e.lid.y;
      p.lidSlope.target = e.lid.slope;
      p.lidLine.target = e.lid.line;
      p.blush.target = e.blush;
      p.tilt.target = (e.head.tilt * Math.PI) / 180;
      p.headDy.target = e.head.dy;
      p.motion.target = e.motion ? 1 : 0;
      p.breathe.target = e.breathe;
      this.brows.forEach((b, i) => {
        const key = e.brows[i];
        if (!key) {
          b.w.target = 0;
          return;
        }
        const [[ox, oy], [ix, iy], w] = this.presets.brows[key];
        if (b.w.value < 1) {
          // grow in place from the brow's midpoint
          const mx = (ox + ix) / 2, my = (oy + iy) / 2;
          b.ox.snap(mx); b.oy.snap(my); b.ix.snap(mx); b.iy.snap(my);
        }
        b.ox.target = ox; b.oy.target = oy; b.ix.target = ix; b.iy.target = iy; b.w.target = w;
      });
      if (e.motion) this._motionKind = e.motion;
      if (instant) {
        for (const s of this.springs) s.snap();
      } else if (e.enter) {
        if (e.enter.eyePop) {
          p.esx.value *= e.enter.eyePop;
          p.esy.value *= e.enter.eyePop;
        }
        if (e.enter.headKick) p.bob.velocity += e.enter.headKick;
      }
    }

    /** Wake-up: eyes closed, then open with a stretch. */
    playIntro() {
      this._intro = 0;
    }

    /** Feed the latest lip-sync result: {viseme, intensity 0..1, active, onset}. */
    setSpeech(s) {
      this.speech = s;
    }

    update(dt) {
      dt = Math.min(dt, 0.1);
      this.t += dt;
      const e = this.expr, p = this.p, sp = this.speech;
      const talking = !!sp.active;

      // Mouth pose: artist shapes when talking, expression rest mouth otherwise.
      for (const k in this.mouthW) {
        const s = this.mouthW[k];
        if (talking) {
          s.target = k === sp.viseme ? 1 : 0;
          s.freq = 11;
          s.damping = 0.92;
        } else {
          s.target = e.mouth[k] || 0;
          s.freq = 5;
          s.damping = 0.88;
        }
      }
      p.talkMix.target = talking ? 1 : 0;
      p.smile.target = talking ? e.talk.smile : e.mouthMods.smile;
      p.width.target = talking ? e.talk.width : e.mouthMods.width;
      p.jaw.target = talking
        ? (JAW_VISEMES.has(sp.viseme) ? 0.78 + 0.34 * sp.intensity : 1)
        : e.mouthMods.jaw;
      p.mdx.target = talking ? 0 : e.mouthMods.dx;
      p.mdy.target = talking ? 0 : e.mouthMods.dy;
      p.mtilt.target = talking ? 0 : e.mouthMods.tilt;

      if (talking && sp.onset) {
        p.bob.velocity += 55 + 50 * sp.intensity; // nod into the stressed syllable
        p.squash.velocity += 4 + 4 * sp.intensity;
      }
      if (talking && !this._wasTalking && Math.random() < 0.5) this.blinker.trigger();
      this._wasTalking = talking;

      // Intro: hold eyes shut, then open with a stretch.
      let introBlink = 0;
      if (this._intro >= 0) {
        this._intro += dt;
        const t = this._intro;
        if (t < 0.7) {
          introBlink = 1;
          p.headDy.value = 22;
        } else if (t < 1.25) {
          introBlink = 1 - easeInOutSine((t - 0.7) / 0.55);
          if (t - dt < 0.7) {
            p.esy.value = 1.25;
            p.bob.velocity -= 120;
          }
        } else this._intro = -1;
      }

      const blink = Math.max(this.blinker.update(dt, e.blink), introBlink);
      this.blink = blink;
      this.gaze.update(dt, talking ? 'talk' : e.gaze);
      for (const s of this.springs) s.step(dt);
    }

    // ------------------------------------------------------------ geometry
    /** Current face as plain geometry in art space (1280x720). */
    frame() {
      const S = this.shapes, p = this.p, t = this.t, e = this.expr;

      // Head transform: breathing, expression motion loop, speech bob.
      let hx = 0, hy = p.headDy.value + p.bob.value, tilt = p.tilt.value;
      hy += Math.sin((2 * Math.PI * t) / 4.2) * 2.2 * p.breathe.value;
      tilt += Math.sin((2 * Math.PI * t) / 7.3) * 0.006 * p.breathe.value;
      const m = p.motion.value;
      switch (this._motionKind) {
        case 'bounce': hy -= Math.abs(Math.sin(Math.PI * t * 1.5)) * 9 * m; break;
        case 'hop': hy -= Math.abs(Math.sin(Math.PI * t * 2.3)) * 15 * m; break;
        case 'tremble': hx += Math.sin(2 * Math.PI * t * 13) * 2.2 * m; break;
        case 'droop':
          hy += (1 - Math.cos((2 * Math.PI * t) / 6)) * 5 * m;
          tilt += Math.sin((2 * Math.PI * t) / 6) * 0.01 * m;
          break;
      }
      const cT = Math.cos(tilt), sT = Math.sin(tilt);
      const head = (x, y) => {
        const dx = x - 640, dy = y - 420;
        return [640 + dx * cT - dy * sT + hx, 420 + dx * sT + dy * cT + hy];
      };

      // ---- mouth: weighted blend of every pose
      const N = S.mouths[S.mouthOrder[0]].outer.length;
      const TN = S.mouths[S.mouthOrder[0]].tongue.length;
      const outer = new Float64Array(N * 2), tongue = new Float64Array(TN * 2);
      let stroke = 0, tT = 0, tB = 0, wsum = 0;
      const ws = [];
      for (const k of S.mouthOrder) {
        const w = Math.max(0, this.mouthW[k].value);
        if (w > 1e-4) { ws.push([k, w]); wsum += w; }
      }
      if (wsum < 1e-6) { ws.push(['X', 1]); wsum = 1; }
      for (const [k, w0] of ws) {
        const w = w0 / wsum, M = S.mouths[k];
        for (let i = 0; i < N; i++) { outer[2 * i] += M.outer[i][0] * w; outer[2 * i + 1] += M.outer[i][1] * w; }
        for (let i = 0; i < TN; i++) { tongue[2 * i] += M.tongue[i][0] * w; tongue[2 * i + 1] += M.tongue[i][1] * w; }
        stroke += M.stroke * w; tT += M.teethTop * w; tB += M.teethBot * w;
      }
      let minX = Infinity, maxX = -Infinity, top = Infinity, bottom = -Infinity;
      for (let i = 0; i < N; i++) {
        const x = outer[2 * i], y = outer[2 * i + 1];
        if (x < minX) minX = x; if (x > maxX) maxX = x;
        if (y < top) top = y; if (y > bottom) bottom = y;
      }
      const jaw = p.jaw.value, width = p.width.value, bend = p.smile.value;
      const cM = Math.cos(p.mtilt.value), sM = Math.sin(p.mtilt.value);
      const mdx = p.mdx.value, mdy = p.mdy.value;
      const mouthXf = (x, y) => {
        y = top + (y - top) * jaw;
        x = 640 + (x - 640) * width;
        const u = clamp((x - 640) / 110, -1.6, 1.6);
        y -= bend * 24 * u * u;
        const dx = x - 640, dy = y - 470;
        return head(640 + dx * cM - dy * sM + mdx, 470 + dx * sM + dy * cM + mdy);
      };
      const mapPts = (arr, n) => { const out = []; for (let i = 0; i < n; i++) out.push(mouthXf(arr[2 * i], arr[2 * i + 1])); return out; };
      const teethLine = (y) => {
        const out = [];
        for (let i = 0; i <= 24; i++) out.push(mouthXf(lerp(minX - 40, maxX + 40, i / 24), y));
        return out;
      };
      const mouth = {
        outer: mapPts(outer, N),
        tongue: mapPts(tongue, TN),
        stroke,
        teethTop: tT > top + 0.75 ? teethLine(tT) : null,
        teethBot: tB < bottom - 0.75 ? teethLine(tB) : null,
      };
      // How open the mouth is (0..1): drives the eye "lift" below.
      const openness = clamp(((bottom - top) * jaw - 18) / 110);

      // ---- eyes
      const blinkPose = S.eyes.closed;
      const EN = blinkPose.pts.length;
      let esum = 0;
      const ews = [];
      for (const k in this.eyeW) {
        const w = Math.max(0, this.eyeW[k].value);
        if (w > 1e-4) { ews.push([k, w]); esum += w; }
      }
      if (esum < 1e-6) { ews.push(['open', 1]); esum = 1; }
      const base = new Float64Array(EN * 2);
      let eStroke = 0, openLike = 0;
      for (const [k, w0] of ews) {
        const w = w0 / esum, E = S.eyes[k];
        for (let i = 0; i < EN; i++) { base[2 * i] += E.pts[i][0] * w; base[2 * i + 1] += E.pts[i][1] * w; }
        eStroke += E.stroke * w;
        if (k === 'open' || k === 'wide') openLike += w;
      }
      const b = this.blink * openLike; // arcs (happy/relax) don't blink
      const sq = p.squash.value;
      const sx = p.esx.value * (1 + 0.035 * sq);
      const sy = p.esy.value * (1 - 0.07 * sq) * (1 + 0.04 * openness);
      const lift = 5 * openness * p.talkMix.value;
      const eyes = [], brows = [];
      for (let side = 0; side < 2; side++) {
        const mir = side === 0 ? 1 : -1;
        const [cx0, cy0] = S.eyeCenters[side];
        const cx = cx0 + this.gaze.x.value + p.eox.value * mir;
        const cy = cy0 + this.gaze.y.value + p.eoy.value - lift;
        const pts = [];
        for (let i = 0; i < EN; i++) {
          const x = lerp(base[2 * i], blinkPose.pts[i][0], b);
          const y = lerp(base[2 * i + 1], blinkPose.pts[i][1], b);
          pts.push(head(cx + x * sx * mir, cy + y * sy));
        }
        const lidAt = (xi) => p.lidY.value + p.lidSlope.value * xi;
        let clip = null, lidLine = null;
        if (p.lidY.value > -70) {
          clip = [[-140, lidAt(-140)], [140, lidAt(140)], [140, 220], [-140, 220]]
            .map(([xi, y]) => head(cx + xi * mir, cy + y));
          if (p.lidLine.value > 0.5) {
            lidLine = { p0: head(cx - 46 * mir, cy + lidAt(-46)), p1: head(cx + 46 * mir, cy + lidAt(46)), w: p.lidLine.value };
          }
        }
        eyes.push({ pts, stroke: lerp(eStroke, blinkPose.stroke, b), clip, lidLine });

        const br = this.brows[side];
        if (br.w.value > 0.4) {
          const bx = cx0 + this.gaze.x.value * 0.3, by = cy0 + this.gaze.y.value * 0.25 - 7 * sq - lift * 1.4;
          brows.push({
            p0: head(bx + br.ox.value * mir, by + br.oy.value),
            p1: head(bx + br.ix.value * mir, by + br.iy.value),
            w: br.w.value,
          });
        }
      }

      const blush = p.blush.value > 0.01
        ? { alpha: clamp(p.blush.value), centers: [head(233, 393), head(1047, 393)] }
        : null;

      return { eyes, brows, mouth, blush, expression: e.name };
    }
  }

  // ---------------------------------------------------------- canvas render
  class CanvasRenderer {
    /** fit: 'cover' (fill, crop edges) | 'contain' | 'stretch' (like generate_faces.py) */
    constructor(canvas, shapes, fit = 'cover') {
      this.canvas = canvas;
      this.ctx = canvas.getContext('2d');
      this.C = shapes.colors;
      this.fit = fit;
    }
    _path(pts, close = true) {
      const c = this.ctx;
      c.beginPath();
      c.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i++) c.lineTo(pts[i][0], pts[i][1]);
      if (close) c.closePath();
    }
    draw(f) {
      const c = this.ctx, W = this.canvas.width, H = this.canvas.height, C = this.C;
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.fillStyle = C.bg;
      c.fillRect(0, 0, W, H);
      let sxf = W / 1280, syf = H / 720;
      if (this.fit === 'cover') sxf = syf = Math.max(sxf, syf);
      else if (this.fit === 'contain') sxf = syf = Math.min(sxf, syf);
      c.setTransform(sxf, 0, 0, syf, (W - 1280 * sxf) / 2, (H - 720 * syf) / 2);
      c.lineJoin = 'round';
      c.lineCap = 'round';

      if (f.blush) {
        for (const [x, y] of f.blush.centers) {
          c.save();
          c.globalAlpha = 0.69 * f.blush.alpha;
          c.translate(x, y);
          c.scale(1, 42 / 63);
          const g = c.createRadialGradient(0, 0, 0, 0, 0, 86);
          g.addColorStop(0, C.blush);
          g.addColorStop(0.5, C.blush);
          g.addColorStop(1, 'rgba(84,139,81,0)');
          c.fillStyle = g;
          c.beginPath();
          c.arc(0, 0, 86, 0, Math.PI * 2);
          c.fill();
          c.restore();
        }
      }

      c.fillStyle = C.line;
      c.strokeStyle = C.line;
      for (const e of f.eyes) {
        c.save();
        if (e.clip) {
          this._path(e.clip);
          c.clip();
        }
        this._path(e.pts);
        c.fill();
        if (e.stroke > 0.3) {
          c.lineWidth = e.stroke;
          c.stroke();
        }
        c.restore();
        if (e.lidLine) {
          c.lineWidth = e.lidLine.w;
          this._path([e.lidLine.p0, e.lidLine.p1], false);
          c.stroke();
        }
      }
      for (const b of f.brows) {
        c.lineWidth = b.w;
        this._path([b.p0, b.p1], false);
        c.stroke();
      }

      const m = f.mouth;
      this._path(m.outer);
      c.fillStyle = C.cavity;
      c.fill();
      c.save();
      c.clip();
      this._path(m.tongue);
      c.fillStyle = C.tongue;
      c.fill();
      c.lineWidth = 9;
      c.strokeStyle = C.line;
      for (const [line, dir] of [[m.teethTop, -1], [m.teethBot, 1]]) {
        if (!line) continue;
        const a = line[0], z = line[line.length - 1];
        this._path(line.concat([[z[0], z[1] + 400 * dir], [a[0], a[1] + 400 * dir]]));
        c.fillStyle = C.teeth;
        c.fill();
        this._path(line, false);
        c.stroke();
      }
      c.restore();
      this._path(m.outer);
      c.lineWidth = m.stroke;
      c.strokeStyle = C.line;
      c.stroke();
    }
  }

  // --------------------------------------------------------------- lip sync
  function makeFFT(n) {
    const levels = Math.round(Math.log2(n));
    const cos = new Float64Array(n / 2), sin = new Float64Array(n / 2);
    for (let i = 0; i < n / 2; i++) { cos[i] = Math.cos((2 * Math.PI * i) / n); sin[i] = Math.sin((2 * Math.PI * i) / n); }
    const rev = new Uint32Array(n);
    for (let i = 0; i < n; i++) {
      let r = 0, x = i;
      for (let j = 0; j < levels; j++) { r = (r << 1) | (x & 1); x >>= 1; }
      rev[i] = r;
    }
    return (re, im) => {
      for (let i = 0; i < n; i++) {
        const j = rev[i];
        if (j > i) {
          let t = re[i]; re[i] = re[j]; re[j] = t;
          t = im[i]; im[i] = im[j]; im[j] = t;
        }
      }
      for (let size = 2; size <= n; size *= 2) {
        const half = size / 2, step = n / size;
        for (let i = 0; i < n; i += size) {
          for (let j = i, k = 0; j < i + half; j++, k += step) {
            const l = j + half;
            const tre = re[l] * cos[k] + im[l] * sin[k];
            const tim = im[l] * cos[k] - re[l] * sin[k];
            re[l] = re[j] - tre; im[l] = im[j] - tim;
            re[j] += tre; im[j] += tim;
          }
        }
      }
    };
  }

  // Frequency bands (Hz) used to read the mouth shape off the spectrum.
  const BANDS = {
    low: [150, 600],     // F0 + first formant of closed vowels (ee, oo)
    mid: [600, 1500],    // first formant of open vowels (ah)
    f2lo: [700, 1700],   // second formant of rounded vowels (oo, oh)
    f2hi: [1800, 3800],  // second formant of spread vowels (ee, eh)
    sib: [4000, 10000],  // hiss: s, sh, f, t
    all: [150, 10000],
  };

  /**
   * Turns raw audio into a few mouth-relevant numbers:
   * loud (0..1, auto-gain), open (jaw), round (lip rounding), sib (hiss).
   * Ratios are self-normalising so it adapts to BMO's Piper voice or a mic.
   */
  class LipSyncAnalyser {
    constructor(sampleRate) {
      this.sr = sampleRate;
      this.n = sampleRate > 32000 ? 2048 : 1024;
      this.hop = Math.round(0.023 * sampleRate);
      this.fft = makeFFT(this.n);
      this.win = new Float64Array(this.n);
      for (let i = 0; i < this.n; i++) this.win[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (this.n - 1));
      this.re = new Float64Array(this.n);
      this.im = new Float64Array(this.n);
      this.bins = {};
      for (const k in BANDS) {
        this.bins[k] = [
          Math.max(1, Math.round((BANDS[k][0] * this.n) / sampleRate)),
          Math.min(this.n / 2 - 1, Math.round((BANDS[k][1] * this.n) / sampleRate)),
        ];
      }
      this.peak = 0.03;
      // Running [mean, mean-abs-deviation] of the formant features in dB.
      // Seeded from BMO's Piper voice so the first syllable is already sane.
      this.stats = { open: [-4, 6.8], spread: [-5, 10] };
    }
    _band(power, k) {
      const [a, b] = this.bins[k];
      let s = 0;
      for (let i = a; i <= b; i++) s += power[i];
      return s;
    }
    _norm(key, x, update, dt) {
      const st = this.stats[key];
      if (update) {
        const a = 1 - Math.exp(-dt / 2.5);
        st[0] += (x - st[0]) * a;
        st[1] += (Math.abs(x - st[0]) - st[1]) * a;
        st[1] = Math.max(st[1], 2);
      }
      return clamp(0.5 + (x - st[0]) / (3 * st[1]));
    }
    /** samples: the most recent audio (Float32/-1..1), length >= this.n. */
    process(samples, dt) {
      const n = this.n, L = samples.length;
      let ss = 0;
      for (let i = L - this.hop; i < L; i++) ss += samples[i] * samples[i];
      const rms = Math.sqrt(ss / this.hop);
      for (let i = 0; i < n; i++) {
        this.re[i] = samples[L - n + i] * this.win[i];
        this.im[i] = 0;
      }
      this.fft(this.re, this.im);
      const power = new Float64Array(n / 2);
      for (let i = 0; i < n / 2; i++) power[i] = this.re[i] * this.re[i] + this.im[i] * this.im[i];
      const eps = 1e-12;
      const low = this._band(power, 'low'), mid = this._band(power, 'mid');
      const f2lo = this._band(power, 'f2lo'), f2hi = this._band(power, 'f2hi');
      const sib = this._band(power, 'sib'), all = this._band(power, 'all') + eps;

      this.peak = Math.max(rms, this.peak * Math.exp(-dt / 1.8), 0.02);
      const voiced = rms > Math.max(0.006, this.peak * 0.09);
      const loud = clamp(rms / this.peak);
      const sibRatio = sib / all;
      const openDb = 10 * Math.log10((mid + eps) / (low + eps));      // high F1 -> jaw open
      const spreadDb = 10 * Math.log10((f2hi + eps) / (f2lo + eps));  // low F2 -> lips rounded
      const learn = voiced && sibRatio < 0.3;
      const openN = this._norm('open', openDb, learn, dt);
      const spreadN = this._norm('spread', spreadDb, learn, dt);
      return {
        rms, voiced, loud,
        open: clamp(Math.sqrt(loud) * lerp(0.35, 1.15, openN)),
        round: clamp(1 - spreadN),
        sib: clamp((sibRatio - 0.12) / 0.3),
        raw: { sibRatio, openDb, spreadDb },
      };
    }
  }

  /**
   * Picks a Rhubarb mouth shape from analyser features, with a minimum hold
   * so shapes read clearly (like animating on 2s), and brief lip closures
   * between words.
   */
  class VisemeSelector {
    constructor() {
      this.viseme = 'X';
      this.hold = 0;
      this.sinceVoice = 9;
      this.loudSlow = 0;
      this.cool = 0;
      this.minHold = 0.075;
    }
    classify(f) {
      if (f.sib > 0.55 && f.open < 0.75) return 'B';
      if (f.round > 0.66) return f.open > 0.55 ? 'E' : 'F';
      if (f.open > 0.72) return 'D';
      if (f.open > 0.4) return 'C';
      return 'B';
    }
    update(f, dt) {
      let want;
      if (!f.voiced) {
        this.sinceVoice += dt;
        want = this.sinceVoice < 0.16 ? 'A' : 'X';
      } else {
        this.sinceVoice = 0;
        want = this.classify(f);
      }
      this.hold -= dt;
      if (want !== this.viseme && this.hold <= 0) {
        this.viseme = want;
        this.hold = this.minHold;
      }
      // Onsets (stressed syllables) drive head bob.
      this.cool -= dt;
      const onset = f.voiced && f.loud - this.loudSlow > 0.3 && this.cool <= 0;
      if (onset) this.cool = 0.2;
      this.loudSlow += (f.loud - this.loudSlow) * (1 - Math.exp(-dt / 0.12));
      return { viseme: this.viseme, intensity: f.loud, active: this.sinceVoice < 0.45, onset };
    }
  }

  /** Browser helper: route any WebAudio node through this to drive a rig. */
  class AudioLipSync {
    constructor(audioCtx) {
      this.node = audioCtx.createAnalyser();
      this.node.fftSize = 2048;
      this.node.smoothingTimeConstant = 0;
      this.buf = new Float32Array(this.node.fftSize);
      this.analyser = new LipSyncAnalyser(audioCtx.sampleRate);
      this.selector = new VisemeSelector();
      this.last = null;
    }
    tick(dt) {
      this.node.getFloatTimeDomainData(this.buf);
      const f = this.analyser.process(this.buf, dt);
      const s = this.selector.update(f, dt);
      this.last = { ...s, features: f };
      return s;
    }
  }

  global.BMOFace = {
    Spring, FaceRig, CanvasRenderer, LipSyncAnalyser, VisemeSelector, AudioLipSync, BANDS,
  };
})(typeof window !== 'undefined' ? window : globalThis);
