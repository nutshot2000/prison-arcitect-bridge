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

local VERSION = "0.5.1"
local MAX_REQUESTS_PER_TICK = 64
local DebugOut = Game.DebugOut  -- patched by the DLL; native actions go through it
local NATIVE = false            -- DLL 0.3+ with verified game functions (zone/save/speed/research)

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

-- Cables and pipes are objects that workmen lay and that then disappear into
-- the game's utility grid, so they are tracked apart from furniture.
local UTILITY_OBJECT = { ElectricalCable = "power", PipeLarge = "water", PipeSmall = "water", PipeHotWater = "water" }
local PLANNED_UTIL = { power = {}, water = {} }  -- "x,y" -> object name

local raw_req = req
req = function(kind, a, b, c, ...)
    if kind == "Construction" then PLANNED[b .. "," .. c] = a
    elseif kind == "PlaceObject" then
        if UTILITY_OBJECT[a] then PLANNED_UTIL[UTILITY_OBJECT[a]][b .. "," .. c] = a
        else
            local okt, t = pcall(function() return World.TimeIndex end)
            PLANNED_OBJECTS[#PLANNED_OBJECTS + 1] = { a, b, c, okt and tonumber(t) or 0 }
        end
    end
    return raw_req(kind, a, b, c, ...)
end

local function planned_at(x, y) return PLANNED[x .. "," .. y] end

-- ---- native actions (DLL) ----------------------------------------------------
local function native(cmd)
    if not NATIVE then
        error("this needs bridge DLL 0.3 or newer (GLU32.dll in the game folder; restart the game after " ..
              "updating it). Check with api.state().native", 0)
    end
    local r = DebugOut("\1" .. cmd)
    if type(r) == "string" and string.sub(r, 1, 6) == "error:" then error(string.sub(r, 8), 0) end
    return r
end

local function split(s, sep)
    local out = {}
    if not s or s == "" then return out end
    for part in string.gmatch(s, "([^" .. sep .. "]+)") do out[#out + 1] = part end
    return out
end


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
-- Names of the game's UI tools. WorkQueue.Request does NOT run them: it builds them
-- as literal materials (measured live: "CancelJobs" became the floor of two cells,
-- and "Building" foundation never turns into walls and floor). Refuse them.
local UI_TOOLS = { Building = 1, BuildingConcrete = 1, Demolish = 1, DemolishWalls = 1, ClearIndoorArea = 1,
                   RemoveTunnels = 1, CancelJobs = 1, BuildingFrame = 1 }
local SPECIAL = {}
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
    for k in pairs(UI_TOOLS) do
        if lower_eq(k, m) then
            error(k .. " is a game UI tool, not a material: scripts would build it as a literal floor. " ..
                  "Build walls + floor instead (api.building / api.room); they are marked indoor for you.", 0)
        end
    end
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

-- Small whole-map picture: each character is a block of cells, showing the
-- most important thing in the block (wall > planned > floor > road > paving > ground).
local RANK = { ["#"] = 7, ["%"] = 7, ["|"] = 6, ["+"] = 5, ["_"] = 4, ["b"] = 4, ["f"] = 4, ["="] = 3, [","] = 2,
               ["~"] = 1, ["."] = 0, ["?"] = 1 }
function api.overview(block)
    block = math.max(2, math.min(10, tonumber(block) or 3))
    local w, h = map_size()
    local rows = {}
    for by = 0, h - 1, block do
        local line = {}
        for bx = 0, w - 1, block do
            local best, br = ".", -1
            for y = by, math.min(by + block - 1, h - 1) do
                for x = bx, math.min(bx + block - 1, w - 1) do
                    local m = Object.GetMaterial(x, y)
                    local c = CHAR[m] or "?"
                    local p = planned_at(x, y)
                    if p and p ~= m then c = "+" end
                    if (RANK[c] or 0) > br then best, br = c, RANK[c] or 0 end
                end
            end
            line[#line + 1] = best
        end
        rows[#rows + 1] = table.concat(line)
    end
    return { block = block, rows = rows,
             how_to_read = "Each character is a " .. block .. "x" .. block .. " block. Row r, column c covers cells x=" ..
                 "c*" .. block .. ".., y=r*" .. block .. ".. (both counted from 0). # wall, | fence, + ordered not built, " ..
                 "_ floor, = road, , paving, . open ground. Use api.map(x1,y1,x2,y2) for exact cells.",
             zones_made = api.zones() }
end
doc("overview", "[block]", "Small picture of the whole map (each character = 3x3 cells). Start here.", "api.overview()")

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

local function world_get(k)
    local ok, v = pcall(function() return World[k] end)
    if ok then return v end
end

local function nonzero(t)
    local out, total = {}, 0
    for k, v in pairs(t or {}) do
        v = tonumber(v) or 0
        if v ~= 0 then out[k] = v; total = total + v end
    end
    return out, total
end

function api.money()
    return { balance = math.floor(tonumber(world_get("Balance")) or 0) }
end
doc("money", "", "Current bank balance in dollars.", "api.money()")

function api.clock()
    -- World.TimeIndex counts game minutes since the prison was founded (1440 per day).
    local t = tonumber(world_get("TimeIndex")) or 0
    local day = math.floor(t / 1440) + 1
    local minute = math.floor(t % 1440)
    return { day = day, hour = math.floor(minute / 60), minute = minute % 60,
             text = string.format("day %d %02d:%02d", day, math.floor(minute / 60), minute % 60) }
end

function api.speed()
    local s
    if NATIVE then s = DebugOut("\1speed") end
    if type(s) ~= "number" then s = Game.GetGameSpeed() end
    return s
end

function api.state()
    local w, h = map_size()
    local ok_p, prisoners = pcall(function() return copy(World.NumPrisoners) end)
    local ok_c, capacity = pcall(function() return copy(World.Capacity) end)
    local pris, total = nonzero(ok_p and prisoners or {})
    local cap, beds = nonzero(ok_c and capacity or {})
    local speed = api.speed()
    return {
        bridge = VERSION,
        native = NATIVE,
        clock = api.clock().text,
        paused = speed == 0,
        speed = speed,
        money = api.money().balance,
        map = { w = w, h = h },
        prisoners_total = total,
        prisoners = pris,
        cell_capacity_total = beds,
        cell_capacity = cap,
        staff = api.staff().by_type,
        zones_made = api.zones(),
        utilities = (function() local ok, u = pcall(api.utilities); return ok and u or nil end)(),
        intake = (function() local ok, i = pcall(api.intake); return ok and i.mode or nil end)(),
        tips = "Use api.overview() to see the layout and api.help() for what you can do.",
    }
end
doc("state", "", "Live summary: money, clock, paused, prisoners, cell capacity, staff, zones made.", "api.state()")

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
    -- objects stand on plain ground, so the floor alone does not show them
    -- (live: a dormitory was offered on top of the power stations)
    local taken = {}
    for _, t in ipairs({ "PowerStation", "WaterPumpStation", "Capacitor", "PowerSwitch", "RoadGate",
                         "WeightsBench", "PhoneBooth", "Tree", "Light" }) do
        local ok, list = pcall(api.objects, t, 1000)
        if ok then
            for _, o in ipairs(list.objects) do
                local s = (t == "PowerStation" or t == "WaterPumpStation") and 3 or (t == "RoadGate" and 7 or 1)
                local cx, cy = math.floor(o.x), math.floor(o.y)
                local h = math.floor(s / 2)
                for x = cx - h, cx - h + s - 1 do for y = cy - (s == 7 and 0 or h), cy + (s == 7 and 0 or h) do
                    taken[x .. "," .. y] = true
                end end
            end
        end
    end
    for _, o in ipairs(PLANNED_OBJECTS) do
        local s = (o[1] == "PowerStation" or o[1] == "WaterPumpStation") and 3 or 1
        for x = o[2], o[2] + s - 1 do for y = o[3], o[3] + s - 1 do taken[x .. "," .. y] = true end end
    end
    local fx1, fy1, fx2, fy2, fences = MW, MH, -1, -1, 0
    for y = 1, MH do
        for x = 1, MW do
            local m = Object.GetMaterial(x - 1, y - 1)
            if m == "Fence" or m == "PerimeterWall" or PLANNED[(x - 1) .. "," .. (y - 1)] == "Fence" then
                fences = fences + 1
                fx1, fy1 = math.min(fx1, x - 1), math.min(fy1, y - 1)
                fx2, fy2 = math.max(fx2, x - 1), math.max(fy2, y - 1)
            end
            local free = OPEN_GROUND[m] and not planned_at(x - 1, y - 1) and not taken[(x - 1) .. "," .. (y - 1)]
            if free then  -- outdoor zones (yard, deliveries) have no floor but are in use
                local ok, rid = pcall(function() return World.GetCell(x - 1, y - 1).Room.i end)
                if ok and tonumber(rid) and tonumber(rid) >= 0 then free = false end
            end
            local b = free and 0 or 1
            S[y][x] = b + S[y - 1][x] + S[y][x - 1] - S[y - 1][x - 1]
        end
    end
    local function blocked(x1, y1, x2, y2)
        return S[y2 + 1][x2 + 1] - S[y1][x2 + 1] - S[y2 + 1][x1] + S[y1][x1]
    end
    -- with a perimeter fence, only look inside it (live: a dormitory was offered outside the fence)
    local lx1, ly1, lx2, ly2 = margin, margin, MW - w - margin, MH - h - margin
    if fences >= 20 then
        lx1, ly1 = math.max(lx1, fx1 + 1 + margin), math.max(ly1, fy1 + 1 + margin)
        lx2, ly2 = math.min(lx2, fx2 - w - margin), math.min(ly2, fy2 - h - margin)
    end
    local best, bestd = nil, nil
    near_x, near_y = tonumber(near_x), tonumber(near_y)
    for y = ly1, ly2 do
        for x = lx1, lx2 do
            if blocked(x - margin, y - margin, x + w - 1 + margin, y + h - 1 + margin) == 0 then
                local d = 0
                if near_x then d = math.abs(x + w / 2 - near_x) + math.abs(y + h / 2 - near_y) end
                if not best or d < bestd then best, bestd = { x1 = x, y1 = y, x2 = x + w - 1, y2 = y + h - 1 }, d end
                if not near_x then return best end
            end
        end
    end
    if not best then
        error("no free " .. w .. "x" .. h .. " area of open ground found" ..
              (fences >= 20 and " inside the fence" or "") .. "; try a smaller size", 0)
    end
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
doc("build_area", "material, x1, y1, x2, y2", "Fill a rectangle with a floor/material (ConcreteFloor, PavingStone, ConcreteTiles...).",
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

-- Rooms only work indoors (cells, kitchens...). The game marks cells indoor when a
-- foundation is finished; walls + floor built as separate orders stay outdoor
-- (measured live: prisoners reported FailedToFindCell until Ind was set). The
-- area is walled all round, so mark it indoor like a finished building.
local function set_indoors(x1, y1, x2, y2)
    for x = x1, x2 do for y = y1, y2 do
        pcall(function() World.GetCell(x, y).Ind = true end)
    end end
end

-- Can a workman walk to the area? Live (30 Sep 2026): rooms ordered beyond the old fence line were
-- unreachable; every workman kept carrying their materials there and giving up, so nothing else got
-- built either (not even the paving that would have opened the fence). Staff open doors, so only
-- walls and fences block them. Skipped when there is no workman to start from.
local function check_reachable(x1, y1, x2, y2, what)
    local ok, r = pcall(function() return api.objects("Workman", 3) end)
    if not ok or type(r) ~= "table" or not r.objects or #r.objects == 0 then return end
    local w, h = map_size()
    local function inside(x, y) return x >= x1 - 1 and x <= x2 + 1 and y >= y1 - 1 and y <= y2 + 1 end
    local seen, todo = {}, {}
    for _, o in ipairs(r.objects) do
        local sx, sy = math.floor(o.x), math.floor(o.y)
        if inside(sx, sy) then return end
        local k = sy * w + sx
        if not seen[k] then seen[k] = true; todo[#todo + 1] = { sx, sy } end
    end
    local i = 1
    while i <= #todo do
        local x, y = todo[i][1], todo[i][2]
        i = i + 1
        for _, d in ipairs({ { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } }) do
            local nx, ny = x + d[1], y + d[2]
            if nx >= 0 and ny >= 0 and nx < w and ny < h and not seen[ny * w + nx] then
                seen[ny * w + nx] = true
                if inside(nx, ny) then return end
                if not WALLS[Object.GetMaterial(nx, ny) or ""] then todo[#todo + 1] = { nx, ny } end
            end
        end
    end
    error(what .. " at " .. x1 .. "," .. y1 .. "-" .. x2 .. "," .. y2 .. ": no workman can walk there (a fence " ..
          "or walls are in the way). Open a way in FIRST: `remove fence x1 y1 x2 y2` on the fence between, wait " ..
          "until it is gone, then order this again. (Ordered now it stalls every workman.)", 0)
end

-- The rectangle must not overlap a room (zoned) or work already ordered. Live (30 Sep 2026): an office
-- ordered over a new solitary block replaced its dividers and doors (later orders win).
local function check_clear(x1, y1, x2, y2, what)
    for x = x1, x2 do
        for y = y1, y2 do
            local ok, i = pcall(function() return World.GetCell(x, y).Room.i end)
            if ok and tonumber(i) and tonumber(i) >= 0 then
                error(what .. " at " .. x1 .. "," .. y1 .. "-" .. x2 .. "," .. y2 .. " overlaps an existing room at " ..
                      x .. "," .. y .. ". Pick empty ground (`space w h`) or `unzone` it first.", 0)
            end
            local p = planned_at(x, y)
            if p and p ~= Object.GetMaterial(x, y) then
                error(what .. " at " .. x1 .. "," .. y1 .. "-" .. x2 .. "," .. y2 .. " overlaps work already ordered (" ..
                      p .. " at " .. x .. "," .. y .. "). Pick empty ground (`space w h`).", 0)
            end
        end
    end
end

-- The door cell must not get a wall: a wall order there was built over the
-- finished door (live: kitchen and shower doors turned into BrickWall). A later
-- order for the same cell replaces the wall order, so order floor there instead.
local function door_gap(x, y, floor)
    req("Construction", floor or "ConcreteFloor", x, y)
end

-- A building: walls around the rectangle, a floor inside, and a door.
function api.building(x1, y1, x2, y2, door_side, door, wall, floor)
    x1, y1, x2, y2 = rect(x1, y1, x2, y2, "building")
    if x2 - x1 < 2 or y2 - y1 < 2 then error("a building needs at least 3 x 3 cells including walls", 0) end
    check_reachable(x1, y1, x2, y2, "building")
    check_clear(x1, y1, x2, y2, "building")
    door_side = door_side and string.lower(door_side) or "south"
    if not SIDES[door_side] then error("door_side must be north, south, east or west", 0) end
    wall = wall or "BrickWall"
    floor = floor or "ConcreteFloor"
    door = door or "Door"
    api.build_area(floor, x1 + 1, y1 + 1, x2 - 1, y2 - 1)
    api.build_wall_rect(wall, x1, y1, x2, y2)
    set_indoors(x1, y1, x2, y2)
    local cx, cy = math.floor((x1 + x2) / 2), math.floor((y1 + y2) / 2)
    local dx, dy, ox, oy
    if door_side == "south" then dx, dy, ox, oy = cx, y2, 0, 1
    elseif door_side == "north" then dx, dy, ox, oy = cx, y1, 0, 1
    elseif door_side == "east" then dx, dy, ox, oy = x2, cy, 1, 0
    else dx, dy, ox, oy = x1, cy, 1, 0 end
    door_gap(dx, dy, floor)
    req("PlaceObject", door, dx, dy, ox, oy)
    return {
        queued = true, walls = { x1 = x1, y1 = y1, x2 = x2, y2 = y2 }, door = { object = door, x = dx, y = dy },
        inside = { x1 = x1 + 1, y1 = y1 + 1, x2 = x2 - 1, y2 = y2 - 1 },
        next = "Workmen build it over time. Furnish the inside with api.furnish(kind, inside...) and zone it " ..
               "with api.zone(room_type, inside...). api.room(...) does all three in one call.",
    }
end
doc("building", "x1, y1, x2, y2, [door_side, door, wall, floor]",
    "Walls + floor + a door (default Door on the south side). Returns the inside rectangle.",
    "api.building(60, 30, 70, 38, \"south\")")

-- Perimeter fence around a rectangle. Where the fence crosses the road it leaves
-- a gap and puts a RoadGate (7 wide) there so trucks and new prisoners get in.
local function is_road(x, y) return string.sub(Object.GetMaterial(x, y) or "", 1, 4) == "Road" end

function api.perimeter(x1, y1, x2, y2, material)
    x1, y1, x2, y2 = rect(x1, y1, x2, y2, "perimeter")
    material = material or "Fence"
    local fence, gates = 0, {}
    -- gates already on the map (live: re-running the fence ordered a second gate next to the first)
    local existing = {}
    local okg, eg = pcall(api.objects, "RoadGate", 50)
    if okg then for _, o in ipairs(eg.objects) do existing[#existing + 1] = o end end
    local function side(y)  -- horizontal side: fence, road runs become gates
        -- A RoadGate is 7 cells wide (ordered at its left cell) and roads are often 5
        -- wide, so the gate also covers the cells beside the road. Find the gate spans
        -- first and never order fence there (an order cannot be taken back: the UI tool
        -- names CancelJobs/Demolish get BUILT as literal materials by the work queue).
        local gate_at = {}
        local x = x1
        while x <= x2 do
            if is_road(x, y) then
                local s = x
                while x <= x2 and is_road(x, y) do x = x + 1 end
                local gx = math.max(x1, s - math.floor(math.max(0, 7 - (x - s)) / 2))
                local have
                for _, o in ipairs(existing) do
                    -- a RoadGate's Pos is its centre: it covers Pos.x-3.5 .. Pos.x+3.5 on row floor(Pos.y)
                    if math.floor(o.y) == y and o.x - 3.5 <= s and o.x + 3.5 >= x then have = o end
                end
                if have then
                    gx = math.floor(have.x - 3.5)
                    gates[#gates + 1] = gx .. "," .. y .. " (already there)"
                else
                    req("PlaceObject", "RoadGate", gx, y, 0, 1)
                    gates[#gates + 1] = gx .. "," .. y .. " (road " .. (x - s) .. " wide)"
                end
                for gc = gx, gx + 6 do gate_at[gc] = true end
            else
                x = x + 1
            end
        end
        for fx = x1, x2 do
            if not gate_at[fx] then req("Construction", material, fx, y); fence = fence + 1 end
        end
    end
    side(y1); side(y2)
    for y = y1 + 1, y2 - 1 do
        for _, x in ipairs({ x1, x2 }) do
            if is_road(x, y) then error("the fence runs along the road at x=" .. x .. "; move that side off the road", 0) end
            req("Construction", material, x, y); fence = fence + 1
        end
    end
    return { fence_cells = fence, road_gates = gates, cost_estimate = fence * 20 + #gates * 1000,
             note = "Keeps prisoners in. Everything the prison uses (deliveries, garbage, power, water) should be inside. " ..
                    (#gates == 0 and "No road crossing found: make sure trucks can still reach Deliveries." or
                     "Road gates open for vehicles and staff.") }
end
doc("perimeter", "x1, y1, x2, y2, [material]", "Fence around the whole prison; road crossings get a RoadGate.",
    "api.perimeter(92, 8, 147, 79)")

-- ---- furnishing ---------------------------------------------------------------
-- Object footprints (width, height) when facing down (0,1).
local SIZE = { Bed = { 1, 2 }, Toilet = { 1, 1 }, Cooker = { 2, 1 }, Fridge = { 2, 1 }, Sink = { 3, 1 },
               Table = { 4, 1 }, Bench = { 4, 1 }, ShowerHead = { 1, 1 }, Drain = { 1, 1 },
               ServingTable = { 5, 1 }, WeightsBench = { 1, 1 }, PhoneBooth = { 1, 1 }, Tv = { 1, 1 },
               OfficeDesk = { 2, 1 }, FilingCabinet = { 1, 1 }, Chair = { 1, 1 }, SofaChairDouble = { 2, 1 },
               GuardLocker = { 1, 1 }, MedicalBed = { 2, 2 }, Bin = { 1, 1 },
               -- sizes from the game's materials.txt
               VisitorTable = { 3, 2 }, Altar = { 3, 2 }, Pews = { 4, 1 }, PrayerMat = { 1, 1 },
               PoolTable = { 3, 2 }, LargeTv = { 2, 1 }, LaundryMachine = { 1, 1 }, LaundryBasket = { 1, 1 },
               IroningBoard = { 3, 1 }, SchoolDesk = { 1, 2 }, LibraryBookshelf = { 3, 1 },
               SortingTable = { 3, 1 }, WorkshopSaw = { 3, 1 }, WorkshopPress = { 3, 1 },
               SofaChairSingle = { 1, 1 }, DrinkMachine = { 1, 1 }, MorgueSlab = { 1, 2 } }

-- PlaceObject anchor for a footprint whose left/top cell is given (facing down, 0,1).
-- Measured live 29 Sep 2026 (object Pos after install): an object ordered at x covers
-- x .. x+w-1 (Table at 110 -> Pos.x 112 = cells 110..113; Sink at 99 -> 100.5 = 99..101),
-- and a height-2 Bed ordered at y covers y-1 .. y (Pos.y 33.0 = cells 32..33).
local function anchor_x(left, w) return left end
local function anchor_y(top, h) return top + h - 1 end

-- face: "down" (default, 0,1) or "up" (0,-1). Things standing against the BOTTOM wall must face up,
-- or their working position is inside the wall (live: kitchen "Sink: Working Position Cannot be Reached").
local function put(list, obj, left, top, face)
    local s = SIZE[obj] or { 1, 1 }
    list[#list + 1] = { obj, anchor_x(left, s[1]), anchor_y(top, s[2]), face == "up" and -1 or 1 }
end

local LAYOUTS = {}

-- Each layout gets the inside rectangle and returns a list of {object, x, y}.
LAYOUTS.kitchen = function(x1, y1, x2, y2, out)
    -- cookers along the top wall; a sink (required) and fridges along the bottom wall
    local x = x1
    while x + 1 <= x2 and #out < 3 do put(out, "Cooker", x, y1); x = x + 2 end
    if y2 - y1 < 2 or x2 - x1 < 2 then error("a kitchen needs at least 3 x 3 cells inside", 0) end
    put(out, "Sink", x1, y2, "up")
    x = x1 + 3
    local fridges = 0
    while x + 1 <= x2 and fridges < 2 do put(out, "Fridge", x, y2, "up"); x = x + 2; fridges = fridges + 1 end
    if y2 - y1 >= 3 then put(out, "Bin", x2, y1 + 2) end  -- trash goes out via bins (game: "not disposing of waste")
    put(out, "Sprinkler", x1, y1 + 1)  -- kitchens start fires; sprinklers cleared "not equipped to handle a fire"
    return "Kitchen: cookers on the top wall, a sink and fridges on the bottom wall. Cookers and fridges need power, " ..
           "the sink needs water (api.hookup). Hire 2+ Cooks. Put a Canteen next to it."
end

LAYOUTS.canteen = function(x1, y1, x2, y2, out)
    -- rows of Table with a Bench above and below; serving table at the top.
    if x2 - x1 + 1 >= 5 then put(out, "ServingTable", x1, y1) end
    -- one serving table fed ~25 at day 27 (3 tables, 79 prisoners, half hungry): wide canteens get two
    if x2 - x1 + 1 >= 11 then put(out, "ServingTable", x1 + 6, y1) end
    local y = y1 + 2
    while y + 2 <= y2 do
        local x = x1
        while x + 3 <= x2 do
            put(out, "Bench", x, y); put(out, "Table", x, y + 1); put(out, "Bench", x, y + 2)
            x = x + 4  -- sets side by side; the empty row between set rows is the walkway
        end
        y = y + 4
    end
    put(out, "Bin", x2, y2)
    put(out, "Sprinkler", x1, y1 + 1)
    return "Canteen: a serving table, rows of tables with benches, a bin and a sprinkler. Zone it as Canteen."
end

LAYOUTS.shower = function(x1, y1, x2, y2, out)
    for x = x1, x2, 2 do put(out, "ShowerHead", x, y1) end
    put(out, "Drain", x1 + 1 <= x2 and x1 + 1 or x1, math.floor((y1 + y2) / 2))
    return "Showers along the back wall and a drain. Zone it as Shower."
end

LAYOUTS.yard = function(x1, y1, x2, y2, out)
    for x = x1, math.min(x2, x1 + 6), 2 do put(out, "WeightsBench", x, y1) end
    put(out, "PhoneBooth", x2, y2)
    if x2 - 1 >= x1 then put(out, "Bin", x2 - 1, y2) end
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

-- Many beds in one room: rows of beds (1x2) with a 1-cell aisle between rows,
-- toilets along the right wall. Cheapest beds per dollar.
LAYOUTS.dormitory = function(x1, y1, x2, y2, out)
    local tx = x2
    for y = y1, y2, 2 do put(out, "Toilet", tx, y) end
    local y = y1
    while y + 1 <= y2 do
        for x = x1, tx - 2, 2 do put(out, "Bed", x, y) end
        y = y + 3
    end
    if tx - 1 > x1 then put(out, "Bin", tx - 1, y1) end
    return "Dormitory: rows of beds and toilets on the right wall. Zone as Dormitory. Toilets need water (hookup)."
end

LAYOUTS.office = function(x1, y1, x2, y2, out)
    put(out, "OfficeDesk", x1, y1); put(out, "Chair", x1, y1 + 1); put(out, "FilingCabinet", x2, y1)
    return "Office: desk, chair, filing cabinet. Zone as Office (Warden, Accountant...)."
end

LAYOUTS.staffroom = function(x1, y1, x2, y2, out)
    -- game requirements (materials.txt): indoor, at least 4x4, a sofa AND a DrinkMachine
    if x2 - x1 < 3 or y2 - y1 < 3 then error("a staff room needs at least 4x4 cells inside", 0) end
    put(out, "Tv", x1, y1); put(out, "DrinkMachine", x2, y1); put(out, "SofaChairDouble", x1, y1 + 2)
    return "Staff room: sofa, drink machine (required) and TV. Tired staff rest here."
end

-- Visitation: rows of VisitorTables (3x2); the game requires at least one, indoors.
LAYOUTS.visitation = function(x1, y1, x2, y2, out)
    local y = y1
    while y + 1 <= y2 do
        local x = x1
        while x + 2 <= x2 do put(out, "VisitorTable", x, y); x = x + 4 end
        y = y + 3
    end
    return "Visitation: visitor tables. Families visit here (8am-8pm); it calms prisoners."
end

LAYOUTS.infirmary = function(x1, y1, x2, y2, out)
    for x = x1, x2 - 1, 3 do put(out, "MedicalBed", x, y1) end
    return "Infirmary: medical beds. Zone as MedicalWard; needs a Doctor (Health research)."
end

-- Game requirements from materials.txt (BEGIN Room ... Requirement) -- 30 Sep 2026.
local function need_inside(kind, x1, y1, x2, y2, w, h)
    if x2 - x1 + 1 < w or y2 - y1 + 1 < h then
        error(("a %s needs at least %dx%d cells inside (the rectangle you give includes the walls, so %dx%d)")
              :format(kind, w, h, w + 2, h + 2), 0)
    end
end

-- Chapel: Altar + Pews + PrayerMat, at least 6x6, indoors. Calms Spirituality.
LAYOUTS.chapel = function(x1, y1, x2, y2, out)
    need_inside("chapel", x1, y1, x2, y2, 6, 6)
    put(out, "Altar", math.floor((x1 + x2) / 2) - 1, y1)
    put(out, "PrayerMat", x1, y1); put(out, "PrayerMat", x2, y1)
    local y = y1 + 3
    while y <= y2 - 1 do  -- the bottom row stays free as a walkway to the door
        local x = x1
        while x + 3 <= x2 do put(out, "Pews", x, y, "up"); x = x + 4 end  -- side by side; the free row is the aisle
        y = y + 2
    end
    return "Chapel: altar, pews and prayer mats. Prisoners with a Spirituality need pray here. Zone as Chapel."
end

-- Common room: no required objects; TV, sofa, pool table, phone. Calms Recreation.
LAYOUTS.commonroom = function(x1, y1, x2, y2, out)
    need_inside("common room", x1, y1, x2, y2, 4, 4)
    put(out, "Tv", x1, y1); put(out, "SofaChairDouble", x1, y1 + 2)
    if x2 - x1 >= 6 and y2 - y1 >= 3 then put(out, "PoolTable", x1 + 4, y1 + 1) end
    put(out, "PhoneBooth", x2, y1)
    if y2 - y1 >= 5 then put(out, "Bench", x1, y2 - 1) end
    put(out, "Bin", x2, y2)
    return "Common room: TV (needs power: hookup), sofa, pool table, phone. Prisoners relax here in FreeTime."
end

-- Parole room: a VisitorTable, at least 5x5 inside. Prisoners up for parole get their hearing here.
LAYOUTS.parole = function(x1, y1, x2, y2, out)
    need_inside("parole room", x1, y1, x2, y2, 5, 5)
    put(out, "VisitorTable", x1 + 1, y1 + 1)
    return "Parole room: a visitor table. Prisoners up for parole have their hearing here (the To-do 'up for parole')."
end

-- Laundry (PrisonLabour): LaundryMachine (power + water), LaundryBasket, IroningBoard. Fixes Clothing.
LAYOUTS.laundry = function(x1, y1, x2, y2, out)
    need_inside("laundry", x1, y1, x2, y2, 4, 3)
    for x = x1, math.min(x2, x1 + 4), 2 do put(out, "LaundryMachine", x, y1) end
    put(out, "LaundryBasket", x2, y1 + 1)
    put(out, "IroningBoard", x1, y2, "up")
    return "Laundry: washing machines (need power AND water: hookup both), a basket and an ironing board. " ..
           "Janitors (Cleaning research) or working prisoners run it; it fixes the Clothing need."
end

-- Classroom (Education): SchoolDesks + a teacher's OfficeDesk, at least 5x5.
LAYOUTS.classroom = function(x1, y1, x2, y2, out)
    need_inside("classroom", x1, y1, x2, y2, 5, 5)
    put(out, "OfficeDesk", x1, y1)
    local y = y1 + 2
    while y + 1 <= y2 - 1 do
        for x = x1, x2, 2 do put(out, "SchoolDesk", x, y) end
        y = y + 3
    end
    return "Classroom: school desks and a teacher's desk. Programs are set in the game's Reform tab."
end

-- Workshop (PrisonLabour): WorkshopSaw + WorkshopPress (power) + a Table, enclosed, at least 5x5.
LAYOUTS.workshop = function(x1, y1, x2, y2, out)
    need_inside("workshop", x1, y1, x2, y2, 5, 5)
    put(out, "WorkshopSaw", x1, y1)
    if x2 - x1 >= 6 then put(out, "WorkshopPress", x1 + 4, y1) else put(out, "WorkshopPress", x1, y1 + 2) end
    put(out, "Table", x1, y2 - 1)
    return "Workshop: saw, press (power: hookup) and a table. Prisoners make licence plates for money; it needs " ..
           "a Workshop Induction program and guards (tools are contraband)."
end

-- Library (PrisonLabour): LibraryBookshelf + SortingTable, at least 5x5.
LAYOUTS.library = function(x1, y1, x2, y2, out)
    need_inside("library", x1, y1, x2, y2, 5, 5)
    put(out, "LibraryBookshelf", x1, y1); put(out, "SortingTable", x1, y1 + 2)
    if x2 - x1 >= 6 then put(out, "LibraryBookshelf", x1 + 4, y1) end
    return "Library: bookshelves and a sorting table. Prisoners relax and read here."
end

-- Morgue (Health): MorgueSlabs (1x2, against a wall). Without one, dead bodies lie where they fell
-- (live day 27: 17 bodies after a riot).
LAYOUTS.morgue = function(x1, y1, x2, y2, out)
    need_inside("morgue", x1, y1, x2, y2, 3, 3)
    for x = x1, x2, 2 do put(out, "MorgueSlab", x, y1) end
    return "Morgue: slabs for the dead (Doctors/Workmen carry bodies here, then a hearse collects them)."
end

-- Rooms that need no furniture: just the zone (they still need a floor, and
-- Deliveries/Garbage/Storage work best next to the road).
local EMPTY_ROOMS = { deliveries = "Deliveries: trucks drop supplies here. Put it next to the road.",
                      garbage = "Garbage: bins are collected here. Put it next to the road.",
                      storage = "Storage: supplies are kept here.",
                      cleaning = "Cleaning cupboard (Cleaning research, 3x3+ inside): Janitors and working prisoners " ..
                                 "clean from here." }

-- furnish kind -> room type to zone
local KIND_ROOM = { kitchen = "Kitchen", canteen = "Canteen", shower = "Shower", yard = "Yard",
                    holding = "HoldingCell", cell = "Cell", office = "Office", staffroom = "Staffroom",
                    infirmary = "MedicalWard", deliveries = "Deliveries", garbage = "Garbage", storage = "Storage",
                    dormitory = "Dormitory", visitation = "Visitation", chapel = "Chapel", commonroom = "CommonRoom",
                    parole = "ParoleRoom", laundry = "Laundry", classroom = "Classroom", workshop = "Workshop",
                    library = "Library", cleaning = "CleaningCupboard", morgue = "Morgue" }
-- research the game needs before the room (or its furniture) can be built
local ROOM_RESEARCH = { laundry = "PrisonLabour", workshop = "PrisonLabour", library = "PrisonLabour",
                        classroom = "Education", cleaning = "Cleaning", infirmary = "Health", morgue = "Health" }

local function kind_names()
    local names = {}
    for k in pairs(KIND_ROOM) do names[#names + 1] = k end
    table.sort(names)
    return table.concat(names, ", ")
end

function api.furnish(kind, x1, y1, x2, y2)
    kind = string.lower(tostring(kind or ""))
    local layout = LAYOUTS[kind]
    if EMPTY_ROOMS[kind] then return { queued = 0, objects = {}, note = EMPTY_ROOMS[kind] } end
    if not layout then
        error("unknown room kind '" .. kind .. "'. Choose one of: " .. kind_names(), 0)
    end
    x1, y1, x2, y2 = rect(x1, y1, x2, y2, "room inside")
    local items = {}
    local note = layout(x1, y1, x2, y2, items)
    if #items == 0 then error("room is too small to furnish as " .. kind, 0) end
    for _, it in ipairs(items) do
        -- general rule: a 1-high object on the bottom row faces up, away from the wall (its working
        -- spot is in front of it; live bug: "Working Position Cannot be Reached")
        local s = SIZE[it[1]] or { 1, 1 }
        if it[4] == nil and it[3] == y2 and y2 > y1 and s[2] == 1 then it[4] = -1 end
        req("PlaceObject", it[1], it[2], it[3], 0, it[4] or 1)
    end
    local placed = {}
    for _, it in ipairs(items) do placed[#placed + 1] = it[1] .. "@" .. it[2] .. "," .. it[3] end
    return { queued = #items, objects = placed, note = note }
end
doc("furnish", "kind, x1, y1, x2, y2",
    "Place the right furniture inside a room's inside area. kind: kitchen, canteen, shower, yard, holding, cell, office, " ..
    "staffroom, infirmary.",
    "api.furnish(\"kitchen\", 61, 31, 69, 37)")

-- Everything for one room in one call: walls + floor + door, furniture, zone.
-- Yards, deliveries and garbage are outdoor areas: no walls, just a floor (or ground) and the zone.
local OUTDOOR = { yard = true, deliveries = true, garbage = true }
local JAIL_DOOR = { holding = true, dormitory = true }
function api.room(kind, x1, y1, x2, y2, door_side)
    kind = string.lower(tostring(kind or ""))
    local room = KIND_ROOM[kind]
    if not room then error("unknown room kind '" .. kind .. "'. Choose one of: " .. kind_names(), 0) end
    x1, y1, x2, y2 = rect(x1, y1, x2, y2, kind)
    local res = ROOM_RESEARCH[kind]
    if res and NATIVE and api.is_researched and not api.is_researched(res) then
        error("a " .. kind .. " needs the " .. res .. " research first. api.unlock(\"" .. kind ..
              "\") lists the steps.", 0)
    end
    if kind == "cleaning" and (x2 - x1 - 1 < 3 or y2 - y1 - 1 < 3) then
        error("a cleaning cupboard needs 3x3 inside (5x5 with walls)", 0)
    end
    local inside, built
    if OUTDOOR[kind] then
        inside = { x1 = x1, y1 = y1, x2 = x2, y2 = y2 }
        check_reachable(x1, y1, x2, y2, kind)
        check_clear(x1, y1, x2, y2, kind)
        if kind ~= "yard" then api.build_area("ConcreteFloor", x1, y1, x2, y2) end
        built = "outdoor area (no walls)"
    else
        local b = api.building(x1, y1, x2, y2, door_side or "south", JAIL_DOOR[kind] and "JailDoor" or "Door")
        inside, built = b.inside, "walls, floor and a " .. b.door.object .. " at " .. b.door.x .. "," .. b.door.y
    end
    local f = api.furnish(kind, inside.x1, inside.y1, inside.x2, inside.y2)
    local z = NATIVE and api.zone(room, inside.x1, inside.y1, inside.x2, inside.y2) or nil
    return { room = room, built = built, inside = inside, furniture = f.objects, zoned = z ~= nil,
             note = f.note .. (z and "" or " Zoning needs bridge DLL 0.3: ask the human to zone the inside rectangle."),
             next = "Workmen build it over time (api.progress()). Resume the game if it is paused." }
end
doc("room", "kind, x1, y1, x2, y2, [door_side]",
    "EASIEST: build a whole room in one call: walls + floor + door + furniture + zone. kind: kitchen, canteen, shower, " ..
    "yard, holding, cell, office, staffroom, infirmary, deliveries, garbage, storage, chapel, commonroom, parole, " ..
    "laundry, classroom, workshop, library, cleaning, morgue. The rectangle includes the walls.",
    "api.room(\"kitchen\", 60, 30, 70, 38, \"south\")")

-- A row of cells facing south onto a corridor. Each cell is 3 wide x 3 deep inside.
-- A row of small rooms opening south onto a 2-cell corridor: walls, dividers,
-- floor, furniture, a door per room and the zone. Used for cells and solitary.
local function room_row(x, y, count, cw, ch, door, zone, furnish, what)
    x, y, count = num(x, "x"), num(y, "y"), num(count or 4, "count")
    if count < 1 or count > 30 then error("count must be 1..30", 0) end
    local x2 = x + count * (cw + 1)
    local y2 = y + ch + 1
    rect(x, y, x2, y2 + 2, what .. " (with its 2-cell corridor)")
    check_reachable(x, y, x2, y2 + 2, what)
    check_clear(x, y, x2, y2 + 2, what)
    -- floors first: a later order for the same cell replaces an earlier one, so the
    -- dividing walls must be ordered after the floor (live bug: cells had no dividers)
    api.build_area("ConcreteFloor", x + 1, y + 1, x2 - 1, y2 - 1)
    api.build_area("ConcreteFloor", x, y2 + 1, x2, y2 + 2)
    api.build_wall_rect("BrickWall", x, y, x2, y2)
    for i = 1, count - 1 do api.build_line("BrickWall", x + i * (cw + 1), y + 1, x + i * (cw + 1), y2 - 1) end
    set_indoors(x, y, x2, y2)
    local rooms = {}
    for i = 0, count - 1 do
        local cx1 = x + 1 + i * (cw + 1)
        if furnish then
            local items = {}
            furnish(cx1, y + 1, cx1 + cw - 1, y2 - 1, items)
            for _, it in ipairs(items) do req("PlaceObject", it[1], it[2], it[3], 0, it[4] or 1) end
        end
        local dx = cx1 + math.floor((cw - 1) / 2)
        door_gap(dx, y2)
        req("PlaceObject", door, dx, y2, 0, 1)
        rooms[#rooms + 1] = { x1 = cx1, y1 = y + 1, x2 = cx1 + cw - 1, y2 = y2 - 1, door = { x = dx, y = y2 } }
    end
    if NATIVE then
        for _, c in ipairs(rooms) do api.zone(zone, c.x1, c.y1, c.x2, c.y2) end
    end
    return { queued = true, cells = rooms, corridor = { x1 = x, y1 = y2 + 1, x2 = x2, y2 = y2 + 2 }, zoned = NATIVE,
             next = NATIVE and ("Every room is zoned as " .. zone .. ". Workmen build it over time (api.progress()).") or
                    ("Ask the human to zone each room as " .. zone .. " (needs bridge DLL 0.3 to do it yourself).") }
end

function api.cell_block(x, y, count, door)
    return room_row(x, y, count, 3, 3, door or "JailDoor", "Cell", LAYOUTS.cell, "cell block")
end
doc("cell_block", "x, y, count, [door]", "A row of 3x3 cells with beds, toilets and jail doors, opening south onto a corridor.",
    "api.cell_block(20, 10, 6)")

-- Solitary cells: 1x1 inside, enclosed, SolitaryDoor (game requirement: Enclosed).
-- Misconduct punishments queue up without them (live: 63 waiting, prison temperature 100).
function api.solitary_block(x, y, count)
    return room_row(x, y, count, 1, 1, "SolitaryDoor", "Solitary", nil, "solitary block")
end
doc("solitary_block", "x, y, count", "A row of 1x1 solitary cells (SolitaryDoor, zoned Solitary) with a corridor below. " ..
    "Uses (count*2+1) x 5 cells.", "api.solitary_block(20, 70, 6)")

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
    return { total = total, by_type = out, note = "Hire more with api.hire(type, count)." }
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

-- Every object ordered through this API since the script started, with the game minute of the order
-- (the easy front end checks them against a save: installed / waiting / silently dropped).
function api.planned()
    local out = {}
    for _, o in ipairs(PLANNED_OBJECTS) do out[#out + 1] = { type = o[1], x = o[2], y = o[3], t = o[4] or 0 } end
    local okt, now = pcall(function() return World.TimeIndex end)
    return { objects = out, now = okt and tonumber(now) or 0 }
end

-- ---- power and water ---------------------------------------------------------------
-- Measured live: ElectricalCable / PipeLarge / PipeSmall ordered with PlaceObject are
-- laid by workmen into the utility grid (they show up in the save's Electricity and
-- Water sections). Cables and pipes may run under walls.
local NEEDS = {
    power = { "WaterPumpStation", "Capacitor", "Cooker", "Fridge", "Tv", "LargeTv", "Light", "LaundryMachine", "Cctv", "CctvMonitor",
              "DoorControlSystem", "MetalDetector", "WorkshopSaw", "WorkshopPress", "ArcadeCabinet", "PhoneMonitor" },
    water = { "Toilet", "ShowerHead", "Sink", "Drain", "LaundryMachine", "Sprinkler" },
}
-- Only real sources seed the network. A Capacitor is NOT a source: it must itself be
-- cabled to the station (live bug: the pump was wired to an unconnected capacitor).
local STATION = { power = { "PowerStation" }, water = { "WaterPumpStation" } }
local SIZE3 = { PowerStation = 3, WaterPumpStation = 3 }

local function lpath(x1, y1, x2, y2)
    -- horizontal first, then vertical; includes both ends
    local cells = {}
    local sx = x2 >= x1 and 1 or -1
    for x = x1, x2, sx do cells[#cells + 1] = { x, y1 } end
    local sy = y2 >= y1 and 1 or -1
    for y = y1 + sy, y2, sy do if y1 ~= y2 then cells[#cells + 1] = { x2, y } end end
    return cells
end

-- small = set of "x,y" cells under fixtures: those get a small pipe (fixtures only
-- connect to small pipes), the rest of a water line is large pipe.
local function lay(kind, cells, small)
    local n = 0
    for _, c in ipairs(cells) do
        local key = c[1] .. "," .. c[2]
        if not PLANNED_UTIL[kind][key] then
            local obj = kind == "power" and "ElectricalCable" or ((small and small[key]) and "PipeSmall" or "PipeLarge")
            req("PlaceObject", obj, c[1], c[2], 0, 1)
            n = n + 1
        end
    end
    return n
end

function api.cable(x1, y1, x2, y2)
    x1, y1, x2, y2 = num(x1, "x1"), num(y1, "y1"), num(x2, "x2"), num(y2, "y2")
    rect(x1, y1, x1, y1, "start"); rect(x2, y2, x2, y2, "end")
    local cells = lpath(x1, y1, x2, y2)
    return { queued = lay("power", cells), cost_each = 10, path = "x first, then y" }
end
doc("cable", "x1, y1, x2, y2", "Lay power cable from one cell to another (along x, then along y). Runs under walls.",
    "api.cable(101, 13, 101, 40)")

function api.pipe(x1, y1, x2, y2)
    x1, y1, x2, y2 = num(x1, "x1"), num(y1, "y1"), num(x2, "x2"), num(y2, "y2")
    rect(x1, y1, x1, y1, "start"); rect(x2, y2, x2, y2, "end")
    local cells = lpath(x1, y1, x2, y2)
    return { queued = lay("water", cells), cost_each = 15, path = "x first, then y", pipe = "PipeLarge" }
end
doc("pipe", "x1, y1, x2, y2", "Lay a large water pipe from one cell to another (along x, then along y).",
    "api.pipe(98, 20, 98, 40)")

-- cells occupied by existing objects of the given types (footprint from their centre)
local function object_cells(types)
    local out = {}
    with_anchor(function(anchor, radius)
        for _, t in ipairs(types) do
            for _, o in ipairs(find_objects(anchor, radius, t)) do
                if o.x and o.y then
                    local s = SIZE3[t] or 1
                    local cx, cy = math.floor(o.x), math.floor(o.y)
                    local h = math.floor(s / 2)
                    for x = cx - h, cx - h + s - 1 do for y = cy - h, cy - h + s - 1 do out[#out + 1] = { x, y, t } end end
                end
            end
        end
    end)
    return out
end

-- Power stations trip (On = false) when demand goes over capacity; the pump only
-- works with power. Measured live: one PowerStation = capacity 50.
function api.utilities(switch_on)
    local out = { power_stations = {}, pumps = {}, capacity = 0, demand = 0, problems = {} }
    with_anchor(function(anchor, radius)
        for o in pairs(Object.GetNearbyObjects(anchor, "PowerStation", radius) or {}) do
            if o ~= anchor then
                -- measured live: the player's on/off is `Switch` (On is recomputed by the game);
                -- a trip sets Switch=false and Overloaded>0. Two stations touching each other
                -- trip at once; each station feeds up to Capacity 50 on its own grid.
                local on, dem, cap = o.Switch ~= false, tonumber(o.Demand) or 0, tonumber(o.Capacity) or 0
                local over = tonumber(o.Overloaded) or 0
                if switch_on and not on then o.Overloaded = 0; o.Switch = true; on = "reset" end
                out.power_stations[#out.power_stations + 1] = { x = math.floor(o.Pos.x), y = math.floor(o.Pos.y), on = on,
                                                                demand = dem, capacity = cap, overloaded = over }
                out.capacity = out.capacity + cap; out.demand = out.demand + dem
                if on == false then
                    local where = "PowerStation at " .. math.floor(o.Pos.x) .. "," .. math.floor(o.Pos.y)
                    if over >= 2 then
                        out.problems[#out.problems + 1] = where .. " is OFF: it shares a grid with another station " ..
                            "(Overloaded 2). Stations do not share load here: give each its own grid - put PowerSwitches " ..
                            "on the cables between them and `switch x y off` - then api.utilities(true)."
                    else
                        out.problems[#out.problems + 1] = where .. " is OFF: too much demand (max 50 per station, a " ..
                            "cooker takes ~10). Move part of the load to its own station with a PowerSwitch split, then " ..
                            "api.utilities(true)."
                    end
                elseif dem > cap * 0.9 then
                    out.problems[#out.problems + 1] = "PowerStation at " .. math.floor(o.Pos.x) .. "," .. math.floor(o.Pos.y) ..
                        " is nearly full (" .. dem .. "/" .. cap .. "): the next cooker or light may trip it."
                end
            end
        end
        for o in pairs(Object.GetNearbyObjects(anchor, "WaterPumpStation", radius) or {}) do
            if o ~= anchor then
                out.pumps[#out.pumps + 1] = { x = math.floor(o.Pos.x), y = math.floor(o.Pos.y), powered = o.Powered == true }
                if o.Powered ~= true then
                    out.problems[#out.problems + 1] = "WaterPumpStation at " .. math.floor(o.Pos.x) .. "," .. math.floor(o.Pos.y) ..
                        " has no power, so there is NO WATER. Check the power stations, then api.hookup(\"power\")."
                end
            end
        end
    end)
    if #out.power_stations == 0 then out.problems[#out.problems + 1] = "No PowerStation: kitchens and the water pump need one." end
    if #out.pumps == 0 then out.problems[#out.problems + 1] = "No WaterPumpStation: toilets, showers and sinks need water." end
    return out
end
doc("utilities", "[switch_on]", "Power stations (on? demand/capacity) and water pumps (powered?). " ..
    "api.utilities(true) switches tripped stations back on.", "api.utilities()")

-- Turn a PowerSwitch on or off (like clicking it in the game). A switch placed on a
-- cable splits the grid; off = everything behind it loses power.
function api.switch(x, y, on)
    x, y = rect(x, y, x, y, "switch")
    local found
    with_anchor(function(anchor, radius)
        for o in pairs(Object.GetNearbyObjects(anchor, "PowerSwitch", radius) or {}) do
            if o ~= anchor and math.floor(o.Pos.x) == x and math.floor(o.Pos.y) == y then found = o end
        end
    end)
    if not found then error("no PowerSwitch installed at " .. x .. "," .. y .. " (order one with api.place_object(\"PowerSwitch\", x, y) on a cable)", 0) end
    -- the player's switch is `Switch` (On is recomputed by the game every tick)
    found.Switch = (on == true or on == "on" or on == 1)
    return { switch = x .. "," .. y, on = found.Switch }
end
doc("switch", "x, y, on", "Turn the PowerSwitch at x,y on (true) or off (false).", "api.switch(130, 10, false)")

-- known: optional list of "x,y" cells that already carry this utility (the easy
-- front end reads them from a fresh save), so existing lines are reused, not re-bought.
function api.hookup(kind, known)
    kind = string.lower(tostring(kind or ""))
    if kind == "" or kind == "both" or kind == "all" then
        local p = api.hookup("power", type(known) == "table" and known.power or nil)
        local w = api.hookup("water", type(known) == "table" and known.water or nil)
        return { power = p, water = w }
    end
    if not NEEDS[kind] then error("kind must be \"power\", \"water\" or \"both\"", 0) end
    -- Without the existing lines (read from a save by the easy `hookup`) every built object looks
    -- unconnected and whole networks get re-bought and cross-wired (live: 118 cables, 4 stations tripped).
    if (type(known) ~= "table" or #known == 0) and next(PLANNED_UTIL[kind]) == nil then
        local okc, st = pcall(api.count, STATION[kind])
        local stations = 0
        if okc then for _, v in pairs(st) do stations = stations + v end end
        if stations > 0 then
            error("hookup needs the cells that already carry " .. kind .. " (use the easy `hookup` verb / pa_hookup, " ..
                  "which reads them from a save); running blind would re-lay and cross-wire existing lines", 0)
        end
    end
    -- the network: stations (built or ordered) plus every cable/pipe ordered through this API
    local net, netlist = {}, {}
    local function add(x, y) local k = x .. "," .. y; if not net[k] then net[k] = true; netlist[#netlist + 1] = { x, y } end end
    for _, c in ipairs(object_cells(STATION[kind])) do add(c[1], c[2]) end
    for _, o in ipairs(PLANNED_OBJECTS) do
        for _, st in ipairs(STATION[kind]) do
            if o[1] == st then
                local s = SIZE3[st] or 1
                for x = o[2], o[2] + s - 1 do for y = o[3], o[3] + s - 1 do add(x, y) end end
            end
        end
    end
    for k in pairs(PLANNED_UTIL[kind]) do local x, y = string.match(k, "(-?%d+),(-?%d+)"); add(tonumber(x), tonumber(y)) end
    local reused = 0
    if type(known) == "table" then
        for _, k in ipairs(known) do
            local x, y = string.match(tostring(k), "(-?%d+),(-?%d+)")
            if x then
                add(tonumber(x), tonumber(y)); reused = reused + 1
                PLANNED_UTIL[kind][k] = PLANNED_UTIL[kind][k] or "existing"
            end
        end
    end
    if #netlist == 0 then
        local st = STATION[kind][1]
        error("no " .. st .. " yet. Order one first: api.place_object(\"" .. st .. "\", x, y) (3x3, $5000), then hookup again.", 0)
    end
    -- everything that needs this utility: built objects plus ordered ones
    local users, seen = {}, {}
    local function user(x, y, t) local k = x .. "," .. y; if not seen[k] then seen[k] = true; users[#users + 1] = { x, y, t } end end
    for _, c in ipairs(object_cells(NEEDS[kind])) do
        -- the map's own street lights are outdoors: do not run cable to them
        local indoor = true
        if c[3] == "Light" then
            local ok, ind = pcall(function() return World.GetCell(c[1], c[2]).Ind end)
            indoor = ok and ind == true
        end
        if indoor then user(c[1], c[2], c[3]) end
    end
    local needs = {}
    for _, t in ipairs(NEEDS[kind]) do needs[t] = true end
    for _, o in ipairs(PLANNED_OBJECTS) do if needs[o[1]] then user(o[2], o[3], o[1]) end end
    -- nearest first, so long lines do not run over fixtures that could have their own short pipe
    local function dist(u)
        local bd
        for _, c in ipairs(netlist) do
            local d = math.abs(c[1] - u[1]) + math.abs(c[2] - u[2])
            if not bd or d < bd then bd = d end
        end
        return bd
    end
    for _, u in ipairs(users) do u[4] = dist(u) end
    table.sort(users, function(a, b) return a[4] < b[4] end)
    -- Power only: split the network into separate grids and track each grid's spare capacity, so a new
    -- user is never wired onto a grid whose station is full (live: a staff room tripped a kitchen's station).
    local comp, headroom = {}, {}
    local function flood(k0, id)
        local stack = { k0 }
        comp[k0] = id
        while #stack > 0 do
            local k = table.remove(stack)
            local x, y = string.match(k, "(-?%d+),(-?%d+)")
            x, y = tonumber(x), tonumber(y)
            for _, n in ipairs({ (x + 1) .. "," .. y, (x - 1) .. "," .. y, x .. "," .. (y + 1), x .. "," .. (y - 1) }) do
                if net[n] and not comp[n] then comp[n] = id; stack[#stack + 1] = n end
            end
        end
    end
    local LOAD = { Cooker = 12, Fridge = 5, WaterPumpStation = 20, LaundryMachine = 10, Tv = 3, LargeTv = 4 }
    local short = {}
    -- grids that actually have a source (station / pump); a line cut off from its source is an island
    -- (live: a staff room kept its cable after the link was cut and looked "connected")
    local has_source = {}
    local nid = 0
    for _, c in ipairs(netlist) do
        local k = c[1] .. "," .. c[2]
        if not comp[k] then nid = nid + 1; flood(k, nid) end
    end
    for _, c in ipairs(object_cells(STATION[kind])) do
        local id = comp[c[1] .. "," .. c[2]]
        if id then has_source[id] = true end
    end
    for _, o in ipairs(PLANNED_OBJECTS) do
        for _, st in ipairs(STATION[kind]) do
            if o[1] == st then local id = comp[o[2] .. "," .. o[3]]; if id then has_source[id] = true end end
        end
    end
    if kind == "power" then
        local util = select(2, pcall(api.utilities)) or {}
        for id = 1, nid do headroom[id] = 0 end
        local built = {}
        for _, st in ipairs(type(util) == "table" and util.power_stations or {}) do
            local id = comp[st.x .. "," .. st.y]
            if id then built[id] = true end
            if id and st.on ~= false then headroom[id] = (headroom[id] or 0) + (st.capacity or 50) - (st.demand or 0) end
        end
        -- a station that is ordered but not built yet brings 50, minus what is already wired to it
        local planned_only = {}
        for _, o in ipairs(PLANNED_OBJECTS) do
            if o[1] == "PowerStation" then
                local id = comp[o[2] .. "," .. o[3]]
                if id and not built[id] then headroom[id] = (headroom[id] or 0) + 50; built[id] = true; planned_only[id] = true end
            end
        end
        for _, u in ipairs(users) do
            local id = comp[u[1] .. "," .. u[2]]
            if id and planned_only[id] then headroom[id] = headroom[id] - (LOAD[u[3]] or 2) end
        end
    end
    local laid, joined = 0, 0
    for _, u in ipairs(users) do
        local uk = u[1] .. "," .. u[2]
        if not (net[uk] and has_source[comp[uk]]) then
            local need = kind == "power" and (LOAD[u[3]] or 2) or 0
            -- candidates: cells of grids with a source and (power) spare capacity, nearest first
            local cands = {}
            for _, c in ipairs(netlist) do
                local id = comp[c[1] .. "," .. c[2]]
                if id and has_source[id] and (kind ~= "power" or (headroom[id] or 0) >= need) then
                    cands[#cands + 1] = { c, math.abs(c[1] - u[1]) + math.abs(c[2] - u[2]), id }
                end
            end
            table.sort(cands, function(a, b) return a[2] < b[2] end)
            -- a route must not run on or next to another grid's line: that would join two grids and
            -- two stations on one grid switch each other off. Try x-then-y and y-then-x.
            local function clean(path, id)
                for i, c in ipairs(path) do
                    for _, n in ipairs({ { 0, 0 }, { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } }) do
                        local o = comp[(c[1] + n[1]) .. "," .. (c[2] + n[2])]
                        if kind == "power" and o and o ~= id and has_source[o] then return false end
                    end
                end
                return true
            end
            local best, path, id
            for i = 1, math.min(#cands, 40) do
                local c = cands[i]
                for _, p in ipairs({ lpath(u[1], u[2], c[1][1], c[1][2]), (function()
                    local q = lpath(c[1][1], c[1][2], u[1], u[2]); local r = {}
                    for j = #q, 1, -1 do r[#r + 1] = q[j] end; return r end)() }) do
                    if clean(p, c[3]) then best, path, id = c[1], p, c[3]; break end
                end
                if best then break end
            end
            if not best then
                short[#short + 1] = u[3] .. "@" .. u[1] .. "," .. u[2]
            else
                table.remove(path)  -- the last cell is already part of the network
                -- reverse so the end under the object is last (small pipe there)
                local rev = {}
                for i = #path, 1, -1 do rev[#rev + 1] = path[i] end
                laid = laid + lay(kind, rev, seen)
                for _, c in ipairs(rev) do add(c[1], c[2]); if id then comp[c[1] .. "," .. c[2]] = id end end
                if id then comp[uk] = id end
                if id then headroom[id] = (headroom[id] or 0) - need end
                joined = joined + 1
            end
        end
    end
    local note = "Workmen lay " .. (kind == "power" and "cable" or "pipes") .. " over time. Run hookup again after " ..
                 "adding rooms. Kitchens (cookers, fridges) need power; toilets, showers and sinks need water."
    if #short > 0 then
        note = "NOT connected (every grid near them is full; each station feeds 50): " .. table.concat(short, ", ") ..
               ". Put a `station power` near them (not touching another station), then hookup again. " .. note
    end
    return { kind = kind, objects_needing_it = #users, newly_connected = joined, pieces_ordered = laid,
             not_connected = short, note = note }
end
doc("hookup", "[power|water|both]", "Connect every object that needs power/water to the nearest cable/pipe or station. " ..
    "Needs a PowerStation / WaterPumpStation first.", "api.hookup(\"both\")")

-- ---- zoning (native) -----------------------------------------------------------
local ZONES = {}          -- zones made through this API: {room, x1, y1, x2, y2}
local ROOM_TYPES = nil    -- cached list from the game
local ROOM_ALIASES = {
    cells = "Cell", holding = "HoldingCell", holdingcell = "HoldingCell", infirmary = "MedicalWard",
    medical = "MedicalWard", medicalward = "MedicalWard", staff = "Staffroom", staffroom = "Staffroom",
    common = "CommonRoom", commonroom = "CommonRoom", cleaning = "CleaningCupboard", cupboard = "CleaningCupboard",
    delivery = "Deliveries", deliveries = "Deliveries", garbage = "Garbage", bins = "Garbage",
    showers = "Shower", kitchen = "Kitchen", canteen = "Canteen", yard = "Yard", office = "Office",
    storage = "Storage", laundry = "Laundry", workshop = "Workshop", visitation = "Visitation",
    none = "None", clear = "None", unzone = "None", solitary = "Solitary", security = "Security",
    wardensoffice = "Office", warden = "Office",
}

function api.room_types()
    if not ROOM_TYPES then ROOM_TYPES = split(native("roomtypes"), ",") end
    return ROOM_TYPES
end
doc("room_types", "", "Every room type the game knows (Cell, HoldingCell, Kitchen, Canteen, Shower, Yard, Office...).",
    "api.room_types()")

local function room_name(name)
    if type(name) ~= "string" or name == "" then error("room type required, e.g. \"Cell\" or \"Kitchen\"", 0) end
    local key = string.lower(string.gsub(name, "[%s_%-]", ""))
    for _, t in ipairs(api.room_types()) do if string.lower(t) == key then return t end end
    if ROOM_ALIASES[key] then return ROOM_ALIASES[key] end
    local pool = {}
    for _, t in ipairs(api.room_types()) do pool[t] = 1 end
    error("unknown room type '" .. name .. "'. Did you mean " .. tostring(suggest(name, pool)) ..
          "? See api.room_types()", 0)
end

local function zoned_cells(x1, y1, x2, y2)
    local n = 0
    for x = x1, x2 do for y = y1, y2 do
        local ok, i = pcall(function() return World.GetCell(x, y).Room.i end)
        if ok and tonumber(i) and tonumber(i) >= 0 then n = n + 1 end
    end end
    return n
end

function api.zone(room_type, x1, y1, x2, y2)
    local room = room_name(room_type)
    x1, y1, x2, y2 = rect(x1, y1, x2, y2, "zone")
    native(string.format("zone:%s %d %d %d %d", room, x1, y1, x2, y2))
    -- forget older zones this one covers completely
    local keep = {}
    for _, z in ipairs(ZONES) do
        if not (z.x1 >= x1 and z.x2 <= x2 and z.y1 >= y1 and z.y2 <= y2) then keep[#keep + 1] = z end
    end
    ZONES = keep
    if room ~= "None" then ZONES[#ZONES + 1] = { room = room, x1 = x1, y1 = y1, x2 = x2, y2 = y2 } end
    local total = (x2 - x1 + 1) * (y2 - y1 + 1)
    local n = zoned_cells(x1, y1, x2, y2)
    return { zoned = room, area = { x1 = x1, y1 = y1, x2 = x2, y2 = y2 }, cells = total,
             cells_in_a_room_now = n,
             note = room == "None" and "Zone removed." or n == 0 and
                 ("NOTHING WAS ZONED: the game skips walls and unfinished foundation ('Building'). Wait until " ..
                  "the floor is built (api.progress()) and zone again.") or
                 ("Zone the INSIDE of a room (not its walls). The game checks each room's needs " ..
                  "(e.g. a Cell needs a Bed and a Toilet); open the room in the game to see them.") }
end
doc("zone", "room_type, x1, y1, x2, y2", "Zone a rectangle as a room (Cell, HoldingCell, Kitchen, Canteen, Shower, Yard, " ..
    "Office, Staffroom, Deliveries, Garbage, Storage...). Use the building's INSIDE rectangle.",
    "api.zone(\"Kitchen\", 61, 31, 69, 37)")

-- Bounding box and size of every room on the map, keyed by the game's room id
-- (types come from a save: see the rooms verb / pa_rooms).
function api.room_boxes()
    local w, h = map_size()
    local boxes = {}
    for x = 0, w - 1 do
        for y = 0, h - 1 do
            local ok, i = pcall(function() return World.GetCell(x, y).Room.i end)
            i = ok and tonumber(i) or -1
            if i >= 0 then
                local k = tostring(i)
                local b = boxes[k]
                if not b then b = { x1 = x, y1 = y, x2 = x, y2 = y, cells = 0 }; boxes[k] = b end
                if x < b.x1 then b.x1 = x end
                if y < b.y1 then b.y1 = y end
                if x > b.x2 then b.x2 = x end
                if y > b.y2 then b.y2 = y end
                b.cells = b.cells + 1
            end
        end
    end
    return boxes
end

function api.unzone(x1, y1, x2, y2) return api.zone("None", x1, y1, x2, y2) end
doc("unzone", "x1, y1, x2, y2", "Remove zoning from a rectangle.", "api.unzone(61, 31, 69, 37)")

function api.zones()
    local out = {}
    for _, z in ipairs(ZONES) do out[#out + 1] = string.format("%s %d,%d-%d,%d", z.room, z.x1, z.y1, z.x2, z.y2) end
    return out
end
doc("zones", "", "Zones made through this API since the prison was loaded (the game does not tell scripts room types).",
    "api.zones()")

-- ---- game speed and saving (native) ----------------------------------------------
function api.pause()
    native("setspeed:0")
    return { paused = true, note = "Nothing moves while paused, but you can still plan, build orders, zone and hire. " ..
                                   "Call api.resume() so workmen can work." }
end
doc("pause", "", "Pause the game.", "api.pause()")

function api.resume(speed)
    speed = tonumber(speed) or 1
    if speed <= 0 or speed > 5 then error("speed must be between 0.1 and 5 (1 = normal)", 0) end
    native("setspeed:" .. string.format("%.2f", speed))
    return { paused = false, speed = speed }
end
doc("resume", "[speed]", "Unpause (speed 1 = normal, 2-5 = faster).", "api.resume(1)")

function api.save(name)
    name = tostring(name or "agent")
    local r = native("save:" .. name)
    return { save = name, status = r,
             note = "The game writes the save right after this call (outside scripts). Check api.save_result()." }
end
doc("save", "[name]", "Save the prison to saves/<name>.prison (letters, digits, _ and - only).", "api.save(\"agent\")")

function api.save_result()
    local r = native("saveresult")
    if r == "pending" then return { done = false } end
    if string.sub(r or "", 1, 3) == "ok " then return { done = true, ok = true, path = string.sub(r, 4) } end
    return { done = r ~= "", ok = false, error = r }
end

-- ---- prisoner intake (native, DLL 0.3.2) -----------------------------------------------
-- The game's own intake modes (Reports > Intake), from its daily decision code.
local INTAKE_MODES = { [0] = "none", [1] = "beds", [2] = "max", [3] = "perday", [4] = "all" }
local INTAKE_TEXT = { none = "no new prisoners", beds = "only while there are free beds",
                      max = "until the prison holds N prisoners", perday = "N prisoners a day",
                      all = "everyone the state sends (floods the prison)" }

function api.intake(mode, n)
    local cmd = "intake"
    if mode ~= nil then
        mode = string.lower(tostring(mode))
        local t
        for k, v in pairs(INTAKE_MODES) do if v == mode then t = k end end
        if t == nil then error("intake mode must be none, beds, max, perday or all", 0) end
        if (mode == "max" or mode == "perday") and not tonumber(n) then error(mode .. " needs a number", 0) end
        cmd = "intake:" .. t .. (tonumber(n) and (" " .. math.floor(tonumber(n))) or "")
    end
    local r = native(cmd)
    local t, total, perday = string.match(r or "", "^(%-?%d+) (%-?%d+) (%-?%d+)$")
    local m = INTAKE_MODES[tonumber(t)] or "?"
    return { mode = m, meaning = INTAKE_TEXT[m], max_total = tonumber(total), per_day = tonumber(perday),
             advice = m == "all" and "Switch to api.intake(\"beds\") so only prisoners you can house arrive." or nil }
end
doc("intake", "[mode, n]", "Prisoner intake. No args: current mode. Modes: beds (only while free beds - recommended), " ..
    "none, max N (total), perday N, all.", "api.intake(\"beds\")")

-- ---- regime / daily schedule (native, DLL 0.4) ------------------------------------------
-- Activity codes from the game's enum (start-up table at 0x140df8bf0).
local ACTIVITIES = { [0] = "Lockup", "Sleep", "Eat", "Shower", "Yard", "Work", "WorkLockdown", "Lockdown",
                     "FreeTime", "EatLockdown", "ShowerLockdown", "Unspecified" }
local ACTIVITY_ALIAS = { nothing = 0, lockup = 0, bangup = 0, cell = 0, sleep = 1, eat = 2, food = 2, meal = 2,
                         shower = 3, wash = 3, yard = 4, exercise = 4, work = 5, lockdown = 7, freetime = 8,
                         free = 8, unspecified = 11 }
local function activity_code(a)
    if tonumber(a) then return math.floor(tonumber(a)) end
    local k = string.lower(string.gsub(tostring(a or ""), "[%s_%-]", ""))
    for code, name in pairs(ACTIVITIES) do if string.lower(name) == k then return code end end
    if ACTIVITY_ALIAS[k] then return ACTIVITY_ALIAS[k] end
    error("unknown activity '" .. tostring(a) .. "': use Sleep, Eat, Shower, Yard, FreeTime, Work or Lockup", 0)
end

-- The schedule everyone follows is the one category that is not all "Unspecified" (the others follow
-- it). Measured live: it sits at index 2 of the game's category array, not at the save's first entry.
local function base_category()
    for c = 0, 7 do
        local ok, r = pcall(native, "regime:" .. c)
        if ok and r and string.find(r, "[^,]") and not string.match(r, "^Unspecified[Unspecified,]*$") then return c end
    end
    return 2
end

function api.regime(cat)
    cat = cat and num(cat, "category") or base_category()
    local names = split(native("regime:" .. cat), ",")
    for i, n in ipairs(names) do if n == "Nothing" then names[i] = "Lockup" end end
    local counts = {}
    for _, n in ipairs(names) do counts[n] = (counts[n] or 0) + 1 end
    local rows = {}
    for h = 0, 23 do rows[#rows + 1] = string.format("%02d %s", h, names[h + 1] or "?") end
    return { category = cat, hours = rows, totals = counts,
             note = "This is the schedule everyone follows. Prisoners need Sleep ~8h, Eat 2-3x, Shower, " ..
                    "Yard and FreeTime (Freedom need); Lockup keeps them in cells." }
end
doc("regime", "[category]", "The daily schedule, hour by hour (default: the one everyone follows).", "api.regime()")

function api.set_regime(from, to, activity, cat)
    from, to = num(from, "from hour"), num(to or from, "to hour")
    cat = cat and num(cat, "category") or base_category()
    if from < 0 or to > 23 or from > to then error("hours are 0..23, from <= to", 0) end
    local code = activity_code(activity)
    for h = from, to do native(string.format("setregime:%d %d %d", cat, h, code)) end
    return api.regime(cat)
end
doc("set_regime", "from_hour, to_hour, activity, [category]", "Set hours of the daily schedule to Sleep, Eat, Shower, " ..
    "Yard, FreeTime, Work or Lockup. Takes effect at the next hour.", "api.set_regime(13, 16, \"FreeTime\")")

-- A schedule that covers every basic need (Sleep 9, Eat 3, Shower 1, Yard 3, FreeTime 7, Lockup 1).
local REGIME_PRESETS = {
    balanced = { "Sleep", "Sleep", "Sleep", "Sleep", "Sleep", "Sleep", "Sleep", "Shower", "Eat", "Yard", "Yard", "Yard",
                 "Eat", "FreeTime", "FreeTime", "FreeTime", "FreeTime", "Eat", "FreeTime", "FreeTime", "FreeTime",
                 "Lockup", "Sleep", "Sleep" },
    work = { "Sleep", "Sleep", "Sleep", "Sleep", "Sleep", "Sleep", "Sleep", "Shower", "Eat", "Work", "Work", "Work",
             "Eat", "Work", "Work", "Yard", "FreeTime", "Eat", "FreeTime", "FreeTime", "FreeTime", "Lockup", "Sleep", "Sleep" },
}
function api.regime_preset(name)
    local p = REGIME_PRESETS[string.lower(tostring(name or "balanced"))]
    if not p then error("presets: balanced, work", 0) end
    local cat = base_category()
    for h = 0, 23 do native(string.format("setregime:%d %d %d", cat, h, activity_code(p[h + 1]))) end
    return api.regime(cat)
end
doc("regime_preset", "[balanced|work]", "Replace the whole schedule with a preset that covers every need.",
    "api.regime_preset(\"balanced\")")

-- ---- camera (native, DLL 0.4) ------------------------------------------------------------
function api.camera(x, y, zoom)
    local r
    if x ~= nil then
        r = native(string.format("camera:%.2f %.2f%s", tonumber(x), tonumber(y), zoom and string.format(" %.4f", tonumber(zoom)) or ""))
    else
        r = native("camera")
    end
    local cx, cy, z = string.match(r or "", "^(%-?[%d.]+) (%-?[%d.]+) (%-?[%d.]+)$")
    return { x = tonumber(cx), y = tonumber(cy), zoom = tonumber(z), note = "zoom = cells per screen pixel" }
end
doc("camera", "[x, y, zoom]", "Where the player's view is (cells). With numbers: move the view there.", "api.camera(110, 40)")

-- Frame a rectangle: centre it and zoom so it fits a screen `px_w` x `px_h` pixels wide.
function api.look_at(x1, y1, x2, y2, px_w, px_h)
    x1, y1, x2, y2 = rect(x1, y1, x2, y2, "view")
    px_w, px_h = tonumber(px_w) or 1920, tonumber(px_h) or 1080
    local z = math.max((x2 - x1 + 3) / px_w, (y2 - y1 + 3) / px_h)
    return api.camera((x1 + x2 + 1) / 2, (y1 + y2 + 1) / 2, z)
end
doc("look_at", "x1, y1, x2, y2", "Move the player's view to show that rectangle (for screenshots).", "api.look_at(95, 38, 120, 48)")

-- ---- removing things --------------------------------------------------------------------
local function remove_util(kind, x1, y1, x2, y2)
    x1, y1, x2, y2 = rect(x1, y1, x2, y2)
    local n = 0
    for x = x1, x2 do for y = y1, y2 do
        native((kind == "power" and "rmcable:" or "rmpipe:") .. x .. " " .. y)
        PLANNED_UTIL[kind][x .. "," .. y] = nil
        n = n + 1
    end end
    return { removed_cells = n, kind = kind, note = "Removed at once (no refund). Things that used it lose " .. kind .. "." }
end
function api.remove_cable(x1, y1, x2, y2) return remove_util("power", x1, y1, x2, y2) end
function api.remove_pipe(x1, y1, x2, y2) return remove_util("water", x1, y1, x2, y2) end
doc("remove_cable", "x1, y1, x2, y2", "Remove electric cable from a rectangle (e.g. a wrong link between grids).",
    "api.remove_cable(130, 10, 130, 10)")
doc("remove_pipe", "x1, y1, x2, y2", "Remove water pipe from a rectangle.", "api.remove_pipe(99, 44, 99, 44)")

-- Dismantle one object near a cell (workmen take it away; the game's own job).
function api.remove(object_type, x, y)
    if type(object_type) ~= "string" or object_type == "" then error("object type required", 0) end
    x, y = rect(x, y, x, y, "position")
    local done
    with_anchor(function(anchor, radius)
        local best, bd
        for o in pairs(Object.GetNearbyObjects(anchor, object_type, radius) or {}) do
            if o ~= anchor then
                local d = math.abs(o.Pos.x - (x + 0.5)) + math.abs(o.Pos.y - (y + 0.5))
                if d < 3 and (not bd or d < bd) then best, bd = o, d end
            end
        end
        if best then WorkQueue.Request("DismantleObject", best); done = { x = best.Pos.x, y = best.Pos.y } end
    end)
    if not done then error("no " .. object_type .. " within 2 cells of " .. x .. "," .. y, 0) end
    return { dismantling = object_type, at = done, note = "Workmen dismantle it over time." }
end
doc("remove", "type, x, y", "Dismantle the object of that type nearest to x,y (within 2 cells).", "api.remove(\"Bench\", 117, 41)")

-- Search the furniture around a cell (the game's SearchObject job: a guard searches it). Tunnel
-- entrances hide under beds/toilets; a search finds contraband and discovers the tunnel, which
-- workmen then fill. Live day 28: a dormitory tunnel (entrance 107,18) led outside the fence.
local SEARCHABLE = { "Bed", "BunkBed", "Toilet", "ShowerHead", "Bench", "Table", "Sink", "Drain", "Cooker",
                     "Fridge", "WeightsBench", "PhoneBooth", "Tv", "SofaChairDouble", "Pews", "OfficeDesk",
                     "FilingCabinet", "ServingTable", "VisitorTable", "Bin", "LaundryBasket", "MedicalBed" }
function api.search(x, y, radius)
    x, y = rect(x, y, x, y, "position")
    radius = tonumber(radius) or 2
    local found = {}
    with_anchor(function(anchor, r)
        for _, t in ipairs(SEARCHABLE) do
            for o in pairs(Object.GetNearbyObjects(anchor, t, r) or {}) do
                if o ~= anchor and math.abs(o.Pos.x - (x + 0.5)) <= radius + 0.6 and
                   math.abs(o.Pos.y - (y + 0.5)) <= radius + 0.6 then
                    WorkQueue.Request("SearchObject", o)
                    found[#found + 1] = t .. "@" .. math.floor(o.Pos.x) .. "," .. math.floor(o.Pos.y)
                end
            end
        end
    end)
    return { searching = found, note = #found == 0 and "nothing to search within " .. radius .. " cells" or
             "Guards search these (SearchObject jobs); a tunnel under one gets discovered and filled." }
end
-- The Emergencies buttons (bridge DLL 0.5): the game's own handlers, found in the button switch.
local EMERGENCY = { shakedown = "shakedown", tunnelsearch = "tunnelsearch", tunnels = "tunnelsearch",
                    tunnel = "tunnelsearch", drugbust = "drugbust", narcoticsearch = "drugbust", drugs = "drugbust",
                    stop = "stopsearch", stopsearch = "stopsearch", bangup = "bangup", lockdown = "lockdown",
                    status = "status" }
function api.emergency(action)
    local key = EMERGENCY[string.lower(string.gsub(tostring(action or "status"), "[%s_%-]", ""))]
    if not key then error("emergency: shakedown, tunnelsearch, drugbust, stop, bangup, lockdown or status", 0) end
    local r = native("emergency:" .. key)
    if type(r) ~= "string" then error("emergencies need bridge DLL 0.5 (scripts\\install_bridge.ps1 with the game closed)", 0) end
    if string.sub(r, 1, 6) == "error:" then error(string.sub(r, 8), 0) end
    local st = {}
    for k, v in string.gmatch(r, "(%a+) (%d)") do st[k] = v == "1" end
    return { done = key, state = st,
             note = key == "tunnelsearch" and "Guards (and dogs) search the whole prison for tunnels; found ones get filled." or
                    key == "shakedown" and "Guards search every cell and object for contraband." or
                    key == "drugbust" and "Guards search for narcotics." or
                    key == "bangup" and "Bangup toggled: prisoners are locked in their cells while it is on." or
                    key == "lockdown" and "Lockdown toggled: everyone is locked in place while it is on." or
                    key == "stopsearch" and "The running search was stopped." or "Current emergency state." }
end
doc("emergency", "action", "The game's Emergencies buttons: shakedown, tunnelsearch, drugbust, stop (a search), " ..
    "bangup / lockdown (toggle), status.", "api.emergency(\"tunnelsearch\")")

-- Grants (bridge DLL 0.5): the list the game's Grants screen shows, and accepting one through the
-- game's own AcceptGrant (pays the advance; the grant's objectives appear on the To-do list).
function api.grants()
    local r = native("grants")
    if type(r) ~= "string" then error("grants need bridge DLL 0.5 (scripts\\install_bridge.ps1 with the game closed)", 0) end
    if string.sub(r, 1, 6) == "error:" then error(string.sub(r, 8), 0) end
    local list = {}
    for item in string.gmatch(r, ";([^;]+)") do
        local name, adv, comp, st, done, lock = string.match(item, "^([^|]*)|(-?%d+)|(-?%d+)|(-?%d+)|(%a*)|(%a+)$")
        if name then
            -- record state measured live: 0 available, 1 accepted, 2 completed (bootstraps paid out at once)
            local state = (done == "done" or tonumber(st) == 2) and "completed" or st == "1" and "accepted" or
                          (lock == "open" and "available" or "locked")
            list[#list + 1] = { name = name, advance = tonumber(adv), completion = tonumber(comp), status = state }
        end
    end
    table.sort(list, function(a, b) return a.name < b.name end)
    return { grants = list, note = "api.grant(name) accepts an available one: the advance is paid now, the " ..
                                   "completion money when its objectives are met (see the game's To-do list)." }
end
doc("grants", "", "Every grant with advance, completion money and status (available, locked, accepted, completed).",
    "api.grants()")

function api.grant(name)
    if type(name) ~= "string" or name == "" then error("grant name required (api.grants() lists them)", 0) end
    local key = name
    if not string.find(key, "^Grant_") then key = "Grant_" .. key end
    local r = native("grant:" .. key)
    if type(r) ~= "string" then error("grants need bridge DLL 0.5", 0) end
    if string.sub(r, 1, 6) == "error:" then error(key .. ": " .. string.sub(r, 8), 0) end
    return { accepted = key, objectives_added = tonumber(string.match(r, "(%-?%d+)$")),
             note = "Accepted: the advance is in the bank; build what the To-do list asks for to get the rest." }
end
doc("grant", "name", "Accept a grant (name from api.grants(), e.g. \"Grant_bootstraps\").", "api.grant(\"Grant_bootstraps\")")

function api.read_letter()
    local r = native("readletter")
    if type(r) ~= "string" then error("needs bridge DLL 0.5.1 (install with the game closed)", 0) end
    return { done = r, note = "The CEO's letter is marked as read (as if opened from the To-do list)." }
end
doc("read_letter", "", "Mark the CEO's letter as read (clears 'Read the CEO's letter' on the To-do list).",
    "api.read_letter()")

function api.objectives()
    local r = native("objectives")
    if type(r) ~= "string" then error("objectives need bridge DLL 0.5", 0) end
    local out = {}
    for item in string.gmatch(r, ";([^;]+)") do out[#out + 1] = item end
    return { count = tonumber(string.match(r, "^(%d+)")), objectives = out }
end
doc("objectives", "", "The live objectives (accepted grants and their parts, tutorial items); child<parent.",
    "api.objectives()")

doc("search", "x, y, [radius]", "Guards search the furniture within radius (default 2) of a cell: finds contraband " ..
    "and tunnel entrances.", "api.search(107, 18)")

-- Replace walls/fences in a rectangle with floor (the work queue turns the cell into floor).
function api.demolish(x1, y1, x2, y2, floor)
    x1, y1, x2, y2 = rect(x1, y1, x2, y2, "area")
    floor = floor or "ConcreteFloor"
    local n = 0
    for x = x1, x2 do for y = y1, y2 do
        local m = Object.GetMaterial(x, y) or ""
        if WALLS[m] or m == "Fence" then req("Construction", floor, x, y); n = n + 1 end
    end end
    return { walls_replaced = n, with = floor, note = "Workmen replace each wall/fence cell with " .. floor .. "." }
end
doc("demolish", "x1, y1, x2, y2, [floor]", "Knock down walls/fences in a rectangle (they become floor).", "api.demolish(92, 9, 92, 78)")

-- ---- screenshot (native, DLL 0.3.1) -------------------------------------------------
function api.screenshot()
    return { status = native("screenshot"), note = "The next frame the game draws is saved; check api.screenshot_result()." }
end
function api.screenshot_result()
    local r = native("screenshotresult") or ""
    if r == "pending" or r == "" then return { done = false } end
    if string.sub(r, 1, 3) == "ok " then return { done = true, ok = true, path = string.sub(r, 4) } end
    return { done = true, ok = false, error = r }
end

-- ---- research (native) -------------------------------------------------------------
-- name = { requires, department that researches it, cost }
local RESEARCH = {
    Maintainance = { "Warden", "Warden", 500 }, Security = { "Warden", "Warden", 500 },
    Legal = { "Warden", "Warden", 5000 }, MentalHealth = { "Warden", "Warden", 500 },
    Finance = { "Warden", "Warden", 500 }, Cctv = { "Security", "Security", 2000 },
    RemoteAccess = { "Security", "Security", 2000 }, Health = { "Warden", "Warden", 500 },
    Cleaning = { "Maintainance", "Maintainance", 2000 }, GroundsKeeping = { "Maintainance", "Maintainance", 2000 },
    Deployment = { "Security", "Security", 1000 }, Patrols = { "Security", "Security", 1000 },
    Dogs = { "Patrols", "Security", 1000 }, PrisonLabour = { "Maintainance", "Maintainance", 1000 },
    Education = { "Warden", "Warden", 2000 }, LandExpansion = { "Finance", "Finance", 1000 },
    Contraband = { "Security", "Security", 1000 }, Policy = { "Warden", "Warden", 1000 },
    Armoury = { "Security", "Security", 2000 }, BodyArmour = { "Armoury", "Security", 1000 },
    Tazers = { "Armoury", "Security", 1000 }, TazersForEveryone = { "Tazers", "Security", 5000 },
    BankLoans = { "Finance", "Finance", 500 }, LowerTaxes1 = { "Finance", "Finance", 10000 },
    LowerTaxes2 = { "LowerTaxes1", "Finance", 50000 }, ExtraGrant = { "Finance", "Finance", 500 },
    AdvancedManagement = { "Warden", "Warden", 1000 }, Deathrow = { "Legal", "Legal", 10000 },
    PermanentPunishment = { "Legal", "Legal", 5000 }, RemoveMinCellSize = { "Legal", "Legal", 10000 },
    ReduceExecutionLiability = { "Deathrow", "Legal", 10000 }, LegalPrep = { "Legal", "Legal", 50000 },
    LegalDefense = { "LegalPrep", "Legal", 50000 }, GuardTowers = { "Armoury", "Security", 5000 },
    NonLethalSniper = { "GuardTowers", "Security", 5000 },
}
local DEPARTMENT_HEAD = { Warden = "Warden", Security = "Chief", Maintainance = "Foreman", Finance = "Accountant",
                          Legal = "Lawyer", MentalHealth = "Psychologist" }
-- what each research unlocks (research.txt tooltips + the Research lines in materials.txt)
local UNLOCKS = { Maintainance = "Foreman", Security = "Chief", Legal = "Lawyer", MentalHealth = "Psychologist",
                  Finance = "Accountant", Health = "Doctor, infirmary", Cleaning = "Janitor, cleaning cupboard",
                  GroundsKeeping = "Gardener", Dogs = "DogHandler, kennel", Armoury = "ArmedGuard, armoury",
                  GuardTowers = "Sniper", Cctv = "CCTV cameras", RemoteAccess = "remote doors",
                  Education = "classroom, programs", PrisonLabour = "laundry, workshop, library, shop, prisoner jobs",
                  Patrols = "guard patrols", Deployment = "guard deployment", Contraband = "metal detectors, searches",
                  Policy = "policy tab", AdvancedManagement = "food/laundry logistics, regime per group",
                  ExtraGrant = "more grants", BankLoans = "bank loans", LandExpansion = "buy more land",
                  BodyArmour = "guard armour", Tazers = "tazers for the Chief", TazersForEveryone = "tazers for guards" }
local RESEARCH_HOURS = { Legal = 12, Education = 12, LandExpansion = 12, Armoury = 12, BankLoans = 12,
                         LowerTaxes1 = 48, LowerTaxes2 = 48, GuardTowers = 18, Deathrow = 24,
                         PermanentPunishment = 24, RemoveMinCellSize = 24, ReduceExecutionLiability = 72,
                         LegalPrep = 72, LegalDefense = 3 }  -- the rest take 6 game hours (Time 360)

local function research_state()
    local out = {}
    for _, item in ipairs(split(native("researchlist"), ",")) do
        local name, desired, pct = string.match(item, "^([^:]+):(%d):(%d+)$")
        if name then out[name] = { researching = desired == "1", percent = tonumber(pct) } end
    end
    return out
end

local function researched(state, name)
    return name == "" or name == nil or (state[name] and state[name].percent >= 100)
end

function api.is_researched(name)
    if name == "Warden" then return api.count("Warden").Warden > 0 end
    return researched(research_state(), name)
end

function api.research(name)
    local st = research_state()
    if name then
        local key
        for k in pairs(RESEARCH) do if string.lower(k) == string.lower(tostring(name)) then key = k end end
        if not key then
            error("unknown research '" .. tostring(name) .. "'. Did you mean " .. tostring(suggest(tostring(name), RESEARCH)) ..
                  "? api.research() lists them.", 0)
        end
        local r = RESEARCH[key]
        if researched(st, key) then return { research = key, status = "already done" } end
        if st[key] and st[key].researching then return { research = key, status = "already in progress", percent = st[key].percent } end
        if not researched(st, r[1]) then error(key .. " needs " .. r[1] .. " researched first", 0) end
        local head = DEPARTMENT_HEAD[r[2]]
        if head and api.count(head)[head] == 0 then
            error(key .. " is researched by the " .. head .. ". Hire one first (api.hire(\"" .. head .. "\")) and give them an Office.", 0)
        end
        local bal = tonumber(world_get("Balance")) or 0
        if bal < r[3] then error(key .. " costs $" .. r[3] .. " but you have $" .. math.floor(bal), 0) end
        native("research:" .. key)
        return { research = key, status = "started", cost = r[3], researched_by = head,
                 note = "The " .. tostring(head) .. " works on it over time (they need an Office). Check api.research()." }
    end
    local list = {}
    for k, r in pairs(RESEARCH) do
        local s = st[k] or { percent = 0 }
        local status
        if s.percent >= 100 then status = "done"
        elseif s.researching then status = "in progress " .. s.percent .. "%"
        elseif researched(st, r[1]) then status = "available"
        else status = "locked (needs " .. r[1] .. ")" end
        list[#list + 1] = { name = k, status = status, cost = r[3], by = DEPARTMENT_HEAD[r[2]], unlocks = UNLOCKS[k],
                            requires = r[1] }
    end
    table.sort(list, function(a, b) return a.name < b.name end)
    return { research = list, warden_hired = researched(st, "Warden"),
             how = "api.research(\"Health\") starts one. The cost is paid when it starts." }
end
doc("research", "[name]", "No name: list research with status. With a name: start researching it.", "api.research(\"Health\")")

-- ---- unlock planner ------------------------------------------------------------------
-- What does it take to get X? Walks the research tree (research.txt: Requires + Admin) back to the Warden
-- and lists the steps still to do, in order: hire the department head, give them an Office, research, build.
local UNLOCK_ALIASES = { janitor = "Cleaning", gardener = "GroundsKeeping", doctor = "Health", foreman = "Maintainance",
    chief = "Security", accountant = "Finance", lawyer = "Legal", psychologist = "MentalHealth", doghandler = "Dogs",
    armedguard = "Armoury", sniper = "GuardTowers", teacher = "Education", laundry = "PrisonLabour",
    workshop = "PrisonLabour", library = "PrisonLabour", shop = "PrisonLabour", classroom = "Education",
    cleaning = "Cleaning", cleaningcupboard = "Cleaning", infirmary = "Health", kennel = "Dogs", armoury = "Armoury",
    cctv = "Cctv", grants = "ExtraGrant", loans = "BankLoans", land = "LandExpansion", logistics = "AdvancedManagement",
    patrols = "Patrols", deployment = "Deployment", metaldetector = "Contraband", tazers = "Tazers" }
local UNLOCK_FINAL = { janitor = "hire Janitor 2", gardener = "hire Gardener 1", doctor = "hire Doctor 2",
    foreman = "hire Foreman", chief = "hire Chief", accountant = "hire Accountant", lawyer = "hire Lawyer",
    psychologist = "hire Psychologist", doghandler = "hire DogHandler 2", armedguard = "hire ArmedGuard 2",
    sniper = "hire Sniper", laundry = "room laundry x1 y1 x2 y2 (8x6 with walls), hookup both; Janitors (unlock janitor) or working prisoners run it",
    workshop = "room workshop x1 y1 x2 y2 (9x7 with walls), hookup power",
    library = "room library x1 y1 x2 y2 (7x7+ with walls)", classroom = "room classroom x1 y1 x2 y2 (7x7+ with walls)",
    cleaning = "room cleaning x1 y1 x2 y2 (5x5 with walls)", cleaningcupboard = "room cleaning x1 y1 x2 y2 (5x5 with walls)",
    infirmary = "room infirmary x1 y1 x2 y2, hire Doctor 2" }

function api.unlock(target)
    if target == nil or target == "" then
        local names = {}
        for k in pairs(UNLOCK_ALIASES) do names[#names + 1] = k end
        table.sort(names)
        return { usage = "api.unlock(\"laundry\") or a research name", targets = names }
    end
    local key = string.lower(string.gsub(tostring(target), "[%s_%-]", ""))
    local res = UNLOCK_ALIASES[key]
    if not res then
        for k in pairs(RESEARCH) do if string.lower(k) == key then res = k end end
    end
    if not res then
        error("don't know how to unlock '" .. tostring(target) .. "'. Try a staff type (Janitor), a room (laundry) " ..
              "or a research name; api.unlock() lists them.", 0)
    end
    local st = research_state()
    local chain, r = {}, res
    while r and r ~= "Warden" and RESEARCH[r] do table.insert(chain, 1, r); r = RESEARCH[r][1] end
    local steps, heads_needed = {}, {}
    local counts = api.count({ "Warden", "Foreman", "Chief", "Accountant", "Lawyer", "Psychologist" })
    if (counts.Warden or 0) == 0 then
        steps[#steps + 1] = { step = "hire Warden", why = "the Warden researches the first level" }
    end
    heads_needed.Warden = true
    local blocked = false
    for _, name in ipairs(chain) do
        local item = RESEARCH[name]
        local head = DEPARTMENT_HEAD[item[2]]
        local s = st[name] or { percent = 0 }
        if s.percent < 100 then
            if head and head ~= "Warden" and (counts[head] or 0) == 0 and not heads_needed[head] then
                steps[#steps + 1] = { step = "hire " .. head, why = head .. " researches " .. name,
                                      after = blocked and "the research above finishes" or nil }
            end
            if head then heads_needed[head] = true end
            if s.researching then
                steps[#steps + 1] = { step = "wait", why = name .. " is being researched: " .. s.percent .. "%" }
            else
                steps[#steps + 1] = { step = "research " .. name,
                                      why = ("$%d, about %d game hours, done by the %s"):format(item[3],
                                            RESEARCH_HOURS[name] or 6, tostring(head)),
                                      after = blocked and "the research above finishes" or nil }
            end
            blocked = true
        end
    end
    local final = UNLOCK_FINAL[key]
    if final then steps[#steps + 1] = { step = final, after = blocked and "the research is done" or nil } end
    local heads = {}
    for h in pairs(heads_needed) do heads[#heads + 1] = h end
    table.sort(heads)
    return { target = target, research = chain, done = not blocked, steps = steps, heads = heads,
             note = "Every department head (" .. table.concat(heads, ", ") .. ") needs their OWN Office " ..
                    "(room office) or they cannot research. Research is paid when it starts." }
end
doc("unlock", "target", "What it takes to unlock a staff type, room or research: the steps still to do, in order.",
    "api.unlock(\"laundry\")")

-- ---- hiring ------------------------------------------------------------------------
-- price from the game's materials.txt; research needed before the game lets you hire them
local STAFF = {
    Workman = { 500 }, Guard = { 500 }, Cook = { 500 }, Warden = { 1000, nil, true },
    Doctor = { 1000, "Health" }, Foreman = { 1000, "Maintainance", true }, Chief = { 1000, "Security", true },
    Accountant = { 1000, "Finance", true }, Psychologist = { 1000, "MentalHealth", true },
    Lawyer = { 5000, "Legal", true }, Janitor = { 500, "Cleaning" }, Gardener = { 500, "GroundsKeeping" },
    DogHandler = { 500, "Dogs" }, ArmedGuard = { 1500, "Armoury" }, Sniper = { 2000, "GuardTowers" },
}

local function arrival_point()
    local w, h = map_size()
    local xs = {}
    for x = 0, w - 1 do
        local m = Object.GetMaterial(x, 0) or ""
        if string.sub(m, 1, 4) == "Road" then xs[#xs + 1] = x end
    end
    if #xs == 0 then return math.floor(w / 2) + 0.5, 1.5 end
    return xs[math.floor((#xs + 1) / 2)] + 0.5, 1.5
end

function api.hire(kind, count)
    count = num(count or 1, "count")
    if count < 1 or count > 20 then error("count must be 1..20", 0) end
    local key
    for k in pairs(STAFF) do if string.lower(k) == string.lower(tostring(kind)) then key = k end end
    if not key then
        local names = {}
        for k in pairs(STAFF) do names[#names + 1] = k end
        table.sort(names)
        error("unknown staff type '" .. tostring(kind) .. "'. Choose one of: " .. table.concat(names, ", "), 0)
    end
    local s = STAFF[key]
    if s[2] then
        if not NATIVE then error(key .. " needs " .. s[2] .. " research, and research cannot be checked without bridge DLL 0.3", 0) end
        local st = research_state()
        if not researched(st, s[2]) then
            error(key .. " needs the " .. s[2] .. " research first: api.research(\"" .. s[2] .. "\")", 0)
        end
    end
    if s[3] then
        local have = api.count(key)[key]
        if have + count > 1 then error("you can only have one " .. key .. " (you have " .. have .. ")", 0) end
    end
    local cost = s[1] * count
    local bal = tonumber(world_get("Balance")) or 0
    if bal < cost then error("hiring " .. count .. " " .. key .. " costs $" .. cost .. " but you have $" .. math.floor(bal), 0) end
    local x, y = arrival_point()
    local made = 0
    for i = 1, count do
        if Object.Spawn(key, x + (i - 1) % 3, y + math.floor((i - 1) / 3)) then made = made + 1 end
    end
    -- charge through the game's finance ledger (shows in the finance report; measured live: a negative
    -- amount is an expense); without DLL 0.4 fall back to adjusting the balance directly
    local charged = false
    if NATIVE and made > 0 then
        charged = pcall(native, "spend:" .. tostring(-s[1] * made) .. " staff_hire_" .. key)
    end
    if not charged then World.Balance = bal - s[1] * made end
    return { hired = made, type = key, cost = s[1] * made, money_left = math.floor(bal - s[1] * made),
             arrives_at = { x = math.floor(x), y = math.floor(y) },
             note = "They walk in from the road. Staff are paid daily wages by the game." }
end
doc("hire", "type, [count]", "Hire staff (Guard, Cook, Workman, Warden; Doctor/Janitor/etc. after research). Costs the game's hire price.",
    "api.hire(\"Guard\", 2)")


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
        native = NATIVE,
        not_available = NATIVE and { "grants (accept them in the game)" } or
            { "zoning, saving, pause/resume, research, intake, regime, camera need the bridge DLL", "grants" },
        materials = { walls = "BrickWall, ConcreteWall, Fence, PerimeterWall",
                      floors = "ConcreteFloor, WoodenFloor, CeramicFloor, PavingStone",
                      not_materials = "Building, Demolish, CancelJobs... are UI tools and get built as junk" },
        objects = "Bed, Toilet, JailDoor, Door, StaffDoor, Cooker, Fridge, Sink, Table, Bench, ServingTable, " ..
                  "ShowerHead, Drain, WeightsBench, PhoneBooth, Tv, OfficeDesk, Chair, FilingCabinet, Light",
        workflow = { "api.state()", "api.overview()", "api.find_space(w, h)",
                     "api.room(kind, x1, y1, x2, y2) (walls+floor+door+furniture+zone)",
                     "api.progress() until finished (the game must not be paused)", "api.hire(type, count)",
                     "api.research(name) once you have a Warden and an Office", "api.save(name)" },
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

-- Drains waiting requests. Update() calls it every tick; DLL 0.3 also calls it
-- from the render loop while the game is paused.
local function pump()
    for _ = 1, MAX_REQUESTS_PER_TICK do
        local line = DebugOut("\1poll")
        if type(line) ~= "string" then break end
        handle(line)
    end
end

-- Say hello to the DLL and hand it our pump (it runs the pump while the game is paused). Also called
-- by `pa-agent reload-mod` so reloaded code answers at once, paused or not.
local function hello()
    local r = DebugOut("\1hello:" .. VERSION, pump)
    bridged = (type(r) == "string")
    NATIVE = bridged and string.find(r, " native", 1, true) ~= nil
    return r
end

function Update(timePassed)
    if bridged == nil then hello() end
    if not bridged then return end
    pump()
end

-- exposed for tests
PA_BRIDGE = { json = json, api = api, handle = handle, VERSION = VERSION, pump = pump, hello = hello }
