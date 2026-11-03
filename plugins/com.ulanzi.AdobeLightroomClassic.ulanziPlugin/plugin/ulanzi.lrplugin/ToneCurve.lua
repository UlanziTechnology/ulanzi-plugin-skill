local LrDevelopController = import 'LrDevelopController'
local M = {}

local BANDMAP = {
  HIGHLIGHTS = 'ParametricHighlights',
  LIGHTS     = 'ParametricLights',
  DARKS      = 'ParametricDarks',
  SHADOWS    = 'ParametricShadows',
}

local ALIAS = { ['高光']='HIGHLIGHTS', ['亮色调']='LIGHTS', ['暗色调']='DARKS', ['阴影']='SHADOWS' }

local function normBand(b)
  b = (b or ''):upper()
  if ALIAS[b] then return ALIAS[b] end
  return b
end

local function parseVal(v)
  v = v or '0'
  if v:sub(1,1) == '=' then return 'ABS', tonumber(v:sub(2)) else return 'DELTA', tonumber(v) end
end

function M.apply(band, val, t)
  band = normBand(band)
  local key = BANDMAP[band]
  if not key then t('Curve: unknown '..tostring(band)); return end

  if val == '++' then
    LrDevelopController.increment(key)
    return
  end

  if val == '--' then
    LrDevelopController.decrement(key)
    return
  end

  local mode, num = parseVal(val or '0')
  if not num then t('Curve: bad number '..tostring(val)); return end
  local cur = LrDevelopController.getValue(key) or 0
  local nv = (mode == 'ABS') and num or (cur + num)
  LrDevelopController.setValue(key, nv)
  t(string.format('Curve: %s %s -> %.3f (cur=%.3f)', band, val, nv, cur))
end

return M