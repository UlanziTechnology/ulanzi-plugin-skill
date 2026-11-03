local LrDevelopController = import 'LrDevelopController'
local M = {}

local MODEMAP = { HUE='HUE', SAT='SAT', LUM='LUM', ['色相']='HUE', ['饱和度']='SAT', ['明亮度']='LUM' }
local COLORMAP = {
  RED='Red', ORANGE='Orange', YELLOW='Yellow', GREEN='Green', AQUA='Aqua', BLUE='Blue', PURPLE='Purple', MAGENTA='Magenta',
  ['红色']='Red', ['橙色']='Orange', ['黄色']='Yellow', ['绿色']='Green', ['浅绿色']='Aqua', ['蓝色']='Blue', ['紫色']='Purple', ['洋红']='Magenta',
}

local function keyFor(mode, color)
  local c = COLORMAP[(color or ''):upper()] or COLORMAP[color or '']
  local m = MODEMAP[(mode or ''):upper()] or MODEMAP[mode or '']
  if not c or not m then return nil end
  if m == 'HUE' then return 'HueAdjustment'..c end
  if m == 'SAT' then return 'SaturationAdjustment'..c end
  if m == 'LUM' then return 'LuminanceAdjustment'..c end
end

local function parseVal(v)
  v = v or '0'
  if v:sub(1,1) == '=' then return 'ABS', tonumber(v:sub(2)) else return 'DELTA', tonumber(v) end
end

function M.apply(mode, color, val, t)
  local key = keyFor(mode, color)
  if not key then t('HSL: bad mode/color '..tostring(mode)..'/'..tostring(color)); return end

  if val == '++' then
    LrDevelopController.increment(key)
    return
  end

  if val == '--' then
    LrDevelopController.decrement(key)
    return
  end

  local how, num = parseVal(val or '0')
  if not num then t('HSL: bad number '..tostring(val)); return end

  if num == 0 then
    LrDevelopController.resetToDefault(key)
    t('HSL: 0值重置 '..tostring(mode)..'/'..tostring(color))
    return
  end

  local cur = LrDevelopController.getValue(key) or 0

  -- t('HSL GET VALUE:'..key..' = '..tostring(cur))

  local nv = (how == 'ABS') and num or (cur + num)
  local ok, err = pcall(function() LrDevelopController.setValue(key, nv) end)
  if not ok then  t('Set FAIL:'..key..' 失败: '..tostring(err)) end
  t(string.format('HSL: %s %s %s -> %.3f (cur=%.3f)', tostring(mode), tostring(color), val, nv, cur))

  -- t('HSL SET SUCCESS:'..key..' = '..tostring(nv))

end

return M