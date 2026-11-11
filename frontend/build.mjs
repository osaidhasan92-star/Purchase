import { build, context } from "esbuild";
import { mkdir, readFile, writeFile } from "node:fs/promises";
const options = {
  entryPoints: ["frontend/src/main.tsx"],
  bundle: true,
  outfile: "frontend-dist/workspace-app.js",
  format: "iife",
  target: ["es2020"],
  jsx: "automatic",
  minify: !process.argv.includes("--watch"),
  define: {
    "process.env.NODE_ENV": JSON.stringify(
      process.argv.includes("--watch") ? "development" : "production",
    ),
  },
  legalComments: "none",
  banner: {
    js: "/*! React, React DOM and Scheduler licenses: THIRD_PARTY_LICENSES.txt */",
  },
};
if (process.argv.includes("--watch")) {
  const compiler = await context(options);
  await compiler.watch();
  console.log(
    "Watching frontend/src. Keep Flask running and reload after changes.",
  );
} else await build(options);

await mkdir("frontend-dist", { recursive: true });
const notices = await Promise.all(
  ["react", "react-dom", "scheduler"].map(
    async (name) =>
      name +
      "\n" +
      (await readFile("node_modules/" + name + "/LICENSE", "utf8")),
  ),
);
await writeFile("frontend-dist/THIRD_PARTY_LICENSES.txt", notices.join("\n\n"));
