local LrApplicationView   = import 'LrApplicationView'
local LrTasks             = import 'LrTasks'

local Router = {}
Router.__index = Router

local function ensureDevelop()
  if LrApplicationView.getCurrentModuleName and LrApplicationView.getCurrentModuleName() ~= 'develop' then
    LrApplicationView.switchToModule('develop')
    LrTasks.sleep(0.05)
  end
end

function Router.new(t, BasicAdjust, ToneCurve, HSL, Tools)
  local self = setmetatable({}, Router)
  self.t = t
  self.BasicAdjust = BasicAdjust
  self.ToneCurve = ToneCurve
  self.HSL = HSL
  self.Tools = Tools
  return self
end

local function split(s, sep)
  local out = {}; for part in string.gmatch(s, "([^"..sep.."]+)") do table.insert(out, part) end; return out
end

local function toUpperTrim(s) return (s or ''):gsub('^%s+',''):gsub('%s+$',''):upper() end

function Router:handle(line)
  -- nil/非字符串防御
  line = tostring(line or '')
  if line == '' then return end
  if line == 'PING' or line == 'HEARTBEAT' then return end
  ensureDevelop()
  self.t('Router: handle '..line)

  local parts = split(line, ':')
  local head = toUpperTrim(parts[1] or '')

  if head == 'BASIC' and #parts >= 3 then
    local param = toUpperTrim(parts[2])
    local val = parts[3]
    return self.BasicAdjust.apply(param, val, self.t)

  elseif head == 'CURVE' and #parts >= 3 then
    local band = toUpperTrim(parts[2])
    local val = parts[3]
    return self.ToneCurve.apply(band, val, self.t)

  elseif head == 'HSL' and #parts >= 4 then
    local mode = toUpperTrim(parts[2])
    local color = toUpperTrim(parts[3])
    local val = parts[4]
    return self.HSL.apply(mode, color, val, self.t)

  elseif head == 'TOOL' and #parts >= 2 then
    local mode = parts[2]
    local val = parts[3]
    return self.Tools.apply(mode, val, self.t)
  end

  self.t('Router: unknown command '..line)
end

return Router