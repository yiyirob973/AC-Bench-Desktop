-- Class sync, part of the AC Bench Lua app.
-- Keeps the "#Pride-<class>" tag in every installed car's ui/ui_car.json up to date:
--   1. works out each car's physics hash (same SHA-256 recipe as ac_carid.py in the desktop app),
--   2. asks the server about those hashes only (POST /v1/cars/lookup, the answer stays in memory),
--   3. writes one class tag per car. An older "#Pride-..." tag is replaced and other tags are left alone. The first
--      original is kept as ui_car.json.gridbak, so the desktop app's Restore still works.
-- ac_bench.lua only calls update() outside benchmark races, and gate() below also skips online races and any time the
-- player is driving.
-- Settings are read from config.json next to this file (the desktop app writes it): server, include_provisional, auto.

local M = {}

local PREFIX_MIN = 3
local START_DELAY = 60          -- seconds after the race loads before the first check
local TICK = 0.5                -- the sync does a small step at most this often (seconds)
local RECHECK_HOURS = 6         -- don't check again within this time (Check now ignores it)
local CHEAP_STEPS = 10          -- cached or unchanged cars that may be skipped in one step
local BATCH = 500               -- hashes per lookup request, same as the desktop app
local MOVING_KMH = 2          -- the player's car has to be slower than this before any work happens

local dir
local cfg = { server = '', include_provisional = false, auto = true, prefix = '#Pride-' }
local state = { hashes = {}, table_version = nil, last_check = nil }   -- hashes[carId] = { sig = string, hash = hex }
local st = {
  phase = 'wait', note = 'starting', elapsed = 0, acc = 0,
  ids = {}, i = 0, hashOf = {}, batches = {}, b = 0, pending = false,
  labels = {}, todo = {}, t = 0,
  n = { cars = 0, hashed = 0, known = 0, tagged = 0, same = 0, skipped = 0, errors = 0 },
}

-- ---------------------------------------------------------------- helpers
local function log(s) ac.log('ac_bench/class_sync: ' .. tostring(s)) end

local function folderOf()
  if __dirname then return __dirname end
  local ok, d = pcall(function() return ac.getFolder(ac.FolderID.ScriptOrigin) end)
  if ok and d then return d end
  return nil
end

local function readFile(p)
  local ok, s = pcall(io.load, p, nil)
  if ok and type(s) == 'string' then return s end
  return nil
end

local function writeFile(p, s)
  local ok, res = pcall(io.save, p, s)
  return ok and res ~= false
end

local function isDir(p)
  local ok, r = pcall(io.dirExists, p)
  return ok and r == true
end

local function isFile(p)
  local ok, r = pcall(io.fileExists, p)
  return ok and r == true
end

local function listNames(p)
  local ok, r = pcall(io.scanDir, p, '*')
  if ok and type(r) == 'table' then return r end
  return {}
end

local function parses(s)
  local ok, v = pcall(JSON.parse, (s:gsub('^\239\187\191', '')))
  return ok and v ~= nil
end

local function lowerHex(s) return (s or ''):lower() end

local function sha256(s)
  return lowerHex(ac.checksumSHA256(s))
end

-- ---------------------------------------------------------------- car identity (mirrors ac_carid.car_hash)
-- Python sorts the data/ files by path parts, not by the joined string, so do the same here.
local function splitPath(s)
  local t = {}
  for part in s:gmatch('[^/]+') do t[#t + 1] = part end
  return t
end

local function pathLess(a, b)
  local x, y = splitPath(a), splitPath(b)
  for k = 1, math.min(#x, #y) do
    if x[k] ~= y[k] then return x[k] < y[k] end
  end
  return #x < #y
end

local function collect(base, rel, out)
  for _, name in ipairs(listNames(base .. '/' .. rel)) do
    local r = rel == '' and name or (rel .. '/' .. name)
    local full = base .. '/' .. r
    if isDir(full) then collect(base, r, out)
    elseif isFile(full) then out[#out + 1] = r end
  end
end

-- list of { rel = 'data.acd' | 'data/x' | 'collider.ini', path = full }, in the order the hash uses
local function physicsFiles(carDir)
  local parts = {}
  if isFile(carDir .. '/data.acd') then parts[#parts + 1] = { rel = 'data.acd', path = carDir .. '/data.acd' } end
  if isDir(carDir .. '/data') then
    local rels = {}
    collect(carDir .. '/data', '', rels)
    table.sort(rels, pathLess)
    for _, r in ipairs(rels) do parts[#parts + 1] = { rel = 'data/' .. r, path = carDir .. '/data/' .. r } end
  end
  if isFile(carDir .. '/collider.ini') then parts[#parts + 1] = { rel = 'collider.ini', path = carDir .. '/collider.ini' } end
  return parts
end

local hasAttr = nil
local function signature(parts)
  if hasAttr == nil then hasAttr = type(io.getAttributes) == 'function' end
  if not hasAttr then return 'n/a' end
  local sig = {}
  for _, p in ipairs(parts) do
    local ok, a = pcall(io.getAttributes, p.path)
    if not ok or type(a) ~= 'table' then return 'n/a' end
    sig[#sig + 1] = p.rel .. ':' .. tostring(a.size) .. ':' .. tostring(a.lastWriteTime)
  end
  return table.concat(sig, '|')
end

local function carHash(parts)
  if #parts == 0 then return nil end
  local buf = {}
  for _, p in ipairs(parts) do
    local data = readFile(p.path)
    if data == nil then return nil end
    buf[#buf + 1] = p.rel .. '\0' .. sha256(data) .. '\n'
  end
  return sha256(table.concat(buf))
end

-- ---------------------------------------------------------------- tag editing (works on the text, so the rest of the file stays as it was)
local function decodeString(token)
  local ok, v = pcall(JSON.parse, token)
  if ok and type(v) == 'string' then return v end
  return nil
end

local function encodeString(s)
  return '"' .. s:gsub('\\', '\\\\'):gsub('"', '\\"') .. '"'
end

-- Finds the tags array. Returns openIdx, closeIdx, { {raw=, val=}, ... }, or nil if there is no tags key, or false and a reason.
local function findTags(raw)
  local from = 1
  while true do
    local s, e = raw:find('"tags"%s*:%s*%[', from)
    if not s then return nil end
    if s == 1 or raw:sub(s - 1, s - 1) ~= '\\' then
      local open, k, items = e, e + 1, {}
      while true do
        local c = raw:sub(k, k)
        if c == '' then return false, 'tags array is not closed' end
        if c == ']' then return open, k, items end
        if c == '"' then
          local j = k + 1
          while true do
            local d = raw:sub(j, j)
            if d == '' then return false, 'unterminated string in tags' end
            if d == '\\' then j = j + 2
            elseif d == '"' then break
            else j = j + 1 end
          end
          local token = raw:sub(k, j)
          local val = decodeString(token)
          if val == nil then return false, 'unreadable tag string' end
          items[#items + 1] = { raw = token, val = val }
          k = j + 1
        elseif c:match('[%s,]') then k = k + 1
        else return false, 'tags is not a list of strings' end
      end
    end
    from = e + 1
  end
end

-- Returns the new file text, nil if nothing needs to change, or false and a reason.
local function withClassTag(raw, prefix, label)
  local bom = ''
  if raw:sub(1, 3) == '\239\187\191' then bom, raw = raw:sub(1, 3), raw:sub(4) end
  local nl = raw:find('\r\n', 1, true) and '\r\n' or '\n'
  local want = prefix .. label
  local lp = prefix:lower()

  local open, close, items = findTags(raw)
  if open == false then return false, close end

  if open == nil then   -- no tags key, add one before the final }
    local last = raw:match('.*()}')
    if not last then return false, 'no closing brace' end
    local before = raw:sub(1, last - 1):gsub('%s+$', '')
    local indent = raw:match('\n([ \t]+)"') or '    '
    local comma = before:sub(-1) == '{' and '' or ','
    return bom .. before .. comma .. nl .. indent .. '"tags": [' .. encodeString(want) .. ']' .. nl .. raw:sub(last)
  end

  local keptRaw, keptVal, seen, oldVal = {}, {}, {}, {}
  for _, it in ipairs(items) do
    oldVal[#oldVal + 1] = it.val
    if it.val:lower():sub(1, #lp) ~= lp then
      local key = it.val:match('^%s*(.-)%s*$'):lower()
      if not seen[key] then
        seen[key] = true
        keptRaw[#keptRaw + 1] = it.raw
        keptVal[#keptVal + 1] = it.val
      end
    end
  end
  local key = want:lower()
  if not seen[key] then
    keptRaw[#keptRaw + 1] = encodeString(want)
    keptVal[#keptVal + 1] = want
  end

  local same = (#oldVal == #keptVal)
  if same then
    for k = 1, #oldVal do if oldVal[k] ~= keptVal[k] then same = false break end end
  end
  if same then return nil end

  local inner = raw:sub(open + 1, close - 1)
  local text
  if inner:find('\n', 1, true) then
    local indent = inner:match('\n([ \t]*)"') or '        '
    local closeIndent = inner:match('\n([ \t]*)$') or ''
    text = nl .. indent .. table.concat(keptRaw, ',' .. nl .. indent) .. nl .. closeIndent
  else
    text = table.concat(keptRaw, ', ')
  end
  return bom .. raw:sub(1, open) .. text .. raw:sub(close)
end

local function applyTag(carId, label)
  local carsDir = M.carsDir
  local f = carsDir .. '/' .. carId .. '/ui/ui_car.json'
  local raw = readFile(f)
  if raw == nil then return 'skipped' end
  local wasValid = parses(raw)
  local new, why = withClassTag(raw, cfg.prefix, label)
  if new == nil then return 'same' end
  if new == false then log(carId .. ': left untouched (' .. tostring(why) .. ')') return 'skipped' end
  if wasValid then
    if not parses(new) then log(carId .. ': edit would break the JSON; left untouched') return 'skipped' end
  end
  local bak = f .. '.gridbak'
  if not isFile(bak) and not writeFile(bak, raw) then
    log(carId .. ': could not write backup; left untouched')
    return 'error'
  end
  if not writeFile(f, new) or readFile(f) ~= new then
    writeFile(f, raw)        -- put the original back
    log(carId .. ': write failed; original restored')
    return 'error'
  end
  return 'changed'
end

-- ---------------------------------------------------------------- state & config
local function loadConfig()
  local s = dir and readFile(dir .. '/config.json')
  if not s then return end
  local ok, c = pcall(JSON.parse, s)
  if not ok or type(c) ~= 'table' then return end
  if type(c.server) == 'string' then cfg.server = c.server:gsub('%s+', ''):gsub('/+$', '') end
  if c.include_provisional ~= nil then cfg.include_provisional = (c.include_provisional == true) end
  if c.auto ~= nil then cfg.auto = (c.auto == true) end
  if type(c.prefix) == 'string' and #c.prefix >= PREFIX_MIN then cfg.prefix = c.prefix end
end

local function loadState()
  local s = dir and readFile(dir .. '/class_sync_state.json')
  if not s then return end
  local ok, c = pcall(JSON.parse, s)
  if ok and type(c) == 'table' and type(c.hashes) == 'table' then
    state.hashes = c.hashes
    state.table_version = c.table_version
    state.last_check = tonumber(c.last_check)
  end
end

local function saveState()
  if not dir then return end
  local parts = {}
  for id, e in pairs(state.hashes) do
    if type(e) == 'table' and e.hash then
      parts[#parts + 1] = string.format('%s:{"sig":%s,"hash":"%s"}', encodeString(id), encodeString(e.sig or ''), e.hash)
    end
  end
  writeFile(dir .. '/class_sync_state.json', '{"table_version":' .. tostring(tonumber(state.table_version) or 'null') ..
    ',"last_check":' .. tostring(tonumber(state.last_check) or 'null') ..
    ',"hashes":{' .. table.concat(parts, ',') .. '}}')
end

-- ---------------------------------------------------------------- phases
local function setPhase(p, note)
  st.phase = p
  if note then st.note = note end
end

local function begin()
  st.ids, st.i, st.hashOf, st.batches, st.b, st.pending = {}, 0, {}, {}, 0, false
  st.labels, st.todo, st.t = {}, {}, 0
  st.n = { cars = 0, hashed = 0, known = 0, tagged = 0, same = 0, skipped = 0, errors = 0 }
  setPhase('scan', 'looking for installed cars')
end

local function doScan()
  local base
  local ok, d = pcall(function() return ac.getFolder(ac.FolderID.ContentCars) end)
  if ok and d then base = d end
  if not base then
    local ok2, root = pcall(function() return ac.getFolder(ac.FolderID.Root) end)
    if ok2 and root then base = root .. '/content/cars' end
  end
  if not base or not isDir(base) then setPhase('off', 'cars folder not found') return end
  M.carsDir = base
  for _, name in ipairs(listNames(base)) do
    if isFile(base .. '/' .. name .. '/ui/ui_car.json') then st.ids[#st.ids + 1] = name end
  end
  table.sort(st.ids)
  st.n.cars = #st.ids
  setPhase('hash', 'checking installed cars')
end

local function doHash()
  -- Cars with a valid cached hash are quick to skip. Hashing a car costs real time, so only one is done per step.
  for _ = 1, CHEAP_STEPS do
    st.i = st.i + 1
    local id = st.ids[st.i]
    if not id then
      saveState()
      local seen, list = {}, {}
      for _, h in pairs(st.hashOf) do
        if not seen[h] then seen[h] = true list[#list + 1] = h end
      end
      table.sort(list)
      for k = 1, #list, BATCH do
        local b = {}
        for j = k, math.min(k + BATCH - 1, #list) do b[#b + 1] = list[j] end
        st.batches[#st.batches + 1] = b
      end
      if #st.batches == 0 then setPhase('done', 'couldn\'t identify any car') return end
      setPhase('lookup', 'asking the server')
      return
    end
    local parts = physicsFiles(M.carsDir .. '/' .. id)
    if #parts > 0 then
      local sig = signature(parts)
      local cached = state.hashes[id]
      local h
      local fresh = false
      if type(cached) == 'table' and cached.hash and (cached.sig == sig or sig == 'n/a') then
        h = cached.hash
      else
        h = carHash(parts)
        if h then state.hashes[id] = { sig = sig, hash = h } st.n.hashed = st.n.hashed + 1 fresh = true end
      end
      if h then st.hashOf[id] = h end
      st.note = string.format('checking cars %d / %d', st.i, #st.ids)
      if fresh then return end
    end
  end
end

local function doLookup()
  if st.pending then return end
  st.b = st.b + 1
  local hashes = st.batches[st.b]
  if not hashes then
    -- all answers are in, build the work list
    for id, h in pairs(st.hashOf) do
      local label = st.labels[h]
      if label then st.todo[#st.todo + 1] = { id = id, label = label } end
    end
    table.sort(st.todo, function(a, b) return a.id < b.id end)
    st.n.known = #st.todo
    setPhase('apply', 'writing class tags')
    return
  end
  st.pending = true
  local body = JSON.stringify({ hashes = hashes })
  web.post(cfg.server .. '/v1/cars/lookup',
    { ['Content-Type'] = 'application/json', ['Accept'] = 'application/json', ['User-Agent'] = 'ac_bench-lua/1' },
    body,
    function(err, response)
      st.pending = false
      local okBody, data = false, nil
      if not err and response and tonumber(response.status) == 200 then
        okBody, data = pcall(JSON.parse, response.body)
      end
      if not okBody or type(data) ~= 'table' then
        setPhase('done', 'server unreachable or returned an error (' .. tostring(err or (response and response.status)) .. ')')
        st.n.errors = st.n.errors + 1
        return
      end
      for _, rec in ipairs(data.cars or {}) do
        local status = tostring(rec.status or ''):lower()
        local label = rec.class
        if type(label) == 'string' and label ~= '' and (status == 'verified' or (cfg.include_provisional and status == 'provisional')) then
          st.labels[rec.car_hash] = label
        end
      end
      if data.table_version then state.table_version = data.table_version end
    end)
end

local function doApply()
  -- Reading a car that's already right is cheap. Writing a tag isn't, so only one is written per step.
  for _ = 1, CHEAP_STEPS do
    st.t = st.t + 1
    local job = st.todo[st.t]
    if not job then
      state.last_check = os.time and os.time() or nil
      saveState()
      setPhase('done', string.format('done, %d tag(s) written, %d already right', st.n.tagged, st.n.same))
      log(st.note)
      return
    end
    local r = applyTag(job.id, job.label)
    if r == 'changed' then st.n.tagged = st.n.tagged + 1
    elseif r == 'same' then st.n.same = st.n.same + 1
    elseif r == 'error' then st.n.errors = st.n.errors + 1
    else st.n.skipped = st.n.skipped + 1 end
    st.note = string.format('writing tags %d / %d', st.t, #st.todo)
    if r == 'changed' then return end
  end
end

-- ---------------------------------------------------------------- public API
M._withClassTag = withClassTag      -- exposed for offline tests
M._carHash = function(d) return carHash(physicsFiles(d)) end
function M.init()
  dir = folderOf()
  loadConfig()
  loadState()
  if type(ac.checksumSHA256) ~= 'function' then
    setPhase('off', 'this CSP version has no ac.checksumSHA256, so cars can\'t be identified')
  elseif cfg.server == '' then
    setPhase('off', 'no server address, open the desktop app once so it can write config.json')
  elseif not cfg.auto then
    setPhase('off', 'automatic tagging is off (use Check now)')
  elseif os.time and state.last_check and math.abs(os.time() - state.last_check) < RECHECK_HOURS * 3600 then
    setPhase('done', 'checked recently, use Check now to run it again')
  end
end

-- Returns 'ok', 'online', 'unknown' or 'moving'.
local function gate()
  local sim = ac.getSim()
  if not sim then return 'unknown' end
  local online = sim.isOnlineRace
  if online == nil then online = sim.isOnline end
  if online == nil then return 'unknown' end
  if online then return 'online' end
  local car = ac.getCar(0)
  if not car or car.speedKmh == nil then return 'unknown' end
  if car.speedKmh >= MOVING_KMH then return 'moving' end
  return 'ok'
end

-- called every frame by ac_bench.lua, but only outside benchmark races
function M.update(dt)
  local p = st.phase
  if p == 'off' or p == 'done' then return end
  st.acc = st.acc + dt
  if st.acc < TICK then return end
  dt, st.acc = st.acc, 0
  local g = gate()
  if g == 'online' then setPhase('off', 'online race, class tagging doesn\'t run online') return end
  if g == 'unknown' then setPhase('off', 'can\'t tell if this is an offline race, so doing nothing') return end
  if g == 'moving' then
    if p ~= 'wait' then st.note = 'paused while driving, continues when you stop' end
    return
  end
  if p == 'wait' then
    st.elapsed = st.elapsed + dt
    st.note = string.format('first check in %ds', math.max(0, math.ceil(START_DELAY - st.elapsed)))
    if st.elapsed >= START_DELAY then begin() end
  elseif p == 'scan' then doScan()
  elseif p == 'hash' then doHash()
  elseif p == 'lookup' then doLookup()
  elseif p == 'apply' then doApply()
  end
end

function M.ui()
  ui.text('Class tags: ' .. st.note)
  if st.phase == 'done' or st.phase == 'apply' then
    ui.text(string.format('%d cars, %d known to the server, %d tagged, %d already right, %d problems',
      st.n.cars, st.n.known, st.n.tagged, st.n.same, st.n.errors))
  end
  if type(ac.checksumSHA256) == 'function' and cfg.server ~= '' then
    if (st.phase == 'done' or st.phase == 'off' or st.phase == 'wait') and ui.button('Check now') then
      loadConfig()
      begin()
    end
  end
end

return M
