let ACTION_SETTING = {
}
const defaultSettings = {
  keypad: {
    keypad: 'playOrPause'
  },
  encoder: {
    press: 'playOrPause',
    prCW: 'zoomOutPlayer',
    prCCW: 'zoomInPlayer',
    rCW: 'zoomOutPlayer',
    rCCW: 'zoomInPlayer'
  }
}
let form = ''
$UD.connect()

$UD.onConnected(conn => {
  console.log('-----log onConnected',$UD.controller)
  console.warn('-----warn onConnected',$UD.controller)
  //获取表单

  if($UD.controller === 'Encoder'){
    form = document.querySelector('#property-inspector-encoder');
    form.classList.remove('hidden');
  }else{
    form = document.querySelector('#property-inspector');
    form.classList.remove('hidden');
  }



  //渲染option
  renderFn()

  //连接上socket,显示配置项
  const el = document.querySelector('.uspi-wrapper');
  el.classList.remove('hidden');



  //监听表单变化，发送参数到上位机
  form.addEventListener(
    'input',
    Utils.debounce(() => {
   

        sendParamFn()
        
        showHideSettingsFn()
    })
  );
});

//获取初始化参数，两个事件都监听，防止遗漏
$UD.onAdd( jsonObj => {
  console.warn('-----onAdd:',$UD.uuid, JSON.stringify(jsonObj))
  const settings = jsonObj.param || {}
  
})

//获取初始化参数
$UD.onParamFromApp( jsonObj => {
  console.warn('-----onParamFromApp:', $UD.uuid, JSON.stringify(jsonObj))

  const settings = jsonObj.param || {}

  let checkParam = settings.press;
  
  if($UD.controller === 'Encoder'){
    checkParam = settings.press;
  }else{
    checkParam = settings.keypad;
  }
  if (!checkParam) {
    sendParamFn()
  }else{
    settingSaveParam(settings)
  }
  

})

let timer = 0

$UD.on('sendToPropertyInspector', jsonObj => {
  console.warn('-----on sendToPropertyInspector:', $UD.uuid, JSON.stringify(jsonObj))
  
  if(jsonObj.payload && jsonObj.payload.connectStatus){
    const connectStatus = jsonObj.payload.connectStatus;
    const clsList = {
      'Connected':'success',
      'Disconnected':'error',
      'Installed':'info',
      'NotInstalled':'warn',
      'Connecting':'info',
      'Updated':'info'
    }
    const connDom = document.querySelector('#connect-status')
    connDom.textContent = $UD.t(connectStatus);
    connDom.className = 'tip '+clsList[connectStatus];

    // if(connectStatus === 'Connected'){
    //   if(timer){
    //     clearTimeout(timer);
    //     timer = 0;
    //   }
    //   document.querySelector('#connect-tip').classList.add('hidden');
    // }else{
    //   timer = setTimeout(() => {
    //     document.querySelector('#connect-tip').classList.remove('hidden');
    //   }, 3000);
    // }

  }
})


$UD.onDidReceiveSettings( jsonObj => {
  console.warn('-----onDidReceiveSettings:', $UD.uuid, $UD.key, $UD.actionid, JSON.stringify(jsonObj))
  if($UD.actionid !== jsonObj.actionid) return;
  if (jsonObj && jsonObj.settings) {
    settingSaveParam(jsonObj.settings)
    if(jsonObj.settings.currentParameter){
      const currentParameter = jsonObj.settings.currentParameter;
      const currentParameterDom = document.querySelector('.current-parameter');
      if(currentParameterDom){
        currentParameterDom.value = currentParameter;
      }
    }
  }
})

//重载表单数据
function settingSaveParam(params) {
  console.warn('===settingSaveParam:', $UD.uuid, $UD.key, $UD.actionid,  JSON.stringify(params))
  ACTION_SETTING = { ...params };
  // Keep existing one-way switching configurations on the downward option.
  if (ACTION_SETTING.action === 'switchParameters') {
    ACTION_SETTING.action = 'SwitchDown';
  }


  showHideSettingsFn()

  console.warn('-----settingSaveParam:', $UD.uuid, $UD.key, JSON.stringify(ACTION_SETTING))

  //渲染表单数据
  Utils.setFormValue(ACTION_SETTING, form);
}


async function renderFn(){
  
  
  if($UD.controller === 'Encoder'){
    const renderName = 'encoder';
    console.log('===renderName', renderName)

    Object.keys(PI_CONFIGS[renderName]).map(key => {
      console.log('===key', key)
      if(key === 'colors'){
        const oColorsItem = form.querySelector('.colors-item');
        oColorsItem.classList.remove('hidden');

      }

      const oSelector = form.querySelector(`.${key}-selector`);
      oSelector.innerHTML = '';
      PI_CONFIGS[renderName][key].map(item => {

        let option = document.createElement('option');
        option.setAttribute('value', item.value);
        option.setAttribute('label', $UD.t(item.label));
        option.setAttribute('data-localize', item.label);
        if(item.selected){
          option.setAttribute('selected', 'selected');
        }
        oSelector.appendChild(option);
      });
    });
  }else{
    const oPressSelector = form.querySelector(".keypad-selector");
    oPressSelector.innerHTML = '';
    PI_CONFIGS.keypad.press.map(item => {
      let option = document.createElement('option');
      option.setAttribute('value', item.value);
      option.setAttribute('label', $UD.t(item.value));
      option.setAttribute('data-localize', item.value);
      
      oPressSelector.appendChild(option);
    });
  }

}

function sendParamFn(){

  const value = Utils.getFormValue(form);
  
  ACTION_SETTING = {
    ...ACTION_SETTING,
    ...value
  }

  console.warn('-----sendParamFn:', JSON.stringify(ACTION_SETTING))
  $UD.setSettings(ACTION_SETTING);
}

function showHideSettingsFn(){
  if($UD.controller === 'Keypad') return;

  //以下旋钮情况下的显示隐藏
  if(ACTION_SETTING.press === 'EXPOSURE'){
    form.querySelector('.stepsize-item').classList.add('hidden')
    form.querySelector('.exposure-stepsize-item').classList.remove('hidden')
  }else{
    form.querySelector('.stepsize-item').classList.remove('hidden')
    form.querySelector('.exposure-stepsize-item').classList.add('hidden')
  }

    if (ACTION_SETTING.stepSize) {
        changeRangeValue('stepSize', ACTION_SETTING.stepSize)
    }
    if (ACTION_SETTING.exposureStepSize) {
        changeRangeValue('exposureStepSize', ACTION_SETTING.exposureStepSize)
    }

}

function changeRangeValue(name, value){
    const rangeInput = form.querySelector(`input[name="${name}"]`);
      const rangeValue = rangeInput.parentElement.querySelector('.rangeValue');
      rangeValue.innerText = value;
}

function openHelp() {
  
}
