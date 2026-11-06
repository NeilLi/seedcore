/** CW-E01 draft design export. Content hashes describe bytes, never authority. */
import {
  assertComponentStructure, canonicalAssemblyString, parseStrictJson, validateAssemblyStructure,
} from '@seedcore/contracts';
import { evaluateAssemblyDrc, parseDrcCatalogFromRaw, sha256Hex } from '@seedcore/drc-solver';
import { compileAssemblyToMjcf, CwS01Error, type CompilerInput } from './compiler.js';

export const BUILD_PACK_MAX_SOURCE_BYTES = 2 * 1024 * 1024;
export const BUILD_PACK_MAX_BYTES = 8 * 1024 * 1024;
export const BUILD_PACK_MAX_FILES = 288;
export interface BuildPackManifest {
  schemaVersion: 'seedcore.cw-e01.build-pack.v1';
  scope: 'offline_design_only'; status: 'draft'; physicalAcceptance: false; executionAuthority: 'none';
  bindings: { assemblyDigest: string; catalogDigest: string; drcDigest: string; drcOptionsDigest: string; compilerOptionsDigest: string };
  bom: { knownSubtotalUsd: number; unpricedPartCount: number; completePricing: boolean };
  wiring: { status: 'unreviewed_design_only'; explicitNetCount: number; unresolvedNetCount: number };
  model: { included: boolean; reason: string | null; modelDigest: string | null };
  omittedAssets: { visualMeshes: true; printableCad: true; firmware: true };
  inventoryScope: 'all_payload_files_excluding_manifest';
  files: { path: string; bytes: number; sha256: string }[];
}
export interface BuildPackResult {
  bytes: Uint8Array;
  manifest: BuildPackManifest;
  files: readonly { path: string; bytes: Uint8Array }[];
}
const encoder = new TextEncoder();
const json = (value: unknown): string => canonicalAssemblyString(value) + '\n';
const digest = (value: unknown): string => sha256Hex(canonicalAssemblyString(value));
const lexical = (a: string, b: string): number => a < b ? -1 : a > b ? 1 : 0;
const fail = (message: string): never => { throw new Error(`CW-E01: ${message}`); };

/** All text cells are quoted; formula prefixes, including hidden whitespace, become literal text. */
export function buildPackCsvCell(value: string | number | null): string {
  let text = value === null ? '' : String(value);
  if (/^[\s\u0000-\u001f\u007f]*[=+@-]/u.test(text) || /^[\t\r\n]/u.test(text)) text = "'" + text;
  return '"' + text.replace(/"/g, '""') + '"';
}
const xmlText = (text: string): string => text.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]/g, '\ufffd')
  .replace(/[<>&"']/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' })[c]!);
function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = crc >>> 1 ^ (crc & 1 ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

/** STORE-only archive: no compression, imported archives, timestamps or caller-selected paths. */
function zipStore(files: readonly { path: string; bytes: Uint8Array }[]): Uint8Array {
  if (files.length > BUILD_PACK_MAX_FILES) fail('Archive file-count bound exceeded');
  const names = new Set<string>();
  let localSize = 0, centralSize = 0;
  for (const file of files) {
    if (!/^[a-zA-Z0-9][a-zA-Z0-9._/-]*$/.test(file.path) || file.path.split('/').some(p => !p || p === '.' || p === '..') || names.has(file.path)) fail('Unsafe or duplicate archive path');
    names.add(file.path);
    const length = encoder.encode(file.path).length;
    localSize += 30 + length + file.bytes.length; centralSize += 46 + length;
    if (localSize + centralSize + 22 > BUILD_PACK_MAX_BYTES) fail('Archive byte bound exceeded');
  }
  const zip = new Uint8Array(localSize + centralSize + 22), view = new DataView(zip.buffer);
  let local = 0, central = localSize;
  const u16 = (at: number, value: number) => view.setUint16(at, value, true);
  const u32 = (at: number, value: number) => view.setUint32(at, value, true);
  for (const file of files) {
    const name = encoder.encode(file.path), crc = crc32(file.bytes), size = file.bytes.length;
    u32(local, 0x04034b50); u16(local+4, 20); u16(local+6, 0x0800); u16(local+8, 0);
    u16(local+10, 0); u16(local+12, 0x0021); // 1980-01-01 00:00:00
    u32(local+14, crc); u32(local+18, size); u32(local+22, size); u16(local+26, name.length);
    zip.set(name, local+30); zip.set(file.bytes, local+30+name.length);
    u32(central, 0x02014b50); u16(central+4, 20); u16(central+6, 20); u16(central+8, 0x0800); u16(central+10, 0);
    u16(central+12, 0); u16(central+14, 0x0021); u32(central+16, crc); u32(central+20, size); u32(central+24, size);
    u16(central+28, name.length); u32(central+38, 0x20); u32(central+42, local); zip.set(name, central+46);
    local += 30 + name.length + size; central += 46 + name.length;
  }
  u32(central, 0x06054b50); u16(central+8, files.length); u16(central+10, files.length);
  u32(central+12, centralSize); u32(central+16, localSize);
  return zip;
}

/** Independently validate all supplied bytes and recompute DRC before exporting any draft. */
export function createBuildPack(input: CompilerInput): BuildPackResult {
  const assembly = validateAssemblyStructure(input.assembly), source = input.catalog;
  if (!source || !Array.isArray(source.partDocuments) || source.partDocuments.length > 256
    || !['verified_local_catalog', 'synthetic_fixture'].includes(source.provenance ?? 'verified_local_catalog')) fail('Invalid catalog');
  let sourceBytes = encoder.encode(source.catalogRawJson).length;
  for (const part of source.partDocuments) {
    if (typeof part.raw_json !== 'string') fail('Invalid component bytes');
    sourceBytes += encoder.encode(part.raw_json).length;
    if (sourceBytes > BUILD_PACK_MAX_SOURCE_BYTES) fail('Catalog exceeds 2 MiB input bound');
  }
  if (sourceBytes > BUILD_PACK_MAX_SOURCE_BYTES) fail('Catalog exceeds 2 MiB input bound');
  const index = parseStrictJson(source.catalogRawJson) as { schema_version: string; parts: { part_id: string; version: string; path: string; sha256: string }[] };
  if (index.schema_version !== 'seedcore.component-catalog.v1' || !Array.isArray(index.parts)) fail('Unsupported source catalog');
  const paths = new Set<string>();
  for (const pin of index.parts) {
    if (typeof pin.path !== 'string' || !/^parts\/[a-zA-Z0-9_.-]+\.sc-part\.json$/.test(pin.path) || pin.path.includes('..') || paths.has(pin.path)) fail('Unsafe or duplicate source part path');
    paths.add(pin.path);
  }
  const catalog = parseDrcCatalogFromRaw(source);
  const documents = source.partDocuments.map(document => {
    const part = parseStrictJson(document.raw_json) as any;
    assertComponentStructure(part);
    if (!/^assets\/[a-zA-Z0-9_.-]+\.glb$/.test(part.mechanical.visual_mesh.uri) || part.mechanical.visual_mesh.uri.includes('..')) fail('Unsafe visual asset reference');
    return { document, part };
  }).sort((a, b) => lexical(a.document.part_id, b.document.part_id));
  const drc = evaluateAssemblyDrc(assembly, catalog, input.drcOptions);
  if (canonicalAssemblyString(drc) !== canonicalAssemblyString(input.drcReport)) fail('Stale or altered DRC report');
  // Options remain a bound, validated input even when this design cannot compile.
  const options = input.options;
  if (!options || Object.keys(options).some(k => !['actuatorMode', 'positionGain', 'timestepSeconds'].includes(k))
    || !['position', 'torque'].includes(options.actuatorMode)
    || (options.timestepSeconds !== undefined && (!Number.isFinite(options.timestepSeconds) || options.timestepSeconds < 0.0001 || options.timestepSeconds > 0.01))
    || (options.positionGain !== undefined && (options.actuatorMode !== 'position' || !Number.isFinite(options.positionGain) || options.positionGain <= 0 || options.positionGain > 1000))) fail('Invalid compiler options');
  const files: { path: string; bytes: Uint8Array }[] = [];
  const inventory: BuildPackManifest['files'] = [];
  const add = (path: string, text: string): void => {
    const bytes = encoder.encode(text);
    if (bytes.length > BUILD_PACK_MAX_SOURCE_BYTES) fail('Individual artifact byte bound exceeded');
    files.push({ path, bytes }); inventory.push({ path, bytes: bytes.length, sha256: sha256Hex(text) });
  };
  add('assembly.sc-assembly.json', json(assembly));
  add('source/catalog.json', source.catalogRawJson);
  const sourceMap = documents.map(({document}, n) => {
    const path = `source/parts/${String(n).padStart(4, '0')}.sc-part.json`;
    add(path, document.raw_json);
    return { partId: document.part_id, path, originalCatalogPath: index.parts.find(p => p.part_id === document.part_id)!.path, sha256: sha256Hex(document.raw_json) };
  });
  add('source/part-map.json', json(sourceMap));
  add('drc-report.json', json(drc));
  add('drc-options.json', json(input.drcOptions ?? {}));
  add('compiler-options.json', json(options));
  const csv = [['part_id','version','name','status','quantity','unit_cost_usd','cost_basis','line_total_usd','node_ids'],
    ...drc.bom.lines.map(line => [line.partId,line.version,line.name,line.status,line.quantity,line.unitCostUsd,line.costBasis,line.lineTotalUsd,line.nodeIds.join(';')])];
  add('bom.csv', csv.map(row => row.map(buildPackCsvCell).join(',')).join('\r\n')+'\r\n');
  add('bom-summary.json', json(drc.bom));
  const netLines = assembly.electrical_nets.flatMap(net => [
    `${net.net_id} | ${net.kind} | UNREVIEWED / unresolved physical wiring`,
    ...net.endpoints.map(ep => `  ${ep.node_id} : ${ep.interface_id} | ${ep.pins?.length ? 'declared pins: '+ep.pins.join(', ') : 'pins unspecified'}`),
  ]);
  const svgLines = ['Draft design only; not a reviewed wiring instruction.', 'Only declared nets/endpoints shown; no inferred connections.', ...netLines]
    .flatMap(line => {
      const characters = Array.from(line.replace(/[\t\r\n]/g, ' ')), rows: string[] = [];
      for (let start=0;start<characters.length;start+=118) rows.push(characters.slice(start,start+118).join(''));
      return rows;
    });
  if (svgLines.length > 1024) fail('Electrical drawing exceeds 1024 rendered lines');
  add('wiring.svg', `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="${Math.max(100, 35+svgLines.length*22)}" viewBox="0 0 960 ${Math.max(100, 35+svgLines.length*22)}"><title>Unreviewed electrical net inventory</title><rect width="100%" height="100%" fill="white"/>${svgLines.map((line,n) => `<text x="16" y="${25+n*22}" fill="black" font-family="monospace" font-size="12">${xmlText(line)}</text>`).join('')}</svg>\n`);
  add('asset-references.json', json({ scope:'reference_inventory_only',physicalAcceptance:false,executionAuthority:'none',
    statement:'No external visual, CAD, firmware or print files are included. Declared source license strings do not establish rights or verify external asset bytes.',
    parts:documents.map(({document,part}) => ({partId:document.part_id,visualMesh:part.mechanical.visual_mesh,
      assetBytesIncluded:false,assetBytesVerified:false,printReady:false,rightsReview:'not_established',supplierReferences:part.identity.supplier_skus})) }));
  let model: BuildPackManifest['model'];
  try {
    const compiled = compileAssemblyToMjcf(input);
    add('model.mjcf.xml', compiled.xml); add('model.cw-s01.json', json(compiled));
    model = { included:true,reason:null,modelDigest:compiled.modelDigest };
  } catch (error) {
    // Only unsupported/blocked model readiness can produce a useful draft without a model.
    if (!(error instanceof CwS01Error) || !['UNSUPPORTED_SUBSET','DRC_NOT_READY','SEMANTIC_INVALID'].includes(error.code)) throw error;
    model = { included:false,reason:error.message,modelDigest:null };
  }
  add('README.txt', 'SeedCore CW-E01 draft design pack\nScope: offline design only; physicalAcceptance: false; executionAuthority: none.\nThis archive does not grant runtime admission, wiring, fabrication or motor authority.\nThe full DRC report is retained, including every blocked/conflict finding. Unknown prices are blank in BOM CSV and excluded from the known subtotal; bom-summary.json preserves counts.\nwiring.svg lists only explicit unreviewed nets and pins; do not wire from it. No print-ready CAD, visual meshes, firmware images or secrets are included. asset-references.json records unverified external references and declared licenses without establishing rights.\nOriginal catalog and part document bytes are preserved; source/part-map.json maps catalog paths to generated archive paths.\nMJCF/model files are included only when the existing compiler accepts the source; this is not runtime/device qualification. Compiler and DRC options are saved and bound. No gesture, execution token, signer context, signed receipt or evidence bundle is included; existing CW-G02 exports retain their separate scope.\nmanifest.json hashes every other archive entry, excluding itself to avoid a circular hash. Re-exporting identical content is byte-identical (ZIP STORE, fixed 1980 timestamp). This exporter does not import or decompress archives.\n');
  inventory.sort((a,b) => lexical(a.path,b.path));
  const manifest: BuildPackManifest = {
    schemaVersion:'seedcore.cw-e01.build-pack.v1',scope:'offline_design_only',status:'draft',physicalAcceptance:false,executionAuthority:'none',
    bindings:{assemblyDigest:drc.assemblyDigest,catalogDigest:drc.catalogDigest,drcDigest:digest(drc),drcOptionsDigest:digest(input.drcOptions ?? {}),compilerOptionsDigest:digest(options)},
    bom:{knownSubtotalUsd:drc.bom.knownSubtotalUsd,unpricedPartCount:drc.bom.unpricedPartCount,completePricing:drc.bom.completePricing},
    wiring:{status:'unreviewed_design_only',explicitNetCount:assembly.electrical_nets.length,unresolvedNetCount:assembly.electrical_nets.length},
    model,omittedAssets:{visualMeshes:true,printableCad:true,firmware:true},inventoryScope:'all_payload_files_excluding_manifest',files:inventory,
  };
  // Do not add the manifest to its own inventory.
  files.push({path:'manifest.json',bytes:encoder.encode(json(manifest))});
  files.sort((a,b) => lexical(a.path,b.path));
  return {bytes:zipStore(files),manifest,files};
}
