export type ChatMessage = { role: "user" | "assistant"; content: string };

export type ImagePayload = { mime_type: string; data_base64: string };

export type IntakeResponse = {
  is_complete: boolean;
  updated_brief: Record<string, unknown>;
  questions: string[];
};

export type MoodboardResponse = {
  prompts: string[];
  images_base64_png: string[];
};

export type DesignItem = { id: string; name: string; category: string; price: number };
export type DesignMaterialLine = {
  material_id: string;
  name: string;
  unit: string;
  unit_price: number;
  quantity: number;
  subtotal: number;
};

export type DesignVariant = {
  title: string;
  rationale: string;
  placement_summary?: string;
  catalog_items: DesignItem[];
  materials: DesignMaterialLine[];
  estimated_total: number;
  image_base64_png?: string | null;
  prompt: string;
};

export type DesignsResponse = { currency?: string; designs: DesignVariant[] };

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export async function postIntake(params: {
  brief: Record<string, unknown>;
  chat_history: ChatMessage[];
  context_images?: ImagePayload[];
  /** Floor plan image(s) only; backend uses these to read dimensions and to skip manual room-size questions. */
  floorplan_images?: ImagePayload[];
  max_questions?: number;
}): Promise<IntakeResponse> {
  const res = await fetch(`${API_BASE}/api/intake`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      brief: params.brief,
      chat_history: params.chat_history,
      context_images: params.context_images ?? [],
      floorplan_images: params.floorplan_images ?? [],
      max_questions: params.max_questions ?? 3,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return (await res.json()) as IntakeResponse;
}

export async function postMoodboard(params: {
  brief: Record<string, unknown>;
  context_images?: ImagePayload[];
  num_images?: number;
}): Promise<MoodboardResponse> {
  const res = await fetch(`${API_BASE}/api/moodboard`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      brief: params.brief,
      context_images: params.context_images ?? [],
      num_images: params.num_images ?? 3,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return (await res.json()) as MoodboardResponse;
}

export async function postDesigns(params: {
  brief: Record<string, unknown>;
  chat_history: ChatMessage[];
  floorplan_text?: string;
  floorplan_images?: ImagePayload[];
  style_reference_images?: ImagePayload[];
  num_designs?: number;
}): Promise<DesignsResponse> {
  const res = await fetch(`${API_BASE}/api/designs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      brief: params.brief,
      chat_history: params.chat_history,
      floorplan_text: params.floorplan_text ?? null,
      floorplan_images: params.floorplan_images ?? [],
      style_reference_images: params.style_reference_images ?? [],
      num_designs: params.num_designs ?? 3,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return (await res.json()) as DesignsResponse;
}

