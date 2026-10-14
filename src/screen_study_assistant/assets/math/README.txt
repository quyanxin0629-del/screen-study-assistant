Offline formula renderer: MathJax 3.2.2, Apache-2.0.
Built with esbuild 0.25.12 (build tool only), MIT.
Source and lock file: tools/math-renderer/.
Rebuild: cd tools/math-renderer && npm ci && npm run build

The Python app uses Qt's QJSEngine and QSvgRenderer. It does not require Node,
a browser, a CDN, or any network resource at runtime. Only base, AMS and
newcommand TeX extensions are included; network/HTML extensions are absent.
The renderer.js.gz asset is gzip-compressed; Python decompresses it in memory.
See LICENSE-MathJax.txt for the license and upstream notices in the bundle.
