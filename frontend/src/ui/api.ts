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

export type MoodboardVariant = {
  label: string;
  components: string[];
  prompt: string;
  image_base64_png?: string | null;
};

export type MoodboardWallPanel = {
  zone_id: string;
  zone_type: string;
  title: string;
  openings_summary: string;
  variants: MoodboardVariant[];
};

export type MoodboardWallsResponse = {
  updated_brief: Record<string, unknown>;
  panels: MoodboardWallPanel[];
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
  layout_verified?: boolean;
  catalog_items: DesignItem[];
  materials: DesignMaterialLine[];
  estimated_total: number;
  image_base64_png?: string | null;
  prompt: string;
};

export type DesignsResponse = { currency?: string; designs: DesignVariant[] };

export type CatalogMaterial = {
  id: string;
  name: string;
  unit: string;
  unit_price: number;
};

/** local | production — which URL to use when VITE_API_BASE is not set */
export type ApiTarget = "local" | "production";

function stripTrailingSlash(url: string): string {
  return url.replace(/\/$/, "");
}

/** Resolve backend URL: explicit VITE_API_BASE wins, else local vs production from env. */
export function resolveApiBase(): string {
  const explicit = (import.meta.env.VITE_API_BASE as string | undefined)?.trim();
  if (explicit) return stripTrailingSlash(explicit);

  const target = ((import.meta.env.VITE_API_TARGET as string | undefined) ?? "local").toLowerCase();
  const local = stripTrailingSlash(
    (import.meta.env.VITE_API_BASE_LOCAL as string | undefined)?.trim() || "http://localhost:8000"
  );
  const production = (import.meta.env.VITE_API_BASE_PRODUCTION as string | undefined)?.trim() || "";

  if (target === "production" || target === "prod") {
    if (!production) {
      console.warn("VITE_API_TARGET=production but VITE_API_BASE_PRODUCTION is empty; falling back to local.");
      return local;
    }
    return stripTrailingSlash(production);
  }
  return local;
}

export function activeApiTarget(): ApiTarget {
  const explicit = (import.meta.env.VITE_API_BASE as string | undefined)?.trim();
  if (explicit) {
    return explicit.includes("localhost") || explicit.includes("127.0.0.1") ? "local" : "production";
  }
  const t = ((import.meta.env.VITE_API_TARGET as string | undefined) ?? "local").toLowerCase();
  return t === "production" || t === "prod" ? "production" : "local";
}

const API_BASE = resolveApiBase();

export async function fetchCatalogMaterials(): Promise<CatalogMaterial[]> {
  const res = await fetch(`${API_BASE}/api/catalog/materials`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return (await res.json()) as CatalogMaterial[];
}

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

export async function postMoodboardWalls(params: {
  brief: Record<string, unknown>;
  floorplan_images?: ImagePayload[];
  context_images?: ImagePayload[];
  variants_per_wall?: number;
}): Promise<MoodboardWallsResponse> {
  const res = await fetch(`${API_BASE}/api/moodboard/walls`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      brief: params.brief,
      floorplan_images: params.floorplan_images ?? [],
      context_images: params.context_images ?? [],
      variants_per_wall: params.variants_per_wall ?? 3,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return (await res.json()) as MoodboardWallsResponse;
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

