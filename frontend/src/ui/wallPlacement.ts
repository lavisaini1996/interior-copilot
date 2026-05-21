/** Mirrors backend/wall_placement.py for instant UI feedback. */

export type WallId = "north" | "south" | "east" | "west";
export type WallAssignments = Record<WallId, string[]>;

const WALL_LABELS: Record<WallId, string> = {
  north: "North",
  south: "South",
  east: "East",
  west: "West",
};

const ITEM_WALL_SPACE_M: Record<string, number> = {
  bed: 1.65,
  headboard: 0,
  wardrobe: 1.85,
  loft: 1.2,
  bedside: 0.55,
  dresser: 1.25,
  chest_of_drawers: 0.9,
  tv_unit: 1.6,
  study: 1.2,
  desk: 1.2,
  wall_desk: 1.0,
  reading_chair: 0.85,
  bench: 1.2,
  mirror: 0.5,
  wall_sconces: 0,
  art: 0,
  planter: 0.45,
  accent_wall: 0,
  wallpaper: 0,
  sofa: 2.1,
  sectional: 2.6,
  accent_chair: 0.85,
  ottoman: 0.7,
  coffee_table: 1.1,
  side_table: 0.5,
  console: 1.2,
  bookshelf: 1.0,
  sideboard: 1.5,
  bar_cabinet: 1.0,
  floor_lamp: 0.4,
  fireplace: 1.2,
  base_cabinets: 2.4,
  wall_cabinets: 0,
  tall_unit: 0.65,
  hob: 0.6,
  chimney: 0,
  oven: 0.6,
  microwave: 0.5,
  sink: 0.8,
  dishwasher: 0.6,
  fridge: 0.7,
  counter: 1.5,
  peninsula: 1.4,
  backsplash: 0,
  open_shelving: 1.0,
  water_purifier: 0.35,
  vanity: 1.2,
  wc: 0.7,
  wall_wc: 0.55,
  shower: 0.9,
  bathtub: 1.7,
  linen: 0.6,
  niche: 0,
  towel_rack: 0,
  glass_partition: 0,
  wall_tile_feature: 0,
  dining_table: 1.6,
  dining_chairs: 0,
  crockery: 1.2,
  wine_rack: 0.6,
  pendant_light: 0,
  walkin: 2.2,
  shoe: 0.9,
  jewelry_safe: 0,
  drawers: 0,
  rod: 0,
  filing: 0.5,
  pegboard: 0,
  pooja_unit: 1.0,
  jali: 0,
  storage: 0.8,
  wall_paneling: 0,
  lighting: 0,
  coat_hooks: 0,
  vertical_garden: 0,
  seating: 1.2,
  cafe_table: 0.9,
  swing: 1.4,
  deck_floor: 0,
  washing_machine: 0.65,
  dryer: 0.65,
  drying_rack: 0.8,
  storage_cabinets: 1.2,
  iron_board: 0,
  chair: 0.75,
};

const DEFAULT_NS_WALL_M = 3.6;
const DEFAULT_EW_WALL_M = 4.2;
const ITEM_CLEARANCE_M = 0.25;
const MIN_USABLE_AFTER_OPENINGS_M = 0.9;

function num(v: unknown): number | null {
  if (v == null) return null;
  const x = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(x) && x > 0 ? x : null;
}

function wallLengthM(brief: Record<string, unknown>, wallId: WallId): number {
  const ln = num(brief.room_length_m);
  const wd = num(brief.room_width_m);
  if (wallId === "north" || wallId === "south") {
    return wd ?? DEFAULT_NS_WALL_M;
  }
  return ln ?? DEFAULT_EW_WALL_M;
}

function openingUsageM(openings: string[]): { useM: number; blocksAll: boolean } {
  let total = 0;
  for (const raw of openings) {
    const op = raw.trim().toLowerCase();
    if (!op) continue;
    if (
      op.includes("full-height") ||
      op.includes("full height") ||
      op.includes("glazing wall") ||
      op.includes("curtain wall") ||
      op.includes("entire wall")
    ) {
      return { useM: 999, blocksAll: true };
    }
    if (op.includes("double door")) total += 1.6;
    else if (op.includes("door")) total += 0.95;
    else if (op.includes("slider") || op.includes("sliding") || op.includes("folding")) total += 1.55;
    else if (op.includes("window") || op.includes("glazing")) total += 1.2;
    else if (op.includes("opening") || op.includes("arch")) total += 0.85;
    else total += 0.75;
  }
  return { useM: total, blocksAll: false };
}

function itemsUsageM(itemIds: string[]): number {
  let total = 0;
  for (const key of itemIds) {
    const space = ITEM_WALL_SPACE_M[key] ?? 0.7;
    if (space > 0) total += space + ITEM_CLEARANCE_M;
  }
  return total;
}

export function canPlaceOnWall(params: {
  brief: Record<string, unknown>;
  wallId: WallId;
  itemId: string;
  assignments: WallAssignments;
  openings: WallAssignments;
}): { ok: boolean; message: string } {
  const { brief, wallId, itemId, assignments, openings } = params;
  const wallName = WALL_LABELS[wallId];
  const itemSpace = ITEM_WALL_SPACE_M[itemId] ?? 0.7;
  if (itemSpace <= 0) return { ok: true, message: "" };

  const wallLen = wallLengthM(brief, wallId);
  const wallOps = openings[wallId] ?? [];
  const { useM: opUse, blocksAll } = openingUsageM(wallOps);

  if (blocksAll) {
    return {
      ok: false,
      message: `Cannot place on the ${wallName} wall: openings (e.g. full-height glazing) use the full wall. Try another wall.`,
    };
  }

  const current = assignments[wallId] ?? [];
  if (current.includes(itemId)) return { ok: true, message: "" };

  const usedItems = itemsUsageM(current);
  const needed = itemSpace + ITEM_CLEARANCE_M;
  const available = wallLen - opUse - usedItems;

  if (available < needed) {
    const opNote = wallOps.length ? ` Doors/windows need ~${opUse.toFixed(1)} m.` : "";
    const ln = num(brief.room_length_m);
    const wd = num(brief.room_width_m);
    const dimNote =
      ln && wd
        ? ` Wall ~${wallLen.toFixed(1)} m (${wallId === "north" || wallId === "south" ? "room width" : "room length"}).`
        : ` Estimated wall ~${wallLen.toFixed(1)} m — add room dimensions from the plan for accuracy.`;
    return {
      ok: false,
      message: `Not enough space on the ${wallName} wall (~${needed.toFixed(1)} m needed, ~${Math.max(0, available).toFixed(1)} m free).${opNote}${dimNote} Try another wall.`,
    };
  }

  if (opUse > 0 && available < needed + MIN_USABLE_AFTER_OPENINGS_M) {
    return {
      ok: false,
      message: `The ${wallName} wall is too tight next to doors/windows. Pick a wall with more clear space.`,
    };
  }

  return { ok: true, message: "" };
}

export function formatPlacementVerification(brief: Record<string, unknown>): string {
  const assignments = (brief.wall_assignments as WallAssignments) || {
    north: [],
    south: [],
    east: [],
    west: [],
  };
  const openings = (brief.wall_openings as WallAssignments) || {
    north: [],
    south: [],
    east: [],
    west: [],
  };
  const lines: string[] = ["Compass placement (verify in image — N/S/E/W):"];
  const deg = brief.floorplan_north_clockwise_deg;
  if (deg != null && !Number.isNaN(Number(deg))) {
    lines.push(`  Plan north: ${Number(deg) % 360}° clockwise from top of floor-plan image.`);
  }
  for (const wid of ["north", "south", "east", "west"] as WallId[]) {
    const items = assignments[wid] ?? [];
    const ops = openings[wid] ?? [];
    const itemTxt = items.map((v) => v.replace(/_/g, " ")).join(", ") || "—";
    const opTxt = ops.join("; ") || "none";
    lines.push(`  ${WALL_LABELS[wid]} wall — Furniture: ${itemTxt} | Openings: ${opTxt}`);
  }
  const ln = num(brief.room_length_m);
  const wd = num(brief.room_width_m);
  if (ln && wd) lines.push(`  Room size: ${ln.toFixed(2)} m (N↔S) × ${wd.toFixed(2)} m (E↔W).`);
  return lines.join("\n");
}
