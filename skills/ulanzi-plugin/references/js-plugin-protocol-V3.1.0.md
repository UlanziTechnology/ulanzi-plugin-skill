# JS 插件开发协议\-V3\.1\.0



版本更新说明

|时间|版本号|变更说明|上位机版本|
|---|---|---|---|
|2024\-5\-8|V1\.0\.2\.7<br>|增加了传送gif图片的功能协议<br>增加了插件打开url窗口的功能协议||
|2024\-5\-8|V1\.0\.2\.8|增加了传送文本功能协议||
|2024\-5\-13<br>|V1\.1\.0<br>|1、修改了插件打开url窗口的功能协议，删除了关闭url窗口指令，改为url窗口自己主动关闭<br>2、在上位机里有字体设置，文本功能协议去除了字体<br>3、修改了通信内容：上位机服务端地址及端口不再固定，启动脚本或者html时作为参数传递进去。<br>4、去除了clearall、init指令，增加了setactive指令<br>5、action实例增加了actionid||
|2024\-5\-15|V1\.1\.1|修改QA\-3内容，新增QA\-5||
|2024\-6\-03<br>|V1\.1\.2|manifest\.json内增加了是否支持多项操作配置（原先不加这个关键字，默认是支持的。）||
|2024\-07\-09<br>|V\.1\.2\.0|加载html时新增参数<br>openurl支持打开插件根目录下的url链接（以/ \./ 起始的链接）<br>添加了selectdialog协议，返回选择文件/文件夹路径<br>增加了toast协议，支持上位机弹出toast。||
|2024\-07\-15<br>|V\.1\.2\.1|插件\-\-\-\-\>上位机的命令在返回时会带上cmdType字段<br>~~不推荐使用openview~~||
|2024\-10\-26|V1\.2\.2|openView 可不传x,y，默认居中<br>openView支持跨域请求<br>openView/openUrl 需要通过param传递html参数||
|2025\-07\-01|V1\.3\.0<br>|增加了Action类型设置：按键\-Keypad、旋钮\-Encoder<br>增加了Action旋钮\-Encoder的布局设置<br>增加了Action是否支持自动更新状态<br>增加了插件需要监控的应用程序设置<br>增加插件指定的配置<br>上位机\-\-\-\-\-\>插件中增加了06）\~19）共计14条协议||
|2025\-07\-10|V1\.3\.1|增加 hotkey协议：请求上位机执行组合键|V1\.7\.2|
|2025\-09\-09<br>|V2\.0\.0<br>|增加keydown、keyup<br>keypress 更名 keydown<br>删除长按开始、长按结束<br>旋钮旋转事件集中到一个协议中<br>新增 [logMessage]，打印日志到文件<br>新增 [showAlert]，显示错误图标到按键 <br>新增字段 按键类型和设备类型：[add]、[加载html]<br>PropertyInspector的html背景色需设置为透明<br>新增主服务与PropertyInspector通讯机制，与param解耦<br>新增[didReceiveSettings]、[setSettings]、[getSettings]\(通过与[sendToPlugin]、[sendToPropertyInspector]的组合使用 来替代paramfromplugin\)|V2\.1|
|2025\-10\-29|V2\.0\.1<br>|manifest\.json中最小支持上位机版本启用，并迁移至[新字段]<br>NodeJS插件 manifest\.json中新增[调试字段]<br>增加[启动参数]注释||
|2025\-11\-06<br>|V2\.0\.2|增加了插件安装到第三方App的字段<br>"InstallToDepsApp": \{<br>"Type": "JavaScript",<br>"CodePath": "install/test\.js"<br>\},||
|2025\-11\-17<br>|V2\.0\.3|新增国际化的[文件命名]规范 <br>新增manifest中[多设备适配]的说明 ||
|2025\-11\-26|V2\.1\.0<br>|D200X新增旋钮协议：<br>[D200X旋钮布局协议]<br>[D200X旋钮布局元素]<br>新增接口：<br>[设置旋钮布局]<br>[设置旋钮布局元素]|V3\.0\.1|
|2025\-12\-18|V2\.1\.1|添加全局设置协议<br>[设置全局参数]<br>[获取全局参数]<br>[发送全局设置参数到Action]|V2\.1\.19<br>V3\.0\.2|
|2026\-1\-13|V2\.1\.2|[设置全局参数] 更新<br>可以通过主服务的UUID更新全局参数，不需要actionID参数，会转发给当前已经connected的子服务|V3\.0\.5<br>|
|2026\-6\-4|V3\.0\.0|新增 AI Agent状态与上下文订阅协议<br>新增 subscribeAiAgentState / unsubscribeAiAgentState / getAiAgentProjects / getAiAgentSessions<br>新增 didReceiveAiAgentState / didReceiveAiAgentProjects / didReceiveAiAgentSessions 返回协议<br>插件主服务需要先订阅对应 AI Agent，才允许接收状态或查询项目、会话<br>订阅功能因 引导安装hook过程还不完善，现在只有在Au05设备在线后，才会启用功能|V3\.2\.0|
|2026\-7\-9<br>|V3\.1\.0<br>|manifest新增：<br>States中 Name必填<br>States中 新增 MultiActionImage，用于多项操作中图标显示<br>新增 SupportedInKeyLogicActions，用于在动作触发器插件中是否显示<br>新增 Detail，Banner，URL 字段，便利于UGC上传时自动解析<br>插件加载新增上位机版本字段softwareVersion<br>addAction run keydown keyup 加载插件PropertyInspector 时 添加多项操作标识: isInMultiAction  指定State执行: multiActionState<br>更换按键显示的内容设置 新增三个协议setState setImage setTitle<br>|V3\.3\.0|

# 一、插件包

插件包安装到指定文件夹后，上位机会自动识别加载，解析manifest\.json，进行功能显示及库资源加载。

## 1、文件夹命名

```JSON
一般为com.ulanzi.+"插件名"+ulanziPlugin，如obs插件，我命名为com.ulanzi.obsstudio.ulanziPlugin，请按这个格式命名，确保统一。
文件夹里面一般包含一个manifest.json及其翻译文件、插件库、图片等资源
```

## 2、配置文件

（下面是个例子）

```JSON
manifest.json
{
        "Author": "Ulanzi",   //会被UGC上传页面解析到表单中
        "Name": "OBS Studio",  //会被UGC上传页面解析到表单中
        "Description": "OBS Studio Operation",  //简介，会被UGC上传页面解析到表单中
        "Detail": "",    //详细介绍，会被UGC上传页面解析到表单中
        "Icon": "resources/store_icon.png",  //会被UGC上传页面解析到表单中
        "Version": "1.0.1",  //会被UGC上传页面解析到表单中
        "Category": "OBS Studio",
        "CategoryIcon": "resources/icon.png",
        "CodePath": "source/main.html", // 主程序可以为".html"和".js"，".html"时使用QWebEngineView加载，".js时"使用Node（版本为20.12.2）加载
        "Type": "JavaScript",
        "Inspect":"--inspect=127.0.0.1:9201",  //NodeJS启用远程调试 每个插件的端口不能重复 需要配合上位机DEBUG运行参数使用
        "URL": "附加链接"   //会被UGC上传页面解析到表单中
        "Banner": [    //封面图，会被UGC上传页面解析到表单中
            "assets/baaner_1.png",
            "assets/banner_2.png"
        ]
        "PrivateAPI": true,
        "UUID": "com.ulanzi.ulanzideck.obsstudio", //会被UGC上传页面解析到表单中
        "Actions": [
                {

                        "Name": "Record",
                        "Icon": "resources/actions/record/icon.png",
**                        "PropertyInspectorPath": "source/actions/record/action_record_inspector.html",**
                        "state": 0,
                        "States": [
                                {
                                       "Name": "Start",  //必填
                                       "Image": "resources/actions/record/on.png",
                                       "MultiActionImage":"resources/actions/record/on.png"
                                },
                                {
                                       "Name": "Stop",
                                       "Image": "resources/actions/record/off.png"
                                       "MultiActionImage":"resources/actions/record/on.png"
                                }
                        ],
                        "Tooltip": "Start/Stop recording to file",
                        "UUID": "com.ulanzi.ulanzideck.obsstudio.record",
                        "SupportedInMultiActions": false,
                        "SupportedInKeyLogicActions": true,  //是否支持在动作触发器中 默认为true
                        "DisableAutomaticStates": true
                },
                {
                        "Name": "Record Pause",
                        "Icon": "resources/actions/record.pause/icon.png",
**                        "PropertyInspectorPath": "source/actions/record_pause/action_record_pause_inspector.html",**
                        "state": 0,
                        "States": [
                                {
                                        "Name": "Pause",
                                        "Image": "resources/actions/record.pause/on.png"
                                },
                                {
                                        "Name": "Unpause",
                                        "Image": "resources/actions/record.pause/off.png"
                                }
                        ],
                        "Tooltip": "Pause an active recording",
                        "UUID": "com.ulanzi.ulanzideck.obsstudio.record.pause",
                        "SupportedInMultiActions": false,
                        "DisableAutomaticStates": true,    // 是否支持自动更新状态
                        "Controllers": [ //Action 类型
                                    "Encoder",     //旋钮
                                    "Keypad"       //按键
                                ],
                        "Encoder": { //旋钮设置
                                "layout": "$B1", // "布局"
                                ~~"TriggerDescription": { //旋钮功能~~
~~                                    "Rotate": "Adjust volume", ~~
~~                                    "Push": "Mute/unmute",~~
~~                                    "Touch": "Mute/unmute" // 触摸~~
~~                                    "LongTouch": "Mute/unmute" // 触摸~~
~~                                }~~
                        },
                },
        "OS": [
                {
                        "Platform": "windows",
                        "MinimumVersion": "10"
                },
                {
                        "Platform": "mac",
                        "MinimumVersion": "10.11"
                }
        ],
        "Software": {
                ~~"MinimumVersion": "6.1"~~   弃用该字段
                "MinVersion":"2.1.0"    无该字段时不做限制
        },
        "ApplicationsToMonitor": {
            "windows": [
                "obs32.exe",
                "obs64.exe"
            ],
            "mac": [
                "com.obsproject.obs-studio"
            ]
        },
        "Profiles": [
            {
                "Name": "My Cool Profile",
                "DeviceType": 0,
                "Readonly": false,
                "DontAutoSwitchWhenInstalled": false,
                "AutoInstall": true
            }
        ],
        "InstallToDepsApp": {
                "Type": "JavaScript",
                "CodePath": "install/test.js"
        },
}
```

```JSON
说明：
{
        "Author": "Ulanzi", //开发者
        "Name": "OBS Studio",//插件名称（上位机插件列表使用）
        "Description": "OBS Studio Operation",//插件描述
        "Icon": "resources/store_icon.png", //插件图标（上位机插件列表使用）图片类别支持svg、png、jpg
        "Version": "1.0.1",//版本
        "Category": "OBS Studio",//类别
        "CategoryIcon": "resources/icon.png",//插件类别图标
        "CodePath": "source/main.html",//插件库入口
        "Type": "JavaScript",//插件开发语言
        "PrivateAPI": true,//插件接口类型
        "UUID": "com.ulanzi.ulanzideck.obsstudio",//插件ID
        "Actions": [
                {
                        "Name": "Record",//  功能图标（上位机插件列表使用）
                        "Icon": "resources/actions/record/icon.png", //  功能名称（上位机插件列表使用）
                        "PropertyInspectorPath": "source/actions/record/action_record_inspector.html",//(JS功能界面文件路径)
                        "state": 0,     //  图标，默认0
                        "States": [    //  图标列表
                                {
                                        "Name": "Start",//这个上位机暂时用不到，插件自己需要使用的
                                        "Image": "resources/actions/record/on.png"    // 图标路径
                                },
                                {
                                        "Name": "Stop",
                                        "Image": "resources/actions/record/off.png"    // 图标路径
                                }
                        ],
                        "Tooltip": "Start/Stop recording to file",//  功能提示，（上位机插件列表使用）
                        "UUID": "com.ulanzi.ulanzideck.obsstudio.record"//  功能ID,
                        "SupportedInMultiActions": false, // 是否支持多项操作
                        "DisableAutomaticStates": true,    // 是否支持自动更新状态
                        "Controllers": [ //Action 类型
                                    "Encoder",     //旋钮
                                    "Keypad"       //按键
                                ],
                        "Encoder": { //旋钮设置
                                "layout": "$B1", //
                                ~~"TriggerDescription": { //旋钮功能~~
~~                                    "Rotate": "Adjust volume", ~~
~~                                    "Push": "Mute/unmute",~~
~~                                    "Touch": "Mute/unmute" // 触摸~~
~~                                    "LongTouch": "Mute/unmute" // 触摸~~
~~                                }~~
                        }
                }
        ],
        "OS": [//插件支持的平台
                {
                        "Platform": "windows",//平台
                        "MinimumVersion": "10"//平台最低版本号
                },
                {
                        "Platform": "mac", //平台
                        "MinimumVersion": "10.11"//平台最低版本号
                }
        ],
        "Software": {//上位机软件
                "MinimumVersion": "6.1"//上位机软件最低版本号
        },
        "ApplicationsToMonitor": { //上位机监控插件需要的应用程序启动或者关闭
            "windows": [
                "obs32.exe",
                "obs64.exe"
            ],
            "mac": [
                "com.obsproject.obs-studio"
            ]
        },
        "Profiles": [//插件关联配置
            {
                "Name": "My Cool Profile",
                "DeviceType": 0,
                "Readonly": false,
                "DontAutoSwitchWhenInstalled": false,
                "AutoInstall": true
            }
        ],
        "InstallToDepsApp": { //需要安装到第三方App的插件脚本
                "Type": "JavaScript",
                "CodePath": "install/test.js"// 脚本在插件包里的路径
        },
}
注意：com.ulanzi.ulanzideck.obsstudio.record中
com.ulanzi.ulanzideck.obsstudio这段表示插件名称，record表示功能名称。
```

## 3、多设备适配

```JSON
manifest.json
{
    ...
    //多设备适配针对每个Action单独配置
    "Actions": [
    {
        ...
        //Controllers: 支持的按键类型，Dail或D200X上，根据按键/旋钮类型显示Action，只有Controllers声明了类型，才会在对应的类型中显示，没有该字段时，默认是按键类型。
        "Controllers": [ //Action 类型
                    "Encoder",     //旋钮
                    "Keypad"       //按键
                ],

        //Devices: 支持的设备,只会在支持的设备上才能看见该Action
        //不存在Devices字段或者为空时，表示适配所有设备
        "Devices": [],

        //列出设备型号，表示支持该设备，型号： D200 | D200H | Dial | D200X | D100N
        "Devices": ["Dial", "D100N"],


        //~ + 设备型号，表示不支持该设备型号，可以和正常型号组合使用
        "Devices": ["~Dial"]
        ...
}


    ],
    ....
}

```

## 4、D200X 布局协议

### 1、方式一：Manifest中声明

```JSON
manifest.json
{
    ...
    //多设备适配针对每个Action单独配置
    "Actions": [
    {
        ...
        {
            ...
            "Name": "Action One",
            "Encoder": { //旋钮设置
                    //使用预置布局
                    "layout": "$UA1",

                    //使用自定义布局
                    "layout": "layout.json", //Manifest.json同级目录下文件路径
            }
            "UUID": "come.ulanzi.test.one"
            ...
        }
        ...
    }


    ],
    ....
}
```

### 2、方式二：通过通信协议设置

[设置旋钮布局]

### 3、窗口坐标

布局的宽高为 126 \* 140，左上角为\(0，0\)点，右下角为\(126，140\)。

### 4、预置布局

#### 1、$UA1（图标 \+ 文字）

```Bash
{
    "id":"$UA1",
    "items": [
        {
            "type": "pixmap",
            "key": "icon",   //key为icon时，等同于普通按键的图标, 非icon时，不会存取数据，需要主动更新
            "background": "transparent",
            "enabled": true,
            "rect": [
                13,
                0,
                100,
                100
            ],
            "zOrder": 0,
            "value": "Images/hotkey.svg"
        },
        {
            "type": "text",
            "key": "title",  //key为title时，等同于普通按键的标题,非title时，不会存取数据，需要主动更新
            "background": "transparent",
            "enabled": true,
            "rect": [
                0,
                105,
                126,
                35
            ],
            "zOrder": 1,
            "alignment": "center",
            "color": "#dfdfdf",
            "font": {
                "size": 7
            },
            "text": ""
        }
    ]
}
```

#### 2、$UA2（文本 \+ 文本）

```Bash
{
    "id": "$UA2",
    "items": [
        {
            "type": "text",
            "key": "text2",
            "background": "#000000",
            "enabled": true,
            "opacity": 1,
            "rect": [
                28,
                7,
                126,
                70
            ],
            "zOrder": 0,
            "alignment": "center",
            "color": "white",
            "font": {
                "size": 8
            },
            "text": "test1"
        },
        {
            "type": "text",
            "key": "title",  //key为title时，等同于普通按键的标题,非title时，不会存取数据，需要主动更新
            "background": "#000000",
            "enabled": true,
            "rect": [
                0,
                95,
                126,
                39
            ],
            "zOrder": 1,
            "alignment": "center",
            "color": "white",
            "font": {
                "size": 8
            },
            "text": "test"
        }
    ]
}
```

## 5、D200X 布局元素

### 1、文本元素（Type: "text"）

#### 功能描述

用于渲染文本内容，支持字体样式、对齐方式、溢出处理，适用于显示状态信息、数值反馈等场景。

#### 属性列表

|属性名|类型|默认值|是否必填|约束条件|描述|
|---|---|---|---|---|---|
|type|string|\-|是|固定值 "text"|元素类型标识|
|key|string|\-|是|同一布局内唯一|元素标识|
|background|string|\-|否|支持命名颜色（如 "white"）、十六进制（如 "\#204cde"）、渐变（如 "0:\#ff0000,1:\#00ff00"）|元素背景色或渐变<br>|
|enabled|boolean|true|否|\-|元素是否启用（false 时隐藏）|
|opacity|number|1|否|取值范围 0\.1\~1，步长 0\.1|元素不透明度|
|rect|Rect|\-|是|x/y/width/height 为非负整数，且范围在 200×100 内|元素坐标与尺寸|
|zOrder|number|0|否|取值范围 0\~700|元素层叠顺序（值越大越靠上）|
|alignment|"center"/"left"/"right"|"center"|否|若 key="title"，则优先使用用户在 Ulanzi Studio软件属性中标题的配置|文本水平对齐方式|
|color|string|"white"|否|支持命名颜色（如 "red"）、十六进制格式（如 "\#ff6b6b"）<br>若 key="title"，则优先使用用户在 Ulanzi Studio软件属性中标题的配置|文本颜色|
|font<br>|Font|\-|否|嵌套对象，size 为必填项（若指定 font 则需填写 size）<br>若 key="title"，则优先使用用户在 Ulanzi Studio软件属性中标题的配置|字体样式配置|
|text|string|\-|是|无长度限制，但需配合 textOverflow 处理溢出|要显示的文本内容|

#### 配置示例

```JSON
{
  "type": "text",
  "key": "title",
  "text": "test",
  "color": "#ffffff",
  "alignment": "center",
  "font": {
    "size": 14,
    "weight": 500,
  },
  "textOverflow": "ellipsis",
  "background": "#2d3436",
  "enabled": true,
  "opacity": 1,
  "rect": { "x": 0, "y": 10, "width": 200, "height": 20 },
  "zOrder": 10
}
```

### 2、图片元素（Type: "pixmap"）

#### 功能描述

用于渲染图片资源，支持本地文件路径或 Base64 编码格式，适用于显示图标、Logo、状态标识等场景。

#### 属性列表

|属性名|类型|默认值|是否必填|约束条件|描述|
|---|---|---|---|---|---|
|type|string|\-|是|固定值 "pixmap"|元素类型标识|
|key|string|\-|是|同一布局内唯一|元素标识|
|background|string|\-<br>|否|支持命名颜色（如 "white"）、十六进制（如 "\#204cde"）、渐变（如 "0:\#ff0000,1:\#00ff00"）|元素背景色或渐变|
|enabled|boolean|true|否|\-|元素是否启用（false 时隐藏）|
|opacity|number|1|否|取值范围 0\.1\~1，步长 0\.1|元素不透明度|
|rect|Rect|\-|是|x/y/width/height 为非负整数，且范围在 200×100 内|元素坐标与尺寸|
|zOrder|number|0|否|取值范围 0\~700|元素层叠顺序（值越大越靠上）|
|value|string|\-|是|两种合法格式：1\. 本地文件路径（相对插件根目录）；2\. Base64 编码字符串（需包含完整 MIME 类型）|图片资源来源<br>|

#### 格式说明

- 本地文件路径：支持 PNG、JPEG、SVG 等常见格式，路径以插件根目录为基准（如 "icons/mute\.png" 表示插件文件夹下 icons 目录中的 mute\.png 文件）；

- Base64 编码：格式为 `data:[MIME类型];base64,[编码字符串]`（如 "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADIAAAAyCAMAAAAp4XiDAAAAUVBMVEWFhYWDg4N\.\.\."）。

#### 配置示例（本地文件）

```JSON
{
    "type": "pixmap",
    "key": "mute-icon",
    "value": "icons/mute.png",
    "background": "transparent",
    "enabled": true,
    "opacity": 0.9,
    "rect": { "x": 160, "y": 30, "width": 30, "height": 30 },
    "zOrder": 20
}
```

#### 配置示例（Base64 编码）

```JSON
{
  "type": "pixmap",
  "key": "logo",
  "value": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADIAAAAyCAMAAAAp4XiDAAAAUVBMVEWFhYWDg4N3d3dtbW17e3t1dXWBgYGHh4d5eXlzc3OLi4ubm5uVlZWPj4+NjY19fX2JiYl/f39ra2uRkZGZmZlpaWmXl5dvb29xcXGTk5NnZ2c4zIwMAAAAGXRSTlMAQObYZgAAAAFiS0dEAIgFHUgAAAAJcEhZcwAACxMAAAsTAQCanBgAAAAHdElNRQfmCBMQIxRQY6VAAAAiklEQVRIx+2VQQEAAAgDaoN9+9e0t9w2AMDQ4MhIyMjIWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFi4iLi4iLi4iLi4iLi4iLi4iLi4iLi4iLi4iLgADjR81v8pV8uAAAAABJRU5ErkJggg==",
  "background": "#f5f5f5",
  "enabled": true,
  "opacity": 1,
  "rect": { "x": 10, "y": 10, "width": 40, "height": 40 },
  "zOrder": 5
}
```

### 4、Rect 类型定义

```JSON
{
    x: number;    // 左上角x坐标（0~200）
    y: number;    // 左上角y坐标（0~100）
    width: number;// 元素宽度（0~200-x）
    height: number;// 元素高度（0~100-y）
};
```

### 5、Range 类型定义

```JSON
{
  min: number; // 进度最小值（必填，整数或小数均可）
  max: number; // 进度最大值（必填，整数或小数均可）
};
```

- 示例：`{ "min": 0, "max": 200 }`（适用于显示 0\~200 的数值进度）、`{ "min": 0.0, "max": 1.0 }`（适用于归一化数值）。



# 二、通信设置

## 1、服务端

### 1）加载插件主服务

```JSON
采用webSocket通信方式
IP  127.0.0.1 // 默认值
服务端的监听端口 3906//默认值，上位机会判断端口使用情况，轮询找到未被占用的端口

//中文 zh-CN 英文 en-US
1、使用node加载js脚本时，传递地址及端口参数 node.exe "C:/1.js" "127.0.0.1" "3906" "en-US"

2、加载html主服务时，Url添加键值对参数：
<"address", "127.0.0.1">,
<"port","3906">,
<"language","en-US">,
<"softwareVersion", "3.3.0">


解析例子
1、Node加载js
console.log('process.argv:',process.argv)
var arguments = process.argv.splice(2);
var params1 = arguments[0];
var params2 = arguments[1];
var params3 = arguments[2];
var params4 = arguments[3];

console.log('arguments0:',process.argv)
console.log('arguments:',arguments)
console.log('params1:', params1)
console.log('params2:', params2)
console.log('params3:', params3)
console.log('params4:', params4)

2、加载html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>URL Parameter Parser</title>
<script>
function getQueryParam(param) {
    var searchParams = new URLSearchParams(window.location.search);
    return searchParams.get(param);
}

window.onload = function() {
    var paramValue = getQueryParam('example');
    if (paramValue) {
        document.getElementById('param-value').textContent = paramValue;
    } else {
        document.getElementById('param-value').textContent = 'Parameter not found.';
    }
};
</script>
</head>
<body>
<p>URL Parameter 'example': <span id="param-value"></span></p>
</body>
</html>
```

### 2）加载插件PropertyInspector

```JSON
加载PropertyInspector html时，Url添加键值对参数：
<"address", "127.0.0.1">,
<"port","3906">,
<"language","en-US">,
<"uuid", "manifest中UUID">,
<"actionid", "">,
<"key", "0_0">,
<"controller", "Keypad">,
<"device", "dial"> ,
<"softwareVersion", "3.3.0">,
<"isInMultiAction", false|true>,
<"multiActionState", 0|1>
```



### 3）客户端建立连接

```JSON
插件的客户端和服务端连接后，立刻向服务端发送一条信息，信息如下
{
    "code": 0,                                // 0-"success" or 非0-"fail"
    "cmd": "connected",                        //连接命令
    "uuid": "com.ulanzi.ulanzideck.obsstudio"    //插件uuid。同配置文件UUID保持一致。用于区分插件
}
```



## 2、上位机\-\-\-\-\>插件

### 1）执行功能

等同于keydown事件， 协议V2\.0\.x之后，推荐使用keydown/keyup灵活组合使用

用户按下按键执行功能的时候。

```JSON
设置
{
    "cmd": "run",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1"                                     //上位机按键key
    "isInMultiAction": false|true,
    "multiActionState": 0|1 ,  // manifest中 States数组中编号
    "param":{
        // 插件设置的参数，若无，则为空，参数一般为键值对：
        "name": "场景",
        "target": "output"
    }
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "run",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",                                     //上位机按键key
    "param":{}
}
```

### 2）传递参数给插件

每个Action都有一个数据储存空间，存放在当前预设页的json中，param可以理解为当前按键Action的存储空间

插件功能被加载的时候。插件UI功能创建的时候。

```JSON
设置
{
    "cmd": "paramfromapp",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",                                     //上位机按键key
    "param":{
        // 插件设置的参数，若无，则为空，参数一般为键值对：
        "name": "场景",
        "target": "output"
    }
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "paramfromapp",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",                                     //上位机按键key
    "param":{}
}
```

### 3）把插件某个功能配置到按键上

用户拖拽插件功能到key上进行配置的时候。

```JSON
设置
{
    "cmd": "add",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",                                     //上位机按键key
    "controller":"Keypad",                           //当前按键类型 Keypad|Encoder
    "device":"dial",                                 //当前设备类型 d200|d200h|dial
    "isInMultiAction": false|true,
    "multiActionState": 0|1 ,  // manifest中 States数组中编号
    "param":{
         // 插件设置的参数
         // 第一次新建的时候没有参数。为空
         // 上位机从自己的配置里读出来，重新加载的时候有参数，需要设置到此处传递给插件
         "name": "场景",
         "target": "output"
    }
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "add",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",                                    //上位机按键key
    "param":{}
}
```

### 4）插件功能活跃状态设置

功能的实例在当前页时，为激活状态，否则为非激活状态。新增的时候（add）默认为激活状态

激活状态，需要向上位机发送最近一次的执行结果；非激活状态，不需要向上位机发送执行结果。

```JSON
设置
{
    "cmd": "setactive",//
    "active"：true, // true -激活，false-非激活
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "key": "0_1",                                     //上位机按键key
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "setactive",
    "active"：true, // true -激活，false-非激活
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "key": "0_1",                                     //上位机按键key
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "param":{
         // 插件设置的参数
         // 第一次新建的时候没有参数。为空
         // 上位机从自己的配置里读出来，重新加载的时候有参数，需要设置到此处传递给插件
         "name": "场景",
         "target": "output"
    }
}
```

### 5）移除插件的功能配置信息

删除复数个插件功能的功能配置信息，比如删除页面，删除Profile配置的时候

```JSON
设置
{
    "cmd": "clear",
    "param":[
        {
            "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
            "key": "0_1",                                     //上位机按键key
            "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
        }
    ]
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "clear",
    "param":[
        {
            "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
            "key": "0_1",                                     //上位机按键key
            "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
        }
    ]
}
```

### 7）UI接收主服务消息

```JSON
请求
{
    "cmd": "sendToPropertyInspector",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",                                     //上位机按键key
    "payload": "JsonValue"
}
```

### 8）主服务接收UI消息

```JSON
请求
{
    "cmd": "sendToPlugin",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",                                     //上位机按键key
    "payload": "JsonValue"
}
```

### 9）按下按键

按下按键。

[执行功能]相当于keydown，不用处理长按的在
[执行功能]里实现业务没问题，需要处理长按的话就在keydown和keyup手动判断长按和持续按下

```JSON
设置
{
    "cmd": "keydown",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1"                                     //上位机按键key
    "isInMultiAction": false|true,  //是否是在多项操作中
    "multiActionState": 0|1 ,  // 多项操作中 States数组中编号
    "param":{
        // 插件设置的参数，若无，则为空，参数一般为键值对：
        "name": "场景",
        "target": "output"
    }
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "keydown",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",                                     //上位机按键key
    "param":{}
}
```

### 10）释放按键

释放按键。

```JSON
设置
{
    "cmd": "keyup",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1"                                     //上位机按键key
    "isInMultiAction": false|true,  //是否是在多项操作中
    "multiActionState": 0|1 ,  // 多项操作中 States数组中编号
    "param":{
        // 插件设置的参数，若无，则为空，参数一般为键值对：
        "name": "场景",
        "target": "output"
    }
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "keyup",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",                                     //上位机按键key
    "param":{}
}
```

### 11）旋钮按下

按键。

```JSON
设置
{
    "cmd": "dialdown",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111",//功能实例uuid
    "key": "0_1",                                     //上位机按键key
    "isInMultiAction": false|true,  //是否是在多项操作中
    "multiActionState": 0|1 ,  // 多项操作中 States数组中编号
    "param":{
        // 插件设置的参数，若无，则为空，参数一般为键值对：
        "name": "场景",
        "target": "output"
    }
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "dialdown",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",                                     //上位机按键key
    "param":{}
}
```

### 12）旋钮释放

释放按键。

```JSON
设置
{
    "cmd": "dialup",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111",//功能实例uuid
    "key": "0_1",                                     //上位机按键key
    "isInMultiAction": false|true,  //是否是在多项操作中
    "multiActionState": 0|1 ,  // 多项操作中 States数组中编号
    "param":{
        // 插件设置的参数，若无，则为空，参数一般为键值对：
        "name": "场景",
        "target": "output"
    }
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "dialup",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",                                     //上位机按键key
    "param":{}
}
```

### 13）旋钮旋转

旋钮左旋转

```JSON
设置
{
    "cmd": "dialrotate",
    "rotateEvent": "left|right|hold-left|hold—right",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1"                                     //上位机按键key
    "param":{
        // 插件设置的参数，若无，则为空，参数一般为键值对：
        "name": "场景",
        "target": "output"
    }
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "leftrotate",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",                                     //上位机按键key
    "param":{}
}
```

### 14）发送设置参数到Action

插件主服务端： 当一个action主动请求，或是property inspector通过setSettings更新参数
property inspector端： 当一个property inspector主动请求，或是插件主服务端通过setSettings更新参数

```JSON
请求
{
    "cmd": "didReceiveSettings",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",
    "settings":"JsonValue"
}
```

### 15）发送全局设置参数到Action

插件主服务端： 当一个action主动请求，或是property inspector通过setGlobalSettings更新参数
property inspector端： 当一个property inspector主动请求，或是插件主服务端通过setGlobalSettings更新参数

```JSON
请求
{
    "cmd": "didReceiveGlobalSettings",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",
    "settings":"JsonValue"
}
```

### 20）AI Agent状态通知（主服务）

当插件主服务通过 subscribeAiAgentState 订阅对应 AI Agent 后，上位机会在收到该 AI Agent 状态变化时，向插件主服务异步推送 didReceiveAiAgentState。 该协议属于“上位机 \-\-\-\-\> 插件”的独立通知协议，不是 subscribeAiAgentState 的同步返回。

```JSON
{
    "cmd": "didReceiveAiAgentState",
    "cmdType": "NOTIFY",
    "uuid": "com.ulanzi.ulanzideck.ai",
    "payload": {
        "type": "state",
        "agent_id": "codex",
        "hook_source": "ai-tool-state-monitor",
        "session_id": "default",
        "state": "working",
        "event": "PreToolUse",
        "host": "DESKTOP",
        "platform": "windows",
        "timestamp": 1780000000000,
        "title": "session title",
        "model": "gpt-5",
        "provider": "openai"
    }
}
```

payload\.state 取值范围：

```Plain Text
idle          会话已建立，AI Agent 当前空闲
thinking      AI Agent 正在理解、推理或准备回复
working       AI Agent 正在调用工具或处理任务
attention     一轮完成，或需要用户关注
notification  通知消息，或等待权限确认
error         Hook、工具调用或 Agent 执行失败
sleeping      会话结束，或 AI Agent 处于非活跃状态
sweeping      上下文压缩、整理或清理中
```

默认情况下，上位机不会转发以下敏感字段：raw、tool\_input、cwd、source\_pid、agent\_pid、pid\_chain。插件显式设置 include\_raw 为 true 时，才会在 didReceiveAiAgentState 中保留完整 hook payload。



## 3、插件\-\-\-\-\>上位机

### 1）插件参数改变\(JS界面控件上的配置项\)

**协议版本2\.0后不推荐使用，使用 **[**sendToPlugin**]** 和 **[**setSettings**]** 替换该协议。**
**理由：既更新参数，又将参数作为插件端的消息转发机制，耦合严重，已在协议V2\.0中拆分**

插件js界面参数变化的时候

```JSON
设置
{
    "cmd": "paramfromplugin",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",                                     //上位机按键key
    "param":{
        // 插件设置的参数
        "name": "场景",
        "target": "output"
    }
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "paramfromplugin",
    "cmdType": "NOTIFY",                             //通知类型  add 20240715
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",                                     //上位机按键key
    "param":{}
}
```

### 2）\[New In V3\.3\] 更换按键显示的内容设置（如图标，文本）

插件的内容显示需要发生变化的时候

```JSON
设置
{
    "cmd": "state",
    "param":{//图标状态更换，若无则为空
        "statelist":[
            {
                "uuid": "com.ulanzi.ulanzideck.obsstudio.record" //功能uuid
                "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111",//功能实例uuid
                "key": 0_1,                                        //上位机按键key
                "type": 0,
                //type: 不存在字段或为-1，不更新图片
                //0-使用配置里的图标列表编号，请对照manifest.json。
                //1-使用自定义图标。
                //2-使用本地图片文件，
                //3-使用自定义的动图，
                //4-使用本地gif文件
                "state": 1, // 图标列表数组编号。请对照manifest.json 【0或者1】
                "data":"图片base64编码数据",   //    自定义图标base64编码数据
                "path":"D:/1.png" ， //本地图片文件，支持相对路径(非./ / 开始的路径)
                "gifdata":"gif的base64编码数据" //自定义gif的base64编码数据
                "gifpath":"D:/1.gif" //gif文件，支持相对路径(非./ /开始的路径)
                "showtext": false,//需要设置文本时，设置true，不需要时设为false，或者不添加该key-value
                "textdata":"test",    //文本内容
            }
        ]
    }
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "state",
    "cmdType": "NOTIFY",                             //通知类型  add 20240715
    "param":{}
}
```



#### 设置状态

```JSON

{
    "cmd": "setState",
    "param":{//图标状态更换，若无则为空
        "uuid": "com.ulanzi.ulanzideck.obsstudio.record" //功能uuid
        "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111",//功能实例uuid
        "key": 0_1,
        "state": 1,  // 必填 0或者1
    }
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "setState",
    "cmdType": "NOTIFY",                             //通知类型  add 20240715
    "param":{}
}
```

#### 设置图标

```JSON

{
    "cmd": "setImage",
    "param":{
        "uuid": "com.ulanzi.ulanzideck.obsstudio.record" //功能uuid
        "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111",//功能实例uuid
        "key": "0_1",  //上位机按键key
        "isDefault": true,    //true表示更新的是默认图标 false表示更新的是临时状态，不填默认是true
         //以骰子插件为例，默认是一个图标，运行结果是临时状态，运行后点击恢复默认，恢复的是默认图标
        "icons":[
            {
              "state": 0,
              "source": "path",
              "path": "images/icon_off.png"
            },
            {
              "state": 1,
              "source": "path",
              "path": "images/icon_off.png"
            }
        ]
    }
}

{
    "cmd": "setImage",
    "param":{
        "uuid": "com.ulanzi.ulanzideck.obsstudio.record" //功能uuid
        "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111",//功能实例uuid
        "key": "0_1",  //上位机按键key
        "isDefault": false,  //只能设置当前状态的临时图
        "icons": {
            "source": "path",
            "path": "images/icon_off.png"
        }
    }
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "setImage",
    "cmdType": "NOTIFY",                             //通知类型  add 20240715
    "param":{}
}
```



```Plain Text
**Icons设置**

source 取值
source=path 默认值。使用 path 加载图标。
{
  "icons": [
    {
      "state": 0,
      "source": "path",
      "path": "images/icon_off.png"
    }
  ]
}
source 可省略：
{
  "icons": [
    {
      "state": 0,
      "path": "images/icon_off.png"
    }
  ]
}

source=base64
使用 base64 数据作为图标来源。
{
  "icons": [
    {
      "state": 0,
      "source": "base64",
      "base64 ": "data:image/png;base64,iVBORw0KGgoAAA..."
    }
  ]
}

source=state
表示复用某个状态的原始默认图标。
注意：复用的是 action 原始默认图标路径，不是当前运行时图标缓存，也不是用户自定义图标。
让 state=1 复用 state=0 的默认图标：
{
  "icons": [
    {
      "state": 1,
      "source": "state",
      "index": 0
    }
  ]
}

混合 path 和 state
state=0 使用指定图片，state=1 复用原始 state=0 默认图标：
{
  "icons": [
    {
      "state": 0,
      "path": "images/icon_off.png"
    },
    {
      "state": 1,
      "source": "state",
      "index": 0
    }
  ]
}


source=clear
清除指定状态的运行默认图标。
{
  "icons": [
    {
      "state": 1,
      "source": "clear"
    }
  ]
}
清除后，该状态会回到原本默认图标逻辑。

clear=true
清除当前 action 的全部运行默认图标。
{
  "clear": true
}
```





#### 设置标题

```JSON

{
    "cmd": "setTitle",
    "param":{//图标状态更换，若无则为空
        "uuid": "com.ulanzi.ulanzideck.obsstudio.record" //功能uuid
        "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111",//功能实例uuid
        "key": 0_1,
        "text":"text",    //文本内容
    }
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "setTitle",
    "cmdType": "NOTIFY",                             //通知类型  add 20240715
    "param":{}
}
```

### 3）请求上位机使用浏览器打开url，用户登录

```JSON
请求
{
    "cmd": "openurl",
    "url": "http://www.baidu.com", //网址
    "local": false  // 未设置该字段时默认为false, false-远端，true-本地
    "param": {
        "key1":"value1",
        "key2":"value2",
    }
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "openurl",
    "cmdType": "NOTIFY",                             //通知类型  add 20240715
    "url": "http://www.baidu.com" //网址
    "local": false  // 未设置该字段时默认为false, false-远端，true-本地
}
```

### 4）请求上位机显示弹窗

```JSON
请求
{
    "cmd": "openview",
    "url": "C:/test.html" //html文件路径
    "width": 200, // 窗口宽度
    "height": 200, // 窗口高度
    "x": 100, // 窗口左上角X位置
    "y": 100, // 窗口左上角Y位置
    "param": {
        "key1":"value1",
        "key2":"value2",
    }
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "openview"
    "cmdType": "NOTIFY",                             //通知类型  add 20240715
}
// 注意：弹窗后，test.html需要主动关闭，测试到window.close()可以通知弹窗关闭
```

### 5）请求上位机弹出选择对话框

```JSON
请求
{
    "cmd": "selectdialog",
    "type": "file", // file-选择文件框，folder-选择文件夹框
    "filter": "image(*.jpg *.png *.gif)" // filter在type=file时使用
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "selectdialog",
    "cmdType": "REQUEST",                             //请求类型  add 20240715
    "type": "file",
    "filter": "image(*.jpg *.png *.gif)",
    "path": "C:/1.png"   // 文件（夹）路径
}
```

### 6）Toast消息提示

插件请求上位机弹出Toast消息提示

```JSON
请求
{
    "cmd": "toast",
    "msg": "这是一个toast消息提示"
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "toast",
    "cmdType": "NOTIFY",                             //通知类型  add 20240715
    "msg": "这是一个toast消息提示"
}
```

### 7）请求上位机执行组合键

mac端会受系统权限影响

```JSON
请求
{
    "cmd": "hotkey",
    "keylist": "Ctrl+S"
}
返回
{
    "code": 0,                                       // 0-"success" or 非0-"fail"
    "cmd": "hotkey",
    "cmdType": "NOTIFY",                             //通知类型
    "keylist": "Ctrl+S"
}

mac下特殊组合键的字符：
⇧
⌃
⌥
⌘
例如：
mac下复制 "⌘ C" //中间带空格
windows下复制 "Ctrl+C" //中间带+号
```

> 组合键有任何问题请联系@陈旭东
>
>

### 8）打印log到文件

log文件位置: \~/AppData\\Roaming\\Ulanzi\\UlanziDeck\\logs\\主服务UUID\.log

```JSON
请求
{
    "cmd": "logMessage",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",                                     //上位机按键key
    "message": "string",     保存到插件UUID.txt中
    "level": "info|debug|warn|error"    //发布版本默认debug及以上，通过启动参数--logLevel=info指定
                                        //不传入默认info
}
```

### 9）SendToPropertyInspector \(主服务\)

会触发[UI接收主服务消息]

```JSON
请求
{
    "cmd": "sendToPropertyInspector",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",                                     //上位机按键key
    "payload": "JsonValue"
}
```

### 10）SendToPlugin （UI）

会触发[主服务接收UI消息]

```JSON
请求
{
    "cmd": "sendToPlugin",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",                                     //上位机按键key
    "payload": "JsonValue"
}
```

### 11）按键上显示错误提示

错误提示会自动消失

```JSON
请求
{
    "cmd": "showAlert",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",
}
```

### 12）保存Action参数

非Active状态下不保存：一些延迟操作如果没注意此点，容易产生bug

```JSON
请求
{
    "cmd": "setSettings",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",
    "settings":"JsonValue"
}
```

### 13）主动获取Action参数

会触发 [发送Action设置参数]
非Active状态下不触发

```JSON
请求
{
    "cmd": "getSettings",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",
}
```



### 14\) 设置旋钮布局

```JSON
请求
{
    "cmd": "setFeedbackLayout",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",
    "layout":"$UA1",
    or
    "layout":"custom-layout.json" //待实现
}
```



### 15\) 设置旋钮布局元素

```JSON
请求
{
    "cmd": "setFeedback",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",
    "layout": {
        "title": {  //[预置布局]中的text元素的key值
            "text": "new text"
            ... //该元素任意属性值
        },
        "icon": {  //[预置布局]中的pixmap元素的key值
            "value": "Images/new.png"
            ... //该元素任意属性值
        }
    }
}
```



### 16\) 设置全局参数\(beta\)

```JSON
使用单个action进行请求时：
请求
{
    "cmd": "setGlobalSettings",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",
    "settings": {
        "key1": {
            "value1": "new text"
        },
        "key2": {
            "value2": "Images/new.png"
        }
    }
}

主服务进行请求时，会转发给与上位机建立connect的子服务
请求
{
    "cmd": "setGlobalSettings",
    "uuid": "com.ulanzi.ulanzideck.obsstudio", //功能uuid
    "settings": {
        "key1": {
            "value1": "new text"
        },
        "key2": {
            "value2": "Images/new.png"
        }
    }
}
转发子服务：
{
    "cmd": "didReceiveGlobalSettings",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "settings": {
        "key1": {
            "value1": "new text"
        },
        "key2": {
            "value2": "Images/new.png"
        }
    }
}
```



### 17\) 获取全局参数\(beta\)

会触发[发送全局设置参数到Action]

```JSON
请求
{
    "cmd": "getGlobalSettings",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //功能uuid
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//功能实例uuid
    "key": "0_1",
}
```



### 18）订阅AI Agent状态与上下文能力（主服务）

插件主服务需要先订阅某个AI Agent，才可以接收该AI Agent的状态通知，并调用该AI Agent的项目列表、会话列表查询协议。 Action 和 PropertyInspector 不直接订阅，主服务收到状态后可通过现有 sendToPropertyInspector / sendToPlugin 协议转发给需要的界面或功能实例。

订阅只在当前 WebSocket 连接生命周期内有效。插件断开连接或重启后，上位机会清理订阅状态，插件需要在重新 connected 后再次订阅。

请求

```JSON
{
    "cmd": "subscribeAiAgentState",
    "uuid": "com.ulanzi.ulanzideck.ai", // 插件主服务UUID
    "payload": {
        "agent_ids": ["claude-code", "codex"], // AI AgentID。为空数组或["*"]表示订阅所有支持的AI Agent
        "states": ["working", "idle"],         // 可选。为空数组表示不过滤状态
        "events": [],                           // 可选。为空数组表示不过滤事件
        "include_raw": false                    // 可选。默认false，是否转发hook原始数据
    }
}
```

返回

```JSON
{
    "code": 0,
    "cmd": "subscribeAiAgentState",
    "cmdType": "REQUEST",
    "uuid": "com.ulanzi.ulanzideck.ai",
    "payload": {
        "subscribed": true,
        "agent_ids": ["claude-code", "codex"],
        "states": ["idle", "working"],
        "events": [],
        "include_raw": false
    }
}
```

订阅成功后，AI Agent状态由上位机通过“上位机\-\-\-\-\>插件”章节中的 didReceiveAiAgentState 协议异步推送。 默认情况下，上位机不会转发以下敏感字段：raw、tool\_input、cwd、source\_pid、agent\_pid、pid\_chain。插件显式设置 include\_raw 为 true 时，才会在 didReceiveAiAgentState 中保留完整 hook payload。

### 19）取消订阅AI Agent状态与上下文能力（主服务）

请求

```JSON
{
    "cmd": "unsubscribeAiAgentState",
    "uuid": "com.ulanzi.ulanzideck.ai",
    "payload": {
        "agent_ids": ["codex"] // 为空数组或["*"]表示取消当前主服务的全部AI Agent订阅
    }
}
```

返回

```JSON
{
    "code": 0,
    "cmd": "unsubscribeAiAgentState",
    "cmdType": "REQUEST",
    "uuid": "com.ulanzi.ulanzideck.ai",
}
```



### 20）获取AI Agent项目列表（主服务）

插件必须已订阅对应 agent\_id，才可以查询该AI Agent的项目列表。

请求

```JSON
{
    "cmd": "getAiAgentProjects",
    "uuid": "com.ulanzi.ulanzideck.ai",
    "payload": {
        "agent_id": "codex"
    }
}
```

返回

```JSON
{
    "code": 0,
    "cmd": "getAiAgentProjects",
    "cmdType": "REQUEST",
    "uuid": "com.ulanzi.ulanzideck.ai",
    "payload": {
        "agent_id": "codex",
        "projects": [
            {
                "project_id": "project-id",
                "name": "project name",
                "path": "D:/workspace/project",
                "session_count": 1,
                "last_activity": "2026-06-04T10:00:00Z"
            }
        ]
    }
}
```

未订阅对应AI Agent时返回

```JSON
{
    "code": 403,
    "cmd": "getAiAgentProjects",
    "cmdType": "REQUEST",
    "uuid": "com.ulanzi.ulanzideck.ai",
    "error": "Plugin is not subscribed to this AI agent."
}
```

### 21）获取AI Agent会话列表（主服务）

插件必须已订阅对应 agent\_id，才可以查询该AI Agent指定项目下的会话列表。

请求

```JSON
{
    "cmd": "getAiAgentSessions",
    "uuid": "com.ulanzi.ulanzideck.ai",
    "payload": {
        "agent_id": "codex",
        "project_id": "project-id"
    }
}
```

返回

```JSON
{
    "code": 0,
    "cmd": "getAiAgentSessions",
    "cmdType": "REQUEST",
    "uuid": "com.ulanzi.ulanzideck.ai",
    "payload": {
        "agent_id": "codex",
        "project_id": "project-id",
        "sessions": [
            {
                "session_id": "session-id",
                "title": "session title",
                "cwd": "D:/workspace/project",
                "created_at": "2026-06-04T09:00:00Z",
                "updated_at": "2026-06-04T10:00:00Z"
            }
        ]
    }
}
```

未订阅对应AI Agent时返回

```JSON
{
    "code": 403,
    "cmd": "getAiAgentSessions",
    "cmdType": "REQUEST",
    "uuid": "com.ulanzi.ulanzideck.ai",
    "error": "Plugin is not subscribed to this AI agent."
}
```



# 三、启动参数

```C++
//启动参数
//windows下
右键Ulanzi Studio应用程序点击属性，在目标栏中末尾添加启动参数

//macOS下
//控制台
cd /Applications/Ulanzi Studio.app/Contents/MacOS
//目前没法将可执行文件加入系统辅助功能权限，会导致无法使用快捷键功能，待解决
open UlanziDeck --args --log 或 ./UlanziDeck --log

//无需控制台
open /Applications/Ulanzi\ Studio.app --args --log --webRemoteDebug


/**
 *  开启控制台，默认不开启 MacOS下不支持，通过终端启动自带控制台
 **/
#define ENABLE_CONSOLE          "--console"
/**
 *  开启日志打印，默认不开启，同时打开插件日志
 **/
#define ENABLE_LOG_PRINT        "--log"
/**
 *  插件日志输出（logMessage 协议）等级，默认为debug，共有info|debug|warn|error. 示例 UlanziDeck.exe --logLevel=info
 **/
#define ENABLE_LOG_LEVEL        "--logLevel"
/**
 *  开启双击触发按键功能，触发run事件 以及 keydown事件，默认不开启
 **/
#define ENABLE_DOUBLE_CLICK     "--doubleClick"

/**
 *  开启插件加载按钮
 **/
#define PLUGIN_PLUGIN_LOAD       "--pluginLoad"

/**
 *  打开Html插件的远程调试
 *  默认端口9292, 通过浏览器打开localhost:9292, 可以远程调试所有加载的html插件
 *  V2.1版本前可以通过--webEngineArgs --remote-debugging-port=<portnumber>的附加参数打开远程调试
 **/
#define WEBVIEW_REMOTE_DEBUG    "--webRemoteDebug"

/**
 * 设置Html插件的远程调试的端口 例：--webRemotePort=9292
**/
#define WEBVIEW_REMOTE_PORT     "--webRemotePort"

/**
 *  打开NodeJS插件的远程调试
 *  在NodeJS插件的manifest.json中配置"Inspect":"--inspect=[host:port]",默认127.0.0.1:9229,
 *  浏览器打开chrome://inspect, 非默认端口时向Discover network targets中添加当前端口，进行调试。
 **/
#define NODEJS_REMOTE_DEBUG     "--nodeRemoteDebug"



```

# 四、数据类型

## 多语言文件名

```JSON
中文：   zh_CN.json
中文繁体：zh_HK.json
英文：   en.json
日语：    ja_JP.json
德语：   de_DE.json
韩语：    ko_KR.json
葡萄牙：  pt_PT.json
西班牙：  es_ES.json
```

## 设备型号

```JSON
D200
D200H
Dial
D200X
AU05
```
