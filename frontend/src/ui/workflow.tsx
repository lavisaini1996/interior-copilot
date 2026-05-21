/**
 * Linear intake → generate workflow. Step status is derived from brief + uploads
 * so the UI stays in sync without a separate manual step index.
 */
import React from "react";

export type WorkflowStepId =
  | "designType"
  | "floorPlan"
  | "planSetup"
  | "wallLayout"
  | "preferences"
  | "styleRefs"
  | "generate"
  | "results";

export type StepStatus = "locked" | "active" | "done";

export type WorkflowStepDef = {
  id: WorkflowStepId;
  label: string;
  hint: string;
};

export const WORKFLOW_STEPS: WorkflowStepDef[] = [
  {
    id: "designType",
    label: "Design type",
    hint: "Choose the room or module you want to design.",
  },
  {
    id: "floorPlan",
    label: "Floor plan",
    hint: "Upload a plan image (recommended) or describe the layout in text.",
  },
  {
    id: "planSetup",
    label: "Plan setup",
    hint: "Set north on the drawing and pick the room if the plan has several.",
  },
  {
    id: "wallLayout",
    label: "Wall layout",
    hint: "Place items on N/S/E/W walls (optional — you can skip).",
  },
  {
    id: "preferences",
    label: "Style & budget",
    hint: "Answer follow-ups in chat until the brief is complete.",
  },
  {
    id: "styleRefs",
    label: "Style references",
    hint: "Optional photos to guide palette and materials.",
  },
  {
    id: "generate",
    label: "Generate designs",
    hint: "Create catalog options with images and INR pricing.",
  },
  {
    id: "results",
    label: "Your designs",
    hint: "Review options, compass placement, and download images.",
  },
];

export type WorkflowStepView = WorkflowStepDef & {
  status: StepStatus;
  stepNumber: number;
};

export type WorkflowSnapshot = {
  steps: WorkflowStepView[];
  activeStepId: WorkflowStepId;
  canGenerate: boolean;
};

export function computeWorkflow(input: {
  brief: Record<string, unknown>;
  floorplanImageCount: number;
  floorplanText: string;
  detectedRoomCount: number;
  skipWallLayout: boolean;
  isComplete: boolean;
  designsCount: number;
  isGenerating: boolean;
}): WorkflowSnapshot {
  const {
    brief,
    floorplanImageCount,
    floorplanText,
    detectedRoomCount,
    skipWallLayout,
    isComplete,
    designsCount,
    isGenerating,
  } = input;

  const hasSpace = Boolean(brief.space_type && String(brief.space_type).trim());
  const hasFloorPlanImage = floorplanImageCount > 0;
  const hasFloorPlanText = floorplanText.trim().length >= 12;
  const hasFloorPlan = hasFloorPlanImage || hasFloorPlanText;

  const needsRoomPick = hasFloorPlanImage && detectedRoomCount > 1;
  const roomSelected =
    !needsRoomPick ||
    Boolean(brief.selected_room_id && String(brief.selected_room_id).trim());

  const planSetupApplies = hasFloorPlanImage;
  const planSetupDone = !planSetupApplies || roomSelected;

  const walls = (brief.wall_assignments as Record<string, string[]>) || {};
  const hasWallAssignment = ["north", "south", "east", "west"].some((w) => {
    const arr = walls[w];
    return Array.isArray(arr) && arr.length > 0;
  });
  const wallLayoutDone = planSetupDone && hasFloorPlan && (skipWallLayout || hasWallAssignment);

  const preferencesDone = isComplete;
  const styleRefsDone = preferencesDone;
  const generateDone = designsCount > 0;
  const resultsDone = generateDone;

  const doneMap: Record<WorkflowStepId, boolean> = {
    designType: hasSpace,
    floorPlan: hasFloorPlan,
    planSetup: !planSetupApplies || (planSetupDone && hasFloorPlan),
    wallLayout: wallLayoutDone,
    preferences: preferencesDone,
    styleRefs: styleRefsDone,
    generate: generateDone,
    results: resultsDone,
  };

  let activeStepId: WorkflowStepId = "results";
  for (const def of WORKFLOW_STEPS) {
    if (!doneMap[def.id]) {
      activeStepId = def.id;
      break;
    }
  }

  if (isGenerating) {
    activeStepId = "generate";
  } else if (generateDone) {
    activeStepId = "results";
  }

  const activeIndex = WORKFLOW_STEPS.findIndex((s) => s.id === activeStepId);

  const steps: WorkflowStepView[] = WORKFLOW_STEPS.map((def, i) => {
    const done = doneMap[def.id];
    let status: StepStatus;
    if (!hasSpace && def.id !== "designType") {
      status = "locked";
    } else if (done) {
      status = "done";
    } else if (def.id === activeStepId) {
      status = "active";
    } else if (i < activeIndex) {
      status = "done";
    } else {
      status = "locked";
    }
    return { ...def, status, stepNumber: i + 1 };
  });

  const canGenerate = preferencesDone && hasFloorPlan && !isGenerating;

  return { steps, activeStepId, canGenerate };
}

export function isStepUnlocked(stepId: WorkflowStepId, steps: WorkflowStepView[]): boolean {
  const target = steps.find((s) => s.id === stepId);
  return target ? target.status !== "locked" : false;
}

export function WorkflowStepper(props: { steps: WorkflowStepView[]; activeStepId: WorkflowStepId }) {
  const { steps, activeStepId } = props;
  return (
    <nav className="wfStrip" aria-label="Design workflow steps">
      {steps.map((s) => (
        <div
          key={s.id}
          className={`wfStep ${s.status}`}
          aria-current={s.id === activeStepId && s.status === "active" ? "step" : undefined}
        >
          <div className="wfStepNum" aria-hidden="true">
            {s.status === "done" ? "✓" : s.stepNumber}
          </div>
          <div className="wfStepText">
            <div className="wfStepLabel">{s.label}</div>
            {s.id === activeStepId && s.status === "active" ? (
              <div className="wfStepHint">{s.hint}</div>
            ) : null}
          </div>
        </div>
      ))}
    </nav>
  );
}

export function WorkflowSection(props: {
  stepId: WorkflowStepId;
  steps: WorkflowStepView[];
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const { stepId, steps, title, children, footer } = props;
  const step = steps.find((s) => s.id === stepId);
  if (!step) return null;
  const locked = step.status === "locked";

  return (
    <section className={`wfPanel ${step.status}`} aria-labelledby={`wf-${stepId}`}>
      <div className="wfPanelHead" id={`wf-${stepId}`}>
        <span className="wfPanelBadge">{step.status === "done" ? "✓" : step.stepNumber}</span>
        <div className="wfPanelTitles">
          <div className="smallTitle">{title}</div>
          <div className="muted">{step.hint}</div>
        </div>
        {step.status === "done" ? <span className="wfDoneTag">Done</span> : null}
        {step.status === "active" ? <span className="wfActiveTag">Current step</span> : null}
      </div>
      <fieldset className="wfPanelBody" disabled={locked}>
        {children}
      </fieldset>
      {footer && !locked ? <div className="wfPanelFooter">{footer}</div> : null}
      {locked ? <div className="wfPanelLockOverlay">Complete the previous step first</div> : null}
    </section>
  );
}
