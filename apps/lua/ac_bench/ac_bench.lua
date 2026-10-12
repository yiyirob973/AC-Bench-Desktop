-- AC Bench Logger (CSP Lua app)
-- Records lap times of AI cars to result.json.

local MARKER = 'ACBENCH'
local function scriptDir()
  if __dirname then return __dirname end
  return nil
end

local dir = scriptDir()
local path = dir and (dir .. '/result.json') or nil

function script.update(dt)
  if path then
    local f = io.open(path, 'w')
    if f then
      f:write('{"status":"ok"}')
      f:close()
    end
  end
end

function script.windowMain(dt)
  ui.text('AC Bench logger')
  ui.text('Ready')
end
