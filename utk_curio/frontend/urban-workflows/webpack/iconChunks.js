/**
 * Ship the Font Awesome icon chunks as webpack writes them.
 *
 * registry/iconRegistry.ts loads every icon it does not bundle with an
 * `import()` of that icon's own module in @fortawesome's solid or brands pack,
 * so webpack splits each of the 2,582 modules into a chunk of its own (an
 * alias name's chunk also holds the module of the icon it names). A module is
 * an SVG path and a few exports, already compact, so minifying and mapping it
 * gains little, while doing it 2,582 times added about a tenth to the
 * production build (11 to 15 s of about 112 s, measured locally).
 *
 * Before the minimizer runs, this plugin finds the chunks that hold nothing but
 * those modules, marks their files minimized, which TerserPlugin passes over,
 * and drops their source map, so SourceMapDevToolPlugin writes none for them.
 */

const PLUGIN = "IconChunksAsWritten";

const ICON_MODULE = /[\\/]@fortawesome[\\/]free-(solid|brands)-svg-icons[\\/]fa[A-Z0-9][A-Za-z0-9]*\.js$/;

function isIconChunk(chunk, chunkGraph) {
  const modules = chunkGraph.getChunkModules(chunk);
  return modules.length > 0 && modules.every((module) => ICON_MODULE.test(module.resource || ""));
}

class IconChunksAsWritten {
  apply(compiler) {
    const { Compilation, sources } = compiler.webpack;
    compiler.hooks.thisCompilation.tap(PLUGIN, (compilation) => {
      compilation.hooks.processAssets.tap(
        { name: PLUGIN, stage: Compilation.PROCESS_ASSETS_STAGE_OPTIMIZE },
        () => {
          for (const chunk of compilation.chunks) {
            if (!isIconChunk(chunk, compilation.chunkGraph)) continue;
            for (const file of chunk.files) {
              compilation.updateAsset(
                file,
                (source) => new sources.RawSource(source.source()),
                { minimized: true },
              );
            }
          }
        },
      );
    });
  }
}

module.exports = IconChunksAsWritten;
