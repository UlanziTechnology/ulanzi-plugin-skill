let ACTION_SETTING = {
}

let form = ''
$UD.connect()

$UD.onConnected(conn => {
  //获取表单
  form = document.querySelector('#property-inspector');

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
  console.warn('-----onAdd:', $UD.uuid, JSON.stringify(jsonObj))


})

//获取初始化参数
$UD.onParamFromApp( jsonObj => {
  console.warn('-----onParamFromApp:', $UD.uuid, JSON.stringify(jsonObj))

  const settings = jsonObj.param || {}
  
  if (!settings.keypad) {
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





//重载表单数据
function settingSaveParam(params) {
  // console.log('===setSetting', params)
  ACTION_SETTING = {
    ...ACTION_SETTING,
    ...params
  };


  showHideSettingsFn()

  //渲染表单数据
  Utils.setFormValue(ACTION_SETTING, form);
}


async function renderFn(){
  

  const oPressSelector = document.querySelector(".keypad-selector");
  oPressSelector.innerHTML = '';
  const renderName = $UD.uuid.split('.')[4]
  
  PI_CONFIGS[renderName].map(item => {
    let option = document.createElement('option');
    option.setAttribute('value', item.value);
    option.setAttribute('label', $UD.t(item.value));
    option.setAttribute('data-localize', item.value);
    oPressSelector.appendChild(option);
  });



}

function sendParamFn(){
  const value = Utils.getFormValue(form);
  
  ACTION_SETTING = {
    ...ACTION_SETTING,
    ...value
  }
  $UD.sendParamFromPlugin(ACTION_SETTING);
}

function showHideSettingsFn(){
}

function openHelp() {
  
}
