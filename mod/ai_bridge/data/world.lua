-- PA Agent Bridge: in-game runtime (world script).
--
-- Talks to pa_bridge.dll (installed as GLU32.dll in the game folder) through
-- the patched Game.DebugOut. Requests arrive as JSON lines:
--   {"id":1,"op":"exec","code":"return Game.Time()"}
--   {"id":2,"op":"call","fn":"build_wall","args":["BrickWall",10,10,20,10]}
--   {"id":3,"op":"ping"}
-- and every request gets exactly one reply:
--   {"type":"result","id":1,"ok":true,"result":...} or ok=false,"error":"..."
--
-- Without the DLL this script does nothing.

local VERSION = "0.3.1"
local MAX_REQUESTS_PER_TICK = 64

---------------------------------------------------------------------------
-- JSON
---------------------------------------------------------------------------
local json = {}

local escapes = { ['"'] = '\\"', ['\\'] = '\\\\', ['\b'] = '\\b', ['\f'] = '\\f',
                  ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t' }

local function esc_str(s)
    return '"' .. string.gsub(s, '[%c"\\]', function(c)
        return escapes[c] or string.format("\\u%04x", string.byte(c))
    end) .. '"'
end

local function is_array(t)
    local n = 0
    for k, _ in pairs(t) do
        if type(k) ~= "number" or k < 1 or math.floor(k) ~= k then return false end
        if k > n then n = k end
    end
    for i = 1, n do if t[i] == nil then return false end end
    return true, n
end

local function encode(v, depth, seen, budget)
    local tv = type(v)
    if tv == "nil" then return "null" end
    if tv == "boolean" then return v and "true" or "false" end
    if tv == "number" then
        if v ~= v or v == math.huge or v == -math.huge then return "null" end
        if math.floor(v) == v and v > -1e15 and v < 1e15 then return string.format("%d", v) end
        return string.format("%.14g", v)
    end
    if tv == "string" then return esc_str(v) end
    if tv ~= "table" then return esc_str("<" .. tv .. ">") end
    if seen[v] then return '"<cycle>"' end
    if depth <= 0 then return '"<table>"' end
    seen[v] = true
    local parts = {}
    local arr, n = is_array(v)
    if arr and n > 0 then
        for i = 1, n do
            budget.n = budget.n - 1
            if budget.n < 0 then parts[#parts + 1] = '"<truncated>"'; break end
            parts[#parts + 1] = encode(v[i], depth - 1, seen, budget)
        end
        seen[v] = nil
        return "[" .. table.concat(parts, ",") .. "]"
    end
    local keys = {}
    for k, _ in pairs(v) do keys[#keys + 1] = k end
    table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
    for _, k in ipairs(keys) do
        budget.n = budget.n - 1
        if budget.n < 0 then parts[#parts + 1] = '"...":"<truncated>"'; break end
        local ok, val = pcall(function() return v[k] end)
        parts[#parts + 1] = esc_str(tostring(k)) .. ":" .. (ok and encode(val, depth - 1, seen, budget) or '"<error>"')
    end
    seen[v] = nil
    return "{" .. table.concat(parts, ",") .. "}"
end

function json.encode(v, depth, max_items)
    return encode(v, depth or 6, {}, { n = max_items or 20000 })
end

local function decode_error(s, i, msg)
    error(string.format("JSON decode error at %d: %s", i, msg), 0)
end

local function skip_ws(s, i)
    local _, e = string.find(s, "^[ \t\r\n]*", i)
    return e + 1
end

local decode_value

local function utf8_char(cp)
    if cp < 0x80 then return string.char(cp) end
    if cp < 0x800 then return string.char(0xC0 + math.floor(cp / 64), 0x80 + cp % 64) end
    return string.char(0xE0 + math.floor(cp / 4096), 0x80 + math.floor(cp / 64) % 64, 0x80 + cp % 64)
end

local function decode_string(s, i)
    local buf = {}
    i = i + 1
    while true do
        local c = string.sub(s, i, i)
        if c == "" then decode_error(s, i, "unterminated string") end
        if c == '"' then return table.concat(buf), i + 1 end
        if c == "\\" then
            local e = string.sub(s, i + 1, i + 1)
            local map = { b = "\b", f = "\f", n = "\n", r = "\r", t = "\t", ['"'] = '"', ["\\"] = "\\", ["/"] = "/" }
            if map[e] then buf[#buf + 1] = map[e]; i = i + 2
            elseif e == "u" then
                local hex = string.sub(s, i + 2, i + 5)
                local cp = tonumber(hex, 16)
                if not cp then decode_error(s, i, "bad \\u escape") end
                buf[#buf + 1] = utf8_char(cp); i = i + 6
            else decode_error(s, i, "bad escape") end
        else
            local j = string.find(s, '["\\]', i)
            if not j then decode_error(s, i, "unterminated string") end
            buf[#buf + 1] = string.sub(s, i, j - 1); i = j
        end
    end
end

decode_value = function(s, i)
    i = skip_ws(s, i)
    local c = string.sub(s, i, i)
    if c == "{" then
        local t = {}
        i = skip_ws(s, i + 1)
        if string.sub(s, i, i) == "}" then return t, i + 1 end
        while true do
            i = skip_ws(s, i)
            if string.sub(s, i, i) ~= '"' then decode_error(s, i, "expected key") end
            local k; k, i = decode_string(s, i)
            i = skip_ws(s, i)
            if string.sub(s, i, i) ~= ":" then decode_error(s, i, "expected ':'") end
            local v; v, i = decode_value(s, i + 1)
            t[k] = v
            i = skip_ws(s, i)
            local d = string.sub(s, i, i)
            if d == "}" then return t, i + 1 end
            if d ~= "," then decode_error(s, i, "expected ',' or '}'") end
            i = i + 1
        end
    elseif c == "[" then
        local t = {}
        i = skip_ws(s, i + 1)
        if string.sub(s, i, i) == "]" then return t, i + 1 end
        while true do
            local v; v, i = decode_value(s, i)
            t[#t + 1] = v
            i = skip_ws(s, i)
            local d = string.sub(s, i, i)
            if d == "]" then return t, i + 1 end
            if d ~= "," then decode_error(s, i, "expected ',' or ']'") end
            i = i + 1
        end
    elseif c == '"' then
        return decode_string(s, i)
    elseif string.sub(s, i, i + 3) == "true" then return true, i + 4
    elseif string.sub(s, i, i + 4) == "false" then return false, i + 5
    elseif string.sub(s, i, i + 3) == "null" then return nil, i + 4
    else
        local num = string.match(s, "^-?%d+%.?%d*[eE]?[-+]?%d*", i)
        if not num or num == "" then decode_error(s, i, "unexpected character '" .. c .. "'") end
        return tonumber(num), i + #num
    end
end

function json.decode(s)
    local v, i = decode_value(s, 1)
    i = skip_ws(s, i)
    if i <= #s then decode_error(s, i, "trailing data") end
    return v
end

---------------------------------------------------------------------------
-- High-level API for agents (also callable from exec as api.*)
--
-- Designed so that small models can play: every helper validates its
-- arguments, explains mistakes in plain words, and says what to do next.
-- api.help() lists everything with examples.
---------------------------------------------------------------------------
local api = {}
local HELP = {}

local function doc(name, args, text, example)
    HELP[#HELP + 1] = { name = name, args = args, does = text, example = example }
end

local function req(kind, ...)
    WorkQueue.Request(kind, ...)
end

local function num(x, name)
    local v = tonumber(x)
    if not v then error((name or "argument") .. " must be a number (got " .. tostring(x) .. ")", 0) end
    return math.floor(v)
end

-- ---- planned work tracking --------------------------------------------------
-- Every construction/object order made through this API is remembered, so a
-- model can see what is still pending (the game only shows finished work to
-- scripts) and find_space does not pick an area that is already planned.
local PLANNED = {}         -- key "x,y" -> material
local PLANNED_OBJECTS = {} -- list of {type, x, y}

local raw_req = req
req = function(kind, a, b, c, ...)
    if kind == "Construction" then PLANNED[b .. "," .. c] = a
    elseif kind == "PlaceObject" then PLANNED_OBJECTS[#PLANNED_OBJECTS + 1] = { a, b, c } end
    return raw_req(kind, a, b, c, ...)
end

local function planned_at(x, y) return PLANNED[x .. "," .. y] end


-- ---- map size (cached) ----------------------------------------------------
local MAP_W, MAP_H
local function map_size()
    if MAP_W then return MAP_W, MAP_H end
    local w, h = 0, 0
    for x = 0, 1000 do if World.GetCell(x, 0).CellX == nil then break end; w = x + 1 end
    for y = 0, 1000 do if World.GetCell(0, y).CellX == nil then break end; h = y + 1 end
    MAP_W, MAP_H = w, h
    return w, h
end

local function rect(x1, y1, x2, y2, what)
    x1, y1 = num(x1, "x1"), num(y1, "y1")
    x2, y2 = num(x2 == nil and x1 or x2, "x2"), num(y2 == nil and y1 or y2, "y2")
    if x2 < x1 then x1, x2 = x2, x1 end
    if y2 < y1 then y1, y2 = y2, y1 end
    local w, h = map_size()
    if x1 < 0 or y1 < 0 or x2 >= w or y2 >= h then
        error(string.format("%s (%d,%d)-(%d,%d) is outside the map, which is %d x %d cells " ..
            "(x 0..%d, y 0..%d). Use api.state() to see the map size.",
            what or "area", x1, y1, x2, y2, w, h, w - 1, h - 1), 0)
    end
    return x1, y1, x2, y2
end

-- ---- names ----------------------------------------------------------------
local WALLS = { BrickWall = 1, ConcreteWall = 1, PerimeterWall = 1, Fence = 1, BurntWall = 1,
                NewBarredWall = 1, NewTiledWall = 1, NewHedgeWall = 1, NewBBlockWall = 1 }
local FLOORS = { ConcreteFloor = 1, WoodenFloor = 1, CeramicFloor = 1, MosaicFloor = 1, MetalFloor = 1,
                 ConcreteTiles = 1, PavingStone = 1, MarbleTiles = 1, WhiteTiles = 1, Carpet = 1,
                 Gravel = 1, Road = 1, Grass = 1, Dirt = 1 }
local SPECIAL = { Building = 1, BuildingConcrete = 1, Demolish = 1, DemolishWalls = 1, ClearIndoorArea = 1,
                  RemoveTunnels = 1, CancelJobs = 1 }
local OPEN_GROUND = { Dirt = 1, Grass = 1, LongGrass = 1, Mud = 1, Gravel = 1, Stone = 1, Snow = 1, Sand = 1 }

local function known_material(m)
    return WALLS[m] or FLOORS[m] or SPECIAL[m]
end

local function lower_eq(a, b) return string.lower(a) == string.lower(b) end

local function suggest(name, pool)
    local best, bestscore = nil, 0
    local ln = string.lower(name)
    for k, _ in pairs(pool) do
        local lk = string.lower(k)
        local score = 0
        if string.find(lk, ln, 1, true) or string.find(ln, lk, 1, true) then score = 50 end
        for i = 1, math.min(#lk, #ln) do if string.sub(lk, i, i) == string.sub(ln, i, i) then score = score + 1 end end
        if score > bestscore then best, bestscore = k, score end
    end
    return best
end

local function check_material(m)
    if type(m) ~= "string" or m == "" then error("material name required, e.g. \"BrickWall\" or \"ConcreteFloor\"", 0) end
    if known_material(m) then return m end
    local all = {}
    for k in pairs(WALLS) do all[k] = 1 end
    for k in pairs(FLOORS) do all[k] = 1 end
    for k in pairs(SPECIAL) do all[k] = 1 end
    for k in pairs(all) do if lower_eq(k, m) then return k end end
    -- unknown but maybe valid: allow, with a hint in the result
    return m, "not a material this API knows; if nothing happens try " .. tostring(suggest(m, all))
end

-- ---- map rendering --------------------------------------------------------
local CHAR = {
    Dirt = ".", Grass = ".", LongGrass = ".", Mud = ".", Gravel = ".", Stone = ".", Snow = ".", Sand = ".",
    Road = "=", RoadMarkings = "=", RoadMarkingsLeft = "=", RoadMarkingsRight = "=",
    RoadCrossing = "=", RoadCrossingLeft = "=", RoadCrossingRight = "=",
    PavingStone = ",", ConcreteTiles = ",",
    ConcreteFloor = "_", WoodenFloor = "_", CeramicFloor = "_", MosaicFloor = "_", MetalFloor = "_",
    MarbleTiles = "_", WhiteTiles = "_", Carpet = "_",
    BrickWall = "#", ConcreteWall = "#", BurntWall = "#", NewBarredWall = "#", NewTiledWall = "#",
    NewBBlockWall = "#", NewHedgeWall = "#", PerimeterWall = "%", Fence = "|",
    Building = "b", BuildingConcrete = "b", BuildingFrame = "f",
    Water = "~",
}

function api.map(x1, y1, x2, y2)
    local w, h = map_size()
    if x1 == nil then x1, y1, x2, y2 = 0, 0, w - 1, h - 1 end
    x1, y1, x2, y2 = rect(x1, y1, x2, y2, "map area")
    if (x2 - x1 + 1) * (y2 - y1 + 1) > 20000 then error("map area too large (max 20000 cells)", 0) end
    local rows, legend, unknown = {}, {}, {}
    for y = y1, y2 do
        local line = {}
        for x = x1, x2 do
            local m = Object.GetMaterial(x, y) or "?"
            local c = CHAR[m]
            if not c then c = "?"; unknown[m] = true end
            local p = planned_at(x, y)
            if p and p ~= m then c = "+"; m = "planned, not built yet (" .. p .. ")" end
            legend[c] = legend[c] or {}
            legend[c][m] = true
            line[#line + 1] = c
        end
        rows[#rows + 1] = table.concat(line)
    end
    local leg = {}
    for c, ms in pairs(legend) do
        local names = {}
        for m in pairs(ms) do names[#names + 1] = m end
        table.sort(names)
        leg[c] = table.concat(names, ", ")
    end
    local ruler = {}
    for x = x1, x2 do ruler[#ruler + 1] = tostring(x % 10) end
    return { origin = { x = x1, y = y1 }, size = { w = x2 - x1 + 1, h = y2 - y1 + 1 },
             x_ruler = table.concat(ruler), rows = rows, legend = leg,
             note = "rows[1] is y=" .. y1 .. "; character i of a row is x=" .. x1 .. "+i-1" }
end
doc("map", "[x1, y1, x2, y2]", "Text map of an area (default: whole map). # wall, _ floor, . open ground, = road, + ordered but not built yet.",
    "api.map(60, 20, 99, 60)")

function api.material_at(x, y)
    x, y = rect(x, y, x, y, "cell")
    return Object.GetMaterial(x, y)
end
doc("material_at", "x, y", "Material of one cell.", "api.material_at(10, 12)")

function api.materials(x1, y1, x2, y2)
    x1, y1, x2, y2 = rect(x1, y1, x2, y2)
    local rows = {}
    for y = y1, y2 do
        local row = {}
        for x = x1, x2 do row[#row + 1] = Object.GetMaterial(x, y) or "?" end
        rows[#rows + 1] = row
    end
    return rows
end

-- ---- state ----------------------------------------------------------------
local function copy(t)
    local out = {}
    if type(t) ~= "table" then return t end
    for k, v in pairs(t) do out[tostring(k)] = tonumber(v) or v end
    return out
end

function api.state()
    local w, h = map_size()
    local ok_p, prisoners = pcall(function() return copy(World.NumPrisoners) end)
    local ok_c, capacity = pcall(function() return copy(World.Capacity) end)
    local total = 0
    if ok_p then for _, v in pairs(prisoners) do total = total + (tonumber(v) or 0) end end
    return {
        bridge = VERSION,
        time = Game.Time(),
        speed = Game.GetGameSpeed(),
        map = { w = w, h = h },
        prisoners_total = total,
        prisoners = ok_p and prisoners or nil,
        cell_capacity = ok_c and capacity or nil,
        tips = "Use api.map() to see the layout and api.help() for what you can do.",
    }
end
doc("state", "", "Live summary: time, speed, map size, prisoners by category, cell capacity.", "api.state()")

function api.info() return api.state() end

-- ---- finding space ----------------------------------------------------------
-- Finds a free w x h rectangle of open ground (plus a margin of open ground
-- around it). Prefers positions near (near_x, near_y) if given.
function api.find_space(w, h, near_x, near_y, margin)
    w, h = num(w, "width"), num(h, "height")
    margin = tonumber(margin) or 1
    local MW, MH = map_size()
    if w < 1 or h < 1 or w > MW or h > MH then error("size must fit the map (" .. MW .. " x " .. MH .. ")", 0) end
    -- blocked grid + 2D prefix sums
    local S = {}
    for y = 0, MH do S[y] = {}; for x = 0, MW do S[y][x] = 0 end end
    for y = 1, MH do
        for x = 1, MW do
            local m = Object.GetMaterial(x - 1, y - 1)
            local b = (OPEN_GROUND[m] and not planned_at(x - 1, y - 1)) and 0 or 1
            S[y][x] = b + S[y - 1][x] + S[y][x - 1] - S[y - 1][x - 1]
        end
    end
    local function blocked(x1, y1, x2, y2)
        return S[y2 + 1][x2 + 1] - S[y1][x2 + 1] - S[y2 + 1][x1] + S[y1][x1]
    end
    local best, bestd = nil, nil
    near_x, near_y = tonumber(near_x), tonumber(near_y)
    for y = margin, MH - h - margin do
        for x = margin, MW - w - margin do
            if blocked(x - margin, y - margin, x + w - 1 + margin, y + h - 1 + margin) == 0 then
                local d = 0
                if near_x then d = math.abs(x + w / 2 - near_x) + math.abs(y + h / 2 - near_y) end
                if not best or d < bestd then best, bestd = { x1 = x, y1 = y, x2 = x + w - 1, y2 = y + h - 1 }, d end
                if not near_x then return best end
            end
        end
    end
    if not best then error("no free " .. w .. "x" .. h .. " area of open ground found; try a smaller size", 0) end
    return best
end
doc("find_space", "w, h, [near_x, near_y, margin]", "Find an empty w x h area of open ground (for a new building).",
    "api.find_space(12, 8, 70, 40)")

-- ---- construction -----------------------------------------------------------
function api.build_area(material, x1, y1, x2, y2)
    local m, hint = check_material(material)
    x1, y1, x2, y2 = rect(x1, y1, x2, y2)
    local n = 0
    for x = x1, x2 do for y = y1, y2 do req("Construction", m, x, y); n = n + 1 end end
    return { queued = n, material = m, hint = hint }
end
doc("build_area", "material, x1, y1, x2, y2", "Fill a rectangle with a floor/material (ConcreteFloor, PavingStone, Building foundation...).",
    "api.build_area(\"ConcreteFloor\", 10, 10, 20, 15)")

function api.build_wall_rect(material, x1, y1, x2, y2)
    local m, hint = check_material(material)
    x1, y1, x2, y2 = rect(x1, y1, x2, y2)
    local n = 0
    for x = x1, x2 do
        req("Construction", m, x, y1); n = n + 1
        if y2 ~= y1 then req("Construction", m, x, y2); n = n + 1 end
    end
    for y = y1 + 1, y2 - 1 do
        req("Construction", m, x1, y); n = n + 1
        if x2 ~= x1 then req("Construction", m, x2, y); n = n + 1 end
    end
    return { queued = n, material = m, hint = hint }
end
doc("build_wall_rect", "material, x1, y1, x2, y2", "Walls around the outline of a rectangle.",
    "api.build_wall_rect(\"BrickWall\", 10, 10, 20, 15)")

function api.build_line(material, x1, y1, x2, y2)
    if num(x1) ~= num(x2) and num(y1) ~= num(y2) then
        error("a line must be horizontal (same y) or vertical (same x)", 0)
    end
    return api.build_area(material, x1, y1, x2, y2)
end
doc("build_line", "material, x1, y1, x2, y2", "Straight horizontal or vertical line (wall, fence, road).",
    "api.build_line(\"BrickWall\", 10, 10, 10, 20)")

function api.place_object(object_type, x, y, ox, oy)
    if type(object_type) ~= "string" or object_type == "" then error("object name required, e.g. \"Bed\"", 0) end
    x, y = rect(x, y, x, y, "object position")
    req("PlaceObject", object_type, x, y, tonumber(ox) or 0, tonumber(oy) or 1)
    return { queued = 1, object = object_type, x = x, y = y }
end
doc("place_object", "name, x, y, [ox, oy]", "Buy and install one object (Bed, Toilet, JailDoor, Door, Cooker...). ox,oy = facing, default 0,1.",
    "api.place_object(\"Toilet\", 12, 11)")

local SIDES = { north = true, south = true, east = true, west = true }

-- A building: walls around the rectangle, a floor inside, and a door.
function api.building(x1, y1, x2, y2, door_side, door, wall, floor)
    x1, y1, x2, y2 = rect(x1, y1, x2, y2, "building")
    if x2 - x1 < 2 or y2 - y1 < 2 then error("a building needs at least 3 x 3 cells including walls", 0) end
    door_side = door_side and string.lower(door_side) or "south"
    if not SIDES[door_side] then error("door_side must be north, south, east or west", 0) end
    wall = wall or "BrickWall"
    floor = floor or "ConcreteFloor"
    door = door or "Door"
    api.build_wall_rect(wall, x1, y1, x2, y2)
    api.build_area(floor, x1 + 1, y1 + 1, x2 - 1, y2 - 1)
    local cx, cy = math.floor((x1 + x2) / 2), math.floor((y1 + y2) / 2)
    local dx, dy, ox, oy
    if door_side == "south" then dx, dy, ox, oy = cx, y2, 0, 1
    elseif door_side == "north" then dx, dy, ox, oy = cx, y1, 0, 1
    elseif door_side == "east" then dx, dy, ox, oy = x2, cy, 1, 0
    else dx, dy, ox, oy = x1, cy, 1, 0 end
    req("PlaceObject", door, dx, dy, ox, oy)
    return {
        queued = true, walls = { x1 = x1, y1 = y1, x2 = x2, y2 = y2 }, door = { object = door, x = dx, y = dy },
        inside = { x1 = x1 + 1, y1 = y1 + 1, x2 = x2 - 1, y2 = y2 - 1 },
        next = "Workmen build it over time. Then furnish the inside with api.furnish(kind, inside) " ..
               "and ask the human to zone the room (zoning is not available from scripts).",
    }
end
doc("building", "x1, y1, x2, y2, [door_side, door, wall, floor]",
    "Walls + floor + a door (default Door on the south side). Returns the inside rectangle.",
    "api.building(60, 30, 70, 38, \"south\")")

-- ---- furnishing ---------------------------------------------------------------
-- Object footprints (width, height) when facing down (0,1).
local SIZE = { Bed = { 1, 2 }, Toilet = { 1, 1 }, Cooker = { 2, 1 }, Fridge = { 2, 1 }, Sink = { 3, 1 },
               Table = { 4, 1 }, Bench = { 4, 1 }, ShowerHead = { 1, 1 }, Drain = { 1, 1 },
               ServingTable = { 5, 1 }, WeightsBench = { 1, 1 }, PhoneBooth = { 1, 1 }, Tv = { 1, 1 },
               OfficeDesk = { 2, 1 }, FilingCabinet = { 1, 1 }, Chair = { 1, 1 }, SofaChairDouble = { 2, 1 },
               GuardLocker = { 1, 1 }, MedicalBed = { 2, 2 }, Bin = { 1, 1 } }

-- PlaceObject anchor offset from the left/top cell of the footprint, by width.
-- Measured live: a width-4 object requested at x lands on cells x-3..x.
-- (Other widths are assumed to follow the same rule; api.calibrate() checks.)
local function anchor_x(left, w) return left + w - 1 end
local function anchor_y(top, h) return top + h - 1 end

local function put(list, obj, left, top)
    local s = SIZE[obj] or { 1, 1 }
    list[#list + 1] = { obj, anchor_x(left, s[1]), anchor_y(top, s[2]) }
end

local LAYOUTS = {}

-- Each layout gets the inside rectangle and returns a list of {object, x, y}.
LAYOUTS.kitchen = function(x1, y1, x2, y2, out)
    local x = x1
    while x + 1 <= x2 do  -- cookers along the top wall, then fridges, then a sink
        if #out < 2 then put(out, "Cooker", x, y1)
        elseif #out < 4 then put(out, "Fridge", x, y1)
        else break end
        x = x + 2
    end
    if x + 2 <= x2 then put(out, "Sink", x, y1) end
    return "Kitchen: cookers, fridges and a sink along the back wall. Zone it as Kitchen, next to a Canteen."
end

LAYOUTS.canteen = function(x1, y1, x2, y2, out)
    -- rows of Table with a Bench above and below; serving table at the top.
    if x2 - x1 + 1 >= 5 then put(out, "ServingTable", x1, y1) end
    local y = y1 + 2
    while y + 2 <= y2 do
        local x = x1
        while x + 3 <= x2 do
            put(out, "Bench", x, y); put(out, "Table", x, y + 1); put(out, "Bench", x, y + 2)
            x = x + 5
        end
        y = y + 4
    end
    return "Canteen: a serving table and rows of tables with benches. Zone it as Canteen."
end

LAYOUTS.shower = function(x1, y1, x2, y2, out)
    for x = x1, x2, 2 do put(out, "ShowerHead", x, y1) end
    put(out, "Drain", x1 + 1 <= x2 and x1 + 1 or x1, math.floor((y1 + y2) / 2))
    return "Showers along the back wall and a drain. Zone it as Shower."
end

LAYOUTS.yard = function(x1, y1, x2, y2, out)
    for x = x1, math.min(x2, x1 + 6), 2 do put(out, "WeightsBench", x, y1) end
    put(out, "PhoneBooth", x2, y2)
    return "Yard: weights benches and a phone booth. Zone it as Yard (it can be outdoors)."
end

LAYOUTS.holding = function(x1, y1, x2, y2, out)
    put(out, "Toilet", x1, y1)
    if x2 - x1 >= 2 then put(out, "Toilet", x2, y1) end
    local y = y1 + 2
    while y <= y2 do
        if x1 + 4 <= x2 + 1 then put(out, "Bench", x1 + 1, y) end
        y = y + 3
    end
    return "Holding cell: toilets and benches. Zone it as HoldingCell; new prisoners wait here."
end

LAYOUTS.cell = function(x1, y1, x2, y2, out)
    put(out, "Bed", x1, y1)
    put(out, "Toilet", x2, y1)
    return "Cell: bed and toilet. Zone it as Cell."
end

LAYOUTS.office = function(x1, y1, x2, y2, out)
    put(out, "OfficeDesk", x1, y1); put(out, "Chair", x1, y1 + 1); put(out, "FilingCabinet", x2, y1)
    return "Office: desk, chair, filing cabinet. Zone as Office (Warden, Accountant...)."
end

LAYOUTS.staffroom = function(x1, y1, x2, y2, out)
    put(out, "Tv", x1, y1); put(out, "SofaChairDouble", x1, y1 + 2)
    return "Staff room: TV and sofa. Zone as Staffroom."
end

function api.furnish(kind, x1, y1, x2, y2)
    kind = string.lower(tostring(kind or ""))
    local layout = LAYOUTS[kind]
    if not layout then
        local names = {}
        for k in pairs(LAYOUTS) do names[#names + 1] = k end
        table.sort(names)
        error("unknown room kind '" .. kind .. "'. Choose one of: " .. table.concat(names, ", "), 0)
    end
    x1, y1, x2, y2 = rect(x1, y1, x2, y2, "room inside")
    local items = {}
    local note = layout(x1, y1, x2, y2, items)
    if #items == 0 then error("room is too small to furnish as " .. kind, 0) end
    for _, it in ipairs(items) do req("PlaceObject", it[1], it[2], it[3], 0, 1) end
    local placed = {}
    for _, it in ipairs(items) do placed[#placed + 1] = it[1] .. "@" .. it[2] .. "," .. it[3] end
    return { queued = #items, objects = placed, note = note }
end
doc("furnish", "kind, x1, y1, x2, y2",
    "Place the right furniture inside a room's inside area. kind: kitchen, canteen, shower, yard, holding, cell, office, staffroom.",
    "api.furnish(\"kitchen\", 61, 31, 69, 37)")

-- A row of cells facing south onto a corridor. Each cell is 3 wide x 3 deep inside.
function api.cell_block(x, y, count, door)
    x, y, count = num(x, "x"), num(y, "y"), num(count or 4, "count")
    if count < 1 or count > 30 then error("count must be 1..30", 0) end
    door = door or "JailDoor"
    local cw, ch = 3, 3
    local x2 = x + count * (cw + 1)
    local y2 = y + ch + 1
    rect(x, y, x2, y2 + 2, "cell block (with its 2-cell corridor)")
    api.build_wall_rect("BrickWall", x, y, x2, y2)
    for i = 1, count - 1 do api.build_line("BrickWall", x + i * (cw + 1), y + 1, x + i * (cw + 1), y2 - 1) end
    api.build_area("ConcreteFloor", x + 1, y + 1, x2 - 1, y2 - 1)
    api.build_area("ConcreteFloor", x, y2 + 1, x2, y2 + 2)
    local cells = {}
    for i = 0, count - 1 do
        local cx1 = x + 1 + i * (cw + 1)
        local items = {}
        LAYOUTS.cell(cx1, y + 1, cx1 + cw - 1, y2 - 1, items)
        for _, it in ipairs(items) do req("PlaceObject", it[1], it[2], it[3], 0, 1) end
        req("PlaceObject", door, cx1 + 1, y2, 0, 1)
        cells[#cells + 1] = { x1 = cx1, y1 = y + 1, x2 = cx1 + cw - 1, y2 = y2 - 1, door = { x = cx1 + 1, y = y2 } }
    end
    return { queued = true, cells = cells, corridor = { x1 = x, y1 = y2 + 1, x2 = x2, y2 = y2 + 2 },
             next = "Ask the human to zone each cell as Cell (zoning is not available from scripts)." }
end
doc("cell_block", "x, y, count, [door]", "A row of 3x3 cells with beds, toilets and jail doors, opening south onto a corridor.",
    "api.cell_block(20, 10, 6)")

-- ---- objects and people ------------------------------------------------------
-- Scripts cannot list objects directly. Object.GetNearbyObjects works from an
-- anchor object, so we spawn a temporary Box, query around it, and delete it
-- in the same tick.
local STAFF_TYPES = { "Workman", "Guard", "ArmedGuard", "DogHandler", "Cook", "Doctor", "Janitor", "Gardener",
                      "Psychologist", "Accountant", "Chief", "Foreman", "Warden", "Lawyer", "Teacher", "Chaplain" }

local function with_anchor(fn)
    local w, h = map_size()
    local anchor = Object.Spawn("Box", w / 2, h / 2)
    if not anchor then error("could not create the temporary search anchor", 0) end
    local ok, res = pcall(fn, anchor, math.sqrt(w * w + h * h) / 2 + 2)
    pcall(Object.Delete, anchor)
    if not ok then error(res, 0) end
    return res
end

local function obj_summary(o, dist)
    local s = {}
    local ok, v
    ok, v = pcall(function() return o.Type end); s.type = ok and v or nil
    ok, v = pcall(function() return o.Pos.x end); s.x = ok and v and math.floor(v * 10 + 0.5) / 10 or nil
    ok, v = pcall(function() return o.Pos.y end); s.y = ok and v and math.floor(v * 10 + 0.5) / 10 or nil
    ok, v = pcall(function() return o["id-uniqueId"] end); s.id = ok and tonumber(v) or nil
    return s
end

local function find_objects(anchor, radius, type_name)
    local ok, near = pcall(Object.GetNearbyObjects, anchor, type_name, radius)
    if not ok or type(near) ~= "table" then return {} end
    local list = {}
    for o, d in pairs(near) do
        if o ~= anchor then list[#list + 1] = obj_summary(o, d) end
    end
    return list
end

function api.objects(type_name, limit)
    if type(type_name) ~= "string" or type_name == "" then error("object type required, e.g. \"Workman\" or \"Bed\"", 0) end
    limit = tonumber(limit) or 200
    return with_anchor(function(anchor, radius)
        local list = find_objects(anchor, radius, type_name)
        if type_name == "Box" then  -- the anchor itself is a Box
            local out = {}
            for _, o in ipairs(list) do if not (o.x == math.floor(MAP_W / 2 * 10) / 10) then out[#out + 1] = o end end
            list = out
        end
        table.sort(list, function(a, b) return (a.id or 0) < (b.id or 0) end)
        local total = #list
        while #list > limit do table.remove(list) end
        return { type = type_name, count = total, objects = list }
    end)
end
doc("objects", "type, [limit]", "List every object of a type with its position (Workman, Guard, Prisoner, Bed, Toilet, Cooker...).",
    "api.objects(\"Workman\")")

function api.count(types)
    if type(types) == "string" then types = { types } end
    if type(types) ~= "table" then error("give a type name or a list of type names", 0) end
    return with_anchor(function(anchor, radius)
        local out = {}
        for _, t in ipairs(types) do out[t] = #find_objects(anchor, radius, t) end
        return out
    end)
end
doc("count", "types", "Count objects of one or more types.", "api.count({\"Bed\", \"Toilet\", \"Cooker\"})")

function api.staff()
    local c = api.count(STAFF_TYPES)
    local out, total = {}, 0
    for k, v in pairs(c) do if v > 0 then out[k] = v; total = total + v end end
    return { total = total, by_type = out,
             note = "Hiring is not available from scripts; ask the human to hire staff in the Staff menu." }
end
doc("staff", "", "How many of each kind of staff you have.", "api.staff()")


function api.progress()
    local done, pending, pend_list = 0, 0, {}
    for key, mat in pairs(PLANNED) do
        local x, y = string.match(key, "(-?%d+),(-?%d+)")
        x, y = tonumber(x), tonumber(y)
        if Object.GetMaterial(x, y) == mat then done = done + 1; PLANNED[key] = nil
        else pending = pending + 1; if #pend_list < 20 then pend_list[#pend_list + 1] = mat .. "@" .. key end end
    end
    local want = {}
    for _, o in ipairs(PLANNED_OBJECTS) do want[o[1]] = (want[o[1]] or 0) + 1 end
    local types = {}
    for t in pairs(want) do types[#types + 1] = t end
    local have = #types > 0 and api.count(types) or {}
    local objects = {}
    for t, n in pairs(want) do objects[t] = { ordered = n, installed = have[t] or 0 } end
    return { construction = { finished_since_last_check = done, still_pending = pending, pending_sample = pend_list },
             objects = objects,
             note = "Objects count as installed when that many exist on the map. Workmen need time, money and " ..
                    "delivered materials; if nothing moves for a long time check money with api.state()." }
end
doc("progress", "", "What you ordered that is finished vs still pending.", "api.progress()")

-- ---- things scripts cannot do -------------------------------------------------
local NOT_AVAILABLE = "is not available from scripts: the game's own function for it crashes outside " ..
                      "the campaign. Ask the human to do it in the game UI."
function api.zone(room_type, x1, y1, x2, y2)
    error("Zoning (" .. tostring(room_type) .. ") " .. NOT_AVAILABLE, 0)
end
function api.save() error("Saving " .. NOT_AVAILABLE, 0) end
function api.camera() error("Camera control " .. NOT_AVAILABLE, 0) end

-- ---- introspection -------------------------------------------------------------
function api.describe(t)
    local out = {}
    if type(t) == "string" then t = _G[t] end
    if type(t) ~= "table" then return type(t) end
    for k, v in pairs(t) do out[tostring(k)] = type(v) end
    return out
end

function api.help()
    return {
        about = "Prison Architect agent API. Coordinates are map cells: x to the right, y down, (0,0) top-left. " ..
                "Construction and objects are carried out by workmen and cost money, like a player's orders.",
        functions = HELP,
        not_available = { "zoning rooms", "hiring staff", "saving", "camera", "pause/unpause" },
        materials = { walls = "BrickWall, ConcreteWall, Fence, PerimeterWall",
                      floors = "ConcreteFloor, WoodenFloor, CeramicFloor, PavingStone",
                      foundation = "Building (brick), BuildingConcrete" },
        objects = "Bed, Toilet, JailDoor, Door, StaffDoor, Cooker, Fridge, Sink, Table, Bench, ServingTable, " ..
                  "ShowerHead, Drain, WeightsBench, PhoneBooth, Tv, OfficeDesk, Chair, FilingCabinet, Light",
        workflow = { "api.state()", "api.map()", "api.find_space(w, h)", "api.building(...)",
                     "api.furnish(kind, inside...)", "api.progress() until finished", "ask the human to zone the room",
                     "api.staff() / api.objects(\"Prisoner\") to check on people" },
    }
end
doc("help", "", "This list.", "api.help()")

---------------------------------------------------------------------------
-- Bridge loop
---------------------------------------------------------------------------
local bridged = nil         -- nil = not checked yet, false = no DLL
local mem = {}              -- persists across exec calls
-- Game.* comes from the campaign scripting system. Many of these functions
-- crash the whole game (not a Lua error) when called in a sandbox prison:
-- verified crashes: SaveMap, CamMove. Code analysis: 79 of the 88 functions
-- (including SetZoneRoom) use the campaign object without a null check. So agent code only sees an
-- allowlist of functions verified safe live; the raw table is exposed as
-- UnsafeGame for deliberate experiments (expect crashes).
local SAFE_GAME = { DebugOut = true, Time = true, GetGameSpeed = true }
local SafeGame = setmetatable({}, { __index = function(_, k)
    if SAFE_GAME[k] then return Game[k] end
    return function()
        error("Game." .. tostring(k) .. " is not on the verified-safe list (campaign functions can crash the game). " ..
              "Use UnsafeGame." .. tostring(k) .. " only if you accept a possible crash.", 2)
    end
end })
local env = setmetatable({ api = api, json = json, mem = mem, Game = SafeGame, UnsafeGame = Game }, { __index = _G })
env._G = env

local function send(tbl)
    Game.DebugOut("\1reply:" .. json.encode(tbl))
end

local function collect(ok, ...)
    if not ok then return false, tostring((...)) end
    if select("#", ...) <= 1 then return true, (...) end
    return true, { ... }
end

local function run(f, ...)
    return collect(pcall(f, ...))
end

local function handle(line)
    local okd, request = pcall(json.decode, line)
    if not okd or type(request) ~= "table" then
        send({ type = "result", id = nil, ok = false, error = "bad request: " .. tostring(request) })
        return
    end
    local id = request.id
    local op = request.op or "exec"
    local ok, result
    if op == "ping" then
        ok, result = true, { pong = true, bridge = VERSION, time = Game.Time() }
    elseif op == "exec" then
        local f, err = loadstring(tostring(request.code or ""), "=agent")
        if not f then
            ok, result = false, "compile error: " .. tostring(err)
        else
            env.this = this
            setfenv(f, env)
            ok, result = run(f)
        end
    elseif op == "call" then
        local fn = api[request.fn or ""]
        if not fn then
            ok, result = false, "unknown api function: " .. tostring(request.fn)
        else
            local args = request.args or {}
            ok, result = run(fn, unpack(args, 1, request.nargs or #args))
        end
    else
        ok, result = false, "unknown op: " .. tostring(op)
    end
    local reply = { type = "result", id = id, ok = ok }
    if ok then reply.result = result else reply.error = result end
    local encoded_ok, err = pcall(send, reply)
    if not encoded_ok then
        send({ type = "result", id = id, ok = false, error = "could not encode result: " .. tostring(err) })
    end
end

function Create()
end

function Update(timePassed)
    if bridged == nil then
        local r = Game.DebugOut("\1hello:" .. VERSION)
        bridged = (type(r) == "string")
    end
    if not bridged then return end
    for _ = 1, MAX_REQUESTS_PER_TICK do
        local line = Game.DebugOut("\1poll")
        if type(line) ~= "string" then break end
        handle(line)
    end
end

-- exposed for tests
PA_BRIDGE = { json = json, api = api, handle = handle, VERSION = VERSION }
