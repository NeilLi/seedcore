/** Bounded JSON text parsing. Duplicate decoded keys are rejected before validation. */
import { validateAssemblyStructure, type RobotAssembly } from './robotAssemblyContracts.js';

export function parseStrictJson(text: string): unknown {
  if (new TextEncoder().encode(text).length > 262144) throw new Error('JSON exceeds 262144 UTF-8 bytes');
  let at = 0, count = 0;
  const fail = (reason: string): never => { throw new Error(`${reason} at character ${at}`); };
  const whitespace = () => { while (/[ \t\r\n]/.test(text[at] ?? '') && at < text.length) at++; };
  const string = (): string => {
    if (text[at] !== '"') return fail('Expected quoted key');
    const start = at++;
    while (at < text.length) {
      const char = text[at++];
      if (char === '\\') at++;
      else if (char === '"') {
        try { return JSON.parse(text.slice(start, at)) as string; }
        catch { return fail('Invalid JSON string'); }
      }
    }
    return fail('Unterminated string');
  };
  const value = (depth: number): unknown => {
    if (++count > 50000 || depth > 32) return fail('JSON nesting/node bound exceeded');
    whitespace();
    const char = text[at];
    if (char === '"') return string();
    if (char === '{') {
      at++; whitespace();
      const result: Record<string, unknown> = Object.create(null), keys = new Set<string>();
      if (text[at] === '}') { at++; return result; }
      for (;;) {
        whitespace(); const key = string();
        if (++count > 50000) return fail('JSON node bound exceeded');
        if (keys.has(key)) return fail(`Duplicate JSON key ${JSON.stringify(key)}`);
        keys.add(key); whitespace();
        if (text[at++] !== ':') return fail('Expected colon');
        result[key] = value(depth + 1); whitespace();
        const end = text[at++];
        if (end === '}') return result;
        if (end !== ',') return fail('Expected comma or closing brace');
      }
    }
    if (char === '[') {
      at++; whitespace(); const result: unknown[] = [];
      if (text[at] === ']') { at++; return result; }
      for (;;) {
        result.push(value(depth + 1)); whitespace(); const end = text[at++];
        if (end === ']') return result;
        if (end !== ',') return fail('Expected comma or closing bracket');
      }
    }
    for (const [token, result] of [['true', true], ['false', false], ['null', null]] as const) {
      if (text.startsWith(token, at)) { at += token.length; return result; }
    }
    const number = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(text.slice(at));
    if (number) {
      at += number[0].length; const result = Number(number[0]);
      if (!Number.isFinite(result) || (Number.isInteger(result) && !Number.isSafeInteger(result))) return fail('Non-finite or unsafe integer');
      return result;
    }
    return fail('Expected JSON value');
  };
  const result = value(0); whitespace();
  if (at !== text.length) return fail('Trailing JSON text');
  return result;
}

export function parseAssemblyText(text: string): RobotAssembly {
  const raw = parseStrictJson(text);
  if (raw && typeof raw === 'object' && 'schema_version' in raw && raw.schema_version === 'seedcore.assembly.v1') {
    throw new Error('Historical assembly v1 drafts are unsupported; use the v2 starter');
  }
  return validateAssemblyStructure(raw);
}
