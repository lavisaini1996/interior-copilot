from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "frontend" / "src" / "ui" / "App.tsx"
t = APP.read_text(encoding="utf-8")

# 1) Remove misplaced chat
chat_start = '          <div className="chat">'
i0 = t.index(chat_start)
i1 = t.index('              <motion.div className="smallTitle">Floor plan (image or text)</motion.div>', i0)
if i1 < 0:
    i1 = t.index('              <div className="smallTitle">Floor plan (image or text)</div>', i0)
i1 = t.rfind('          <div className="uploadRow">', i0, i1)
t = t[:i0] + t[i1:]

# 2) Close designType, open floorPlan
anchor = (
    '            </select>\n'
    '          </div>\n\n'
    '          <div className="uploadRow">\n'
    '            <div className="uploadMeta">\n'
    '              <div className="smallTitle">Floor plan (image or text)</div>'
)
repl = (
    '            </select>\n'
    '          </div>\n'
    '        </WorkflowSection>\n\n'
    '        <WorkflowSection stepId="floorPlan" steps={workflow.steps} title="Floor plan">\n'
    '          <div className="uploadRow">\n'
    '            <div className="uploadMeta">\n'
    '              <motion.div className="smallTitle">Floor plan image</div>'
)
repl = (
    '            </select>\n'
    '          </div>\n'
    '        </WorkflowSection>\n\n'
    '        <WorkflowSection stepId="floorPlan" steps={workflow.steps} title="Floor plan">\n'
    '          <div className="uploadRow">\n'
    '            <div className="uploadMeta">\n'
    '              <div className="smallTitle">Floor plan image</div>'
)
t = t.replace(anchor, repl, 1)

north = '          {floorplanRefs.length ? (\n            <div className="fpNorthPanel">'
insert = (
    '          <textarea\n'
    '            className="input"\n'
    '            placeholder="Floor plan text (optional). Example: Room 4.2m x 3.6m, door on south wall, window on east."\n'
    '            value={floorplanText}\n'
    '            onChange={(e) => setFloorplanText(e.target.value)}\n'
    '            rows={3}\n'
    '            disabled={isBusy}\n'
    '            style={{ marginTop: 12 }}\n'
    '          />\n'
    '        </WorkflowSection>\n\n'
    '        <WorkflowSection stepId="planSetup" steps={workflow.steps} title="Plan setup">\n'
    '          {!floorplanRefs.length ? (\n'
    '            <p className="muted">No plan image — optional. Upload an image in step 2 for north arrow and room picker.</p>\n'
    '          ) : null}\n'
    + north
)
t = t.replace(north, insert, 1)

while 'door on south wall near left' in t:
    i = t.index('door on south wall near left')
    s = t.rfind('<textarea', 0, i)
    e = t.index('/>\n', i) + 3
    t = t[:s] + t[e + 1 :]

wl = '          {floorplanRefs.length || brief.space_type ? (\n            <div className="wlCard">'
t = t.replace(
    wl,
    '        </WorkflowSection>\n\n'
    '        <WorkflowSection stepId="wallLayout" steps={workflow.steps} title="Wall layout (optional)">\n'
    '          <button type="button" className="btn secondary" style={{ marginBottom: 12 }} '
    'onClick={() => setSkipWallLayout(true)} disabled={isBusy || skipWallLayout}>\n'
    '            Continue without wall layout\n'
    '          </button>\n'
    '          {floorplanRefs.length || brief.space_type ? (\n'
    '            <div className="wlCard" style={{ border: "none", padding: 0, background: "transparent" }}>',
    1,
)

wall_close = (
    '              />\n'
    '            </div>\n'
    '          ) : null}\n\n'
    '          <div className="uploadRow">\n'
    '            <div className="uploadMeta">\n'
    '              <div className="smallTitle">Optional: style reference images</div>'
)
prefs = (
    '              />\n'
    '            </div>\n'
    '          ) : (\n'
    '            <p className="muted">Upload a floor plan in step 2 to place items on walls.</p>\n'
    '          )}\n'
    '        </WorkflowSection>\n\n'
    '        <WorkflowSection stepId="preferences" steps={workflow.steps} title="Style & budget (chat)">\n'
    '          <div className="chat">\n'
    '            {chat.map((m, idx) => (\n'
    '              <motion.div key={idx} className={`msg ${m.role}`}>\n'
    '                <div className="role">{m.role}</div>\n'
    '                <pre className="content">{m.content}</pre>\n'
    '              </div>\n'
    '            ))}\n'
    '          </div>\n'
    '          <div className="composer">\n'
    '            <textarea className="input" placeholder="Your answer…" value={input} '
    'onChange={(e) => setInput(e.target.value)} rows={3} disabled={isBusy} />\n'
    '            <button className="btn primary" onClick={onSend} disabled={isBusy || !input.trim()}>Send</button>\n'
    '          </div>\n'
    '          {error ? (\n'
    '            <div className="error">\n'
    '              <div className="errorTitle">Error</div>\n'
    '              <pre className="errorBody">{error}</pre>\n'
    '            </div>\n'
    '          ) : null}\n'
    '          <div className="statusRow">\n'
    '            <motion.div className={`pill ${isComplete ? "ok" : "warn"}`}>{isComplete ? "Brief complete" : "Needs more info"}</div>\n'
    '            {pendingQuestions.length ? (\n'
    '              <div className="pill neutral">{pendingQuestions.length} follow-up question(s)</div>\n'
    '            ) : (\n'
    '              <div className="pill neutral">No pending questions</div>\n'
    '            )}\n'
    '            {isBusy ? <div className="pill neutral">Working…</div> : null}\n'
    '          </div>\n'
    '        </WorkflowSection>\n\n'
    '        <WorkflowSection stepId="styleRefs" steps={workflow.steps} title="Style references (optional)">\n'
    '          <div className="uploadRow">\n'
    '            <div className="uploadMeta">\n'
    '              <div className="smallTitle">Optional: style reference images</div>'
)
# strip accidental motion tags
prefs = (
    prefs.replace('<motion.div key={idx}', '<div key={idx}')
    .replace('<motion.div className={`pill', '<motion.div className={`pill')
)
prefs = prefs.replace('<motion.div className={`pill', '<div className={`pill')

t = t.replace(wall_close, prefs, 1)

comp = '          <div className="composer">'
while t.count(comp) > 1:
    i2 = t.index(comp, t.index(comp) + 1)
    j2 = t.index('          <div className="uploadRow">', i2)
    t = t[:i2] + t[j2:]

t = t.replace(
    '          </motion.div>\n        </section>\n\n        <section className="card">\n          <div className="cardTitle">Design options',
    '          </div>\n        </WorkflowSection>\n\n'
    '        <WorkflowSection stepId="generate" steps={workflow.steps} title="Generate designs">\n'
    '          <div className="wfGenerateBlock">\n'
    '            <p className="muted">{workflow.canGenerate ? "Brief complete — generate catalog designs with images." : "Complete step 5 (chat) first."}</p>\n'
    '            <button className="btn primary" onClick={onGenerate} disabled={isBusy || !workflow.canGenerate}>Generate designs</button>\n'
    '          </div>\n'
    '        </WorkflowSection>\n\n'
    '        <WorkflowSection stepId="results" steps={workflow.steps} title="Your designs">\n'
    '          <div className="cardTitle" style={{ marginBottom: 12 }}>Design options',
    1,
)
t = t.replace(
    '          </div>\n        </section>\n\n        <section className="card">\n          <div className="cardTitle">Design options',
    '          </div>\n        </WorkflowSection>\n\n'
    '        <WorkflowSection stepId="generate" steps={workflow.steps} title="Generate designs">\n'
    '          <div className="wfGenerateBlock">\n'
    '            <p className="muted">{workflow.canGenerate ? "Brief complete — generate catalog designs with images." : "Complete step 5 (chat) first."}</p>\n'
    '            <button className="btn primary" onClick={onGenerate} disabled={isBusy || !workflow.canGenerate}>Generate designs</button>\n'
    '          </div>\n'
    '        </WorkflowSection>\n\n'
    '        <WorkflowSection stepId="results" steps={workflow.steps} title="Your designs">\n'
    '          <div className="cardTitle" style={{ marginBottom: 12 }}>Design options',
    1,
)

t = t.replace(
    '        </section>\n\n        <section className="card">\n          <div className="cardTitle">Live brief (debug)</div>\n'
    '          <pre className="mono">{briefJson}</pre>\n        </section>\n      </div>',
    '        </WorkflowSection>\n      </div>',
    1,
)

APP.write_text(t, encoding="utf-8")
print('ok')
