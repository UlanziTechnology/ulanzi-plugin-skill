local LrTasks           = import 'LrTasks'
local LrLogger          = import 'LrLogger'
local LrPathUtils       = import 'LrPathUtils'
local Config = require 'Config'
local LrApplication = import 'LrApplication'


local log = LrLogger('ulanziDebug'); log:enable('print')


local function t(msg) 
  if not Config.LOG_TO_FILE then return end
  log:trace(msg)
end

t('333333444Main: starting init 333')

local prefs = {
  port = Config.TCP_PORT,
  bindAddress = '127.0.0.1',
  
}

_G.running = _G.running or false
_G.isRAW = false

local TcpServer     = require 'TcpServer'
local CommandRouter = require 'CommandRouter'
local BasicAdjust   = require 'BasicAdjust'
local ToneCurve     = require 'ToneCurve'
local HSL           = require 'HSL'
local Tools         = require 'Tools'


local router = CommandRouter.new(t, BasicAdjust, ToneCurve, HSL, Tools)


local function startWatchCurrentPhoto()

    LrTasks.startAsyncTask(function()

          -- t('1111333333Main: starting get cur raw 333')
        local catalog = LrApplication.activeCatalog()

        local lastPhoto = nil
          -- t('1111333333Main: starting get cur raw running:'..tostring(_G.running))

        while _G.running do

            local targets = catalog:getTargetPhotos()

            local current = targets and targets[1]
            
          t('1111333333Main: starting get cur raw lastPhoto:'..tostring(lastPhoto)..' ,isRAW:'..tostring(_G.isRAW))

            if current ~= lastPhoto then
                lastPhoto = current

                if current then
                    local fileFormat = current:getRawMetadata("fileFormat")
                    

                  -- t('1111333333Main: starting get cur raw fileFormat = '..tostring(fileFormat).." for photo "..tostring(current))
                    -- 回调
                    _G.isRAW = fileFormat and (fileFormat == "RAW" or fileFormat == "DNG")
                else
                    _G.isRAW = false
                end
            end

            -- 轮询间隔
            LrTasks.sleep(1.0)
        end
    end)

end


LrTasks.startAsyncTask(function()
  -- t('Main: starting init '..tostring(_G.running))
  if not _G.running then
    _G.running = true
    -- t('Main: starting TCP server at '..prefs.bindAddress..':'..prefs.port)
    TcpServer.start(router, t, prefs)
    startWatchCurrentPhoto()
  end
end)





t('333333Main: starting init 333')