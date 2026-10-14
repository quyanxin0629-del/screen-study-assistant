import {build} from 'esbuild';
import {writeFileSync} from 'node:fs';
import {gzipSync} from 'node:zlib';

const result = await build({
  entryPoints: ['renderer.js'], bundle: true, minify: true, format: 'iife',
  globalName: 'StudyMath', platform: 'browser', target: 'es2015', write: false,
});
writeFileSync('../../src/screen_study_assistant/assets/math/renderer.js.gz',
  gzipSync(result.outputFiles[0].contents, {level: 9}));
