"""Build the blinded second-rater pack (pre-registration section 6, control coding).

Outputs (docs/second_rater/):
  Second_Rater_Brief_and_Designs.docx   brief + current-state workflows + control lists + blinded designs
  Second_Rater_Answer_Sheet.xlsx        one grid per workflow: controls x designs, dropdown answers
  KEY_<workflow>.json                   design letter -> run id (author only, never sent to the rater)

Run:  python3 scripts/second_rater_pack.py
Score the returned sheet with scripts/second_rater_score.py.
"""
import json, random, re, sys
from pathlib import Path
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_BREAK
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "second_rater"
OUT.mkdir(exist_ok=True)
SEED = 20261026

WORKFLOWS = [
    ("R2R-ACR-01", "r2r_account_reconciliation.json"),
    ("P2P-TWM-01", "p2p_three_way_matching.json"),
]
LETTERS = "ABCDEFGHIJ"
RUNS_PER_CONDITION = 1   # last run of each condition; None = all runs

def load(p):
    return json.load(open(p))

_FINAL = None
def final_controls():
    """The author's final coding, exactly as control_coding_final.py builds it (borderline decisions applied)."""
    global _FINAL
    if _FINAL is None:
        import importlib.util, argparse
        spec = importlib.util.spec_from_file_location("ccf", ROOT / "scripts" / "control_coding_final.py")
        ccf = importlib.util.module_from_spec(spec); spec.loader.exec_module(ccf)
        args = argparse.Namespace(set_name="heldout-v1", runs_root=ROOT / "runs")
        _FINAL, _ = ccf.build(args)
    return _FINAL

def gather(wf, enc_file):
    enc = load(ROOT / "data/encodings/heldout" / enc_file)
    cands = {c["id"]: c for c in load(ROOT / f"docs/control_coding/controls_{wf}.json")["candidates"]}
    export = [x["control_id"] for x in load(ROOT / "export/results/governance_controls.json")["controls"] if x["workflow_id"] == wf]
    fin = {min(f["ids"]): f for f in final_controls().values() if f["wf"] == wf}
    assert sorted(fin) == sorted(export), (wf, sorted(fin), sorted(export))
    controls = []
    for i, cid in enumerate(export, 1):
        f = fin[cid]
        members = [cands[x] for x in f["members"] if x in cands]
        desc = "; ".join(dict.fromkeys(x["title"] for x in members)) or f["name"]
        cat = ", ".join(sorted(set(x["category"] for x in members)))
        author = {rid: {"present": bool(v)} for rid, v in f["pres"].items()}
        locs = [int(m.group(1)) for x in members for rec in x["council_present"] + x["baseline_present"]
                for m in [re.search(r"(\d{1,2})\s*$", rec.get("step_id", ""))] if m]
        loc = max(set(locs), key=locs.count) if locs else 0
        controls.append({"id": cid, "name": f["name"], "desc": desc, "category": cat, "author": author, "loc": loc})
    controls.sort(key=lambda c: (c["loc"] or 99, c["id"]))
    for i, c in enumerate(controls, 1):
        c["n"] = i
    run_ids = sorted(controls[0]["author"].keys())
    if RUNS_PER_CONDITION:
        run_ids = (sorted(r for r in run_ids if "-council-" in r)[-RUNS_PER_CONDITION:]
                   + sorted(r for r in run_ids if "-baseline-" in r)[-RUNS_PER_CONDITION:])
        for c in controls:
            c["author"] = {r: c["author"][r] for r in run_ids}
    rng = random.Random(f"{SEED}-{wf}")
    rng.shuffle(run_ids)
    designs = []
    for letter, rid in zip(LETTERS, run_ids):
        tss = load(ROOT / "runs" / rid / "tss.json")
        designs.append({"letter": letter, "run_id": rid, "steps": tss["steps"]})
    json.dump({"workflow_id": wf, "seed": SEED,
               "key": {d["letter"]: d["run_id"] for d in designs},
               "controls": [{"n": c["n"], "id": c["id"], "author": c["author"]} for c in controls]},
              open(OUT / f"KEY_{wf}.json", "w"), indent=1)
    return enc, controls, designs

def blind_text(text, step_map):
    """Replace step ids in free text with neutral step numbers."""
    for sid, n in sorted(step_map.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"\b{re.escape(sid)}\b", f"Step {n}", text)
    text = re.sub(r"\b(?:TS|T|ACR-T|TS-ACR|TWM-T|TS-TWM)-?0?(\d{1,2})\b", r"Step \1", text)
    return text

def sentences(text):
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+(?=[A-Z\"(])", text.strip()) if x.strip()]

def norm(x):
    return re.sub(r"[^a-z0-9 ]", "", x.lower()).strip()

def mark_new(items, known):
    """Prefix items that do not appear in the current-state workflow with '+'."""
    out = []
    for it in items:
        n = norm(it)
        out.append(it if any(n == k or n in k or k in n for k in known) else "+ " + it)
    return out

# ---------- docx ----------
def para(doc, text, bold=False, italic=False, size=11, style=None):
    p = doc.add_paragraph(style=style) if style else doc.add_paragraph()
    r = p.add_run(text); r.bold = bold; r.italic = italic; r.font.size = Pt(size)
    return p

def table(doc, rows, header, widths=None, size=8):
    t = doc.add_table(rows=1, cols=len(header)); t.style = "Table Grid"
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]; c.text = ""; r = c.paragraphs[0].add_run(h); r.bold = True; r.font.size = Pt(size)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            lines = v if isinstance(v, list) else [str(v)]
            for k, line in enumerate(lines):
                par = cells[i].paragraphs[0] if k == 0 else cells[i].add_paragraph()
                par.paragraph_format.space_after = Pt(1)
                r = par.add_run(line); r.font.size = Pt(size)
                if line.startswith("+ ") or ": + " in line or "; + " in line: r.bold = True
    if widths:
        t.autofit = False
        for i, w in enumerate(widths):
            t.columns[i].width = Cm(w)
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    return t

def build_docx(packs):
    doc = Document()
    st = doc.styles["Normal"]; st.font.name = "Arial"; st.font.size = Pt(11)
    from docx.enum.section import WD_ORIENT
    for sec in doc.sections:
        sec.orientation = WD_ORIENT.LANDSCAPE
        sec.page_width, sec.page_height = Cm(29.7), Cm(21.0)
        sec.left_margin = sec.right_margin = Cm(1.5); sec.top_margin = sec.bottom_margin = Cm(1.5)

    doc.add_heading("Second-rater brief: governance controls in redesigned finance workflows", 0)
    para(doc, "Prepared for the second rater, October 2026. Please read the brief (two pages) before opening the answer sheet.", italic=True)

    doc.add_heading("1. What this is", 1)
    para(doc, "My MSc dissertation tests whether a team of AI agents produces better redesigns of finance workflows than a single AI agent. One of the measures is the governance controls that appear in the redesigned workflow: exception queues, approval gates, evidence logs, fallbacks, segregation of duties and so on. I have already coded these myself. My supervisor requires an independent second coder who does not know which design came from which system, so that the coding can be checked for agreement.")
    para(doc, "You will look at two workflows. For each one you get the current-state process and two redesigned versions, labelled A and B in random order: one from the agent team and one from the single agent. You will not be told which is which, and please do not try to guess; length and style are not reliable clues and guessing would undermine the exercise.")

    doc.add_heading("2. What you have to do", 1)
    para(doc, "For each workflow:")
    for s in ["Read the current-state workflow (how the process runs today). This is the starting point every design was asked to redesign.",
              "Read the control list. Each control is a specific mechanism: a check, log, gate, queue, fallback or approval acting on a specific object at a specific point in the workflow.",
              "Read Design A step by step against the current state. As you finish each step, go to the controls listed for that step in the answer sheet and choose an answer for Design A.",
              "Repeat for Design B."]:
        para(doc, s, style="List Number")
    para(doc, "There is nothing to write. Every answer is one of three dropdown choices. The optional Notes column is there only if you want to record why a call was hard.")
    para(doc, "How the designs are laid out", bold=True)
    for s in ["Each workflow is one side-by-side table: current state in the left column, Design A and Design B beside it, rows aligned by step position. A design may have more or fewer steps than the current state, so a row is a position, not a guaranteed match.",
              "Each step's mechanism is broken into short lines rather than a paragraph.",
              "A bold line starting with + marks an actor, input or output that does not appear in the current-state workflow. These are the places most likely to hold a new control, but a control can also sit in the mechanism text of an unchanged step, so please still read the whole cell.",
              "The control list is ordered by where in the workflow the control sits (approximate step of the current-state process), so you can tick controls step by step as you read."]:
        para(doc, s, style="List Bullet")

    doc.add_heading("3. The test to apply", 1)
    para(doc, "This is the same test I applied, so please apply it exactly, without adjusting for what you think good practice should be:", bold=True)
    para(doc, "A design HAS a control if its text states the same mechanism (the same check or action) acting on the same object at the same point in the workflow.")
    for s in ["Wording does not matter. A less detailed statement of the same mechanism still counts.",
              "A statement of principle, goal or accountability with no operative mechanism does NOT count. \"The controller is accountable for accuracy\" is not a control. \"The controller approves the reconciliation before it is posted\" is.",
              "A neighbouring step is a different point. If the control list says the check happens at extraction and the design puts an equivalent check at matching, that is Absent for this control.",
              "The same check performed by a different person or system is still the same control.",
              "Something implied by the design's description counts, as long as a mechanism is actually described and not merely named as a goal.",
              "Where it comes from does not matter: a control that is simply carried over from the current-state workflow still counts as present."]:
        para(doc, s, style="List Bullet")
    para(doc, "The three answers:", bold=True)
    for s in ["Present: the mechanism is there under the test above.",
              "Absent: it is not there, or only a goal or principle is stated.",
              "Borderline: the text could reasonably be read either way. Use this sparingly, but do use it rather than forcing a call."]:
        para(doc, s, style="List Bullet")

    doc.add_heading("4. Practical points", 1)
    for s in ["Time: about 45 minutes to an hour per workflow. Please finish one design completely before starting the next.",
              "Please do not discuss the designs with me until the sheet is returned. I will not answer questions about individual controls during the exercise; if a control definition is unclear, answer Borderline and note it.",
              "Do not change the control list or the design labels.",
              "When done, fill in the declaration on the first sheet and send the file back.",
              "Your coding will be reported in the dissertation as the independent second rater, anonymised as \"a chartered accountant with CFO experience, not otherwise involved in the study\", unless you prefer to be named."]:
        para(doc, s, style="List Bullet")

    for wf, enc, controls, designs in packs:
        doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        doc.add_heading(f"Workflow {wf}: {enc['name']}", 0)
        doc.add_heading("Current-state workflow (the starting point)", 1)
        enc_map = {s["step_id"]: i for i, s in enumerate(enc["steps"], 1)}
        known = set()
        for st in enc["steps"]:
            known.add(norm(st["actor"])); known.update(norm(x) for x in st["inputs"] + st["outputs"])
        rows = [(i, s["name"], s["actor"], sentences(s["description"]), s["inputs"], s["outputs"])
                for i, s in enumerate(enc["steps"], 1)]
        table(doc, rows, ["#", "Step", "Actor", "What happens", "Inputs", "Outputs"], [0.8, 4, 3, 11, 4, 4])

        doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        doc.add_heading(f"Control list ({len(controls)} controls), in workflow order", 1)
        para(doc, "Numbers match the rows of the answer sheet. 'Where' is the approximate current-state step at which the control acts; a control at a different step is a different control.", italic=True, size=9)
        rows = [(c["n"], f"Step {c['loc']}" if c["loc"] else "Any", c["name"], c["desc"], c["category"]) for c in controls]
        table(doc, rows, ["#", "Where", "Control", "What to look for", "Type"], [0.8, 1.6, 7, 13, 3])

        doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        doc.add_heading(f"{wf}: current state and the two designs, side by side", 1)
        para(doc, "Rows are step positions. Bold + marks an actor, input or output not in the current state.", italic=True, size=9)
        def cell(st, step_map=None):
            bt = (lambda x: blind_text(x, step_map)) if step_map else (lambda x: x)
            return ([bt(st["name"]).upper()] + ["Actor: " + a for a in mark_new([bt(st.get("actor", ""))], known)]
                    + sentences(bt(st.get("description", "")))
                    + ["In: " + "; ".join(mark_new([bt(x) for x in st.get("inputs", [])], known))]
                    + ["Out: " + "; ".join(mark_new([bt(x) for x in st.get("outputs", [])], known))])
        maxn = max([len(enc["steps"])] + [len(d["steps"]) for d in designs])
        rows = []
        for i in range(maxn):
            row = [str(i + 1), cell(enc["steps"][i]) if i < len(enc["steps"]) else ""]
            for d in designs:
                sm = {s["step_id"]: k for k, s in enumerate(d["steps"], 1)}; sm.update(enc_map)
                row.append(cell(d["steps"][i], sm) if i < len(d["steps"]) else "")
            rows.append(row)
        w = (26.7 - 0.7) / (1 + len(designs))
        table(doc, rows, ["#", "Current state"] + [f"Design {d['letter']}" for d in designs], [0.7] + [w] * (1 + len(designs)), size=7.5)
    doc.save(OUT / "Second_Rater_Brief_and_Designs.docx")

# ---------- xlsx ----------
def build_xlsx(packs):
    wb = Workbook()
    ws = wb.active; ws.title = "Read me"
    lines = [
        ("Second-rater answer sheet", True),
        ("", False),
        ("One sheet per workflow. Rows are controls (numbered as in the brief, in workflow order), columns Design A and Design B are the two redesigns.", False),
        ("For every cell choose Present, Absent or Borderline from the dropdown. Please leave no cell empty.", False),
        ("The test: a design HAS a control if its text states the same mechanism acting on the same object at the same point in the workflow. Wording does not matter; a stated goal with no mechanism does not count; a neighbouring step is a different point.", False),
        ("Notes column is optional.", False),
        ("", False),
        ("Declaration (please complete):", True),
        ("Rater name:", False),
        ("Date completed:", False),
        ("I was not told, and did not attempt to work out, which system produced each design (Yes/No):", False),
        ("Approximate hours spent:", False),
    ]
    for i, (t, b) in enumerate(lines, 1):
        c = ws.cell(row=i, column=1, value=t); c.font = Font(name="Arial", bold=b, size=11)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 110; ws.column_dimensions["B"].width = 30
    for r in range(9, 13):
        ws.cell(row=r, column=2).fill = PatternFill("solid", fgColor="FFF2CC")

    thin = Side(style="thin", color="BBBBBB"); border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for wf, enc, controls, designs in packs:
        ws = wb.create_sheet(wf)
        dv = DataValidation(type="list", formula1='"Present,Absent,Borderline"', allow_blank=True, showDropDown=False)
        dv.error = "Choose Present, Absent or Borderline"; dv.errorTitle = "Answer"
        ws.add_data_validation(dv)
        hdr = ["#", "Where", "Control", "What to look for"] + [f"Design {d['letter']}" for d in designs] + ["Notes (optional)"]
        for j, h in enumerate(hdr, 1):
            c = ws.cell(row=1, column=j, value=h); c.font = Font(name="Arial", bold=True, size=10)
            c.fill = PatternFill("solid", fgColor="D9E2F3"); c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
            c.border = border
        for i, ctl in enumerate(controls, 2):
            vals = [ctl["n"], f"Step {ctl['loc']}" if ctl["loc"] else "Any", ctl["name"], ctl["desc"]] + [""] * len(designs) + [""]
            for j, v in enumerate(vals, 1):
                c = ws.cell(row=i, column=j, value=v); c.font = Font(name="Arial", size=10); c.border = border
                c.alignment = Alignment(wrap_text=True, vertical="top")
            for j in range(5, 5 + len(designs)):
                ws.cell(row=i, column=j).fill = PatternFill("solid", fgColor="FFF2CC")
                dv.add(ws.cell(row=i, column=j))
        ws.column_dimensions["A"].width = 5; ws.column_dimensions["B"].width = 8; ws.column_dimensions["C"].width = 38; ws.column_dimensions["D"].width = 60
        for j in range(5, 5 + len(designs)):
            ws.column_dimensions[get_column_letter(j)].width = 12
        ws.column_dimensions[get_column_letter(5 + len(designs))].width = 40
        ws.freeze_panes = "E2"
        ws.sheet_view.zoomScale = 90
    wb.save(OUT / "Second_Rater_Answer_Sheet.xlsx")

if __name__ == "__main__":
    packs = []
    for wf, enc_file in WORKFLOWS:
        enc, controls, designs = gather(wf, enc_file)
        packs.append((wf, enc, controls, designs))
        print(wf, len(controls), "controls,", len(designs), "designs")
    build_docx(packs)
    build_xlsx(packs)
    print("written to", OUT)
