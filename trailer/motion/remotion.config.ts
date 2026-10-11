// Remotion CLI config. The public dir is trailer/build/public, filled by tools/build.py
// (conformed clips in media/, JSON data in data/).
import { Config } from "@remotion/cli/config";

Config.setPublicDir("../build/public");
Config.setVideoImageFormat("jpeg");
Config.setJpegQuality(92);
Config.setConcurrency(2);
Config.setChromiumOpenGlRenderer("swangle");
Config.setOverwriteOutput(true);
// Set REMOTION_BROWSER to use a local Chrome/Chromium instead of the auto-downloaded one.
if (process.env.REMOTION_BROWSER) {
  Config.setBrowserExecutable(process.env.REMOTION_BROWSER);
}
