"""Fixed corpus for the Acme X200 fixture manuals (pure text, no I/O)."""

from __future__ import annotations

import random

TITLE = "Acme X200 Service Manual"
SUBTITLE = "Model X200 · Revision 4"
PRODUCT_MODEL = "Acme X200"

SPECS = [
    "35 N·m",
    "M8",
    "12 V",
    "P/N 4471-A",
    "0.25 mm ±0.05",
    "90°",
    "2.5 L",
    "10 A",
]

PARTS = [
    "drive belt",
    "idler pulley",
    "cover plate",
    "control board",
    "coolant reservoir",
    "fuel filter",
    "mounting bracket",
    "pressure valve",
    "wiring harness",
    "cooling fan",
    "gearbox housing",
    "bearing carrier",
]

FILLER = [
    "Inspect the {part} for wear, cracks, and signs of overheating before continuing.",
    "Clean the {part} with a lint-free cloth and allow it to dry completely.",
    "Do not operate the unit while the {part} is removed.",
    "Keep the area around the {part} free of oil and debris.",
    "Record any damage to the {part} on the service log.",
    "Support the {part} with a stand so that it does not fall during removal.",
    "Wear protective gloves when handling the {part}.",
    "Compare the {part} against the reference illustration before refitting.",
    "Replace the {part} if it shows any sign of deformation.",
    "Allow the unit to cool before touching the {part}.",
]

# One sentence template per spec string; {part} is filled from PARTS.
SPEC_SENTENCES = {
    "35 N·m": "Tighten the {part} bolts to 35 N·m in a cross pattern.",
    "M8": "Use only M8 fasteners when refitting the {part}.",
    "12 V": "The control circuit runs from a 12 V supply, so disconnect it before servicing the "
    "{part}.",
    "P/N 4471-A": "Replace the {part} with genuine part P/N 4471-A if wear is visible.",
    "0.25 mm ±0.05": "Set the clearance at the {part} to 0.25 mm ±0.05 using a feeler gauge.",
    "90°": "Rotate the {part} through 90° until it seats fully.",
    "2.5 L": "Refill the system with 2.5 L of the specified fluid after removing the {part}.",
    "10 A": "Protect the circuit that feeds the {part} with a 10 A fuse.",
}

# whole word -> (head, tail); drawn as "head-" / "tail" at a forced line break.
HYPHEN_WORDS = {
    "adjustment": ("adjust", "ment"),
    "assembly": ("assem", "bly"),
    "lubrication": ("lubri", "cation"),
    "replacement": ("replace", "ment"),
    "alignment": ("align", "ment"),
}
HYPHEN_SENTENCES = [
    "Complete the {word} of the {part} before moving on to the next step.",
    "Any {word} work on the {part} must be done with the unit switched off.",
    "The {word} procedure for the {part} is described in the paragraphs below.",
]

FIG_REF_SENTENCE = "The arrangement of the {part} is shown in the illustration (see Figure {n})."
TABLE_REF_SENTENCE = "The values for the {part} are listed below (see Table {n})."

BULLET_LISTS = [
    ["Torque wrench, 10 to 60 N·m", "Feeler gauge set", "Socket set with M8 socket", "Clean rags"],
    [
        "Disconnect the 12 V supply",
        "Drain the coolant reservoir",
        "Remove the cover plate",
        "Tag all connectors",
    ],
    [
        "Drive belt, P/N 4471-A",
        "Idler pulley kit",
        "Replacement gasket set",
        "Thread locking compound",
    ],
    [
        "Check the belt for fraying",
        "Check pulley alignment",
        "Check tension at mid-span",
        "Rotate by hand 90°",
    ],
    [
        "Fuse rating must be 10 A",
        "Use insulated tools only",
        "Inspect the harness for chafing",
        "Verify polarity at the board",
    ],
    [
        "Fill to the MAX mark",
        "Capacity is about 2.5 L",
        "Run the unit for five minutes",
        "Re-check the fluid level",
    ],
    [
        "Fit the cover plate",
        "Torque the bolts in sequence",
        "Reconnect the 12 V supply",
        "Clear the service log",
    ],
]

SECTIONS_CLEAN = [
    ("1. Safety and Preparation", ["1.1 General Precautions", "1.2 Tools and Materials"]),
    (
        "2. Drive Assembly",
        ["2.1 Belt Inspection", "2.2 Tension Adjustment", "2.3 Idler Replacement"],
    ),
    ("3. Electrical System", ["3.1 Power Supply", "3.2 Fuse Replacement"]),
    (
        "4. Cooling and Lubrication",
        ["4.1 Coolant Service", "4.2 Lubrication Points", "4.3 Reservoir Refill"],
    ),
    ("5. Final Assembly and Testing", ["5.1 Reassembly", "5.2 Functional Test"]),
]

FIGURE_CAPTIONS = [
    "Drive belt routing around the idler pulley.",
    "Idler pulley mounting positions.",
    "Cover plate and bracket layout.",
    "Control board connector locations.",
    "Coolant flow through the reservoir.",
    "Pressure valve exploded view.",
    "Wiring harness routing.",
    "Cooling fan orientation.",
    "Gearbox housing bolt sequence.",
    "Bearing carrier cross-section.",
    "Fuse box layout.",
    "Lubrication points overview.",
    "Final assembly checklist diagram.",
    "Test connection diagram.",
]

# --- tables (header rows first). None marks a cell covered by a span. ---
TABLE_1 = {
    "caption": "Table 1. Fastener torque specifications.",
    "rows": [
        ["Component", "Fastener", "Torque", "Grade"],
        ["Cover plate", "M8", "35 N·m", "8.8"],
        ["Mounting bracket", "M10", "48 N·m", "8.8"],
        ["Idler pulley", "M8", "25 N·m", "10.9"],
        ["Gearbox housing", "M12", "85 N·m", "10.9"],
        ["Bearing carrier", "M6", "12 N·m", "8.8"],
        ["Cooling fan", "M5", "6 N·m", "4.8"],
    ],
    "spans": [],
    "header_rows": 1,
    "col_widths": [130, 90, 90, 80],
    "bordered": True,
}
TABLE_2 = {
    "caption": "Table 2. Electrical ratings.",
    "rows": [
        ["Circuit", "Voltage", "Current", "Fuse"],
        ["Control board", "12 V", "2.5 A", "10 A"],
        ["Cooling fan", "12 V", "4.2 A", "10 A"],
        ["Sensor bus", "5 V", "0.8 A", "2 A"],
        ["Heater element", "24 V", "8.5 A", "15 A"],
        ["Display", "3.3 V", "0.3 A", "1 A"],
    ],
    "spans": [],
    "header_rows": 1,
    "col_widths": [130, 90, 90, 80],
    "bordered": True,
}
TABLE_3 = {
    "caption": "Table 3. Replacement parts list.",
    "rows": [
        ["Part number", "Description", "Qty", "Weight (g)"],
        ["P/N 4471-A", "Drive belt", "1", "210"],
        ["P/N 4472-B", "Idler pulley", "2", "145"],
        ["P/N 5120-C", "Cover plate gasket", "1", "32"],
        ["P/N 6008-D", "Bearing 6008", "4", "70"],
        ["P/N 7731-E", "Fuse 10 A", "5", "2"],
        ["P/N 8802-F", "Wiring harness", "1", "540"],
    ],
    "spans": [],
    "header_rows": 1,
    "col_widths": [110, 160, 50, 80],
    "bordered": True,
}
TABLE_4 = {
    "caption": "Table 4. Service intervals.",
    "rows": [
        ["Task", "Interval", None, "Notes"],
        [None, "Hours", "Months", None],
        ["Belt inspection", "250", "3", "Visual"],
        ["Belt replacement", "1000", "12", "P/N 4471-A"],
        ["Coolant change", "500", "6", "2.5 L"],
        ["Fuse check", "250", "3", "10 A rating"],
        ["Full service", "2000", "24", "All items"],
    ],
    "spans": [(0, 0, 2, 1), (0, 1, 1, 2), (0, 3, 2, 1)],
    "header_rows": 2,
    "col_widths": [130, 70, 70, 100],
    "bordered": True,
}
TABLE_5 = {
    "caption": "Table 5. Connector pin assignments.",
    "rows": [
        ["Connector", "Pin", "Signal", "Rating"],
        ["J1", "1", "12 V supply", "10 A"],
        [None, "2", "Ground", ""],
        ["J2", "1", "Fan control", "2.5 A"],
        ["J3", "1", "", ""],
        ["J4", "1", "Sensor 5 V", "0.8 A"],
        ["J5", "1", "", ""],
    ],
    "spans": [(1, 0, 2, 1)],
    "header_rows": 1,
    "col_widths": [100, 60, 140, 80],
    "bordered": True,
    "ragged": True,
}
TABLE_6 = {
    "caption": "Table 6. Fluid capacities.",
    "rows": [
        ["System", "Capacity", "Fluid", "Change interval"],
        ["Coolant", "2.5 L", "Type C", "6 months"],
        ["Gearbox", "1.2 L", "Type G", "12 months"],
        ["Hydraulic", "0.8 L", "Type H", "24 months"],
        ["Fuel tank", "18 L", "Diesel", "n/a"],
        ["Washer", "1.5 L", "Water mix", "as needed"],
    ],
    "spans": [],
    "header_rows": 1,
    "col_widths": [110, 90, 100, 110],
    "bordered": False,
}
TABLES = [TABLE_1, TABLE_2, TABLE_3, TABLE_4, TABLE_5, TABLE_6]


def make_paragraph(
    rng: random.Random,
    n_sentences: int = 4,
    specs: list[str] | None = None,
    fig_refs: list[int] | None = None,
    table_refs: list[int] | None = None,
    hyphen_word: str | None = None,
) -> tuple[str, list[str]]:
    """Build one paragraph. Returns (text, specs_inserted)."""
    specs = list(specs or [])
    sentences: list[str] = []
    for spec in specs:
        sentences.append(SPEC_SENTENCES[spec].format(part=rng.choice(PARTS)))
    if hyphen_word:
        tpl = rng.choice(HYPHEN_SENTENCES)
        sentences.append(tpl.format(word=hyphen_word, part=rng.choice(PARTS)))
    while len(sentences) < n_sentences:
        sentences.append(rng.choice(FILLER).format(part=rng.choice(PARTS)))
    rng.shuffle(sentences)
    for n in fig_refs or []:
        sentences.append(FIG_REF_SENTENCE.format(part=rng.choice(PARTS), n=n))
    for n in table_refs or []:
        sentences.append(TABLE_REF_SENTENCE.format(part=rng.choice(PARTS), n=n))
    return " ".join(sentences), specs


def random_specs(rng: random.Random) -> list[str]:
    """70% one spec, 15% two, 15% none."""
    r = rng.random()
    if r < 0.15:
        return []
    if r < 0.85:
        return [rng.choice(SPECS)]
    return rng.sample(SPECS, 2)
