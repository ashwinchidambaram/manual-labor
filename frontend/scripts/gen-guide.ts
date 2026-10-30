// Writes docs/USER_GUIDE.md from the guide text, the hint registry and HOTKEYS.
// Usage: npm run gen-guide (from frontend/). Deterministic: no timestamps.
import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { renderUserGuide } from "../src/onboarding/userGuide";

const out = resolve(dirname(fileURLToPath(import.meta.url)), "../../docs/USER_GUIDE.md");
writeFileSync(out, renderUserGuide());
console.log(`wrote ${out}`);
