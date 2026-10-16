// biome-ignore-all lint/plugin: these are the rule's fixtures
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterAll, describe, expect, it } from "vitest";

const frontend = path.join(import.meta.dirname, "..");
const dir = mkdtempSync(path.join(tmpdir(), "no-gap-margins-"));
afterAll(() => rmSync(dir, { recursive: true, force: true }));

const refused = {
  "a margined icon in a button": '<Button><Plus className="mr-2 h-4 w-4" />Add</Button>',
  "a margined label in a menu item":
    '<DropdownMenuItem><Plus /><span className="ml-2">Add</span></DropdownMenuItem>',
  "a margin behind a breakpoint":
    '<Button><Reply /><span className="sr-only sm:not-sr-only sm:ml-1">Reply</span></Button>',
  "a margin in a class list":
    '<CommandItem><Check className={cn("mr-2 h-4 w-4", on)} /></CommandItem>',
  "a margined icon shown on a condition":
    '<Button>{busy && <Loader2 className="mr-1.5 h-4 w-4" />}Save</Button>',
  "a margined icon in either branch":
    '<Button>{busy ? <Spinner /> : <Download className="mr-1.5 h-4 w-4" />}Install</Button>',
  "a margined icon in a fragment":
    '<AlertDialogAction>{busy ? (<><Loader2 className="mr-2 h-4 w-4" />Leaving</>) : "Leave"}</AlertDialogAction>',
  "a margined icon in a slotted child":
    '<Button asChild><Link><Plus className="mr-2 h-4 w-4" />Add</Link></Button>',
  "a margined icon in a slot asked for explicitly":
    '<Button asChild={true}><Link><Plus className="mr-2 h-4 w-4" />Add</Link></Button>',
  "a margined icon in a fragment child": '<Button><><Plus className="mr-2" />Add</></Button>',
  "a margined icon behind two conditions":
    '<Button>{on && (busy ? <Plus className="mr-2" /> : null)}Add</Button>',
};
const allowed = {
  "an icon and label left to the gap": '<Button><Plus className="h-4 w-4" />Add</Button>',
  "ml-auto, which pushes a child to the end":
    '<DropdownMenuItem>Open<ChevronRight className="ml-auto" /></DropdownMenuItem>',
  "a negative margin": '<Button><Plus className="-ml-1 h-4 w-4" />Add</Button>',
  "a margin a level down, under no gap":
    '<Button><span className="flex"><Plus className="mr-2" />Add</span></Button>',
  "a margin in a context menu item, which sets no gap":
    '<ContextMenuItem><Copy className="mr-2 h-4 w-4" />Copy</ContextMenuItem>',
  "a margin on the control itself": '<Button className="ml-2"><Plus />Add</Button>',
  "a margin in a child when asChild is off":
    '<Button asChild={false}><span className="flex"><Plus className="mr-2" />Add</span></Button>',
};

/** Lints every fixture in one Biome run, and says which files it flagged. */
const flagged = (() => {
  const sources = Object.values({ ...refused, ...allowed });
  const files = sources.map((element, index) => {
    const file = path.join(dir, `${index}.tsx`);
    writeFileSync(file, `export const x = (busy: boolean, on: boolean) => ${element};\n`);
    return file;
  });
  let output: string;
  try {
    output = execFileSync(
      path.join(frontend, "node_modules/.bin/biome"),
      ["lint", `--config-path=${frontend}`, "--only=plugin", "--reporter=json", ...files],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }
    );
  } catch (error) {
    output = (error as { stdout: string }).stdout;
  }
  const report = JSON.parse(output) as {
    diagnostics: { message: string; location: { path: string } }[];
  };
  return new Set(
    report.diagnostics
      .filter((diagnostic) => diagnostic.message.includes("already spaces its children"))
      .map((diagnostic) => path.basename(diagnostic.location.path))
  );
})();

const fileOf = (element: string) =>
  `${Object.values({ ...refused, ...allowed }).indexOf(element)}.tsx`;

describe("the no-gap-margins rule", () => {
  it.each(Object.entries(refused))("refuses %s", (_, element) => {
    expect(flagged.has(fileOf(element))).toBe(true);
  });

  it.each(Object.entries(allowed))("allows %s", (_, element) => {
    expect(flagged.has(fileOf(element))).toBe(false);
  });
});
