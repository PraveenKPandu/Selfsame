// ESM capture loader (registered by esmRegister.mjs via module.register).
//
// For each target module (resolved under the capture root), it reads the export
// names WITHOUT executing the module (es-module-lexer), then returns a synthetic
// wrapper module that imports the real module and re-exports each function
// wrapped with a recorder call. No source mutation, no double-execution.
import { init, parse } from 'es-module-lexer';
import { readFileSync, realpathSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

let ROOT = '';

export function initialize(data) {
  try { ROOT = realpathSync(data.root); } catch { ROOT = data.root; }
}

function underRoot(url) {
  if (!url.startsWith('file://')) return false;
  const p = fileURLToPath(url.split('?')[0]);
  return p.startsWith(ROOT) && !p.includes('/node_modules/');
}

const ORIG = 'selfsame-orig';

export async function load(url, context, nextLoad) {
  // The wrapper imports "<url>?selfsame-orig" — serve the real source for that.
  if (url.includes(ORIG)) return nextLoad(url.split('?')[0], context);

  const clean = url.split('?')[0];
  if (underRoot(url) && /\.(mjs|js)$/.test(clean)) {
    let names;
    try {
      await init;
      const source = readFileSync(fileURLToPath(clean), 'utf8');
      const [, exports] = parse(source);
      names = [...new Set(exports.map((e) => e.n).filter(Boolean))];
    } catch {
      return nextLoad(url, context); // can't lex -> don't wrap (sound under-capture)
    }
    const orig = url + (url.includes('?') ? '&' : '?') + ORIG;
    const rel = fileURLToPath(clean).slice(ROOT.length).replace(/^\//, '');
    let src = `import * as __o from ${JSON.stringify(orig)};\n`;
    src += "const __rec = (k, a) => { try { globalThis.__selfsame_record && globalThis.__selfsame_record(k, a); } catch (e) {} };\n";
    src += "const __isFn = (f) => typeof f === 'function' && !/^class[\\s{]/.test(Function.prototype.toString.call(f));\n";
    for (const name of names) {
      if (name === 'default') {
        const k = JSON.stringify(rel + '::(default)');
        src += `export default __isFn(__o.default) ? function (...a) { __rec(${k}, a); return __o.default.apply(this, a); } : __o.default;\n`;
      } else if (/^[A-Za-z_$][\w$]*$/.test(name)) {
        const ref = `__o[${JSON.stringify(name)}]`;
        const k = JSON.stringify(rel + '::' + name);
        src += `export const ${name} = __isFn(${ref}) ? function (...a) { __rec(${k}, a); return ${ref}.apply(this, a); } : ${ref};\n`;
      }
      // names that aren't valid identifiers are skipped (sound under-capture)
    }
    return { format: 'module', source: src, shortCircuit: true };
  }
  return nextLoad(url, context);
}
