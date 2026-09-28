-- AI bridge probe: object script
local R = {}
local function put(k, v) R[#R+1] = k .. "=" .. tostring(v) end
local function keys(t)
    if type(t) ~= "table" then return type(t) end
    local out = {}
    for k, _ in pairs(t) do out[#out+1] = tostring(k) end
    table.sort(out)
    return table.concat(out, ",")
end
local function try(label, f)
    local ok, res = pcall(f)
    put(label, (ok and "ok:" or "err:") .. tostring(res))
    return ok, res
end

local function RunProbe(tag, self)
    R = {}
    put("tag", tag)
    for _, n in ipairs({"io","os","debug","package","require","loadfile","dofile","loadstring","load",
                        "getfenv","setfenv","collectgarbage","newproxy","coroutine","string","math","table",
                        "Game","World","Object","WorkQueue","Interface","Objective","Trigger","Camera"}) do
        put("type." .. n, type(_G[n]))
    end
    put("dump", type(string.dump))
    put("keys.G", keys(_G))
    put("keys.Game", keys(Game))
    put("keys.World", keys(World))
    put("keys.Object", keys(Object))
    put("keys.WorkQueue", keys(WorkQueue))
    put("keys.Interface", keys(Interface))
    put("keys.Objective", keys(Objective))
    try("loadstring", function() return loadstring("return 6*7")() end)
    try("Game.Time", function() return Game.Time() end)
    try("Game.GetGameSpeed", function() return Game.GetGameSpeed() end)
    try("World.NumPrisoners", function() return keys(World.NumPrisoners()) end)
    try("World.Capacity", function() return keys(World.Capacity()) end)
    try("World.GetCell", function() return keys(World.GetCell(5, 5)) end)
    try("Object.GetMaterial", function() return Object.GetMaterial(5, 5) end)
    if self then
        try("self.keys", function() return keys(self) end)
        try("self.Pos", function() return tostring(self.Pos.x) .. "," .. tostring(self.Pos.y) end)
        try("nearby.Workman", function()
            local n = 0
            for _ in pairs(self.GetNearbyObjects("Workman", 200)) do n = n + 1 end
            return n
        end)
    end
    -- Real player-equivalent actions (cost money, done by workmen). Small and near the probe.
    local px, py = 20, 20
    if self and self.Pos then px, py = math.floor(self.Pos.x) + 3, math.floor(self.Pos.y) end
    try("WQ.Construction", function() WorkQueue.Request("Construction", "ConcreteWall", px, py); return px .. "," .. py end)
    try("WQ.PlaceObject", function() WorkQueue.Request("PlaceObject", "Bench", px + 2, py + 2); return "queued" end)

    local text = table.concat(R, "\n")
    pcall(function() Game.DebugOut("[AIBRIDGE " .. tag .. "]\n" .. text) end)
    return R
end

local done = false
function Create()
    this.AiProbeCreated = "yes"
end
function Update(timePassed)
    if done then return end
    done = true
    local r = RunProbe("object", this)
    for i, line in ipairs(r) do
        this["AiProbe" .. i] = line
    end
    this.AiProbeCount = #r
end
