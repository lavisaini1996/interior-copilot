import React, { useEffect, useMemo, useState } from "react";
import {
  ChatMessage,
  DesignVariant,
  fetchCatalogMaterials,
  ImagePayload,
  postDesigns,
  postIntake,
  type CatalogMaterial,
} from "./api";
import {
  canPlaceOnWall,
  normalizeDimsToMetres,
  resolveRoomDims,
  type WallAssignments as PlacementWalls,
} from "./wallPlacement";
import { SpeechInput } from "./SpeechInput";
import { intakeAssistantTail } from "./intakeMessages";
import { computeWorkflow, WorkflowSection, WorkflowStepper } from "./workflow";

type WallId = "north" | "south" | "east" | "west";
type WallAssignments = Record<WallId, string[]>;

const EMPTY_WALL_ASSIGNMENTS: WallAssignments = {
  north: [],
  south: [],
  east: [],
  west: [],
};

function makeDefaultBrief(): Record<string, unknown> {
  return {
    space_type: null,
    style_direction: null,
    mood_keywords: [],
    color_preferences: [],
    material_preferences: [],
    budget_band: null,
    must_include: [],
    must_avoid: [],
    notes: "",
    room_length_m: null,
    room_width_m: null,
    ceiling_height_m: null,
    use_floorplan_image_for_scale_only: false,
    rooms_detected: [],
    selected_room_id: null,
    selected_room_name: null,
    wall_assignments: { north: [], south: [], east: [], west: [] },
    wall_openings: { north: [], south: [], east: [], west: [] },
    floorplan_north_clockwise_deg: 0,
  };
}

const DEFAULT_BRIEF: Record<string, unknown> = makeDefaultBrief();

type WallItem = { value: string; label: string };

const WALL_ITEMS_BY_ROOM: Record<string, WallItem[]> = {
  bedroom: [
    { value: "bed", label: "Bed" },
    { value: "headboard", label: "Upholstered headboard" },
    { value: "wardrobe", label: "Wardrobe" },
    { value: "loft", label: "Loft storage" },
    { value: "bedside", label: "Bedside table" },
    { value: "dresser", label: "Dresser" },
    { value: "chest_of_drawers", label: "Chest of drawers" },
    { value: "tv_unit", label: "TV unit" },
    { value: "study", label: "Study desk" },
    { value: "reading_chair", label: "Reading chair" },
    { value: "bench", label: "Bench at foot" },
    { value: "mirror", label: "Mirror" },
    { value: "wall_sconces", label: "Wall sconces" },
    { value: "art", label: "Art / wall decor" },
    { value: "planter", label: "Planter" },
    { value: "accent_wall", label: "Accent wall / paneling" },
    { value: "wallpaper", label: "Wallpaper feature" },
  ],
  living: [
    { value: "sofa", label: "Sofa" },
    { value: "sectional", label: "Sectional sofa" },
    { value: "accent_chair", label: "Accent chair" },
    { value: "ottoman", label: "Ottoman" },
    { value: "coffee_table", label: "Coffee table" },
    { value: "side_table", label: "Side table" },
    { value: "tv_unit", label: "TV unit" },
    { value: "console", label: "Console" },
    { value: "bookshelf", label: "Bookshelf" },
    { value: "sideboard", label: "Sideboard / Buffet" },
    { value: "bar_cabinet", label: "Bar cabinet" },
    { value: "floor_lamp", label: "Floor lamp" },
    { value: "art", label: "Art / gallery wall" },
    { value: "mirror", label: "Mirror" },
    { value: "planter", label: "Planter" },
    { value: "accent_wall", label: "Accent wall / paneling" },
    { value: "fireplace", label: "Fireplace / faux fireplace" },
  ],
  kitchen: [
    { value: "base_cabinets", label: "Base cabinets" },
    { value: "wall_cabinets", label: "Wall / upper cabinets" },
    { value: "tall_unit", label: "Tall unit (pantry)" },
    { value: "hob", label: "Hob / Cooktop" },
    { value: "chimney", label: "Chimney / hood" },
    { value: "oven", label: "Built-in oven" },
    { value: "microwave", label: "Microwave nook" },
    { value: "sink", label: "Sink" },
    { value: "dishwasher", label: "Dishwasher" },
    { value: "fridge", label: "Fridge" },
    { value: "counter", label: "Breakfast counter" },
    { value: "peninsula", label: "Peninsula" },
    { value: "backsplash", label: "Backsplash" },
    { value: "open_shelving", label: "Open shelving" },
    { value: "water_purifier", label: "Water purifier" },
  ],
  bathroom: [
    { value: "vanity", label: "Vanity / counter" },
    { value: "wc", label: "WC" },
    { value: "wall_wc", label: "Wall-hung WC" },
    { value: "shower", label: "Shower / enclosure" },
    { value: "bathtub", label: "Bathtub" },
    { value: "mirror", label: "Mirror" },
    { value: "linen", label: "Linen cupboard" },
    { value: "niche", label: "Recessed niche" },
    { value: "towel_rack", label: "Towel rack" },
    { value: "glass_partition", label: "Glass partition" },
    { value: "planter", label: "Planter" },
    { value: "wall_tile_feature", label: "Feature wall tile" },
  ],
  dining: [
    { value: "dining_table", label: "Dining table" },
    { value: "dining_chairs", label: "Dining chairs" },
    { value: "bench", label: "Bench seating" },
    { value: "sideboard", label: "Sideboard / Buffet" },
    { value: "crockery", label: "Crockery unit" },
    { value: "bar_cabinet", label: "Bar cabinet" },
    { value: "wine_rack", label: "Wine rack" },
    { value: "pendant_light", label: "Pendant light(s)" },
    { value: "mirror", label: "Mirror" },
    { value: "art", label: "Art / wall decor" },
    { value: "accent_wall", label: "Accent wall / paneling" },
  ],
  wardrobes: [
    { value: "wardrobe", label: "Wardrobe (hinged/sliding)" },
    { value: "walkin", label: "Walk-in wardrobe layout" },
    { value: "loft", label: "Loft storage" },
    { value: "shoe", label: "Shoe storage" },
    { value: "dresser", label: "Dressing unit" },
    { value: "mirror", label: "Mirror" },
    { value: "jewelry_safe", label: "Jewelry / safe drawer" },
    { value: "drawers", label: "Pull-out drawers" },
    { value: "rod", label: "Hanging rod section" },
  ],
  study: [
    { value: "desk", label: "Desk" },
    { value: "wall_desk", label: "Wall-mounted desk" },
    { value: "chair", label: "Office chair" },
    { value: "bookshelf", label: "Bookshelf" },
    { value: "filing", label: "Filing cabinet" },
    { value: "pegboard", label: "Pegboard / pinboard" },
    { value: "art", label: "Art / wall decor" },
    { value: "planter", label: "Planter" },
    { value: "wardrobe", label: "Wardrobe" },
    { value: "accent_wall", label: "Accent wall / paneling" },
  ],
  pooja: [
    { value: "pooja_unit", label: "Pooja unit / mandir" },
    { value: "jali", label: "Jali / lattice screen" },
    { value: "storage", label: "Drawer storage" },
    { value: "wall_paneling", label: "Wood paneling" },
    { value: "art", label: "Devotional art" },
    { value: "lighting", label: "Cove / spot lighting" },
  ],
  foyer: [
    { value: "shoe", label: "Shoe storage" },
    { value: "console", label: "Console table" },
    { value: "mirror", label: "Mirror" },
    { value: "bench", label: "Bench" },
    { value: "coat_hooks", label: "Coat hooks" },
    { value: "art", label: "Art / wall decor" },
    { value: "planter", label: "Planter" },
    { value: "accent_wall", label: "Accent wall / paneling" },
  ],
  balcony: [
    { value: "planter", label: "Planter" },
    { value: "vertical_garden", label: "Vertical garden" },
    { value: "seating", label: "Seating bench" },
    { value: "cafe_table", label: "Café table" },
    { value: "swing", label: "Swing / jhoola" },
    { value: "lighting", label: "String / wall lighting" },
    { value: "deck_floor", label: "Deck flooring" },
  ],
  utility: [
    { value: "washing_machine", label: "Washing machine" },
    { value: "dryer", label: "Dryer" },
    { value: "drying_rack", label: "Drying rack" },
    { value: "sink", label: "Utility sink" },
    { value: "storage_cabinets", label: "Storage cabinets" },
    { value: "iron_board", label: "Iron / fold-out board" },
  ],
};
WALL_ITEMS_BY_ROOM.hall = WALL_ITEMS_BY_ROOM.living;

const ROOM_KEY_ALIASES: Record<string, string> = {
  // Bedrooms
  bedroom: "bedroom",
  bed: "bedroom",
  "master bedroom": "bedroom",
  "kids bedroom": "bedroom",
  "guest bedroom": "bedroom",
  headboards: "bedroom",
  "vanity beds": "bedroom",
  // Living / hall
  living: "living",
  "living room": "living",
  hall: "hall",
  lounge: "living",
  "tv units": "living",
  "multi-functional": "living",
  // Kitchen
  kitchen: "kitchen",
  kitchens: "kitchen",
  // Bathroom
  bathroom: "bathroom",
  "powder room": "bathroom",
  toilet: "bathroom",
  washroom: "bathroom",
  // Dining
  dining: "dining",
  "dining room": "dining",
  crockery: "dining",
  "bar units": "dining",
  // Wardrobes
  wardrobes: "wardrobes",
  wardrobe: "wardrobes",
  "walk-in closet": "wardrobes",
  "dresser units": "wardrobes",
  // Study / office
  study: "study",
  "study units": "study",
  "study room": "study",
  "home office": "study",
  // Pooja
  pooja: "pooja",
  "pooja units": "pooja",
  "pooja room": "pooja",
  // Foyer
  foyer: "foyer",
  "foyer units": "foyer",
  "foyer / entryway": "foyer",
  shoe: "foyer",
  partitions: "foyer",
  paneling: "foyer",
  // Balcony
  balcony: "balcony",
  // Utility
  utility: "utility",
  "utility / laundry": "utility",
  laundry: "utility",
};

function resolveRoomItemKey(brief: Record<string, unknown>): string {
  const candidates = [
    String(brief.selected_room_name ?? ""),
    String(brief.space_type ?? ""),
  ];
  for (const raw of candidates) {
    const low = raw.toLowerCase().trim();
    if (!low) continue;
    if (ROOM_KEY_ALIASES[low]) return ROOM_KEY_ALIASES[low];
    for (const alias of Object.keys(ROOM_KEY_ALIASES)) {
      if (low.includes(alias)) return ROOM_KEY_ALIASES[alias];
    }
  }
  return "bedroom";
}

function b64ToDataUrlPng(b64: string) {
  return `data:image/png;base64,${b64}`;
}

function formatINR(amount: number) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(amount);
}

function stepIndex(
  step:
    | "idle"
    | "analyzing"
    | "services"
    | "materials"
    | "catalog"
    | "rendering"
    | "pricing"
    | "done"
    | "error",
) {
  switch (step) {
    case "analyzing":
      return 0;
    case "services":
      return 1;
    case "materials":
      return 2;
    case "catalog":
      return 3;
    case "rendering":
      return 4;
    case "pricing":
      return 5;
    case "done":
      return 6;
    case "error":
    case "idle":
    default:
      return -1;
  }
}

type UploadedRef = {
  id: string;
  name: string;
  mime_type: string;
  data_base64: string;
  preview_data_url: string;
};

function stripDataUrlPrefix(dataUrl: string) {
  const idx = dataUrl.indexOf("base64,");
  if (idx === -1) return dataUrl;
  return dataUrl.slice(idx + "base64,".length);
}

const FULL_ROOM_TYPES = [
  "Master Bedroom",
  "Kids Bedroom",
  "Guest Bedroom",
  "Living Room",
  "Hall",
  "Dining Room",
  "Kitchen",
  "Bathroom",
  "Powder Room",
  "Study Room",
  "Home Office",
  "Pooja Room",
  "Foyer / Entryway",
  "Balcony",
  "Walk-in Closet",
  "Utility / Laundry",
] as const;

const MODULAR_SERVICE_TYPES = [
  "Kitchens",
  "Wardrobes",
  "Multi-functional",
  "TV Units",
  "Dining",
  "Crockery",
  "Bar units",
  "Pooja Units",
  "Shoe",
  "Foyer Units",
  "Dresser Units",
  "Study Units",
  "Vanity Beds",
  "Headboards",
  "Partitions",
  "Paneling",
] as const;

function labelForItem(value: string, items: WallItem[]): string {
  return items.find((i) => i.value === value)?.label ?? value;
}

function WallLayout(props: {
  brief: Record<string, unknown>;
  assignments: WallAssignments;
  openings?: WallAssignments;
  items: WallItem[];
  roomLabel: string;
  disabled?: boolean;
  onChange: (next: WallAssignments) => void;
}) {
  const { brief, assignments, openings, items, roomLabel, disabled, onChange } = props;
  const [activeWall, setActiveWall] = React.useState<WallId | null>(null);
  const [placementWarning, setPlacementWarning] = React.useState<string | null>(null);

  const emptyOpenings: WallAssignments = { north: [], south: [], east: [], west: [] };
  const wallOpenings = openings ?? emptyOpenings;

  const toggle = (wall: WallId, value: string) => {
    const current = assignments[wall] ?? [];
    if (current.includes(value)) {
      setPlacementWarning(null);
      onChange({ ...assignments, [wall]: current.filter((v) => v !== value) });
      return;
    }
    const check = canPlaceOnWall({
      brief,
      wallId: wall,
      itemId: value,
      assignments,
      openings: wallOpenings as PlacementWalls,
    });
    if (!check.ok) {
      setPlacementWarning(check.message);
      return;
    }
    setPlacementWarning(null);
    onChange({ ...assignments, [wall]: [...current, value] });
  };

  const clearWall = (wall: WallId) => onChange({ ...assignments, [wall]: [] });
  const clearAll = () => onChange({ ...EMPTY_WALL_ASSIGNMENTS });

  const walls: { id: WallId; label: string }[] = [
    { id: "north", label: "North" },
    { id: "east", label: "East" },
    { id: "south", label: "South" },
    { id: "west", label: "West" },
  ];

  const roomDims = resolveRoomDims(brief);
  const hasRoomDims = Boolean(roomDims.lengthM && roomDims.widthM);

  return (
    <div>
      <div className="wlHeader">
        <div className="muted">
          Click a wall to place items. Room: <strong>{roomLabel}</strong>. Generated images will lock furniture and
          doors/windows to these N/S/E/W walls.
          {typeof brief.floorplan_north_clockwise_deg === "number" &&
          !Number.isNaN(Number(brief.floorplan_north_clockwise_deg)) ? (
            <>
              {" "}
              Plan north is <strong>{Number(brief.floorplan_north_clockwise_deg) % 360}°</strong> clockwise from the top
              of your uploaded plan — align ↑ N on this diagram with north on the sheet.
            </>
          ) : null}
        </div>
        <button className="btn secondary" onClick={clearAll} disabled={disabled}>
          Reset all walls
        </button>
      </div>

      {placementWarning ? (
        <div className="wlPlacementWarn" role="alert">
          {placementWarning}
        </div>
      ) : null}

      <div className="wlBoard">
        <svg viewBox="0 0 320 220" className="wlSvg" role="img" aria-label="Room wall layout">
          <rect x="40" y="30" width="240" height="160" rx="6" className="wlRoomRect" />
          <text x="160" y="48" textAnchor="middle" className="wlCompassN">
            ↑ N
          </text>
          {/* North */}
          <g
            className={`wlWall ${activeWall === "north" ? "active" : ""}`}
            onClick={() => !disabled && setActiveWall("north")}
          >
            <rect x="40" y="22" width="240" height="14" />
            <text x="160" y="33" textAnchor="middle" className="wlWallLabel">
              N · {assignments.north.length || 0}
            </text>
          </g>
          {/* South */}
          <g
            className={`wlWall ${activeWall === "south" ? "active" : ""}`}
            onClick={() => !disabled && setActiveWall("south")}
          >
            <rect x="40" y="184" width="240" height="14" />
            <text x="160" y="195" textAnchor="middle" className="wlWallLabel">
              S · {assignments.south.length || 0}
            </text>
          </g>
          {/* East */}
          <g
            className={`wlWall ${activeWall === "east" ? "active" : ""}`}
            onClick={() => !disabled && setActiveWall("east")}
          >
            <rect x="274" y="30" width="14" height="160" />
            <text x="281" y="115" textAnchor="middle" className="wlWallLabel" transform="rotate(90 281 115)">
              E · {assignments.east.length || 0}
            </text>
          </g>
          {/* West */}
          <g
            className={`wlWall ${activeWall === "west" ? "active" : ""}`}
            onClick={() => !disabled && setActiveWall("west")}
          >
            <rect x="32" y="30" width="14" height="160" />
            <text x="39" y="115" textAnchor="middle" className="wlWallLabel" transform="rotate(-90 39 115)">
              W · {assignments.west.length || 0}
            </text>
          </g>
        </svg>

        <div className="wlSummary">
          {walls.map((w) => (
            <div className="wlSummaryRow" key={w.id}>
              <div className="wlSummaryLabel">{w.label}</div>
              <div>
                <div className="wlChips">
                  {(assignments[w.id] ?? []).length === 0 ? (
                    <span className="muted">(no furniture)</span>
                  ) : (
                    (assignments[w.id] ?? []).map((v) => (
                      <span className="wlChip" key={v}>
                        {labelForItem(v, items)}
                      </span>
                    ))
                  )}
                </div>
                {(openings?.[w.id] ?? []).length > 0 ? (
                  <div className="wlOpeningRow">
                    <span className="wlOpeningLabel">Openings</span>
                    <div className="wlChips">
                      {(openings![w.id] ?? []).map((op) => (
                        <span className="wlChip wlOpeningChip" key={op}>
                          {op}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </div>

      {activeWall ? (
        <div className="wlEditor">
          {!hasRoomDims ? (
            <p className="muted" style={{ marginBottom: 8 }}>
              Room size not read from the plan — item limits use conservative estimates. Select a room with dimensions
              for accurate fit checks.
            </p>
          ) : null}
          <div className="wlEditorHead">
            <div className="smallTitle">Place on {activeWall.toUpperCase()} wall</div>
            <div>
              <button className="btn secondary" onClick={() => clearWall(activeWall)} disabled={disabled}>
                Clear this wall
              </button>
              <button className="btn secondary" onClick={() => setActiveWall(null)} disabled={disabled} style={{ marginLeft: 8 }}>
                Done
              </button>
            </div>
          </div>
          <div className="wlItemGrid">
            {items.map((it) => {
              const selected = (assignments[activeWall] ?? []).includes(it.value);
              const fit =
                selected || !activeWall
                  ? { ok: true, message: "" }
                  : canPlaceOnWall({
                      brief,
                      wallId: activeWall,
                      itemId: it.value,
                      assignments,
                      openings: wallOpenings as PlacementWalls,
                    });
              const blocked = !selected && !fit.ok;
              return (
                <button
                  key={it.value}
                  className={`wlItemBtn ${selected ? "on" : ""} ${blocked ? "blocked" : ""}`}
                  onClick={() => !blocked && toggle(activeWall, it.value)}
                  disabled={disabled || blocked}
                  type="button"
                  title={blocked ? fit.message : selected ? "Remove from this wall" : undefined}
                  aria-disabled={blocked || disabled}
                >
                  {it.label}
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function App() {
  const [brief, setBrief] = useState<Record<string, unknown>>(makeDefaultBrief());
  const [chat, setChat] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content:
        "Upload a floor plan (step 2), then pick your room in plan setup. Step 1 materials are optional. Pricing is in INR. I will ask follow-ups for style and budget before generating catalog-backed designs.",
    },
  ]);
  const [input, setInput] = useState("");
  const [pendingQuestions, setPendingQuestions] = useState<string[]>([]);
  const [isComplete, setIsComplete] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  const [processingFloorplan, setProcessingFloorplan] = useState(false);
  const [syncingPlan, setSyncingPlan] = useState(false);
  const [designs, setDesigns] = useState<DesignVariant[]>([]);
  const [designCurrency, setDesignCurrency] = useState("INR");
  const [genStep, setGenStep] = useState<
    "idle" | "analyzing" | "services" | "materials" | "catalog" | "rendering" | "pricing" | "done" | "error"
  >("idle");
  const [error, setError] = useState<string | null>(null);
  const [styleRefs, setStyleRefs] = useState<UploadedRef[]>([]);
  const [floorplanRefs, setFloorplanRefs] = useState<UploadedRef[]>([]);
  const [floorplanPreview, setFloorplanPreview] = useState<UploadedRef | null>(null);
  const [floorplanText, setFloorplanText] = useState("");
  const [skipWallLayout, setSkipWallLayout] = useState(false);
  const [skipDesignMaterials, setSkipDesignMaterials] = useState(false);
  const [catalogMaterials, setCatalogMaterials] = useState<CatalogMaterial[]>([]);
  const [catalogMaterialsError, setCatalogMaterialsError] = useState<string | null>(null);

  const isGenerating =
    isBusy && genStep !== "idle" && genStep !== "done" && genStep !== "error";

  const genSteps = useMemo(
    () => [
      { key: "analyzing" as const, label: "Analyzing floor plan" },
      { key: "services" as const, label: "Applying services we offer" },
      { key: "materials" as const, label: "Applying material/finish preferences" },
      { key: "catalog" as const, label: "Selecting catalog items" },
      { key: "rendering" as const, label: "Generating images" },
      { key: "pricing" as const, label: "Pricing materials" },
    ],
    [],
  );

  const genOverlayTitle = useMemo(() => {
    const map: Record<string, string> = {
      analyzing: "Analyzing floor plan…",
      services: "Applying services…",
      materials: "Applying materials…",
      catalog: "Selecting catalog items…",
      rendering: "Generating images…",
      pricing: "Pricing in INR…",
    };
    return map[genStep] ?? "Generating…";
  }, [genStep]);

  const detectedRooms = useMemo(() => {
    const rooms = (brief as any)?.rooms_detected;
    return Array.isArray(rooms) ? rooms : [];
  }, [brief]);

  const selectedRoomIdForSelect = useMemo(() => {
    const rooms = detectedRooms;
    const rawId = String((brief as any)?.selected_room_id ?? "").trim();
    if (rawId && rooms.some((r: any) => String(r?.id) === rawId)) return rawId;
    const name = String((brief as any)?.selected_room_name ?? "").trim();
    if (name) {
      const byName = rooms.find((r: any) => String(r?.name ?? "").trim().toLowerCase() === name.toLowerCase());
      if (byName?.id) return String(byName.id);
    }
    return rawId;
  }, [brief, detectedRooms]);

  const hasFloorPlan = floorplanRefs.length > 0 || floorplanText.trim().length >= 12;

  useEffect(() => {
    if (!floorplanPreview) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFloorplanPreview(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [floorplanPreview]);


  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const mats = await fetchCatalogMaterials();
        if (!cancelled) {
          setCatalogMaterials(mats);
          setCatalogMaterialsError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setCatalogMaterialsError(e instanceof Error ? e.message : String(e));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedMaterialNames = useMemo(() => {
    const m = brief.material_preferences;
    return Array.isArray(m) ? m.map((x) => String(x)) : [];
  }, [brief.material_preferences]);

  const hasDesignNotes = useMemo(() => {
    return String(brief.notes ?? "").trim().length > 0;
  }, [brief.notes]);

  const onCatalogMaterialsChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const selected = Array.from(e.target.selectedOptions, (opt) => opt.value);
    setBrief((b) => ({ ...b, material_preferences: selected }));
    setSkipDesignMaterials(false);
  };

  const workflow = useMemo(
    () =>
      computeWorkflow({
        brief,
        floorplanImageCount: floorplanRefs.length,
        floorplanText,
        detectedRoomCount: detectedRooms.length,
        skipWallLayout,
        skipDesignMaterials,
        isComplete,
        designsCount: designs.length,
        isGenerating,
      }),
    [
      brief,
      floorplanRefs.length,
      floorplanText,
      detectedRooms.length,
      skipWallLayout,
      skipDesignMaterials,
      isComplete,
      designs.length,
      isGenerating,
    ],
  );

  const briefJson = useMemo(() => JSON.stringify(brief, null, 2), [brief]);

  const intakeContextImages: ImagePayload[] = useMemo(() => {
    // Give the intake assistant whatever context we have.
    const all = [...floorplanRefs, ...styleRefs];
    return all.map((r) => ({ mime_type: r.mime_type, data_base64: r.data_base64 }));
  }, [floorplanRefs, styleRefs]);

  const floorplanImages: ImagePayload[] = useMemo(
    () => floorplanRefs.map((r) => ({ mime_type: r.mime_type, data_base64: r.data_base64 })),
    [floorplanRefs],
  );

  async function syncFloorplanIntake(nextBrief: Record<string, unknown>) {
    if (!floorplanRefs.length) return;
    setError(null);
    setSyncingPlan(true);
    setIsBusy(true);
    try {
      const fpPayload: ImagePayload[] = floorplanRefs.map((r) => ({
        mime_type: r.mime_type,
        data_base64: r.data_base64,
      }));
      const stylePayload: ImagePayload[] = styleRefs.map((r) => ({
        mime_type: r.mime_type,
        data_base64: r.data_base64,
      }));
      const resp = await postIntake({
        brief: nextBrief,
        chat_history: chat,
        context_images: [...fpPayload, ...stylePayload],
        floorplan_images: fpPayload,
        max_questions: 4,
      });
      setBrief(resp.updated_brief as Record<string, unknown>);
      setPendingQuestions(resp.questions);
      setIsComplete(resp.is_complete);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setSyncingPlan(false);
      setIsBusy(false);
    }
  }

  const applySelectedRoom = (room: { id?: string; name?: string; length_m?: number; width_m?: number } | null) => {
    const rawLn =
      room?.length_m != null ? Number(room.length_m) : Number((brief as any).room_length_m) || null;
    const rawWd =
      room?.width_m != null ? Number(room.width_m) : Number((brief as any).room_width_m) || null;
    const { lengthM, widthM } = normalizeDimsToMetres(
      rawLn != null && Number.isFinite(rawLn) ? rawLn : null,
      rawWd != null && Number.isFinite(rawWd) ? rawWd : null,
    );
    const nextBrief: Record<string, unknown> = {
      ...brief,
      selected_room_id: room?.id ?? null,
      selected_room_name: room?.name ?? null,
      space_type: room?.name ? String(room.name).toLowerCase() : null,
      room_length_m: lengthM ?? (brief as any).room_length_m,
      room_width_m: widthM ?? (brief as any).room_width_m,
      wall_assignments: { ...EMPTY_WALL_ASSIGNMENTS },
      wall_openings: { ...EMPTY_WALL_ASSIGNMENTS },
    };
    setBrief(nextBrief);
    if (floorplanRefs.length && room?.id) void syncFloorplanIntake(nextBrief);
  };

  const styleImages: ImagePayload[] = useMemo(
    () => styleRefs.map((r) => ({ mime_type: r.mime_type, data_base64: r.data_base64 })),
    [styleRefs],
  );

  async function toUploadedRefs(files: FileList | null, limit: number) {
    if (!files || files.length === 0) return [];
    const picked = Array.from(files).slice(0, limit); // keep payload bounded
    const converted = await Promise.all(
      picked.map(
        (f) =>
          new Promise<UploadedRef>((resolve, reject) => {
            const reader = new FileReader();
            reader.onerror = () => reject(new Error(`Failed to read file: ${f.name}`));
            reader.onload = () => {
              const dataUrl = String(reader.result ?? "");
              resolve({
                id: crypto.randomUUID(),
                name: f.name,
                mime_type: f.type || "image/png",
                preview_data_url: dataUrl,
                data_base64: stripDataUrlPrefix(dataUrl),
              });
            };
            reader.readAsDataURL(f);
          }),
      ),
    );
    return converted;
  }

  async function onPickStyleImages(files: FileList | null) {
    setError(null);
    const converted = await toUploadedRefs(files, 6);
    if (!converted.length) return;
    setStyleRefs((prev) => [...prev, ...converted].slice(0, 6));
  }

  async function onPickFloorplan(files: FileList | null) {
    setError(null);
    const converted = await toUploadedRefs(files, 1);
    if (!converted.length) return;
    const newFp = converted.slice(0, 1);
    setFloorplanRefs(newFp);
    setProcessingFloorplan(true);

    const fpPayload: ImagePayload[] = newFp.map((r) => ({ mime_type: r.mime_type, data_base64: r.data_base64 }));
    const stylePayload: ImagePayload[] = styleRefs.map((r) => ({ mime_type: r.mime_type, data_base64: r.data_base64 }));
    const contextForIntake = [...fpPayload, ...stylePayload];

    const userLine =
      "[Floor plan image attached] Read dimensions from the plan where shown. Ask only follow-ups that are still missing (style, materials, budget in INR, etc.). If the plan has no readable scale, I will say I want layout scaled only from the drawing.";
    const nextChat: ChatMessage[] = [...chat, { role: "user", content: userLine }];

    setIsBusy(true);
    setDesigns([]);
    try {
      const resp = await postIntake({
        brief: {
          ...brief,
          rooms_detected: [],
          selected_room_id: null,
          selected_room_name: null,
          wall_assignments: { ...EMPTY_WALL_ASSIGNMENTS },
          wall_openings: { ...EMPTY_WALL_ASSIGNMENTS },
        },
        chat_history: nextChat,
        context_images: contextForIntake,
        floorplan_images: fpPayload,
        max_questions: 4,
      });
      setBrief(resp.updated_brief as Record<string, unknown>);
      setPendingQuestions([]);
      setIsComplete(resp.is_complete);
      setChat([...nextChat, ...intakeAssistantTail(resp.is_complete, true)]);
    } catch (e: any) {
      setError(e?.message ?? String(e));
      setFloorplanRefs([]);
    } finally {
      setProcessingFloorplan(false);
      setIsBusy(false);
    }
  }

  async function onSend() {
    const trimmed = input.trim();
    if (!trimmed || isBusy) return;
    setError(null);
    setDesigns([]);

    const nextChat = [...chat, { role: "user" as const, content: trimmed }];
    setInput("");
    setIsBusy(true);

    try {
      const resp = await postIntake({
        brief,
        chat_history: nextChat,
        context_images: intakeContextImages,
        floorplan_images: floorplanImages,
        max_questions: 4,
      });
      setBrief(resp.updated_brief as Record<string, unknown>);
      setPendingQuestions([]);
      setIsComplete(resp.is_complete);
      setChat([...nextChat, ...intakeAssistantTail(resp.is_complete, floorplanImages.length > 0)]);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setIsBusy(false);
    }
  }

  async function onGenerate() {
    if (isBusy) return;
    setError(null);
    setIsBusy(true);
    setDesigns([]);
    setGenStep("analyzing");
    try {
      if (!floorplanImages.length && !floorplanText.trim()) {
        throw new Error("Please add a floor plan image or describe the floor plan in text before generating designs.");
      }

      let t1: number | null = null;
      let t2: number | null = null;
      let t3: number | null = null;
      let t4: number | null = null;
      let t5: number | null = null;
      t1 = window.setTimeout(() => setGenStep("services"), 700);
      t2 = window.setTimeout(() => setGenStep("materials"), 1400);
      t3 = window.setTimeout(() => setGenStep("catalog"), 2200);
      t4 = window.setTimeout(() => setGenStep("rendering"), 3200);
      t5 = window.setTimeout(() => setGenStep("pricing"), 5200);

      const resp = await postDesigns({
        brief,
        chat_history: chat,
        floorplan_text: floorplanText.trim() || undefined,
        floorplan_images: floorplanImages,
        style_reference_images: styleImages,
        num_designs: 3,
      });
      setDesignCurrency(resp.currency ?? "INR");
      setDesigns(resp.designs);
      setGenStep("done");
      setChat((c) => [
        ...c,
        {
          role: "assistant",
          content:
            "Design options generated. Tell me which option you prefer (1/2/3) and what to change (layout, palette, materials) and I’ll iterate using only catalog items.",
        },
      ]);

      if (t1) window.clearTimeout(t1);
      if (t2) window.clearTimeout(t2);
      if (t3) window.clearTimeout(t3);
      if (t4) window.clearTimeout(t4);
      if (t5) window.clearTimeout(t5);
    } catch (e: any) {
      setError(e?.message ?? String(e));
      setGenStep("error");
    } finally {
      setIsBusy(false);
    }
  }

  function onReset() {
    setBrief(makeDefaultBrief());
    setChat([
      {
        role: "assistant",
        content:
          "Upload a floor plan (step 2), then pick your room in plan setup. Step 1 materials are optional. Pricing is in INR. I will ask follow-ups for style and budget before generating catalog-backed designs.",
      },
    ]);
    setPendingQuestions([]);
    setIsComplete(false);
    setDesigns([]);
    setDesignCurrency("INR");
    setGenStep("idle");
    setError(null);
    setInput("");
    setStyleRefs([]);
    setFloorplanRefs([]);
    setFloorplanText("");
    setProcessingFloorplan(false);
    setSyncingPlan(false);
    setSkipWallLayout(false);
    setSkipDesignMaterials(false);
  }

  return (
    <div className="page">
      {isBusy && genStep !== "idle" ? (
        <div className="fullscreenLoader" role="status" aria-live="polite" aria-label={genOverlayTitle}>
          <div className="fullscreenLoaderCard">
            <div className="spinner" aria-hidden="true" />
            <div className="fullscreenLoaderTitle">{genOverlayTitle}</div>
            <div className="fullscreenLoaderSub">
              {hasFloorPlan && !skipWallLayout
                ? "Generating 1 room render + 3 catalog options (~1–2 min, economy mode). Options 2–3 show BOM only."
                : "Please wait — this can take a minute."}
            </div>
            <div className="stepper" style={{ marginTop: 14 }}>
              {genSteps.map((s, i) => {
                const cur = stepIndex(genStep);
                const done = cur >= 0 && i < cur;
                const active = cur === i;
                return (
                  <div key={s.key} className={`step ${done ? "done" : ""} ${active ? "active" : ""}`}>
                    <div className="rail" aria-hidden="true">
                      <div className="dot" />
                      {i < genSteps.length - 1 ? <div className="line" /> : null}
                    </div>
                    <div className="stepBody">
                      <div className="stepTitle">
                        {i + 1}. {s.label}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      ) : null}

      <header className="header">
        <div>
          <div className="title">Interior Copilot</div>
          <div className="subtitle">
            Follow the steps in order — each unlocks the next until you generate designs.
          </div>
        </div>
        <div className="headerActions">
          <button className="btn secondary" onClick={onReset} disabled={isBusy}>
            Reset
          </button>
          <button
            className="btn primary"
            onClick={onGenerate}
            disabled={isBusy || !workflow.canGenerate}
            title={
              workflow.canGenerate
                ? undefined
                : "Complete earlier steps and finish the brief in chat (step 5) first."
            }
          >
            Generate designs
          </button>
        </div>
      </header>

      <section className="card wfOverviewCard">
        <WorkflowStepper steps={workflow.steps} activeStepId={workflow.activeStepId} />
      </section>

      <div className="wfFlow">
        <WorkflowSection
          stepId="designType"
          steps={workflow.steps}
          title="Material preference (optional)"
          footer={
            !hasDesignNotes && selectedMaterialNames.length === 0 ? (
              <button
                type="button"
                className="btn secondary"
                onClick={() => setSkipDesignMaterials(true)}
                disabled={isBusy || skipDesignMaterials}
              >
                Continue without materials
              </button>
            ) : null
          }
        >
          <p className="muted" style={{ marginBottom: 12 }}>
            Optional step. Choose finishes from the catalog and/or describe preferences by voice. Pick your room from the
            floor plan in step 3.
          </p>

          <div className="uploadRow" style={{ marginTop: 0 }}>
            <div className="uploadMeta">
              <div className="smallTitle">Materials from catalog</div>
              <div className="muted">Hold Ctrl (Windows) or ⌘ (Mac) to select multiple. Names only.</div>
            </div>
            <select
              className="select catalogMatSelect"
              multiple
              size={8}
              value={selectedMaterialNames}
              onChange={onCatalogMaterialsChange}
              disabled={isBusy || !catalogMaterials.length}
              aria-label="Catalog materials"
            >
              {catalogMaterials.map((m) => (
                <option key={m.id} value={m.name}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>
          {catalogMaterialsError ? (
            <p className="pill warn" style={{ marginTop: 8 }}>
              Could not load catalog: {catalogMaterialsError}
            </p>
          ) : null}

          <SpeechInput
            label="Speak or type preferences (optional)"
            placeholder="e.g. Bedroom ground floor, modern minimal, ₹5 lakh budget, elegant mood…"
            value={String(brief.notes ?? "")}
            onChange={(text) => setBrief((b) => ({ ...b, notes: text }))}
            disabled={isBusy}
          />
        </WorkflowSection>

        <WorkflowSection stepId="floorPlan" steps={workflow.steps} title="Floor plan">
          <div className="uploadRow">
            <div className="uploadMeta">
              <div className="smallTitle">Floor plan image</div>
              <div className="muted">Upload a plan image (recommended), or add a text description below.</div>
            </div>
            <label className="fileBtn">
              <input
                type="file"
                accept="image/*"
                onChange={(e) => onPickFloorplan(e.target.files)}
                disabled={isBusy || processingFloorplan}
              />
              Add floor plan image
            </label>
            {floorplanRefs.length ? (
              <button
                className="btn secondary"
                onClick={() => {
                  setFloorplanRefs([]);
                  setProcessingFloorplan(false);
                }}
                disabled={isBusy || processingFloorplan}
              >
                Clear
              </button>
            ) : null}
          </div>
          {floorplanRefs.length ? (
            <div className="thumbs fpThumbs">
              {floorplanRefs.map((r) => (
                <div className="thumb" key={r.id} title="Click to preview">
                  <button
                    type="button"
                    className="thumbBtn"
                    onClick={() => setFloorplanPreview(r)}
                    disabled={isBusy || processingFloorplan}
                    aria-label={`Preview ${r.name}`}
                  >
                    <img className="thumbImg" src={r.preview_data_url} alt={r.name} />
                  </button>
                  <button
                    className="thumbX"
                    onClick={() => setFloorplanRefs((prev) => prev.filter((x) => x.id !== r.id))}
                    disabled={isBusy || processingFloorplan}
                    aria-label={`Remove ${r.name}`}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          ) : null}
          {processingFloorplan ? (
            <div className="planSyncLoader fpProcessingLoader" role="status" aria-live="polite">
              <div className="spinner" aria-hidden="true" />
              <div>
                <div className="planSyncLoaderTitle">Reading your floor plan…</div>
                <div className="muted planSyncLoaderSub">
                  Detecting rooms and layout. The room dropdown in Plan setup will appear when this finishes.
                </div>
              </div>
            </div>
          ) : null}
          <textarea
            className="input"
            placeholder="Floor plan text (optional). Example: Room 4.2m x 3.6m, door on south wall, window on east."
            value={floorplanText}
            onChange={(e) => setFloorplanText(e.target.value)}
            rows={3}
            disabled={isBusy || processingFloorplan}
            style={{ marginTop: 12 }}
          />
        </WorkflowSection>

        <WorkflowSection stepId="planSetup" steps={workflow.steps} title="Plan setup">
          {!hasFloorPlan ? (
            <p className="muted">Add a floor plan in step 2 first, then pick a room here.</p>
          ) : null}

          {hasFloorPlan && processingFloorplan && detectedRooms.length === 0 ? (
            <div className="planSyncLoader" role="status" aria-live="polite" style={{ marginBottom: 16 }}>
              <div className="spinner" aria-hidden="true" />
              <div>
                <div className="planSyncLoaderTitle">Processing floor plan…</div>
                <div className="muted planSyncLoaderSub">Room list loading — please wait.</div>
              </div>
            </div>
          ) : null}

          {hasFloorPlan && detectedRooms.length >= 1 ? (
            <div style={{ marginTop: 0, marginBottom: 16 }}>
              <div className="uploadRow">
                <div className="uploadMeta">
                  <div className="smallTitle">Select room from floor plan</div>
                  <div className="muted">Choose which room on the plan you want to design.</div>
                </div>
                <select
                  className="select"
                  value={selectedRoomIdForSelect}
                  onChange={(e) => {
                    const id = e.target.value || null;
                    const room = detectedRooms.find((x: any) => String(x?.id) === String(id)) ?? null;
                    applySelectedRoom(room as { id?: string; name?: string; length_m?: number; width_m?: number });
                  }}
                  disabled={isBusy || syncingPlan}
                >
                  <option value="">Select room…</option>
                  {detectedRooms.map((r: any) => (
                    <option key={String(r.id)} value={String(r.id)}>
                      {String(r.name)}
                      {r.length_m && r.width_m ? ` (${r.length_m}m × ${r.width_m}m)` : ""}
                    </option>
                  ))}
                </select>
              </div>
              {syncingPlan ? (
                <div className="planSyncLoader" role="status" aria-live="polite">
                  <div className="spinner" aria-hidden="true" />
                  <div>
                    <div className="planSyncLoaderTitle">Reading this room on the plan…</div>
                    <div className="muted planSyncLoaderSub">
                      Detecting doors and windows on each wall. Wall layout updates when this finishes.
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}

          {!floorplanRefs.length ? (
            <p className="muted">No plan image — optional. Upload an image in step 2 for automatic room and north detection.</p>
          ) : null}
          {floorplanRefs.length ? (
            <p className="muted" style={{ marginTop: 8 }}>
              Plan north and doors/windows are detected automatically when you select a room. Check step 4 for hallway,
              closet, and balcony openings on each wall.
            </p>
          ) : null}

        </WorkflowSection>

        <WorkflowSection stepId="wallLayout" steps={workflow.steps} title="Wall layout (optional)">
          <button
            type="button"
            className="btn secondary"
            style={{ marginBottom: 12 }}
            onClick={() => setSkipWallLayout(true)}
            disabled={isBusy || skipWallLayout}
          >
            Continue without wall layout
          </button>
          {hasFloorPlan && !(brief as any)?.selected_room_id ? (
            <p className="muted">Select a room in Plan setup to load doors and windows on each wall.</p>
          ) : null}
          {hasFloorPlan && (brief as any)?.selected_room_id && syncingPlan ? (
            <div className="planSyncLoader wlSyncLoader" role="status" aria-live="polite">
              <div className="spinner" aria-hidden="true" />
              <div>
                <div className="planSyncLoaderTitle">
                  Updating wall layout for {(brief as any).selected_room_name || "this room"}…
                </div>
                <div className="muted planSyncLoaderSub">North, south, east, and west openings will refresh shortly.</div>
              </div>
            </div>
          ) : null}
          {hasFloorPlan && (brief as any)?.selected_room_id && !syncingPlan ? (
            <WallLayout
              key={String((brief as any).selected_room_id)}
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
          ) : null}
          {!hasFloorPlan ? (
            <p className="muted">Add a floor plan in step 2 to place items on walls.</p>
          ) : null}
        </WorkflowSection>

        <WorkflowSection stepId="preferences" steps={workflow.steps} title="Style & budget (optional)">
          <p className="muted" style={{ marginBottom: 10 }}>
            No follow-up questions — add preferences in step 1 notes or optional chat below. Anything missing is filled
            automatically (random style, budget band, and mood).
          </p>
          <div className="chat">
            {chat.map((m, idx) => (
              <div key={idx} className={`msg ${m.role}`}>
                <div className="role">{m.role}</div>
                <pre className="content">{m.content}</pre>
              </div>
            ))}
          </div>

          <div className="composer">
            <textarea
              className="input"
              placeholder="Optional: style, budget (INR), mood, room name…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              rows={3}
              disabled={isBusy}
            />
            <button className="btn primary" onClick={onSend} disabled={isBusy || !input.trim()}>
              Send
            </button>
          </div>

          {error ? (
            <div className="error">
              <div className="errorTitle">Error</div>
              <pre className="errorBody">{error}</pre>
              <div className="hint">
                Make sure the backend is running and that <code>GEMINI_API_KEY</code> is set in <code>.env</code>.
              </div>
            </div>
          ) : null}

          <div className="statusRow">
            <div className={`pill ${isComplete ? "ok" : "warn"}`}>
              {isComplete ? "Brief complete" : "Needs more info"}
            </div>
            <div className="pill neutral">Preferences auto-filled when not specified</div>
            {isBusy ? <div className="pill neutral">Working…</div> : null}
          </div>
        </WorkflowSection>

        <WorkflowSection stepId="styleRefs" steps={workflow.steps} title="Style references (optional)">
          <div className="uploadRow">
            <div className="uploadMeta">
              <div className="smallTitle">Optional: style reference images</div>
              <div className="muted">Helps infer style, palette, and materials.</div>
            </div>
            <label className="fileBtn">
              <input
                type="file"
                accept="image/*"
                multiple
                onChange={(e) => onPickStyleImages(e.target.files)}
                disabled={isBusy}
              />
              Add style images
            </label>
            {styleRefs.length ? (
              <button className="btn secondary" onClick={() => setStyleRefs([])} disabled={isBusy}>
                Clear
              </button>
            ) : null}
          </div>
          {styleRefs.length ? (
            <div className="thumbs">
              {styleRefs.map((r) => (
                <div className="thumb" key={r.id} title={r.name}>
                  <img className="thumbImg" src={r.preview_data_url} alt={r.name} />
                  <button
                    className="thumbX"
                    onClick={() => setStyleRefs((prev) => prev.filter((x) => x.id !== r.id))}
                    disabled={isBusy}
                    aria-label={`Remove ${r.name}`}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          ) : null}


        </WorkflowSection>

        <WorkflowSection stepId="generate" steps={workflow.steps} title="Generate designs">
          <div className="wfGenerateBlock">
            <p className="muted">
              {workflow.canGenerate
                ? "Your brief is complete. Generate catalog design options with images and INR pricing."
                : "Finish step 5 (chat) until the brief shows complete, then generate here."}
            </p>
            <button className="btn primary" onClick={onGenerate} disabled={isBusy || !workflow.canGenerate}>
              Generate designs
            </button>
          </div>
        </WorkflowSection>

        <WorkflowSection stepId="results" steps={workflow.steps} title="Your designs">
          <div className="cardTitle" style={{ marginBottom: 12 }}>Design options (catalog only, {designCurrency})</div>
          {isBusy && !designs.length ? (
            <div className="empty">
              <div className="smallTitle">Generating…</div>
              <div className="muted">We’re applying your selected services + materials, then generating images.</div>
              {(() => {
                const cur = stepIndex(genStep);
                return (
                  <div className="stepper" style={{ marginTop: 12 }}>
                    {genSteps.map((s, i) => {
                      const done = cur >= 0 && i < cur;
                      const active = cur === i;
                      return (
                        <div key={s.key} className={`step ${done ? "done" : ""} ${active ? "active" : ""}`}>
                          <div className="rail" aria-hidden="true">
                            <div className="dot" />
                            {i < genSteps.length - 1 ? <div className="line" /> : null}
                          </div>
                          <div className="stepBody">
                            <div className="stepTitle">
                              {i + 1}. {s.label}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                );
              })()}
            </div>
          ) : designs.length ? (
            <div className="images">
              {designs.map((d, i) => (
                <div className="imgWrap" key={i}>
                  {d.image_base64_png ? (
                    <img className="img" src={b64ToDataUrlPng(d.image_base64_png)} alt={`Design option ${i + 1}`} />
                  ) : (
                    <div className="empty">
                      No verified image for this option — wall layout could not be matched. Try Generate again or
                      check options marked Layout verified first.
                    </div>
                  )}
                  <div className="smallTitle">
                    Option {i + 1}: {d.title}
                    {d.layout_verified ? (
                      <span className="pill ok" style={{ marginLeft: 8 }}>
                        Layout verified
                      </span>
                    ) : d.image_base64_png ? (
                      <span className="pill warn" style={{ marginLeft: 8 }}>
                        Layout not verified
                      </span>
                    ) : null}
                  </div>
                  {d.placement_summary ? (
                    <pre className="content placementMap">{d.placement_summary}</pre>
                  ) : null}
                  <pre className="content">{d.rationale}</pre>

                  <div className="prompts">
                    <div className="smallTitle">Catalog items</div>
                    <ul>
                      {d.catalog_items.map((it) => (
                        <li key={it.id} className="mono">
                          {it.name} — {formatINR(it.price)}
                        </li>
                      ))}
                    </ul>
                    <div className="smallTitle">Materials (priced)</div>
                    <ul>
                      {d.materials.map((m) => (
                        <li key={m.material_id} className="mono">
                          {m.name}: {m.quantity} {m.unit} × {formatINR(m.unit_price)} = {formatINR(m.subtotal)}
                        </li>
                      ))}
                    </ul>
                    <div className="pill ok">Estimated total: {formatINR(d.estimated_total)}</div>
                  </div>

                  {d.image_base64_png ? (
                    <a className="download" href={b64ToDataUrlPng(d.image_base64_png)} download={`design_${i + 1}.png`}>
                      Download PNG
                    </a>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <div className="empty">
              No designs yet. Answer follow-ups until the brief shows complete, add a floor plan (image or text), then click
              Generate designs.
            </div>
          )}

        </WorkflowSection>

      </div>

      {floorplanPreview ? (
        <div
          className="imgModalOverlay"
          role="dialog"
          aria-modal="true"
          aria-label="Floor plan preview"
          onClick={() => setFloorplanPreview(null)}
        >
          <div className="imgModal" onClick={(e) => e.stopPropagation()}>
            <div className="imgModalTop">
              <div className="imgModalTitle">{floorplanPreview.name}</div>
              <button className="btn secondary" onClick={() => setFloorplanPreview(null)}>
                Close
              </button>
            </div>
            <img className="imgModalImg" src={floorplanPreview.preview_data_url} alt={floorplanPreview.name} />
            <div className="muted" style={{ marginTop: 8 }}>
              Tip: press <strong>Esc</strong> to close.
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

