import { CwS02Error } from './mujocoAsset.js';

// A closed grammar for the compiler's own output, not a general MJCF importer.
// In particular no <size memory=...>, replication, defaults, assets or extensions
// may allocate resources or introduce state before topology checks run.
const attributes: Record<string, readonly string[]> = {
  mujoco: ['model'], compiler: ['angle','inertiafromgeom','fusestatic','balanceinertia'],
  option: ['timestep','gravity'], worldbody: [], actuator: [],
  body: ['name','pos','quat'],
  joint: ['name','type','pos','axis','ref','limited','range','actuatorfrclimited','actuatorfrcrange'],
  inertial: ['pos','mass','fullinertia'],
  geom: ['name','type','size','mass','contype','conaffinity'],
  position: ['name','joint','gear','ctrllimited','forcelimited','forcerange','kp','ctrlrange'],
  motor: ['name','joint','gear','ctrllimited','forcelimited','forcerange','ctrlrange'],
};
const children: Record<string, readonly string[]> = {
  '': ['mujoco'], mujoco: ['compiler','option','worldbody','actuator'],
  worldbody: ['body'], body: ['joint','inertial','geom','body'], actuator: ['position','motor'],
};
export interface CwS01XmlElement { tag: string; attrs: Record<string, string> }
export function readCwS01Xml(xml: string): CwS01XmlElement[] {
  const reject = (): never => { throw new CwS02Error('UNSUPPORTED_SUBSET', 'Require bounded, asset-free CW-S01 compiler XML; arbitrary MJCF elements/attributes are unsupported'); };
  if (typeof xml !== 'string' || new TextEncoder().encode(xml).length > 131072) reject();
  const result: CwS01XmlElement[] = [], stack: string[] = [];
  let offset = 0, roots = 0;
  for (const token of xml.matchAll(/<[^<>]*>/g)) {
    if (xml.slice(offset, token.index).trim()) reject();
    offset = token.index! + token[0].length;
    const m = /^<(\/?)([a-z]+)((?:\s+[a-z][a-z0-9_]*="[^"<>&]*")*)\s*(\/?)>$/.exec(token[0]);
    if (!m || !Object.hasOwn(attributes, m[2])) reject();
    const [, closing, tag, raw, selfClosing] = m!;
    if (closing) { if (raw.trim() || selfClosing || stack.pop() !== tag) reject(); continue; }
    const parent = stack.at(-1) ?? '';
    if (!children[parent]?.includes(tag) || (parent === '' && ++roots !== 1)) reject();
    const attrs: Record<string, string> = {};
    for (const a of raw.matchAll(/([a-z][a-z0-9_]*)="([^"]*)"/g)) {
      if (!attributes[tag].includes(a[1]) || Object.hasOwn(attrs, a[1])) reject();
      attrs[a[1]] = a[2];
    }
    if (Object.keys(attrs).length !== attributes[tag].length) reject();
    const constant: Record<string, string> = tag === 'mujoco' ? {model:'seedcore_cw_s01'} :
      tag === 'compiler' ? {angle:'radian',inertiafromgeom:'false',fusestatic:'false',balanceinertia:'false'} :
      tag === 'option' ? {gravity:'0 0 -9.81'} :
      tag === 'geom' ? {type:'box',mass:'0',contype:'0',conaffinity:'0'} :
      tag === 'joint' ? {type:'hinge',limited:'true',actuatorfrclimited:'true'} :
      ['position','motor'].includes(tag) ? {gear:'1',ctrllimited:'true',forcelimited:'true'} : {};
    for (const [key, value] of Object.entries(constant)) if (attrs[key] !== value) reject();
    for (const [key, value] of Object.entries(attrs)) {
      if (key in constant) continue;
      if (key === 'name' || key === 'joint') {
        if (!/^cw_(body|joint|actuator|box)_\d+$/.test(value)) reject();
      } else {
        const n = value.split(' ').map(Number);
        const size = ['pos','axis','size','gravity'].includes(key) ? 3 : key === 'quat' ? 4 :
          key === 'fullinertia' ? 6 : ['range','actuatorfrcrange','forcerange','ctrlrange'].includes(key) ? 2 : 1;
        if (!value.trim() || n.length !== size || n.some(v => !Number.isFinite(v) || Math.abs(v) > 1e9)) reject();
      }
    }
    if (tag === 'geom' && attrs.size.split(' ').map(Number).some(v => v <= 0 || v > 0.5)) reject();
    if (tag === 'inertial' && (Number(attrs.mass) <= 0 || Number(attrs.mass) > 5)) reject();
    result.push({ tag, attrs });
    if (result.length > 256 || (tag === 'body' && result.filter(e => e.tag === tag).length > 32) ||
        (tag === 'joint' && result.filter(e => e.tag === tag).length > 3)) reject();
    if (!selfClosing) stack.push(tag);
  }
  if (stack.length || roots !== 1 || xml.slice(offset).trim()) reject();
  for (const tag of ['compiler','option','worldbody','actuator']) if (result.filter(e => e.tag === tag).length !== 1) reject();
  if (result.filter(e => e.tag === 'inertial').reduce((sum, e) => sum + Number(e.attrs.mass), 0) > 5) reject();
  return result;
}
