import type { ChatMessage } from "./api";

/** Assistant line after intake — no follow-up question lists. */
export function intakeAssistantTail(isComplete: boolean, hasFloorPlan: boolean): ChatMessage[] {
  if (!isComplete) {
    return [
      {
        role: "assistant",
        content: "Still processing your plan — try again in a moment.",
      },
    ];
  }
  if (hasFloorPlan) {
    return [
      {
        role: "assistant",
        content:
          "Ready to go. Pick your room in Plan setup (step 3). Style, budget, and mood are set from your notes or sensible defaults — use optional chat below only if you want to change them.",
      },
    ];
  }
  return [
    {
      role: "assistant",
      content:
        "Preferences are set. Upload a floor plan in step 2, then continue through plan setup and generate.",
    },
  ];
}
