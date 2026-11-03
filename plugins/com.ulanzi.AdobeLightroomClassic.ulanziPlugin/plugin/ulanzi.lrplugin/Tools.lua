local LrDialogs = import 'LrDialogs'

local M = {}

local function toast(message, fadeDelay)
  fadeDelay = tonumber(fadeDelay) or 1.5  -- 安全转换 + 默认值
  LrDialogs.showBezel( message, fadeDelay )
end

function M.apply(event, message, t)
  
  if event == 'TOAST' then
    t('Toast: showing "' .. tostring(message) .. '" for 1.5s')
    toast(message)
  end
end

return M