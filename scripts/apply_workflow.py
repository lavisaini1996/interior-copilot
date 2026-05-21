"""Splice workflow sections into App.tsx."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "frontend" / "src" / "ui" / "App.tsx"
old = (ROOT / "scripts" / "old_block.txt").read_text(encoding="utf-8")
design = (ROOT / "scripts" / "design_block.txt").read_text(encoding="utf-8")


def slice_block(s: str, start: str, end: str) -> str:
    i = s.index(start)
    j = s.index(end, i + len(start)) if end else len(s)
    return s[i:j]


chat = slice_block(old, '          <div className="chat">', '          <div className="uploadRow">')

floor_part = slice_block(
    old,
    '          <div className="uploadRow">\n            <div className="uploadMeta">\n              <div className="smallTitle">Floor plan',
    '          ) : null}\n\n          {floorplanRefs.length ? (\n            <div className="fpNorthPanel">',
)

plan_part = slice_block(old, '            <div className="fpNorthPanel">', "          {detectedRooms.length > 1 ?")

room_part = slice_block(old, "          {detectedRooms.length > 1 ?", "          {floorplanRefs.length || brief.space_type")

textarea_part = slice_block(
    old,
    "          <textarea",
    '          <div className="uploadRow">\n            <div className="uploadMeta">\n              <div className="smallTitle">Optional: style reference images</div>',
)

i_style_row = old.index('              <div className="smallTitle">Optional: style reference images</div>')
i_style_row = old.rfind('          <div className="uploadRow">', 0, i_style_row)
i_composer = old.index('          <div className="composer">', i_style_row)
style_only = old[i_style_row:i_composer]
composer_part = old[i_composer:]

wall_layout_jsx = """          {floorplanRefs.length || brief.space_type ? (
            <WallLayout
              brief={brief}
              assignments={
                ((brief as any).wall_assignments as WallAssignments) || { ...EMPTY_WALL_ASSIGNMENTS }
              }
              openings={((brief as any).wall_openings as WallAssignments) || { ...EMPTY_WALL_ASSIGNMENTS }}
              items={WALL_ITEMS_BY_ROOM[resolveRoomItemKey(brief)] || WALL_ITEMS_BY_ROOM.bedroom}
              roomLabel={String(
                (brief as any).selected_room_name || (brief as any).space_type || "Bedroom",
              )}
              disabled={isBusy}
              onChange={(next) =>
                setBrief((b) => ({
                  ...b,
                  wall_assignments: next,
                }))
              }
            />
          ) : (
            <p className="muted">Complete step 2 (floor plan) to place items on walls.</p>
          )}"""

new_block = (
    "\n        </WorkflowSection>\n\n"
    '        <WorkflowSection stepId="floorPlan" steps={workflow.steps} title="Floor plan">\n'
    + floor_part.replace("Floor plan (image or text)", "Floor plan image").replace(
        "Upload a floor plan screenshot/photo, or describe it below.",
        "Upload a plan image (recommended), or add a text description below.",
    )
    + "\n"
    + textarea_part
    + "\n        </WorkflowSection>\n\n"
    '        <WorkflowSection stepId="planSetup" steps={workflow.steps} title="Plan setup">\n'
    "          {!floorplanRefs.length ? (\n"
    '            <p className="muted">No plan image — optional. Upload an image in step 2 for north arrow and room picker.</p>\n'
    "          ) : null}\n"
    + plan_part
    + room_part
    + "\n        </WorkflowSection>\n\n"
    '        <WorkflowSection stepId="wallLayout" steps={workflow.steps} title="Wall layout (optional)">\n'
    "          <button\n"
    '            type="button"\n'
    '            className="btn secondary"\n'
    "            style={{ marginBottom: 12 }}\n"
    "            onClick={() => setSkipWallLayout(true)}\n"
    "            disabled={isBusy || skipWallLayout}\n"
    "          >\n"
    "            Continue without wall layout\n"
    "          </button>\n"
    + wall_layout_jsx
    + "\n        </WorkflowSection>\n\n"
    '        <WorkflowSection stepId="preferences" steps={workflow.steps} title="Style & budget (chat)">\n'
    + chat
    + composer_part
    + "\n        </WorkflowSection>\n\n"
    '        <WorkflowSection stepId="styleRefs" steps={workflow.steps} title="Style references (optional)">\n'
    + style_only
    + "\n        </WorkflowSection>\n\n"
    '        <WorkflowSection stepId="generate" steps={workflow.steps} title="Generate designs">\n'
    '          <div className="wfGenerateBlock">\n'
    '            <p className="muted">\n'
    "              {workflow.canGenerate\n"
    '                ? "Your brief is complete. Generate catalog design options with images and INR pricing."\n'
    '                : "Finish step 5 (chat) until the brief shows complete, then generate here."}\n'
    "            </p>\n"
    '            <button className="btn primary" onClick={onGenerate} disabled={isBusy || !workflow.canGenerate}>\n'
    "              Generate designs\n"
    "            </button>\n"
    "          </div>\n"
    "        </WorkflowSection>\n\n"
    '        <WorkflowSection stepId="results" steps={workflow.steps} title="Your designs">\n'
)

design_inner = design.replace("        <section className=\"card\">\n", "").replace("        </section>\n", "")
design_inner = design_inner.replace(
    "          <div className=\"cardTitle\">Design options (catalog only, {designCurrency})</div>\n",
    '          <div className="cardTitle" style={{ marginBottom: 12 }}>Design options (catalog only, {designCurrency})</div>\n',
)

new_block += design_inner + "\n        </WorkflowSection>\n"

t = APP.read_text(encoding="utf-8")
if old not in t:
    raise SystemExit("old block not in App.tsx")
t = t.replace(old, new_block, 1)

t = t.replace(
    "\n        <section className=\"card\">\n          <div className=\"cardTitle\">Live brief (debug)</div>\n"
    "          <pre className=\"mono\">{briefJson}</pre>\n        </section>",
    "",
)

while "door on south wall near left" in t:
    i = t.index("door on south wall near left")
    s = t.rfind("<textarea", 0, i)
    e = t.index("/>\n", i) + 3
    t = t[:s] + t[e + 1 :]

APP.write_text(t, encoding="utf-8")
print("ok")
