local LrDevelopController = import 'LrDevelopController'
local LrApplication = import 'LrApplication'

local M = {}

local KEYMAP = {
  TEMPERATURE = 'Temperature',
  TINT        = 'Tint',
  EXPOSURE    = 'Exposure2012',
  CONTRAST    = 'Contrast2012',
  HIGHLIGHTS  = 'Highlights2012',
  SHADOWS     = 'Shadows2012',
  WHITES      = 'Whites2012',
  BLACKS      = 'Blacks2012',
  TEXTURE     = 'Texture',
  CLARITY     = 'Clarity2012',
  DEHAZE      = 'Dehaze',
  VIBRANCE    = 'Vibrance',
  SATURATION  = 'Saturation',
}

local ALIAS = {
  ['色温'] = 'TEMPERATURE', ['色调'] = 'TINT', ['曝光度'] = 'EXPOSURE', ['对比度'] = 'CONTRAST',
  ['高光'] = 'HIGHLIGHTS', ['阴影'] = 'SHADOWS', ['白色色阶'] = 'WHITES', ['黑色色阶'] = 'BLACKS',
  ['纹理'] = 'TEXTURE', ['清晰度'] = 'CLARITY', ['去朦胧'] = 'DEHAZE', ['鲜艳度'] = 'VIBRANCE',
  ['饱和度'] = 'SATURATION',
}

local function normParam(p)
  p = (p or ''):upper()
  if ALIAS[p] then return ALIAS[p] end
  return p
end

local function parseVal(v)
  v = v or '0'
  if v:sub(1,1) == '=' then
    return 'ABS', tonumber(v:sub(2))
  else
    return 'DELTA', tonumber(v)
  end
end


function M.delta(param, delta, t)
  param = normParam(param)
  local key = KEYMAP[param]
  if not key then t('Basic: unknown '..tostring(param)); return end
  local cur = LrDevelopController.getValue(key)
  if cur == nil then t('Basic: no value for '..key); return end
  local nv = (cur or 0) + (delta or 0)
  LrDevelopController.setValue(key, nv)
  t(string.format('Basic: %s %+.3f -> %.3f', param, delta or 0, nv or 0))
end

function M.apply(param, val, t)
  param = normParam(param)
  local key = KEYMAP[param]
  if not key then t('Basic: unknown '..tostring(param)); return end


 

  if val == '++' then
    LrDevelopController.increment(key)
    return
  end

  if val == '--' then
    LrDevelopController.decrement(key)
    return
  end


  t('00Basic APPLY: '..tostring(param)..' = '..tostring(val))

  if type(val) == "string" and val:find("default", 1, true) then
    t('11Basic: value contains "default", will replace it with actual default number for '..tostring(param))
    if param == 'TEMPERATURE' then
      local isRaw = _G.isRAW  
      t('22Checking if current photo is RAW: isRaw = '..tostring(isRaw))
      local defaultNumStr = isRaw and "50" or "1"
      val = val:gsub("default", defaultNumStr)
    elseif param == 'EXPOSURE' then
      local defaultNumStr = "0.1"
      val = val:gsub("default", defaultNumStr)
    else
      val = val:gsub("default", "1")
    end
      t('33Basic: after replacement, value is '..tostring(val))
  end

  local mode, num = parseVal(val or '0')
  if not num then t('Basic: bad number '..tostring(val)); return end
  local cur = LrDevelopController.getValue(key) or 0
  local nv = (mode == 'ABS') and num or (cur + num)
  LrDevelopController.setValue(key, nv)
  t(string.format('Basic: %s %s -> %.3f (cur=%.3f)', param, val, nv, cur))
end

return M