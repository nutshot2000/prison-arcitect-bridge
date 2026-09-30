-- Offline tests for world.lua with a fake DLL + fake game API.
-- Run with Lua 5.1 or Luau:  luau test_world.lua   (WORLD_SRC must hold world.lua's source)
local inbox, outbox, calls = {}, {}, {}
local W, H = 100, 80
Game = {
    DebugOut = function(s)
        if string.sub(s, 1, 1) ~= "\1" then return end
        s = string.sub(s, 2)
        if s == "poll" then return table.remove(inbox, 1) end
        if string.sub(s, 1, 6) == "hello:" then return "pa_bridge test" end
        if string.sub(s, 1, 6) == "reply:" then outbox[#outbox + 1] = string.sub(s, 7) end
    end,
    Time = function() return 123.5 end,
    GetGameSpeed = function() return 1 end,
    SetZoneRoom = function() error("must never be called") end,
    SaveMap = function() error("must never be called") end,
    CamMove = function() error("must never be called") end,
}
WorkQueue = { Request = function(...) calls[#calls + 1] = { ... } end }
local built = {}   -- "x,y" -> material, simulates finished construction
local world_objects = { { Type = "Workman", Pos = { x = 5, y = 5 } }, { Type = "Workman", Pos = { x = 6, y = 5 } },
                        { Type = "Bed", Pos = { x = 31, y = 41 } } }
local spawned, deleted = 0, 0
Object = {
    GetMaterial = function(x, y)
        if built[x .. "," .. y] then return built[x .. "," .. y] end
        if x >= 90 and x <= 95 then return "Road" end
        if x >= 10 and x <= 19 and y >= 10 and y <= 19 then return "BrickWall" end
        return "Dirt"
    end,
    Spawn = function(t, x, y) spawned = spawned + 1; local o = { Type = t, Pos = { x = x, y = y } }; world_objects[#world_objects + 1] = o; return o end,
    Delete = function(o) for i, v in ipairs(world_objects) do if v == o then table.remove(world_objects, i); deleted = deleted + 1 end end end,
    GetNearbyObjects = function(anchor, t, r)
        local out = {}
        for _, o in ipairs(world_objects) do if o.Type == t then out[o] = 1 end end
        return out
    end,
}
World = {
    GetCell = function(x, y) if x >= 0 and y >= 0 and x < W and y < H then return { CellX = x, CellY = y } end return {} end,
    NumPrisoners = { Normal = 3, MinSec = 2 },
    Capacity = { Normal = 4 },
    Balance = 10000,
    TimeIndex = 1440 + 8 * 60 + 5,
}
this = { Name = "world" }

local src = WORLD_SRC or assert(io.open(arg and arg[1] or "ai_bridge/data/world.lua")):read("*a")
assert(loadstring(src, "world.lua"))()
local J = PA_BRIDGE.json
local api = PA_BRIDGE.api

local function roundtrip(req)
    inbox[#inbox + 1] = req
    Update(0.1)
    local r = table.remove(outbox, 1)
    assert(r, "no reply for " .. req)
    return J.decode(r), r
end
local function call(fn, ...)
    local args = { ... }
    local r = roundtrip(J.encode({ id = 1, op = "call", fn = fn, args = args, nargs = select("#", ...) }))
    return r
end

-- JSON
local t = J.decode('{"a":[1,2,{"b":"x\\n\\u00e9"}],"c":true,"d":null,"e":-1.5e2}')
assert(t.a[2] == 2 and t.a[3].b == "x\n\195\169" and t.c == true and t.d == nil and t.e == -150)
assert(J.encode({ 1, 2, 3 }) == "[1,2,3]")
local cyc = {}; cyc.self = cyc
assert(J.encode(cyc) == '{"self":"<cycle>"}')

-- exec basics
local r2
local r = roundtrip('{"id":1,"op":"ping"}'); assert(r.ok and r.result.pong)
r = roundtrip('{"id":2,"op":"exec","code":"return 6*7"}'); assert(r.result == 42)
roundtrip('{"id":3,"op":"exec","code":"mem.x = 5"}')
r = roundtrip('{"id":4,"op":"exec","code":"return mem.x + 1"}'); assert(r.result == 6)
r = roundtrip('{"id":5,"op":"exec","code":"return +"}'); assert(not r.ok and string.find(r.error, "compile error"))
r = roundtrip('not json'); assert(not r.ok)

-- the safe Game table
r = roundtrip('{"id":6,"op":"exec","code":"return Game.Time()"}'); assert(r.ok and r.result == 123.5)
r = roundtrip('{"id":7,"op":"exec","code":"return Game.SaveMap(\\"x\\")"}')
assert(not r.ok and string.find(r.error, "verified%-safe"), "SaveMap must be blocked: " .. tostring(r.error))
r = roundtrip('{"id":8,"op":"exec","code":"return Game.SetZoneRoom(\\"Cell\\",1,1,2,2)"}')
assert(not r.ok and string.find(r.error, "verified%-safe"), "SetZoneRoom must be blocked")

-- state / map / help
r = call("state"); assert(r.ok and r.result.map.w == 100 and r.result.map.h == 80 and r.result.prisoners_total == 5)
r = call("map", 8, 10, 12, 11)
assert(r.ok and r.result.rows[1] == ".." .. "###" and r.result.x_ruler == "89012", J.encode(r))
r = call("map"); assert(r.ok and #r.result.rows == 80 and #r.result.rows[1] == 100)
assert(string.sub(r.result.rows[1], 91, 91) == "=")
r = call("help"); assert(r.ok and #r.result.functions >= 10)

-- validation messages
r = call("build_area", "ConcreteFloor", 95, 70, 120, 75)
assert(not r.ok and string.find(r.error, "outside the map"), r.error)
r = call("build_line", "BrickWall", 0, 0, 3, 3); assert(not r.ok and string.find(r.error, "horizontal"))
r = call("build_area", "concretefloor", 1, 1, 1, 1); assert(r.ok and r.result.material == "ConcreteFloor")
r = call("furnish", "spaceship", 1, 1, 5, 5); assert(not r.ok and string.find(r.error, "kitchen"))
r = call("zone", "Cell", 1, 1, 3, 3); assert(not r.ok and string.find(r.error, "DLL 0.3"), r.error)
r = call("camera", 1, 1, 3, 3); assert(not r.ok)

-- construction helpers
calls = {}
r = call("build_wall_rect", "BrickWall", 0, 0, 3, 2); assert(r.result.queued == 10)
calls = {}
r = call("building", 30, 30, 36, 35, "east")
assert(r.ok and r.result.door.x == 36 and r.result.inside.x1 == 31, J.encode(r))
local doors = 0
for _, c in ipairs(calls) do if c[1] == "PlaceObject" and c[2] == "Door" then doors = doors + 1 end end
assert(doors == 1)
calls = {}
r = call("furnish", "kitchen", 31, 31, 39, 36); assert(r.ok and r.result.queued >= 4, J.encode(r))
for _, c in ipairs(calls) do
    -- against the bottom wall: must face up (0,-1) or the working spot is in the wall (live bug)
    if c[2] == "Sink" or (c[2] == "Fridge" and c[4] == 36) then assert(c[6] == -1, c[2] .. " must face up") end
    if c[2] == "Cooker" then assert(c[6] == 1, "cookers on the top wall face down") end
end
calls = {}
r = call("cell_block", 30, 40, 3); assert(r.ok and #r.result.cells == 3, J.encode(r))
local beds, jd = 0, 0
for _, c in ipairs(calls) do
    if c[2] == "Bed" then beds = beds + 1 end
    if c[2] == "JailDoor" then jd = jd + 1 end
end
assert(beds == 3 and jd == 3)
-- the dividing walls must be the LAST order for their cells (a later floor order replaced them live)
local last = {}
for _, c in ipairs(calls) do if c[1] == "Construction" then last[c[3] .. "," .. c[4]] = c[2] end end
for y = 41, 43 do assert(last["34," .. y] == "BrickWall" and last["38," .. y] == "BrickWall", "divider wall lost at y " .. y) end
-- door cells must end up as floor, never wall (live: walls were built over finished doors)
for _, c in ipairs(r.result.cells) do
    assert(last[c.door.x .. "," .. c.door.y] == "ConcreteFloor", "wall ordered on cell door " .. c.door.x .. "," .. c.door.y)
end
calls = {}
r = call("building", 60, 60, 66, 66, "east")
last = {}
for _, c in ipairs(calls) do if c[1] == "Construction" then last[c[3] .. "," .. c[4]] = c[2] end end
assert(last["66,63"] == "ConcreteFloor", "wall ordered on building door: " .. tostring(last["66,63"]))
-- furniture must fit inside the room: an object ordered at x covers x..x+w-1 (measured live)
calls = {}
r = call("furnish", "canteen", 57, 39, 66, 46); assert(r.ok, r.error)
for _, c in ipairs(calls) do
    local w = ({ Table = 4, Bench = 4, ServingTable = 5 })[c[2]]
    if w then assert(c[3] >= 57 and c[3] + w - 1 <= 66, c[2] .. " at " .. c[3] .. " sticks out of 57..66") end
end

-- find_space avoids walls and road
r = call("find_space", 8, 6); assert(r.ok, r.error)
local s = r.result
assert(not (s.x1 <= 19 and s.x2 >= 10 and s.y1 <= 19 and s.y2 >= 10), "overlaps wall block")
assert(s.x2 < 90)
r = call("find_space", 8, 6, 60, 40); assert(r.ok and math.abs((r.result.x1 + 4) - 60) <= 1, J.encode(r))
-- a power station on plain dirt must block the space around it
world_objects[#world_objects + 1] = { Type = "PowerStation", Pos = { x = 61.5, y = 41.5 } }
r = call("find_space", 8, 6, 60, 40); assert(r.ok, r.error)
assert(r.result.x2 < 60 or r.result.x1 > 62 or r.result.y2 < 40 or r.result.y1 > 42, "space overlaps the station: " .. J.encode(r))
table.remove(world_objects)

-- objects / staff / count (temporary anchor must be cleaned up)
r = call("objects", "Workman"); assert(r.ok and r.result.count == 2, J.encode(r))
assert(spawned == deleted, "anchor leaked")
r = call("staff"); assert(r.ok and r.result.total == 2 and r.result.by_type.Workman == 2)
r = call("count", { "Bed", "Toilet" }); assert(r.ok and r.result.Bed == 1 and r.result.Toilet == 0)
r = call("objects"); assert(not r.ok and string.find(r.error, "type required"))

-- planned work: map overlay, progress, find_space avoidance
calls = {}
r = call("build_area", "ConcreteFloor", 40, 60, 41, 60)
r = call("map", 40, 60, 42, 60); assert(r.result.rows[1] == "++.", J.encode(r))
built["40,60"] = "ConcreteFloor"
r = call("map", 40, 60, 42, 60); assert(r.result.rows[1] == "_+.", J.encode(r))
r = call("progress"); assert(r.ok and r.result.construction.finished_since_last_check >= 1, J.encode(r))
local found41 = false
for _, v in ipairs(r.result.construction.pending_sample) do if v == "ConcreteFloor@41,60" then found41 = true end end
r2 = call("progress"); assert(r2.result.construction.finished_since_last_check == 0, "finished work is only reported once")
r = call("build_area", "ConcreteFloor", 0, 20, 89, 79)  -- plan almost everything free
r = call("find_space", 5, 5); assert(r.ok, r.error)
assert(r.result.y2 < 19, "find_space must avoid planned cells: " .. J.encode(r))

-- several requests in one tick
inbox = { '{"id":20,"op":"ping"}', '{"id":21,"op":"ping"}', '{"id":22,"op":"ping"}' }
outbox = {}
Update(0.1)
assert(#outbox == 3); outbox = {}

-- power and water
r = call("hookup", "power"); assert(not r.ok and string.find(r.error, "PowerStation"), r.error)
r = call("place_object", "Capacitor", 50, 5)
r = call("hookup", "power"); assert(not r.ok and string.find(r.error, "PowerStation"), "a capacitor is not a power source")
world_objects[#world_objects + 1] = { Type = "Light", Pos = { x = 88.5, y = 70.5 } }  -- outdoors (no Ind)
calls = {}
r = call("place_object", "PowerStation", 60, 5)
r = call("place_object", "Cooker", 70, 5)
r = call("hookup", "power"); assert(r.ok and r.result.newly_connected >= 1, J.encode(r))
local cab = {}
for _, c in ipairs(calls) do if c[2] == "ElectricalCable" then cab[c[3] .. "," .. c[4]] = true end end
for x = 63, 70 do assert(cab[x .. ",5"], "cable from the cooker at 70,5 to the station edge at 62,5 missing " .. x) end
assert(not cab["62,5"], "no cable on the station itself")
assert(not cab["88,70"], "outdoor street light must not be cabled")
assert(cab["50,5"], "the capacitor is connected like any other user")
r = call("hookup", "power"); assert(r.result.pieces_ordered == 0, "second hookup must not re-lay")
-- cells that already have cable (read from a save) are reused: a cooker next to them needs 1 piece
r = call("place_object", "Cooker", 75, 20)
r = call("hookup", "power", { "71,20", "72,20", "73,20", "74,20", "70,20", "70,19", "70,18" })
assert(r.ok and r.result.pieces_ordered <= 2, "existing cable must be reused: " .. J.encode(r))
calls = {}
r = call("place_object", "WaterPumpStation", 60, 20)
r = call("place_object", "Toilet", 60, 30)
r = call("hookup", "water"); assert(r.ok and r.result.newly_connected >= 1, J.encode(r))
local pipes = {}
for _, c in ipairs(calls) do if c[2] == "PipeLarge" or c[2] == "PipeSmall" then pipes[c[3] .. "," .. c[4]] = c[2] end end
assert(pipes["60,30"] == "PipeSmall", "small pipe goes under the toilet: " .. tostring(pipes["60,30"]) .. " " .. J.encode(r))
for y = 23, 29 do assert(pipes["60," .. y] == "PipeLarge", "large pipe from the pump edge to the toilet missing at y " .. y) end
r = call("progress"); assert(r.ok and not r.result.objects.PipeLarge, "utilities are not counted as furniture")

-- perimeter: road crossing becomes a RoadGate (fake map: road at x >= 90)
calls = {}
r = call("perimeter", 80, 2, 97, 70)
assert(r.ok and #r.result.road_gates == 2 and string.find(r.result.road_gates[1], "90,2"), J.encode(r))
for _, c in ipairs(calls) do
    if c[1] == "Construction" then assert(c[3] < 90 or c[3] > 96, "fence inside the 7-wide gate at " .. c[3]); assert(c[2] == "Fence", "only fence is ordered, got " .. c[2]) end
end
r = call("perimeter", 80, 2, 95, 70); assert(not r.ok and string.find(r.error, "along the road"), r.error)
-- an existing gate is reused, not ordered again
world_objects[#world_objects + 1] = { Type = "RoadGate", Pos = { x = 93.5, y = 2.5 } }
calls = {}
r = call("perimeter", 80, 2, 97, 70); assert(r.ok and string.find(r.result.road_gates[1], "already there"), J.encode(r))
local newgates = 0
for _, c in ipairs(calls) do if c[2] == "RoadGate" then newgates = newgates + 1 end end
assert(newgates == 1, "only the bottom crossing needs a new gate, got " .. newgates)
table.remove(world_objects)

r = call("build_area", "Building", 1, 1, 2, 2); assert(not r.ok and string.find(r.error, "UI tool"), r.error)
r = call("build_area", "cancelJobs", 1, 1, 2, 2); assert(not r.ok)

-- hiring without DLL 0.3
r = call("hire", "Guard", 1); assert(r.ok and r.result.hired == 1 and World.Balance == 9500, J.encode(r))
r = call("hire", "Doctor", 1); assert(not r.ok and string.find(r.error, "Health"), r.error)

-- state with money and clock
r = call("state"); assert(r.ok and r.result.money == 9500 and r.result.clock == "day 2 08:05" and not r.result.native, J.encode(r))
r = call("overview"); assert(r.ok and #r.result.rows == 27 and #r.result.rows[1] == 34, J.encode(r.result.rows))

---------------------------------------------------------------------------
-- DLL 0.3 (native actions): reload the script with a fake native DLL
---------------------------------------------------------------------------
local zoned, speed, saves, started = {}, 1, {}, {}
local research = { Warden = 100, Health = 0, Maintainance = 0 }
World.GetCell = function(x, y)
    if x >= 0 and y >= 0 and x < W and y < H then
        return { CellX = x, CellY = y, Room = { i = zoned[x .. "," .. y] and 7 or -1 } }
    end
    return {}
end
local pump_fn
intake_state = "4 0 0"
regime = {}
for h = 0, 23 do regime[h] = 0 end
cam = { 50, 40, 0.05 }
removed = {}
Game.DebugOut = function(s, fn)
    if string.sub(s, 1, 1) ~= "\1" then return end
    s = string.sub(s, 2)
    if s == "poll" then return table.remove(inbox, 1) end
    if string.sub(s, 1, 6) == "hello:" then pump_fn = fn; return "pa_bridge 0.3.0 native" end
    if string.sub(s, 1, 6) == "reply:" then outbox[#outbox + 1] = string.sub(s, 7); return end
    if s == "roomtypes" then return "None,Cell,HoldingCell,Kitchen,Canteen,Shower,Yard,Office,MedicalWard,Deliveries,Garbage,Chapel,CommonRoom,ParoleRoom,Laundry,Classroom,Workshop,Library,CleaningCupboard,Visitation" end
    local t, a, b, c, d = string.match(s, "^zone:(%S+) (%-?%d+) (%-?%d+) (%-?%d+) (%-?%d+)$")
    if t then
        for x = tonumber(a), tonumber(c) do for y = tonumber(b), tonumber(d) do zoned[x .. "," .. y] = t ~= "None" or nil end end
        return "ok 1"
    end
    if s == "speed" then return speed end
    local sp = string.match(s, "^setspeed:(.+)$"); if sp then speed = tonumber(sp); return "ok" end
    local sv = string.match(s, "^save:(.+)$"); if sv then saves[#saves + 1] = sv; return "queued" end
    if s == "saveresult" then return "ok C:/saves/" .. tostring(saves[#saves]) .. ".prison" end
    if s == "researchlist" then
        local parts = {}
        for k, v in pairs(research) do parts[#parts + 1] = k .. ":" .. (started[k] and 1 or 0) .. ":" .. v end
        return table.concat(parts, ",")
    end
    local rs = string.match(s, "^research:(.+)$"); if rs then started[rs] = true; return "ok" end
    local rc = string.match(s, "^regime:(%d+)$")
    if rc then
        local names = { [0] = "Nothing", "Sleep", "Eat", "Shower", "Yard", "Work", "WorkLockdown", "Lockdown",
                        "FreeTime", "EatLockdown", "ShowerLockdown", "Unspecified" }
        local out = {}
        for h = 0, 23 do out[#out + 1] = names[regime[h]] end
        return table.concat(out, ",")
    end
    local c, h, a = string.match(s, "^setregime:(%d+) (%d+) (%d+)$")
    if c then regime[tonumber(h)] = tonumber(a); return "ok" end
    local cx, cy, cz = string.match(s, "^camera:(%S+) (%S+) ?(%S*)$")
    if cx then cam = { tonumber(cx), tonumber(cy), tonumber(cz) or cam[3] } end
    if cx or s == "camera" then return string.format("%.3f %.3f %.3f", cam[1], cam[2], cam[3]) end
    local ux, uy = string.match(s, "^rm%a+:(%d+) (%d+)$")
    if ux then removed[#removed + 1] = s; return "ok" end
    if s == "intake" then return intake_state end
    local it, n = string.match(s, "^intake:(%d) ?(%d*)$")
    if it then intake_state = it .. " 0 " .. (n ~= "" and n or "0"); return intake_state end
    return "error: unknown native " .. s
end
assert(loadstring(src, "world.lua"))()
api = PA_BRIDGE.api
inbox, outbox = {}, {}
Update(0.1)
assert(type(pump_fn) == "function", "hello must hand the pump to the DLL")
inbox = { '{"id":30,"op":"ping"}' }
pump_fn()   -- the DLL calls this while paused
assert(#outbox == 1 and J.decode(outbox[1]).id == 30); outbox = {}

r = call("state"); assert(r.ok and r.result.native == true and r.result.paused == false, J.encode(r))
r = call("zone", "kitchen", 2, 2, 4, 3); assert(r.ok and r.result.zoned == "Kitchen" and r.result.cells_in_a_room_now == 6, J.encode(r))
r = call("zone", "Spaceship", 2, 2, 4, 3); assert(not r.ok and string.find(r.error, "room_types"), r.error)
r = call("zone", "infirmary", 2, 2, 4, 3); assert(r.ok and r.result.zoned == "MedicalWard", J.encode(r))
r = call("zones"); assert(r.ok and #r.result == 1 and string.find(r.result[1], "MedicalWard"), J.encode(r))
r = call("unzone", 2, 2, 4, 3); assert(r.ok and r.result.cells_in_a_room_now == 0)
r = call("zones"); assert(#r.result == 0, J.encode(r))
calls = {}
r = call("room", "kitchen", 40, 5, 50, 12); assert(r.ok and r.result.zoned and r.result.inside.x1 == 41, J.encode(r))
assert(zoned["41,6"] and not zoned["40,5"], "room must zone the inside only")
r = call("room", "deliveries", 60, 1, 65, 4); assert(r.ok and r.result.built == "outdoor area (no walls)", J.encode(r))
r = call("cell_block", 30, 50, 2); assert(r.ok and r.result.zoned and zoned["31,51"], J.encode(r))
r = call("intake"); assert(r.ok and r.result.mode == "all" and r.result.advice, J.encode(r))
r = call("intake", "beds"); assert(r.ok and r.result.mode == "beds" and intake_state == "1 0 0", J.encode(r))
r = call("intake", "perday", 3); assert(r.ok and r.result.per_day == 3, J.encode(r))
r = call("intake", "perday"); assert(not r.ok and string.find(r.error, "number"), r.error)
r = call("intake", "lots"); assert(not r.ok)
r = call("state"); assert(r.result.intake == "perday", J.encode(r.result))
calls = {}
r = call("solitary_block", 10, 60, 3); assert(r.ok and #r.result.cells == 3 and zoned["11,61"], J.encode(r))
local sd = 0
for _, c in ipairs(calls) do if c[2] == "SolitaryDoor" then sd = sd + 1; assert(c[4] == 62, "solitary door on the wall row") end end
assert(sd == 3, "one SolitaryDoor per solitary cell")
calls = {}
r = call("furnish", "staffroom", 10, 20, 15, 25); assert(r.ok, r.error)
local drink = false
for _, c in ipairs(calls) do if c[2] == "DrinkMachine" then drink = true end end
assert(drink, "a staff room needs a DrinkMachine (game requirement)")
r = call("furnish", "staffroom", 10, 20, 12, 22); assert(not r.ok and string.find(r.error, "4x4"), r.error)
r = call("room", "visitation", 20, 20, 30, 28); assert(r.ok and r.result.room == "Visitation" and #r.result.furniture >= 2, J.encode(r))
-- regime, camera, removal (DLL 0.4)
r = call("regime"); assert(r.ok and r.result.totals.Lockup == 24 and r.result.hours[1] == "00 Lockup", J.encode(r))
r = call("set_regime", 13, 16, "free time"); assert(r.ok and r.result.totals.FreeTime == 4 and regime[13] == 8, J.encode(r))
r = call("set_regime", 5, 3, "Eat"); assert(not r.ok, "from > to must fail")
r = call("set_regime", 1, 1, "Party"); assert(not r.ok and string.find(r.error, "unknown activity"), r.error)
r = call("regime_preset", "balanced"); assert(r.ok and r.result.totals.Sleep == 9 and r.result.totals.Eat == 3, J.encode(r))
r = call("camera"); assert(r.ok and r.result.x == 50, J.encode(r))
r = call("look_at", 10, 10, 29, 19); assert(r.ok and r.result.x == 20 and r.result.y == 15, J.encode(r))
r = call("remove_cable", 5, 5, 6, 5); assert(r.ok and r.result.removed_cells == 2 and removed[1] == "rmcable:5 5", J.encode(r))
r = call("remove_pipe", 7, 7, 7, 7); assert(r.ok and removed[3] == "rmpipe:7 7", J.encode(removed))
r = call("pause"); assert(r.ok and speed == 0)
r = call("state"); assert(r.result.paused == true)
r = call("resume", 2); assert(r.ok and speed == 2)
r = call("save", "test_1"); assert(r.ok and saves[1] == "test_1")
r = call("save_result"); assert(r.ok and r.result.ok and string.find(r.result.path, "test_1"), J.encode(r))
r = call("hire", "Doctor"); assert(not r.ok and string.find(r.error, "research"), r.error)
r = call("research", "Health"); assert(not r.ok and string.find(r.error, "Warden"), r.error)  -- no Warden hired yet
r = call("hire", "Warden"); assert(r.ok and r.result.hired == 1, J.encode(r))
r = call("hire", "Warden"); assert(not r.ok and string.find(r.error, "only have one"), r.error)
r = call("research", "Health"); assert(r.ok and r.result.status == "started" and started.Health, J.encode(r))
r = call("research", "Cleaning"); assert(not r.ok and string.find(r.error, "Maintainance"), r.error)
r = call("research"); assert(r.ok and #r.result.research > 20, J.encode(r))
research.Health = 100
r = call("hire", "doctor", 2); assert(r.ok and r.result.hired == 2 and r.result.type == "Doctor", J.encode(r))
-- unlock planner: laundry = Maintainance (Warden) -> hire Foreman -> PrisonLabour -> build
r = call("unlock", "laundry"); assert(r.ok, r.error)
local st = {}
for _, x in ipairs(r.result.steps) do st[#st + 1] = x.step end
local joined = table.concat(st, " | ")
assert(string.find(joined, "research Maintainance") and string.find(joined, "hire Foreman") and
       string.find(joined, "research PrisonLabour") and string.find(joined, "room laundry"), joined)
assert(joined:find("research Maintainance") < joined:find("hire Foreman") and
       joined:find("hire Foreman") < joined:find("research PrisonLabour"), joined)
assert(not r.result.done)
r = call("unlock", "Doctor"); assert(r.ok and r.result.done, J.encode(r))  -- Health is done
r = call("unlock", "nonsense"); assert(not r.ok and string.find(r.error, "api.unlock"), r.error)
-- rooms gated by research
r = call("room", "laundry", 70, 40, 76, 45); assert(not r.ok and string.find(r.error, "PrisonLabour"), r.error)
research.Maintainance = 100; research.PrisonLabour = 100
r = call("unlock", "laundry"); assert(r.ok and r.result.done, J.encode(r))
calls = {}
r = call("room", "laundry", 70, 40, 76, 45); assert(r.ok and r.result.room == "Laundry", J.encode(r))
local lm = 0
for _, c in ipairs(calls) do if c[2] == "LaundryMachine" then lm = lm + 1 end end
assert(lm >= 2, "laundry machines placed")
-- chapel: 6x6 inside minimum; altar sits inside the top wall
r = call("room", "chapel", 80, 40, 85, 45); assert(not r.ok and string.find(r.error, "6x6"), r.error)
calls = {}
r = call("room", "chapel", 80, 50, 89, 59); assert(r.ok and r.result.room == "Chapel", J.encode(r))
for _, c in ipairs(calls) do
    if c[1] == "PlaceObject" and c[2] == "Altar" then assert(c[4] == 52, "altar (h 2) anchored one below the top row") end
    if c[1] == "PlaceObject" and c[2] == "Pews" then assert(c[4] < 59 and c[3] + 3 <= 88, "pews inside") end
end
r = call("room", "commonroom", 70, 50, 79, 57); assert(r.ok and r.result.room == "CommonRoom", J.encode(r))
r = call("room", "parole", 70, 60, 76, 66); assert(r.ok and r.result.room == "ParoleRoom", J.encode(r))
r = call("room", "classroom", 80, 62, 88, 70); assert(not r.ok and string.find(r.error, "Education"), r.error)
World.Balance = 100
r = call("hire", "Guard", 1); assert(not r.ok and string.find(r.error, "costs"), r.error)
-- a room behind a closed fence ring is refused (workmen could never reach it)
for x = 55, 68 do built[x .. ",55"] = "Fence"; built[x .. ",68"] = "Fence" end
for y = 55, 68 do built["55," .. y] = "Fence"; built["68," .. y] = "Fence" end
World.Balance = 100000
r = call("room", "office", 58, 58, 63, 63); assert(not r.ok and string.find(r.error, "no workman can walk there"), J.encode(r))
r = call("room", "yard", 57, 57, 66, 66); assert(not r.ok and string.find(r.error, "remove fence"), J.encode(r))
built["55,60"] = "ConcreteTiles"  -- a gap in the fence
r = call("room", "office", 58, 58, 63, 63); assert(r.ok, J.encode(r))
World.Balance = 100
---------------------------------------------------------------------------
-- capacity-aware, island-aware, non-cross-wiring power hookup (fresh script, controlled world)
---------------------------------------------------------------------------
for i = #world_objects, 1, -1 do table.remove(world_objects, i) end
-- station A (10..12, 10..12) is full; station B (40..42, 10..12) has room
world_objects[#world_objects + 1] = { Type = "PowerStation", Pos = { x = 11.5, y = 11.5 }, Switch = true, Demand = 48, Capacity = 50 }
world_objects[#world_objects + 1] = { Type = "PowerStation", Pos = { x = 41.5, y = 11.5 }, Switch = true, Demand = 10, Capacity = 50 }
world_objects[#world_objects + 1] = { Type = "Cooker", Pos = { x = 15.5, y = 20.5 } }   -- nearer to A, A is full
world_objects[#world_objects + 1] = { Type = "Tv", Pos = { x = 25.5, y = 30.5 } }      -- on an island (no station)
assert(loadstring(src, "world.lua"))()
api = PA_BRIDGE.api
inbox, outbox = {}, {}
Update(0.1)
calls = {}
local known = { "25,30", "25,31", "25,32" }                      -- island under the TV
for x = 13, 20 do known[#known + 1] = x .. ",11" end          -- A's line east to x=20
r = call("hookup", "power", known)
assert(r.ok, r.error)
local cab = {}
for _, c in ipairs(calls) do if c[2] == "ElectricalCable" then cab[c[3] .. "," .. c[4]] = true end end
assert(r.result.newly_connected == 2, "cooker (to B) and island TV connected: " .. J.encode(r))
for k in pairs(cab) do
    local x, y = string.match(k, "(%d+),(%d+)")
    x, y = tonumber(x), tonumber(y)
    assert(not (y >= 10 and y <= 12 and x >= 9 and x <= 21), "route touches full grid A at " .. k)
end
-- with B full too, the cooker is reported instead of wired
world_objects[2].Demand = 50
calls = {}
assert(loadstring(src, "world.lua"))(); api = PA_BRIDGE.api; Update(0.1)
r = call("hookup", "power", known)
assert(r.ok and #r.result.not_connected >= 1 and string.find(r.result.note, "station power"), J.encode(r))
print("world.lua tests passed")
