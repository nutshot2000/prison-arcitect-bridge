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
        if x >= 90 then return "Road" end
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
r = call("zone", "Cell", 1, 1, 3, 3); assert(not r.ok and string.find(r.error, "Ask the human"))
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
calls = {}
r = call("cell_block", 30, 40, 3); assert(r.ok and #r.result.cells == 3, J.encode(r))
local beds, jd = 0, 0
for _, c in ipairs(calls) do
    if c[2] == "Bed" then beds = beds + 1 end
    if c[2] == "JailDoor" then jd = jd + 1 end
end
assert(beds == 3 and jd == 3)

-- find_space avoids walls and road
r = call("find_space", 8, 6); assert(r.ok, r.error)
local s = r.result
assert(not (s.x1 <= 19 and s.x2 >= 10 and s.y1 <= 19 and s.y2 >= 10), "overlaps wall block")
assert(s.x2 < 90)
r = call("find_space", 8, 6, 60, 40); assert(r.ok and math.abs((r.result.x1 + 4) - 60) <= 1, J.encode(r))

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
assert(#outbox == 3)
print("world.lua tests passed")
