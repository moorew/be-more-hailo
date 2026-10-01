/*!
 * bmo-face.js - procedural face rig for BMO (be-more-hailo).
 *
 * Every mouth and eye pose from the artwork is stored as a morph-compatible
 * contour (shapes.json) and the rig blends between them with springs. Around
 * that sit behaviour layers (blinks, winks, glances, breathing, speech bob),
 * "marks" (tongues, dimples, brows, sparkles, notes...) that pop in with an
 * expression, and critters (bee, ladybug, worm, butterfly) that BMO watches.
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
  const smoothstep = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
  const wrapPi = (a) => a - 2 * Math.PI * Math.round(a / (2 * Math.PI));
  const TAU = 2 * Math.PI;
  const hexRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const rgbHex = (c) => '#' + c.map((v) => Math.round(clamp(v, 0, 255)).toString(16).padStart(2, '0')).join('');

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
  const NO_LID2_Y = 95;

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
      eyeSpin: pick('eyeSpin'),
      lid: { ...d.lid, ...(e.lid || {}) },
      lid2: { ...d.lid2, ...(e.lid2 || {}) },
      brows: pick('brows'),
      marks: pick('marks'),
      markOffset: e.markOffset || {},
      blush: pick('blush'),
      blushColor: pick('blushColor'),
      gaze: pick('gaze'),
      blink: pick('blink'),
      motion: pick('motion'),
      head: { ...d.head, ...(e.head || {}) },
      breathe: pick('breathe'),
      flash: pick('flash'),
      critter: pick('critter'),
      react: pick('react'),
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
    wink:      { every: [2.2, 5.5], c: 0.06, h: 0.04, o: 0.12, dbl: 0.1 },
    none:      { every: [1e9, 1e9], c: 0.06, h: 0.04, o: 0.12, dbl: 0 },
  };
  const WINK = { every: [2.5, 5.0], c: 0.08, h: 0.35, o: 0.18, dbl: 0 }; // right eye only

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
      this.cfg = typeof mode === 'string' ? BLINK_MODES[mode] || BLINK_MODES.normal : mode;
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
      } else if (this.cfg.every[0] >= 1e8) {
        this.next = 1e9; // 'none': never blink (a later mode clamps this back down)
      } else {
        this.next = Math.min(this.next, this.cfg.every[1]) - dt;
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
      this.side = 1;
    }
    pick(mode) {
      let x = 0, y = 0, hold = 1.5, freq = 7;
      const side = () => (Math.random() < 0.5 ? -1 : 1);
      switch (mode) {
        case 'wander':
          if (Math.random() < 0.3) { x = rand(14, 24) * side(); y = rand(-12, 10); hold = rand(0.5, 1.3); }
          else { x = rand(-5, 5); y = rand(-3, 3); hold = rand(1.0, 3.2); }
          break;
        case 'attentive':
          x = rand(-3, 3); y = rand(-2, 2); hold = rand(1.2, 3.5);
          break;
        case 'think': {
          const r = Math.random();
          if (r < 0.75) this.side = -this.side;
          x = r < 0.85 ? 20 * this.side + rand(-4, 4) : rand(-4, 4);
          y = rand(-20, -13); hold = rand(0.9, 2.2);
          break;
        }
        case 'talk':
          if (Math.random() < 0.2) { x = rand(9, 15) * side(); y = rand(-6, 4); hold = rand(0.4, 0.9); }
          else { x = rand(-4, 4); y = rand(-3, 2); hold = rand(0.8, 2.2); }
          break;
        case 'down':
          x = rand(-9, 9); y = rand(9, 14); hold = rand(1.5, 3.5);
          break;
        case 'shifty': // detective: slow slides from side to side
          this.side = Math.random() < 0.8 ? -this.side : this.side;
          x = Math.random() < 0.85 ? rand(18, 26) * this.side : 0;
          y = rand(-2, 2); hold = rand(1.0, 2.4); freq = 2.2;
          break;
        case 'away': // bored: looks off and up, rarely back
          if (Math.random() < 0.18) { x = rand(-3, 3); y = rand(-2, 2); hold = rand(0.6, 1.2); }
          else { x = rand(14, 22) * this.side; y = rand(-14, -6); hold = rand(2.5, 5); }
          freq = 3.5;
          break;
        default: // fixed
          hold = 1;
      }
      this.x.target = x;
      this.y.target = y;
      this.x.freq = this.y.freq = freq;
      this.hold = hold;
    }
    update(dt, mode, target) {
      if (mode !== this.mode) {
        this.mode = mode;
        this.hold = 0;
      }
      if (mode === 'track' && target) {
        this.x.target = target[0];
        this.y.target = target[1];
        this.x.freq = this.y.freq = 5;
      } else {
        this.hold -= dt;
        if (this.hold <= 0) this.pick(mode);
      }
      this.x.step(dt);
      this.y.step(dt);
    }
  }

  // Critter paths (art pixels). facing: +1 moving right, -1 moving left.
  function critterPose(name, t) {
    switch (name) {
      case 'bee': {
        const u = (TAU * t) / 8;
        return {
          x: 640 + 470 * Math.sin(u),
          y: 290 + 140 * Math.sin(2 * u + 0.6) + 6 * Math.sin(TAU * 9 * t),
          facing: clamp(Math.cos(u) * 4, -1, 1),
          angle: 0.12 * Math.sin(TAU * 0.7 * t),
          flap: 0.55 + 0.45 * Math.abs(Math.sin(TAU * 13 * t)),
          sx: 1, sy: 1,
        };
      }
      case 'ladybug': {
        const s = t % 15;
        let x, facing;
        if (s < 7) { x = lerp(-110, 1390, s / 7); facing = 1; }
        else if (s < 7.5) { x = 1390; facing = 1; }
        else if (s < 14.5) { x = lerp(1390, -110, (s - 7.5) / 7); facing = -1; }
        else { x = -110; facing = -1; }
        return {
          x, y: 652 - 3 * Math.abs(Math.sin(TAU * 3 * t)), facing,
          angle: 0.07 * Math.sin(TAU * 3 * t), flap: 1, sx: 1, sy: 1,
        };
      }
      case 'worm': {
        const s = t % 18, k = Math.sin(TAU * 1.1 * t);
        return {
          x: 1400 - (1520 * Math.min(s, 16)) / 16 + 18 * k, y: 600, facing: -1,
          angle: 0.03 * k, flap: 1, sx: 1 + 0.1 * k, sy: 1 - 0.07 * k,
        };
      }
      case 'butterfly': {
        const u = (TAU * t) / 12;
        return {
          x: 640 + 520 * Math.sin(u),
          y: 165 + 60 * Math.sin((TAU * t) / 6 + 1) + 12 * Math.sin(TAU * 0.9 * t),
          facing: clamp(Math.cos(u) * 4, -1, 1),
          angle: 0.18 * Math.sin((TAU * t) / 3.3), flap: 1,
          sx: 0.3 + 0.7 * Math.abs(Math.cos(TAU * 2.4 * t)), sy: 1,
        };
      }
      default:
        return { x: -500, y: -500, facing: 1, angle: 0, flap: 1, sx: 1, sy: 1 };
    }
  }

  // Lub-dub, once a second (0..~1).
  function heartbeat(t) {
    const ph = t % 1;
    const p1 = ph > 0.5 ? ph - 1 : ph;
    return Math.exp(-((p1 / 0.06) ** 2)) + 0.6 * Math.exp(-(((ph - 0.22) / 0.07) ** 2));
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
      this.markVis = {};
      for (const k of Object.keys(shapes.marks || {})) this.markVis[k] = S(0, 4.5, 0.55);
      // Per-expression nudge for marks (art units); kept while a mark fades out.
      this.markOff = {};
      for (const k of Object.keys(shapes.marks || {})) this.markOff[k] = [0, 0];

      this.p = {
        smile: S(0, 5, 0.85), jaw: S(1, 9, 0.55), width: S(1, 5, 0.8),
        mdx: S(0, 4, 0.85), mdy: S(0, 4, 0.85), mtilt: S(0, 4, 0.85),
        esx: S(1, 4.5, 0.55), esy: S(1, 4.5, 0.55), eox: S(0, 4, 0.85), eoy: S(0, 4, 0.85),
        lidY: S(NO_LID_Y, 4, 0.9), lidSlope: S(0, 4, 0.9), lidLine: S(0, 4, 0.9), lidLen: S(46, 4, 0.9),
        lid2Y: S(NO_LID2_Y, 4, 0.9), lid2Slope: S(0, 4, 0.9), lid2Line: S(0, 4, 0.9), lid2Len: S(46, 4, 0.9),
        blush: S(0, 1.5, 1), tilt: S(0, 2.5, 0.8), headDy: S(0, 2.5, 0.8),
        bob: S(0, 5, 0.38), squash: S(0, 6, 0.4), talkMix: S(0, 5, 1),
        motion: S(0, 1.5, 1), breathe: S(1, 1, 1), spinSpeed: S(0, 1.2, 1),
      };
      this.brows = [0, 1].map(() => ({
        ox: S(0, 5, 0.8), oy: S(-100, 5, 0.8), ix: S(0, 5, 0.8), iy: S(-100, 5, 0.8), w: S(0, 5, 0.9),
      }));
      this.critter = { name: null, t: 0, vis: S(0, 3, 0.7), pose: null };

      this.blinker = new Blinker();
      this.winker = new Blinker();
      this.gaze = new Gaze();
      this.speech = { viseme: 'X', intensity: 0, active: false, onset: false };
      this.spinAngle = 0;
      this.flash = 0;
      this.wink = 0;
      this._swap = -1;          // glyph-eye swap progress (0..1), -1 when idle
      this._swapTargets = null; // eye weights to apply at the swap midpoint
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
      // Glyph eyes (hearts, stars, spirals...) can't morph cleanly into other
      // shapes, so those swaps shrink the eyes away and pop the new ones in.
      const eyeTargets = {};
      for (const k in this.eyeW) eyeTargets[k] = e.eye[k] || 0;
      const dominant = (get) => Object.keys(this.eyeW).reduce((a, k) => (get(k) > get(a) ? k : a));
      const was = dominant((k) => this.eyeW[k].value), next = dominant((k) => eyeTargets[k]);
      const glyph = (k) => !!this.shapes.eyes[k].glyph;
      if (!instant && was !== next && (glyph(was) || glyph(next))) {
        this._swapTargets = eyeTargets;
        if (this._swap < 0 || this._swap >= 0.5) this._swap = 0;
      } else {
        this._swapTargets = null;
        for (const k in this.eyeW) this.eyeW[k].target = eyeTargets[k];
      }
      for (const k in this.markVis) {
        this.markVis[k].target = e.marks.includes(k) ? 1 : 0;
        if (e.marks.includes(k)) this.markOff[k] = e.markOffset[k] || [0, 0];
      }
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
      p.lidLen.target = e.lid.len;
      p.lid2Y.target = e.lid2.y;
      p.lid2Slope.target = e.lid2.slope;
      p.lid2Line.target = e.lid2.line;
      p.lid2Len.target = e.lid2.len;
      p.blush.target = e.blush;
      p.tilt.target = (e.head.tilt * Math.PI) / 180;
      p.headDy.target = e.head.dy;
      p.motion.target = e.motion ? 1 : 0;
      p.breathe.target = e.breathe;
      p.spinSpeed.target = e.eyeSpin;
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
      const c = this.critter;
      if (e.critter) {
        if (c.name !== e.critter || c.vis.value < 0.05) {
          c.name = e.critter;
          c.t = 0;
          c.vis.snap(0);
        }
        c.vis.target = 1;
      } else {
        c.vis.target = 0;
      }
      if (e.flash) this.flash = 1;
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

      // Critter: advance its path; BMO watches it and reacts when it's close.
      const c = this.critter;
      let near = 0, track = null;
      if (c.name && (c.vis.target > 0 || c.vis.value > 0.01)) {
        c.t += dt;
        c.pose = critterPose(c.name, c.t);
        if (e.critter === c.name) {
          track = [clamp((c.pose.x - 640) * 0.045, -24, 24), clamp((c.pose.y - 300) * 0.06, -16, 18)];
          if (e.react) near = smoothstep(e.react.radius, e.react.radius * 0.45, Math.hypot(c.pose.x - 640, c.pose.y - 400)) * c.vis.value;
        }
      }

      // Mouth pose: artist shapes when talking, expression rest mouth otherwise.
      for (const k in this.mouthW) {
        const s = this.mouthW[k];
        if (talking) {
          s.target = k === sp.viseme ? 1 : 0;
          s.freq = 11;
          s.damping = 0.92;
        } else {
          const rest = e.mouth[k] || 0;
          s.target = e.react ? lerp(rest, e.react.mouth[k] || 0, near) : rest;
          s.freq = 5;
          s.damping = 0.88;
        }
      }
      if (e.react) {
        const k = 1 + (e.react.eyeScale - 1) * near;
        p.esx.target = e.eyeScale[0] * k;
        p.esy.target = e.eyeScale[1] * k;
      }
      // Marks on the mouth (tongue, dimples...) tuck away while talking.
      for (const k in this.markVis) {
        const on = e.marks.includes(k) && !(talking && this.shapes.marks[k].anchor === 'mouth');
        this.markVis[k].target = on ? 1 : 0;
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

      this.blink = Math.max(this.blinker.update(dt, e.blink), introBlink);
      this.wink = e.blink === 'wink' ? this.winker.update(dt, WINK) : this.winker.update(dt, BLINK_MODES.none);
      this.gaze.update(dt, talking ? 'talk' : e.gaze, track);
      this.flash *= Math.exp(-dt / 0.14);
      if (this._swap >= 0) {
        const before = this._swap;
        this._swap += dt / 0.26;
        if (before < 0.5 && this._swap >= 0.5 && this._swapTargets) {
          for (const k in this.eyeW) this.eyeW[k].snap(this._swapTargets[k]);
          this.spinAngle = 0; // new glyphs appear upright
          this._swapTargets = null;
        }
        if (this._swap >= 1) this._swap = -1;
      }
      for (const s of this.springs) s.step(dt);

      // Spinning eyes (dizzy); once the spin stops they settle back upright.
      this.spinAngle += p.spinSpeed.value * dt;
      if (Math.abs(p.spinSpeed.target) < 1e-3) this.spinAngle -= wrapPi(this.spinAngle) * (1 - Math.exp(-dt * 5));
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
      let eyeMul = 1, eyeRot = 0;
      switch (this._motionKind) {
        case 'bounce': hy -= Math.abs(Math.sin(Math.PI * t * 1.5)) * 9 * m; break;
        case 'hop': hy -= Math.abs(Math.sin(Math.PI * t * 2.3)) * 15 * m; break;
        case 'tremble': hx += Math.sin(TAU * t * 13) * 2.2 * m; break;
        case 'droop':
          hy += (1 - Math.cos(TAU * t / 6)) * 5 * m;
          tilt += Math.sin(TAU * t / 6) * 0.01 * m;
          break;
        case 'woozy':
          hx += Math.cos(TAU * 0.55 * t) * 12 * m;
          hy += Math.sin(TAU * 0.55 * t) * 8 * m;
          tilt += Math.sin(TAU * 0.55 * t) * 0.025 * m;
          break;
        case 'pulse': eyeMul = 1 + 0.12 * heartbeat(t) * m; break;
        case 'twinkle':
          eyeRot = 0.16 * Math.sin(TAU * 0.45 * t) * m;
          eyeMul = 1 + 0.05 * Math.sin(TAU * 1.3 * t) * m;
          break;
        case 'shake': {
          const ph = t % 2.4, env = ph < 0.4 ? Math.sin((Math.PI * ph) / 0.4) : 0;
          hx += Math.sin(TAU * 16 * t) * 9 * env * m;
          break;
        }
        case 'groove':
          hy -= Math.abs(Math.sin(TAU * t)) * 11 * m;
          tilt += Math.sin(Math.PI * t) * 0.025 * m;
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

      // ---- eyes: blend poses (each pose mirrors for the right eye unless noMirror)
      const blinkPose = S.eyes.closed;
      const EN = blinkPose.pts.length;
      let esum = 0;
      const ews = [];
      for (const k in this.eyeW) {
        const w = Math.max(0, this.eyeW[k].value);
        if (w > 1e-4) { ews.push([k, w]); esum += w; }
      }
      if (esum < 1e-6) { ews.push(['open', 1]); esum = 1; }
      const base = [new Float64Array(EN * 2), new Float64Array(EN * 2)];
      let eStroke = 0, openLike = 0;
      const fill = [0, 0, 0], sCol = [0, 0, 0];
      for (const [k, w0] of ews) {
        const w = w0 / esum, E = S.eyes[k];
        for (let side = 0; side < 2; side++) {
          const mir = side === 1 && !E.noMirror ? -1 : 1, b = base[side];
          for (let i = 0; i < EN; i++) { b[2 * i] += E.pts[i][0] * mir * w; b[2 * i + 1] += E.pts[i][1] * w; }
        }
        eStroke += E.stroke * w;
        const f = hexRgb(E.fill || '#000000'), sc = hexRgb(E.strokeColor || '#000000');
        for (let j = 0; j < 3; j++) { fill[j] += f[j] * w; sCol[j] += sc[j] * w; }
        if (E.blinks) openLike += w;
      }
      const sq = p.squash.value;
      const swapK = this._swap >= 0 ? Math.max(0.03, Math.abs(Math.cos(Math.PI * this._swap))) : 1;
      const sx = p.esx.value * (1 + 0.035 * sq) * eyeMul * swapK;
      const sy = p.esy.value * (1 - 0.07 * sq) * (1 + 0.04 * openness) * eyeMul * swapK;
      const lift = 5 * openness * p.talkMix.value;
      const rot = this.spinAngle + eyeRot, cR = Math.cos(rot), sR = Math.sin(rot);
      const gx = this.gaze.x.value, gy = this.gaze.y.value;
      const eyes = [], brows = [], eyePos = [];
      for (let side = 0; side < 2; side++) {
        const mir = side === 0 ? 1 : -1;
        const blinkAmt = Math.max(this.blink, side === 1 ? this.wink : 0) * openLike;
        const [cx0, cy0] = S.eyeCenters[side];
        const sockX = cx0 + p.eox.value * mir, sockY = cy0 + p.eoy.value - lift;
        const cx = sockX + gx, cy = sockY + gy;
        eyePos.push([cx, cy]);
        const place = (x, y) => {
          x *= sx; y *= sy;
          return head(cx + x * cR - y * sR, cy + x * sR + y * cR);
        };
        const b = base[side], pts = [];
        for (let i = 0; i < EN; i++) {
          pts.push(place(lerp(b[2 * i], blinkPose.pts[i][0], blinkAmt), lerp(b[2 * i + 1], blinkPose.pts[i][1], blinkAmt)));
        }
        const details = [];
        for (const [k, w0] of ews) {
          const E = S.eyes[k];
          if (!E.details) continue;
          const a = smoothstep(0.35, 0.9, w0 / esum) * (1 - blinkAmt);
          if (a < 0.01) continue;
          for (const d of E.details) {
            const dm = side === 1 && !E.noMirror && !d.noMirror ? -1 : 1;
            details.push({ pts: d.pts.map(([x, y]) => place(x * dm, y)), fill: d.fill, alpha: d.alpha * a });
          }
        }
        // Lids sit on the socket and only partly follow the gaze.
        const lcx = sockX + gx * 0.15, lcy = sockY + gy * 0.7;
        const at = (xi) => p.lidY.value + p.lidSlope.value * xi;
        const at2 = (xi) => p.lid2Y.value + p.lid2Slope.value * xi;
        let clip = null;
        const lidLines = [];
        if (p.lidY.value > -70 || p.lid2Y.value < 70) {
          clip = [[-300, at(-300)], [300, at(300)], [300, at2(300)], [-300, at2(-300)]]
            .map(([xi, y]) => head(lcx + xi * mir, lcy + y));
        }
        if (p.lidLine.value > 0.5) {
          const L = p.lidLen.value;
          lidLines.push({ p0: head(lcx - L * mir, lcy + at(-L)), p1: head(lcx + L * mir, lcy + at(L)), w: p.lidLine.value });
        }
        if (p.lid2Line.value > 0.5) {
          const L = p.lid2Len.value;
          lidLines.push({ p0: head(lcx - L * mir, lcy + at2(-L)), p1: head(lcx + L * mir, lcy + at2(L)), w: p.lid2Line.value });
        }
        let brow = null;
        const br = this.brows[side];
        if (br.w.value > 0.4) {
          const bx = cx0 + gx * 0.3, by = cy0 + gy * 0.25 - 7 * sq - lift * 1.4;
          brow = {
            p0: head(bx + br.ox.value * mir, by + br.oy.value),
            p1: head(bx + br.ix.value * mir, by + br.iy.value),
            w: br.w.value,
          };
          brows.push(brow);
        }
        eyes.push({
          pts, stroke: lerp(eStroke, blinkPose.stroke, blinkAmt),
          fill: rgbHex(fill), strokeColor: rgbHex(sCol), details, clip, lidLines, brow,
        });
      }

      // ---- marks: pop in/out (scale about their centre) with small animations
      const marks = [];
      for (const k in this.markVis) {
        const vis = this.markVis[k].value;
        if (vis < 0.01) continue;
        const M = S.marks[k], an = M.anim || {};
        let ox = 0, oy = 0;
        if (M.anchor === 'eyeL' || M.anchor === 'eyeR') {
          const side = M.anchor === 'eyeL' ? 0 : 1;
          const [cx0, cy0] = S.eyeCenters[side];
          const mir = side === 0 ? 1 : -1;
          ox = cx0 + p.eox.value * mir + gx * 0.5 - M.ref[0];
          oy = cy0 + p.eoy.value + gy * 0.5 - lift - M.ref[1];
        }
        ox += this.markOff[k][0]; oy += this.markOff[k][1];
        let scale = vis, alpha = clamp(vis * 1.5), arot = 0, ax = 0, ay = 0, aroot = null;
        if (an.type === 'wiggle') { arot = an.amp * Math.sin(TAU * an.freq * t); aroot = an.root; }
        else if (an.type === 'blink') alpha *= Math.sin(TAU * an.freq * t) > -0.3 ? 1 : 0.15;
        else if (an.type === 'twinkle') {
          const k2 = 0.5 + 0.5 * Math.sin(TAU * (an.freq * t + an.phase));
          scale *= 0.55 + 0.6 * k2; alpha *= 0.35 + 0.65 * k2; arot = 0.3 * Math.sin(TAU * (0.3 * t + an.phase));
        } else if (an.type === 'float') {
          const u = (t / an.period + an.phase) % 1;
          ay = -an.rise * u; ax = 8 * Math.sin(TAU * u); alpha *= Math.sin(Math.PI * u);
        }
        // centroid of the whole mark (scale-in pivot)
        let mx = 0, my = 0, n = 0;
        for (const it of M.items) for (const [x, y] of it.pts) { mx += x; my += y; n++; }
        mx /= n; my /= n;
        const [rx, ry] = aroot || [mx, my];
        const cA = Math.cos(arot), sA = Math.sin(arot);
        M.items.forEach((it, idx) => {
          const sh = an.type === 'shiver' ? an.amp * Math.sin(TAU * an.freq * t + idx * 1.7) : 0;
          const pts = it.pts.map(([x0, y0]) => {
            let x = x0 - rx, y = y0 - ry;
            [x, y] = [x * cA - y * sA + rx, x * sA + y * cA + ry];
            x = mx + (x - mx) * scale + ax + ox + sh;
            y = my + (y - my) * scale + ay + oy;
            return M.anchor === 'mouth' ? mouthXf(x, y) : head(x, y);
          });
          if (alpha > 0.01) marks.push({ key: k, kind: it.kind, closed: it.closed, pts, width: it.width * Math.max(0, scale), color: it.color, alpha: clamp(alpha) });
        });
      }

      // ---- critter (in front of the face, not attached to BMO's head)
      let critter = null;
      const c = this.critter;
      if (c.name && c.pose && c.vis.value > 0.01) {
        const C = S.critters[c.name], q = c.pose;
        const k = (C.width / C.size[0]) * c.vis.value;
        const flip = q.facing * C.faces * q.sx;
        const ang = q.angle + (C.tilt || 0) * Math.sign(q.facing);
        const cA = Math.cos(ang), sA = Math.sin(ang);
        const [wx, wy] = C.wingRoot || [0, 0];
        const xf = (x, y, wing) => {
          if (wing) { x = wx + (x - wx) * q.flap; y = wy + (y - wy) * q.flap; }
          x = (x - C.size[0] / 2) * k * flip;
          y = (y - C.size[1] / 2) * k * q.sy;
          return [q.x + x * cA - y * sA, q.y + x * sA + y * cA];
        };
        critter = {
          name: c.name, center: [q.x, q.y],
          parts: C.parts.map((pt) => ({
            pts: pt.pts.map(([x, y]) => xf(x, y, pt.group === 'wing')),
            fill: pt.fill, stroke: pt.stroke, width: pt.width * k, alpha: pt.alpha, closed: pt.closed,
          })),
        };
      }

      const blush = p.blush.value > 0.01
        ? { alpha: clamp(p.blush.value), centers: [head(233, 393), head(1047, 393)], color: e.blushColor || S.colors.blush }
        : null;

      return { eyes, brows, mouth, marks, critter, blush, flash: this.flash > 0.01 ? this.flash : 0, expression: e.name };
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
      c.globalAlpha = 1;
      c.fillStyle = C.bg;
      c.fillRect(0, 0, W, H);
      let sxf = W / 1280, syf = H / 720;
      if (this.fit === 'cover') sxf = syf = Math.max(sxf, syf);
      else if (this.fit === 'contain') sxf = syf = Math.min(sxf, syf);
      c.setTransform(sxf, 0, 0, syf, (W - 1280 * sxf) / 2, (H - 720 * syf) / 2);
      c.lineJoin = 'round';
      c.lineCap = 'round';

      if (f.blush) {
        const [r, g, b] = hexRgb(f.blush.color);
        for (const [x, y] of f.blush.centers) {
          c.save();
          c.globalAlpha = 0.69 * f.blush.alpha;
          c.translate(x, y);
          c.scale(1, 42 / 63);
          const grad = c.createRadialGradient(0, 0, 0, 0, 0, 86);
          grad.addColorStop(0, f.blush.color);
          grad.addColorStop(0.5, f.blush.color);
          grad.addColorStop(1, `rgba(${r},${g},${b},0)`);
          c.fillStyle = grad;
          c.beginPath();
          c.arc(0, 0, 86, 0, Math.PI * 2);
          c.fill();
          c.restore();
        }
      }

      for (const e of f.eyes) {
        c.save();
        if (e.clip) {
          this._path(e.clip);
          c.clip();
        }
        this._path(e.pts);
        c.fillStyle = e.fill;
        c.fill();
        if (e.stroke > 0.3) {
          c.lineWidth = e.stroke;
          c.strokeStyle = e.strokeColor;
          c.stroke();
        }
        for (const d of e.details) {
          c.globalAlpha = d.alpha;
          this._path(d.pts);
          c.fillStyle = d.fill;
          c.fill();
        }
        c.restore();
        c.strokeStyle = C.line;
        for (const l of e.lidLines) {
          c.lineWidth = l.w;
          this._path([l.p0, l.p1], false);
          c.stroke();
        }
      }
      c.strokeStyle = C.line;
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

      for (const k of f.marks) {
        c.globalAlpha = k.alpha;
        this._path(k.pts, k.closed);
        if (k.kind === 'fill') { c.fillStyle = k.color; c.fill(); }
        else if (k.width > 0.3) { c.lineWidth = k.width; c.strokeStyle = k.color; c.stroke(); }
      }
      c.globalAlpha = 1;

      if (f.critter) {
        for (const pt of f.critter.parts) {
          c.globalAlpha = pt.alpha;
          this._path(pt.pts, pt.closed);
          if (pt.fill && pt.closed) { c.fillStyle = pt.fill; c.fill(); }
          if (pt.stroke && pt.width > 0.3) { c.lineWidth = pt.width; c.strokeStyle = pt.stroke; c.stroke(); }
        }
        c.globalAlpha = 1;
      }

      if (f.flash > 0) {
        c.setTransform(1, 0, 0, 1, 0, 0);
        c.globalAlpha = f.flash;
        c.fillStyle = '#FFFFFF';
        c.fillRect(0, 0, W, H);
        c.globalAlpha = 1;
      }
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
    critterPose, heartbeat,
  };
})(typeof window !== 'undefined' ? window : globalThis);
