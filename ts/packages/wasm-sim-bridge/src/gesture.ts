/** CW-MOM-01: closed declarative target curves. No scripts, inference or authority. */
import { canonicalAssemblyString, parseStrictJson } from '@seedcore/contracts';
import { sha256Hex } from '@seedcore/drc-solver';
import { assertCompiledModelCurrent, type CompiledMjcf, type CurrentModelBinding } from './compiler.js';
import { assertQualifiedMujocoSettings } from './mujocoAsset.js';
import { readCwS01Xml } from './mujocoXml.js';

export const CW_S04_GESTURE = 'seedcore.cw-s04.gesture.v1' as const;
export const CW_S04_COMPILER = 'seedcore.cw-s04.hermite.v1' as const;
export const CW_S04_MAX_TICKS = 120;
export const CW_S04_DT = 0.002;
export const CW_S04_MAX_BODIES = 5;
export interface GestureBinding extends CurrentModelBinding { revisionDigest: string; authorityEpoch: number }
export interface GestureKnot { tick: number; positionRad: number; velocityRadS: number }
export interface GestureTrack {
  jointId: string;
  maxVelocityRadS: number;
  maxAccelerationRadS2: number;
  knots: GestureKnot[];
}
export interface GestureDraft {
  schemaVersion: typeof CW_S04_GESTURE;
  scope: 'offline_simulation_only'; physicalAcceptance: false; executionAuthority: 'none';
  name: string;
  binding: GestureBinding;
  interpolation: 'cubic_hermite';
  durationTicks: number;
  timeScale: number;
  loops: number;
  tracks: GestureTrack[];
  /** A display-only indicator, not an electrical output or catalog device. */
  virtualLed: { tick: number; color: string }[];
}
export interface GestureSegment {
  startTick: number; endTick: number;
  coefficients: [number, number, number, number];
  minPositionRad: number; maxPositionRad: number;
  maxVelocityRadS: number; maxAccelerationRadS2: number;
}
export interface CompiledGesture {
  compiler: typeof CW_S04_COMPILER;
  draft: GestureDraft;
  totalTicks: number;
  tracks: { jointId: string; segments: GestureSegment[] }[];
  gestureDigest: string;
}
export class GestureError extends Error {
  constructor(readonly code: 'GESTURE_INVALID' | 'GESTURE_BINDING_MISMATCH' | 'GESTURE_BOUNDS' | 'REPLAY_INVALID', message: string) {
    super(`${code}: ${message}`); this.name = 'GestureError';
  }
}
const fail = (message: string): never => { throw new GestureError('GESTURE_INVALID', message); };
export const gestureHash = (value: unknown): string => sha256Hex(canonicalAssemblyString(value));
export function freezeGestureValue<T>(value: T): T {
  if (value && typeof value === 'object') {
    for (const child of Object.values(value)) freezeGestureValue(child);
    Object.freeze(value);
  }
  return value;
}
function record(value: any, keys: string[], at: string): void {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).length !== keys.length || keys.some(k => !Object.hasOwn(value, k))) fail(`Unexpected fields at ${at}`);
}
function number(value: any, max: number, at: string): void {
  if (typeof value !== 'number' || !Number.isFinite(value) || Math.abs(value) > max) fail(`Invalid finite number at ${at}`);
}
function integer(value: any, min: number, max: number, at: string): void {
  if (!Number.isSafeInteger(value) || value < min || value > max) fail(`Invalid integer at ${at}`);
}
export function assertGestureBinding(actual: GestureBinding, expected: GestureBinding): void {
  const keys = ['revisionDigest','assemblyDigest','catalogDigest','drcDigest','modelDigest','authorityEpoch'] as const;
  record(actual, [...keys], 'binding'); record(expected, [...keys], 'expected binding');
  for (const key of keys) {
    if (key === 'authorityEpoch') integer(actual[key], 0, Number.MAX_SAFE_INTEGER, key);
    else if (typeof actual[key] !== 'string' || !/^[a-f0-9]{64}$/.test(actual[key])) fail(`Invalid digest ${key}`);
    if (actual[key] !== expected[key]) throw new GestureError('GESTURE_BINDING_MISMATCH', `Changed ${key}; recompile the gesture`);
  }
}

/** Clones and bounds both raw text (including duplicate keys) and direct JS inputs. */
export function parseGestureDraft(raw: unknown): GestureDraft {
  let text: string;
  try { text = typeof raw === 'string' ? raw : canonicalAssemblyString(raw); }
  catch { return fail('Gesture must be declarative JSON'); }
  if (new TextEncoder().encode(text).length > 65536) fail('Gesture exceeds 64 KiB');
  let d: any;
  try { d = parseStrictJson(text); } catch (e) { return fail(String(e)); }
  record(d, ['schemaVersion','scope','physicalAcceptance','executionAuthority','name','binding','interpolation','durationTicks','timeScale','loops','tracks','virtualLed'], 'gesture');
  if (d.schemaVersion !== CW_S04_GESTURE || d.scope !== 'offline_simulation_only' || d.physicalAcceptance !== false ||
      d.executionAuthority !== 'none' || d.interpolation !== 'cubic_hermite') fail('Unsupported gesture scope/interpolation');
  if (typeof d.name !== 'string' || !d.name.trim() || d.name.length > 80) fail('Name must contain 1–80 characters');
  assertGestureBinding(d.binding, d.binding);
  integer(d.durationTicks, 1, CW_S04_MAX_TICKS, 'durationTicks');
  number(d.timeScale, 4, 'timeScale'); if (d.timeScale < 0.25) fail('timeScale must be 0.25–4');
  integer(d.loops, 1, 4, 'loops');
  integer(d.durationTicks * d.timeScale * d.loops, 1, CW_S04_MAX_TICKS, 'scaled total ticks');
  if (!Array.isArray(d.tracks) || d.tracks.length < 1 || d.tracks.length > 3) fail('Require 1–3 joint tracks');
  const ids = new Set<string>();
  for (const t of d.tracks) {
    record(t, ['jointId','maxVelocityRadS','maxAccelerationRadS2','knots'], 'track');
    if (typeof t.jointId !== 'string' || !/^[a-zA-Z0-9_.-]{1,80}$/.test(t.jointId) || ids.has(t.jointId)) fail('Invalid/duplicate joint ID');
    ids.add(t.jointId);
    number(t.maxVelocityRadS, 100, 'maxVelocityRadS'); number(t.maxAccelerationRadS2, 1000, 'maxAccelerationRadS2');
    if (t.maxVelocityRadS <= 0 || t.maxAccelerationRadS2 <= 0) fail('Curve limits must be positive');
    if (!Array.isArray(t.knots) || t.knots.length < 2 || t.knots.length > 32) fail('Require 2–32 knots per joint');
    let previous = -1;
    for (const k of t.knots) {
      record(k, ['tick','positionRad','velocityRadS'], 'knot');
      integer(k.tick, 0, d.durationTicks, 'knot.tick');
      integer(k.tick * d.timeScale, 0, CW_S04_MAX_TICKS, 'scaled knot.tick');
      if (k.tick <= previous) fail('Knot ticks must strictly increase'); previous = k.tick;
      number(k.positionRad, 10, 'positionRad'); number(k.velocityRadS, 100, 'velocityRadS');
    }
    if (t.knots[0].tick !== 0 || t.knots.at(-1).tick !== d.durationTicks ||
        t.knots[0].velocityRadS !== 0 || t.knots.at(-1).velocityRadS !== 0) fail('Every track must span the timeline with zero endpoint velocity');
    if (d.loops > 1 && t.knots[0].positionRad !== t.knots.at(-1).positionRad) fail('Loop seam must return to the initial position');
  }
  if (!Array.isArray(d.virtualLed) || d.virtualLed.length < 1 || d.virtualLed.length > 32) fail('Require 1–32 virtual LED cues');
  let previous = -1;
  for (const cue of d.virtualLed) {
    record(cue, ['tick','color'], 'virtualLed'); integer(cue.tick, 0, d.durationTicks, 'virtualLed.tick');
    integer(cue.tick * d.timeScale, 0, CW_S04_MAX_TICKS, 'scaled LED tick');
    if (cue.tick <= previous || typeof cue.color !== 'string' || !/^#[0-9a-f]{6}$/.test(cue.color)) fail('Invalid virtual LED cue');
    previous = cue.tick;
  }
  if (d.virtualLed[0].tick !== 0) fail('Virtual LED needs an explicit initial cue');
  return d as GestureDraft;
}
const position = ([a,b,c,d]: readonly number[], u: number) => ((a*u+b)*u+c)*u+d;
function quadraticRoots(a: number, b: number, c: number): number[] {
  if (a === 0) return b === 0 ? [] : [-c/b];
  const disc = b*b - 4*a*c;
  if (disc < 0) return [];
  const q = -0.5 * (b + (b >= 0 ? 1 : -1) * Math.sqrt(disc));
  return q === 0 ? [0] : [q/a, c/q];
}
/** Analytic extrema, including interiors; never endpoint-only sampling. */
function segment(k0: GestureKnot, k1: GestureKnot, scale: number): GestureSegment {
  const sourceSeconds = (k1.tick-k0.tick)*CW_S04_DT, seconds = sourceSeconds*scale;
  const [p0,p1,v0,v1] = [k0.positionRad,k1.positionRad,k0.velocityRadS,k1.velocityRadS];
  const coefficients: [number,number,number,number] = [2*(p0-p1)+sourceSeconds*(v0+v1), 3*(p1-p0)-sourceSeconds*(2*v0+v1), sourceSeconds*v0, p0];
  const [a,b,c] = coefficients;
  const interior = (v: number) => v > 0 && v < 1;
  const positions = [p0,p1,...quadraticRoots(3*a,2*b,c).filter(interior).map(u => position(coefficients,u))];
  const velocities = [0,1,...(a === 0 ? [] : [-b/(3*a)].filter(interior))].map(u => Math.abs((3*a*u*u+2*b*u+c)/seconds));
  const accelerations = [Math.abs(2*b/(seconds*seconds)), Math.abs((6*a+2*b)/(seconds*seconds))];
  return {startTick:k0.tick*scale,endTick:k1.tick*scale,coefficients,
    minPositionRad:Math.min(...positions),maxPositionRad:Math.max(...positions),
    maxVelocityRadS:Math.max(...velocities),maxAccelerationRadS2:Math.max(...accelerations)};
}

export function compileGesture(raw: unknown, model: CompiledMjcf, expected: GestureBinding): CompiledGesture {
  const draft = parseGestureDraft(raw);
  assertGestureBinding(draft.binding, expected); assertCompiledModelCurrent(model, expected); assertQualifiedMujocoSettings(model);
  if (model.manifest.catalogProvenance !== 'synthetic_fixture' || model.manifest.options.actuatorMode !== 'position' ||
      model.manifest.joints.length < 1 || model.manifest.joints.length > 3 || model.manifest.bodies.length > CW_S04_MAX_BODIES) {
    fail('CW-S04 v1 supports synthetic CW-S02 position fixtures with at most five bodies only');
  }
  const xml = readCwS01Xml(model.xml);
  const tracks = model.manifest.joints.map(j => {
    const t = draft.tracks.find(t => t.jointId === j.jointId);
    if (!t || draft.tracks.length !== model.manifest.joints.length) return fail('Require exactly one track for each model joint');
    if (t.knots[0].positionRad !== j.restAngleRad) fail('Initial target must equal the model home');
    if (t.maxVelocityRadS > j.maxVelocityRadS) throw new GestureError('GESTURE_BOUNDS','Target velocity limit exceeds model metadata');
    const joint = xml.find(e => e.tag === 'joint' && e.attrs.name === j.jointName);
    const actuator = xml.find(e => e.tag === 'position' && e.attrs.name === j.actuatorName && e.attrs.joint === j.jointName);
    if (!joint || !actuator) return fail('Joint/position actuator mapping missing');
    const [lo,hi] = joint.attrs.range.split(' ').map(Number), [clo,chi] = actuator.attrs.ctrlrange.split(' ').map(Number);
    const segments = t.knots.slice(1).map((k,i) => segment(t.knots[i],k,draft.timeScale));
    for (const s of segments) {
      if (![s.minPositionRad,s.maxPositionRad,s.maxVelocityRadS,s.maxAccelerationRadS2].every(Number.isFinite) ||
          s.minPositionRad < Math.max(lo,clo) || s.maxPositionRad > Math.min(hi,chi) ||
          s.maxVelocityRadS > t.maxVelocityRadS || s.maxAccelerationRadS2 > t.maxAccelerationRadS2) {
        throw new GestureError('GESTURE_BOUNDS',`Full curve exceeds target position/velocity/acceleration bounds for ${j.jointId}`);
      }
    }
    return {jointId:j.jointId,segments};
  });
  // Canonical joint order; input is cloned, and every retained value is immutable.
  draft.tracks = tracks.map(t => draft.tracks.find(source => source.jointId === t.jointId)!);
  const payload = {compiler:CW_S04_COMPILER,draft,totalTicks:draft.durationTicks*draft.timeScale*draft.loops,tracks};
  return freezeGestureValue({...payload,gestureDigest:gestureHash(payload)});
}
export function assertCompiledGestureCurrent(compiled: CompiledGesture, model: CompiledMjcf, expected: GestureBinding, expectedDigest: string): void {
  const fresh = compileGesture(compiled.draft, model, expected);
  if (fresh.gestureDigest !== expectedDigest || canonicalAssemblyString(fresh) !== canonicalAssemblyString(compiled)) {
    throw new GestureError('GESTURE_BINDING_MISMATCH','Changed gesture or compilation; fresh compilation required');
  }
}
/** Evaluate an already compiled immutable gesture in simulation ticks; no state mutation. */
export function gestureFrameAtTick(compiled: CompiledGesture, tick: number): { targetRad: number[]; virtualLed: string } {
  integer(tick, 0, compiled.totalTicks, 'playback tick');
  const duration = compiled.draft.durationTicks*compiled.draft.timeScale;
  const local = tick === compiled.totalTicks ? duration : tick % duration;
  return {targetRad:compiled.tracks.map((t,i) => {
    // Preserve authored endpoint/seam values exactly; Horner rounding must not
    // introduce a discontinuity or an out-of-range control at a valid knot.
    const knot = compiled.draft.tracks[i].knots.find(k => k.tick*compiled.draft.timeScale === local);
    if (knot) return knot.positionRad;
    const s = t.segments.find(s => local <= s.endTick)!;
    return position(s.coefficients,(local-s.startTick)/(s.endTick-s.startTick));
  }),virtualLed:compiled.draft.virtualLed.filter(c => c.tick*compiled.draft.timeScale <= local).at(-1)!.color};
}
export function createTabletopGestureExample(model: CompiledMjcf, binding: GestureBinding): GestureDraft {
  return {schemaVersion:CW_S04_GESTURE,scope:'offline_simulation_only',physicalAcceptance:false,executionAuthority:'none',
    name:'Synthetic tabletop tilt and return',binding:{...binding},interpolation:'cubic_hermite',durationTicks:120,timeScale:1,loops:1,
    tracks:model.manifest.joints.map((j,i) => ({jointId:j.jointId,maxVelocityRadS:Math.min(0.1,j.maxVelocityRadS),maxAccelerationRadS2:10,
      knots:[{tick:0,positionRad:j.restAngleRad,velocityRadS:0},{tick:60,positionRad:j.restAngleRad+(i%2 ? -0.001 : 0.001),velocityRadS:0},{tick:120,positionRad:j.restAngleRad,velocityRadS:0}]})),
    virtualLed:[{tick:0,color:'#4d8064'},{tick:60,color:'#d19b42'},{tick:120,color:'#4d8064'}]};
}
