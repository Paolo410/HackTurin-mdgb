// QC helper: bundle once, render several frames as JPEG contact images.
// usage: node scripts/stills.mjs 90 290 480 ...   (frames at 30 fps) -> ../build/stills/f<frame>.jpg
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const frames = process.argv.slice(2).map(Number);
const serveUrl = await bundle({ entryPoint: path.join(root, "src/index.ts"), publicDir: path.resolve(root, "../build/public") });
const browserExecutable = process.env.REMOTION_BROWSER || null;
const composition = await selectComposition({ serveUrl, id: "Trailer", inputProps: {}, browserExecutable, chromiumOptions: { gl: "swangle" } });
for (const frame of frames) {
  const output = path.resolve(root, `../build/stills/f${String(frame).padStart(4, "0")}.jpg`);
  await renderStill({ composition, serveUrl, output, frame, imageFormat: "jpeg", jpegQuality: 80, browserExecutable,
    chromiumOptions: { gl: "swangle" }, scale: 0.5 });
  console.log("still", frame, output);
}
