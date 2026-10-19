import {build} from 'esbuild';
import {mkdir,copyFile,readFile,writeFile} from 'node:fs/promises';
await mkdir('dist',{recursive:true});
await build({entryPoints:['src/app.ts'],outfile:'dist/app.js',bundle:true,format:'esm',platform:'browser',target:'es2022',legalComments:'inline'});
for(const file of ['index.html','app.css','favicon.svg']) await copyFile(`src/${file}`,`dist/${file}`);
const notices = await Promise.all(['three/LICENSE','ajv/LICENSE','fast-deep-equal/LICENSE'].map(async name=>`${name}\n${await readFile(`../../node_modules/${name}`,'utf8')}`));
await writeFile('dist/third-party-notices.txt',notices.join('\n\n'));
