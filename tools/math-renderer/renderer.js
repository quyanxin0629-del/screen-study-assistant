// Offline SVG output, with no DOM, browser, network, or dynamically loaded extensions.
import {mathjax} from 'mathjax-full/js/mathjax.js';
import {TeX} from 'mathjax-full/js/input/tex.js';
import {SVG} from 'mathjax-full/js/output/svg.js';
import {liteAdaptor} from 'mathjax-full/js/adaptors/liteAdaptor.js';
import {RegisterHTMLHandler} from 'mathjax-full/js/handlers/html.js';
import 'mathjax-full/js/input/tex/base/BaseConfiguration.js';
import 'mathjax-full/js/input/tex/ams/AmsConfiguration.js';
import 'mathjax-full/js/input/tex/newcommand/NewcommandConfiguration.js';

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);

export function render(source, display) {
  // A fresh input processor keeps model-defined macros scoped to this formula.
  const document = mathjax.document('', {
    InputJax: new TeX({
      packages: ['base', 'ams', 'newcommand'],
      maxBuffer: 8192,
      maxMacros: 1000,
      formatError: (_jax, error) => { throw error; },
    }),
    OutputJax: new SVG({fontCache: 'none'}),
  });
  const node = document.convert(source, {display: !!display});
  const svg = adaptor.tags(node, 'svg')[0];
  return JSON.stringify({
    svg: adaptor.outerHTML(svg),
    width: adaptor.getAttribute(svg, 'width'),
    height: adaptor.getAttribute(svg, 'height'),
  });
}
