local LrTasks           = import 'LrTasks'
local LrSocket          = import 'LrSocket'
local LrFunctionContext = import 'LrFunctionContext'

local M = {}
local _server = nil
local _running = false
local _t = function(_) end
local _router = nil
local _prefs = nil

local function bindOnce(context)
  _t('TcpServer: bind '..tostring(_prefs.bindAddress)..':'..tostring(_prefs.port))
  _server = LrSocket.bind {
    functionContext = context,
    plugin = _PLUGIN,
    address = _prefs.bindAddress,
    port = _prefs.port,
    mode = 'receive',
    onMessage = function(sock, msg)
      local line = (msg or ''):gsub('[\r\n]', '')
      if line ~= '' then
        _t('TcpServer: onMessage '..line)
        -- 内置心跳处理：立刻回复，避免上层路由与超时
        if line == 'PING' or line == 'HEARTBEAT' then
          local ok, e = pcall(function() sock:send('PONG\n') end)
          if not ok then _t('TcpServer: send PONG failed: '..tostring(e)) end
          return
        end
        LrTasks.startAsyncTask(function()
          local ok, err = pcall(function() _router:handle(line) end)
          if not ok then _t('Router error: '..tostring(err)) end
        end)
      end
    end,
    
    onError = function(_, err)
      local e = tostring(err or 'unknown')
      _t('TcpServer: onError '..e..' -> reconnect')
      _server = nil
    end,
    onClosed = function(_)
      _t('TcpServer: onClosed -> reconnect')
      _server = nil
    end,
  }
  if _server then
    _t('TcpServer: listening '..tostring(_prefs.port)..' ('..tostring(_prefs.bindAddress)..')')
  else
    _t('TcpServer: bind failed '..tostring(_prefs.bindAddress)..':'..tostring(_prefs.port))
  end
end

local function supervisor()
  _t('TcpServer: supervisor enter')
  local backoff = 1.0
  while _running do
    LrFunctionContext.callWithContext('ulanzi_ctx', function(context)
      if not _running then return end
      bindOnce(context)
      if _server then backoff = 1.0 end
      while _running and _server do
        LrTasks.sleep(0.5)
      end
      _t('TcpServer: context exit; running='..tostring(_running)..' server='..tostring(_server))
    end)
    if _running and not _server then
      _t(string.format('TcpServer: rebind after %.1fs', backoff))
      LrTasks.sleep(backoff)
      backoff = math.min(backoff * 2, 10.0)
    end
  end
  _t('TcpServer: supervisor exit')
end

function M.start(router, t, prefs)
  if _running then return end
  _router, _t, _prefs = router, t, prefs
  _running = true
  LrTasks.startAsyncTask(supervisor)
end

function M.stop()
  _running = false
end

return M