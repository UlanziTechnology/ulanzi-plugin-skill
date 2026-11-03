import { UlanziApi } from './actions/ulanzi-api/index.js';

import Action from './actions/action.js'

import LrServer from './actions/lrServer.js';
import SelectedSliderState from './actions/selectedSliderState.js';

const $UD = new UlanziApi();
const selectedSliderState = new SelectedSliderState($UD);

const $LRSERVER = new LrServer($UD)
$LRSERVER.start()

const ACTION_CACHES = {}

$UD.connect('com.ulanzi.ulanzideck.lrc')



$UD.onDidReceiveGlobalSettings( jsonObj => {
  console.warn('-----main onDidReceiveGlobalSettings:', $UD.uuid, JSON.stringify(jsonObj))
  if (jsonObj.settings) selectedSliderState.restore(jsonObj.settings);

})



$UD.onConnected(conn => {
  console.warn('-----main getGlobalSettings', $UD.uuid)
  $UD.getGlobalSettings('com.ulanzi.ulanzideck.lrc___0_0___112233')
})

//需要翻译
$UD.localizeUI()

console.warn('---===main.js loaded language', $UD.language)

//把插件某个功能配置到按键上
$UD.onAdd(jsn => {
  const context = jsn.context; //唯一id
  const instance = ACTION_CACHES[context];
  const settings = jsn.param;
  if (!instance) {
    ACTION_CACHES[context] = new Action(context, $UD, $LRSERVER, selectedSliderState);
  }
  ACTION_CACHES[context].add(settings)
})

//插件功能活跃状态设置
$UD.onSetActive(jsn =>{
  const context = jsn.context
  const instance = ACTION_CACHES[context];
  if (instance) {
    instance.setActive(jsn.active)
  }
})

//按键按下时发送的事件
$UD.onKeyDown(jsn =>{
  const context = jsn.context
  const instance = ACTION_CACHES[context];
  const settings = jsn.param
  if (instance) instance.keyDown(settings);
})

//按键抬起时发送的事件
$UD.onKeyUp(jsn =>{
  const context = jsn.context
  const instance = ACTION_CACHES[context];
  const settings = jsn.param
  if (instance) instance.keyUp(settings);
})


//旋钮按下时发送的事件
$UD.onDialDown(jsn =>{
  const context = jsn.context
  const instance = ACTION_CACHES[context];
  const settings = jsn.param
  if (instance) instance.dialDown(settings);
})



//旋钮旋转时发送的事件
$UD.onDialRotateLeft(jsn =>{
  const context = jsn.context
  const instance = ACTION_CACHES[context];
  const settings = jsn.param
  if (instance) instance.dialRotateLeft(settings);
})

//旋钮旋转时发送的事件
$UD.onDialRotateRight(jsn =>{
  const context = jsn.context
  const instance = ACTION_CACHES[context];
  const settings = jsn.param
  if (instance) instance.dialRotateRight(settings);
})

//旋钮按住向左旋转时发送的事件
$UD.onDialRotateHoldLeft(jsn =>{
  const context = jsn.context
  const instance = ACTION_CACHES[context];
  const settings = jsn.param
  if (instance) instance.dialRotateHoldLeft(settings);
})

//旋钮按住向右旋转时发送的事件
$UD.onDialRotateHoldRight(jsn =>{
  const context = jsn.context
  const instance = ACTION_CACHES[context];
  const settings = jsn.param
  if (instance) instance.dialRotateHoldRight(settings);
})

//接收上位机保存的参数
$UD.onDidReceiveSettings(jsn =>{
  console.warn('---===onDidReceiveSettings', JSON.stringify(jsn))
  const settings = jsn.settings
  const context = jsn.context
  const instance = ACTION_CACHES[context];
  if (instance && settings){
    instance.didReceiveSettings(settings);
  }
})


//移除插件的功能配置信息
$UD.onClear(jsn =>{
  if(jsn.param){
    for(let i = 0; i<jsn.param.length; i++){
      const context = jsn.param[i].context
      console.warn('---===onClear context:', ACTION_CACHES[context], context)
      if (ACTION_CACHES[context]){
        ACTION_CACHES[context].clear()
        delete ACTION_CACHES[context]
      } else {
        selectedSliderState.remove(context);
      }
    }
  }
})

//重载插件功能配置信息变化
$UD.onParamFromApp(jsn =>{
  const settings = jsn.param
  const context = jsn.context
  $UD.lastContext = context  //记录最后一次操作的context，方便app.js使用
  const instance = ACTION_CACHES[context];
  if (instance && settings){
    instance.paramFromApp(settings);
  }

})

//监听插件功能配置信息变化
$UD.onParamFromPlugin(jsn =>{
  const settings = jsn.param
  const context = jsn.context
  const instance = ACTION_CACHES[context];
  if (instance && settings){
    instance.paramFromPlugin(settings);
  }
})


