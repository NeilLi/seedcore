const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const source = 'packages/component-registry/schema/v2.sc-assembly.schema.json';
const target = path.join(root, 'ts/packages/contracts/src/robotAssemblySchema.ts');
const schema = JSON.parse(fs.readFileSync(path.join(root, source), 'utf8'));
const result = `// Generated from ${source}. Do not edit.\nexport const ROBOT_ASSEMBLY_SCHEMA = ${JSON.stringify(schema, null, 2)} as const;\n`;
if (process.argv.includes('--check')) {
  if (!fs.existsSync(target) || fs.readFileSync(target, 'utf8') !== result) {
    throw new Error('Assembly schema binding is stale; run tools/robotics/generate-assembly-schema.cjs');
  }
} else {
  fs.writeFileSync(target, result);
}
