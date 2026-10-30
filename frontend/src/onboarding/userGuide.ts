// docs/USER_GUIDE.md, generated from the guide text, the hint registry and HOTKEYS (design 12 section 6).
// `npm run gen-guide` writes it; userGuide.test.ts fails when the committed file drifts from this output.
import { HOTKEYS, LOCAL_KEYS, SCOPE_TITLES, type HotkeyScope } from "../hotkeys";
import { GLOSSARY } from "./glossary";
import { GUARANTEES, GUIDE_STEPS, copyText, keyLabel, keycap } from "./guide";

const code = (s: string): string => `\`${s}\``;
const cell = (s: string): string => s.replace(/\|/g, "\\|");
const keys = (ks: string[]): string => ks.map((k) => code(keycap(k))).join(" / ");

export const USER_GUIDE_HEADER = "Generated from frontend/src; edit there";

export function renderUserGuide(): string {
  const out: string[] = [];
  out.push("# Manual Labor user guide", "");
  out.push(
    `> ${USER_GUIDE_HEADER} (onboarding/guide.ts, onboarding/hints.ts, hotkeys.ts), then run \`npm run gen-guide\` in frontend/. A test fails when this file and the source disagree.`,
    "",
  );
  out.push("## Getting started", "");
  out.push("Manual Labor turns PDF and DOCX manuals into a reviewed knowledge base in four steps. The same text is shown in the app's guide panel and in Help.", "");
  GUIDE_STEPS.forEach((s, i) => {
    const nav = (["goScope", "goVerify", "goAgent", "goExport"] as const)[i];
    out.push(`### ${i + 1}. ${s.title}`, "");
    out.push(`Screen: ${s.route} (key ${code(keyLabel(nav))})`, "");
    out.push(copyText(s.what, (id) => code(keyLabel(id))), "");
    out.push("What to do:", "");
    s.do.forEach((d, j) => out.push(`${j + 1}. ${copyText(d, (id) => code(keyLabel(id)))}`));
    out.push("", "Why you can trust this:", "");
    for (const t of s.trust) out.push(`- ${t}`);
    out.push("");
  });
  out.push("## How it works", "");
  for (const g of GUARANTEES) out.push(`- **${g.claim}** ${g.how}`);
  out.push("");
  out.push("## Keyboard shortcuts", "");
  out.push("Every key below comes from the single hotkey map (frontend/src/hotkeys.ts). Keys never fire while you type in a text field, except where noted.", "");
  for (const scope of Object.keys(SCOPE_TITLES) as HotkeyScope[]) {
    const rows = Object.values(HOTKEYS).filter((h) => h.scope === scope);
    if (!rows.length) continue;
    out.push(`### ${SCOPE_TITLES[scope]}`, "", "| Keys | Action |", "|---|---|");
    for (const h of rows) out.push(`| ${cell(`${h.mod ? "`Ctrl/Cmd`+" : ""}${keys(h.keys)}`)} | ${cell(h.label)}${h.when ? ` (${cell(h.when)})` : ""} |`);
    out.push("");
  }
  out.push("### Inside a widget", "", "| Keys | Where | Action |", "|---|---|---|");
  for (const k of LOCAL_KEYS) out.push(`| ${cell(keys(k.keys))} | ${cell(k.widget)} | ${cell(k.label)} |`);
  out.push("");
  out.push("## Glossary", "");
  for (const g of GLOSSARY) out.push(`- **${g.term}**${g.hotkey ? ` (${code(keyLabel(g.hotkey))})` : ""}: ${g.text}`);
  out.push("");
  out.push("## Reset the guide", "");
  out.push(
    `The welcome on Scope shows once per project and stays hidden after Start with step 1 or I have used this before. To see it again, open Help (${code(keyLabel("help"))}), stay on the Guide tab and choose Show the welcome again. From a script: \`PUT /api/ui/guide\` with the body \`{"seen": false}\`. If the server cannot store the flag, the browser keeps it in localStorage instead.`,
    "",
  );
  return out.join("\n");
}
