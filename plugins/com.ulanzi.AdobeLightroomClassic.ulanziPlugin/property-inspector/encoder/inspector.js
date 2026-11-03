let ACTION_SETTING = {
}
const defaultSettings = {
}
let form = ''
$UD.connect()



let renderName = $UD.uuid && $UD.uuid.split('.')[4]
let currentParameter = 'TEMPERATURE'


$UD.onConnected(conn => {
  renderName = $UD.uuid.split('.')[4]
  console.log('-----log onConnected', $UD.controller)
  console.warn('-----warn onConnected', $UD.controller)
  //获取表单
  form = document.querySelector('#property-inspector-encoder');
  form.classList.remove('hidden');


  //渲染option
  renderFn()

  //连接上socket,显示配置项
  const el = document.querySelector('.uspi-wrapper');
  el.classList.remove('hidden');



  //监听表单变化，发送参数到上位机
  const pendingInputs = new Map();
  form.addEventListener('input', event => {
    const snapshot = { ...ACTION_SETTING, ...Utils.getFormValue(form) };
    if (renderName === 'general' && ['stepSize', 'exposureStepSize'].includes(event.target.name)) {
      snapshot.selectedSliderStepEdit = {
        context: ACTION_SETTING.currentParameterContext || '',
        parameter: currentParameter,
        name: event.target.name,
        value: event.target.value
      };
    }
    ACTION_SETTING = { ...snapshot };
    delete ACTION_SETTING.selectedSliderStepEdit;
    showHideSettingsFn();
    const edit = snapshot.selectedSliderStepEdit;
    const saveKey = edit ? `${edit.context}:${edit.name}` : 'settings';
    if (!pendingInputs.has(saveKey)) {
      pendingInputs.set(saveKey, Utils.debounce(value => {
        sendParamFn(value);
        pendingInputs.delete(saveKey);
      }));
    }
    pendingInputs.get(saveKey)(snapshot);
  });


  if (renderName === 'general') {
    console.warn('-----getGlobalSettings', $UD.uuid)
    $UD.getGlobalSettings()
  }

});

//获取初始化参数，两个事件都监听，防止遗漏
$UD.onAdd(jsonObj => {
  console.warn('-----onAdd:', $UD.uuid, JSON.stringify(jsonObj))
  const settings = jsonObj.param || {}

})

//获取初始化参数
$UD.onParamFromApp(jsonObj => {
  console.warn('-----onParamFromApp:', $UD.uuid, JSON.stringify(jsonObj))

  const settings = jsonObj.param || {}


  if (!settings.rCCW) {
    sendParamFn()
  } else {
    settingSaveParam(settings)
  }

})

let timer = 0

$UD.on('sendToPropertyInspector', jsonObj => {
  console.warn('-----on sendToPropertyInspector:', $UD.uuid, JSON.stringify(jsonObj))

  if (jsonObj.payload && jsonObj.payload.connectStatus) {
    const connectStatus = jsonObj.payload.connectStatus;
    const clsList = {
      'Connected': 'success',
      'Disconnected': 'error',
      'Installed': 'info',
      'NotInstalled': 'warn',
      'Connecting': 'info',
      'Updated': 'info'
    }
    const connDom = document.querySelector('#connect-status')
    connDom.textContent = $UD.t(connectStatus);
    connDom.className = 'tip ' + clsList[connectStatus];

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
  if (jsonObj.payload && jsonObj.payload.currentParameter) {
    currentParameter = jsonObj.payload.currentParameter;
    if (renderName === 'general') {
      const { currentParameter, currentParameterContext, stepSize, exposureStepSize } = jsonObj.payload;
      settingSaveParam({ ...ACTION_SETTING, currentParameter, currentParameterContext, stepSize, exposureStepSize });
    } else {
      showHideSettingsFn()
    }
  }
})


$UD.onDidReceiveSettings(jsonObj => {
  console.warn('-----onDidReceiveSettings:', $UD.uuid, JSON.stringify(jsonObj))
  if ($UD.actionid !== jsonObj.actionid) return;
  if (jsonObj && jsonObj.settings) {
    settingSaveParam(jsonObj.settings)
  }
})

$UD.onDidReceiveGlobalSettings(async jsonObj => {
  
  console.warn('-----onDidReceiveGlobalSettings:', $UD.uuid, JSON.stringify(jsonObj))
  if (!ACTION_SETTING.currentParameter && jsonObj.settings && jsonObj.settings.currentParameter) {
    currentParameter = jsonObj.settings.currentParameter;
  }
  showHideSettingsFn()

})


//重载表单数据
function settingSaveParam(params) {
  console.warn('===settingSaveParam:', JSON.stringify(params))
  ACTION_SETTING = { ...params };
  delete ACTION_SETTING.selectedSliderStepEdit;
  if (renderName === 'general' && params.currentParameter) currentParameter = params.currentParameter;


  showHideSettingsFn()

  console.warn('-----settingSaveParam:', JSON.stringify(ACTION_SETTING))

  //渲染表单数据
  Utils.setFormValue(ACTION_SETTING, form);
}


async function renderFn() {

  console.log('===renderName', renderName)

  Object.keys(PI_CONFIGS[renderName]).map(key => {
    console.log('===key', key)

    const oSelector = form.querySelector(`.${key}-selector`);

    form.querySelector(`.${key}-item`).classList.remove('hidden');
    oSelector.innerHTML = '';
    PI_CONFIGS[renderName][key].map(item => {

      let option = document.createElement('option');
      option.setAttribute('value', item.value);
      option.setAttribute('label', $UD.t(item.label));
      option.setAttribute('data-localize', item.label);
      if (item.selected) {
        option.setAttribute('selected', 'selected');
      }
      oSelector.appendChild(option);
    });
  });

  if (renderName === 'general') {
    form.querySelectorAll('.general-item').forEach(el => {
      el.classList.remove('hidden');
    });
  } else if (renderName !== 'mouseSelect' && renderName !== 'photoPreview') {
    form.querySelector('.stepsize-item').classList.remove('hidden');
  }

}

function sendParamFn(snapshot) {
  const settings = snapshot || { ...ACTION_SETTING, ...Utils.getFormValue(form) };
  console.warn('-----sendParamFn:', JSON.stringify(settings))
  $UD.setSettings(settings);
}


async function showHideSettingsFn() {


  if (renderName === 'general') {
    await $UD.localizeUI()
    const currentParameterDom = document.querySelector('.current-parameter');
    if (currentParameterDom) {
      currentParameterDom.value = $UD.t(currentParameter);
    }

    //曝光特殊处理
    if (currentParameter === 'EXPOSURE') {
      form.querySelector('.stepsize-item').classList.add('hidden')
      form.querySelector('.exposure-stepsize-item').classList.remove('hidden')
    } else {
      form.querySelector('.stepsize-item').classList.remove('hidden')
      form.querySelector('.exposure-stepsize-item').classList.add('hidden')
    }
  }

  if (ACTION_SETTING.stepSize) {
    changeRangeValue('stepSize', ACTION_SETTING.stepSize)
  }
  if (ACTION_SETTING.exposureStepSize) {
    changeRangeValue('exposureStepSize', ACTION_SETTING.exposureStepSize)
  }
}

function changeRangeValue(name, value) {
  const rangeInput = form.querySelector(`input[name="${name}"]`);
  const rangeValue = rangeInput.parentElement.querySelector('.rangeValue');
  rangeValue.innerText = value;
}


function openHelp() {

}
