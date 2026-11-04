# JavaScript Plugin Development Protocol — V3.1.0

English translation of the supplied V3.1.0 protocol. Command names, property names, wire values, version requirements, and documented behavior are preserved; human-readable sample text is translated. The examples retain the source's illustrative pseudocode, legacy material, and inconsistencies and are not all executable JSON. Consult the [implementation notes](protocol-v3.1-notes.md) before implementing or copying an example.


## Version history

| Date | Protocol version | Changes | Host version |
|---|---|---|---|
|2024-5-8|V1.0.2.7<br>|Added commands for sending GIF images and opening a URL window from a plugin.||
|2024-5-8|V1.0.2.8|Added text transmission.||
|2024-5-13<br>|V1.1.0<br>|1. Changed the URL-window command: removed the close command; the window now closes itself.<br>2. Removed font settings from text transmission because the host provides font settings.<br>3. The host server address and port are no longer fixed; they are passed as startup arguments to the script or HTML page.<br>4. Removed clearall and init; added setactive.<br>5. Added actionid to action instances.||
|2024-5-15|V1.1.1|Updated QA-3 and added QA-5.||
|2024-6-03<br>|V1.1.2|Added a manifest.json option for multi-action support; previously, support was enabled when the field was omitted.||
|2024-07-09<br>|V.1.2.0|Added HTML startup parameters.<br>openurl supports plugin-root URLs beginning with / or ./ .<br>Added selectdialog to return a file/folder path.<br>Added toast for host notifications.||
|2024-07-15<br>|V.1.2.1|Responses to plugin-to-host commands include cmdType.<br>~~Use of openview is not recommended.~~||
|2024-10-26|V1.2.2|openView defaults to a centered window when x and y are omitted.<br>openView supports cross-origin requests.<br>openView/openUrl pass HTML parameters through param.||
|2025-07-01|V1.3.0<br>|Added action controller types: Keypad and Encoder.<br>Added Encoder layouts and automatic state-update configuration.<br>Added application monitoring and plugin-specific configuration.<br>Added 14 host-to-plugin commands, numbered 06–19.||
|2025-07-10|V1.3.1|Added hotkey to request host execution of a keyboard shortcut.|V1.7.2|
|2025-09-09<br>|V2.0.0<br>|Added keydown and keyup; renamed keypress to keydown.<br>Removed long-press-start and long-press-end events.<br>Consolidated dial rotation events into one command.<br>Added logMessage for file logging and showAlert for a temporary key error icon.<br>Added controller and device fields to add and HTML startup parameters.<br>Property Inspector HTML backgrounds must be transparent.<br>Added main-service/Property Inspector messaging independent of param.<br>Added didReceiveSettings, setSettings and getSettings; combine these with sendToPlugin/sendToPropertyInspector to replace paramfromplugin.|V2.1|
|2025-10-29|V2.0.1<br>|Enabled the minimum host version in manifest.json and migrated it to a new field.<br>Added NodeJS debugging fields to manifest.json.<br>Added startup-argument notes.||
|2025-11-06<br>|V2.0.2|Added fields for installing plugin scripts into third-party applications:<br>"InstallToDepsApp": {<br>"Type": "JavaScript",<br>"CodePath": "install/test.js"<br>},||
|2025-11-17<br>|V2.0.3|Added localization filename conventions and manifest multi-device configuration notes.||
|2025-11-26|V2.1.0<br>|Added D200X dial layouts and layout elements.<br>Added setFeedbackLayout and setFeedback.|V3.0.1|
|2025-12-18|V2.1.1|Added global settings: setGlobalSettings, getGlobalSettings, and delivery of global settings to actions.|V2.1.19<br>V3.0.2|
|2026-1-13|V2.1.2|Updated setGlobalSettings: the main-service UUID can update global settings without actionID; updates are forwarded to child services that are already connected.|V3.0.5<br>|
|2026-6-4|V3.0.0|Added AI Agent state/context subscriptions.<br>Added subscribeAiAgentState, unsubscribeAiAgentState, getAiAgentProjects and getAiAgentSessions.<br>Added didReceiveAiAgentState, didReceiveAiAgentProjects and didReceiveAiAgentSessions responses.<br>The main service must subscribe to an AI Agent before receiving its state or querying projects/sessions.<br>While hook-installation guidance remains incomplete, this capability is enabled only when an Au05 device is online.|V3.2.0|
|2026-7-9<br>|V3.1.0<br>|Manifest: States[].Name is required; added States[].MultiActionImage for multi-action icons; added SupportedInKeyLogicActions to control visibility in action-trigger plugins; added Detail, Banner and URL for UGC upload parsing.<br>Plugin startup adds softwareVersion.<br>addAction, run, keydown, keyup and Property Inspector startup add isInMultiAction and multiActionState for selected-state execution.<br>Added setState, setImage and setTitle to update key display content.|V3.3.0|

# I. Plugin package

After the package is installed in the designated folder, the host detects and loads it, parses manifest.json, displays its actions, and loads its libraries and resources.

## 1. Folder naming

```JSON
Use the folder format com.ulanzi.{pluginName}.ulanziPlugin, for example com.ulanzi.obsstudio.ulanziPlugin. Follow this format for consistency.
The folder normally contains manifest.json, localization files, plugin libraries, images, and other resources.
```

## 2. Configuration file

The following is an illustrative example.

Each action's `States` array must contain one or two entries only, with indices 0 and optionally 1. The manifest default `state`, `setState`, and `multiActionState` must reference an existing entry. More display variants, such as weather conditions or progress steps, use dynamic image/title updates rather than additional declared states. See [Action state limits](protocol-v3.1-notes.md#action-state-limits).

```JSON
manifest.json
{
        "Author": "Ulanzi",   //Parsed into the UGC upload form
        "Name": "OBS Studio",  //Parsed into the UGC upload form
        "Description": "OBS Studio Operation",  //Short introduction; parsed into the UGC upload form
        "Detail": "",    //Detailed introduction; parsed into the UGC upload form
        "Icon": "resources/store_icon.png",  //Parsed into the UGC upload form
        "Version": "1.0.1",  //Parsed into the UGC upload form
        "Category": "OBS Studio",
        "CategoryIcon": "resources/icon.png",
        "CodePath": "source/main.html", // The entrypoint may be .html (loaded in QWebEngineView) or .js (loaded in Node 20.12.2)
        "Type": "JavaScript",
        "Inspect":"--inspect=127.0.0.1:9201",  //Enable NodeJS remote debugging; each plugin needs a unique port and the host debugging startup flag
        "URL": "Related link"   //Parsed into the UGC upload form
        "Banner": [    //Banner images; parsed into the UGC upload form
            "assets/baaner_1.png",
            "assets/banner_2.png"
        ]
        "PrivateAPI": true,
        "UUID": "com.ulanzi.ulanzideck.obsstudio", //Parsed into the UGC upload form
        "Actions": [
                {

                        "Name": "Record",
                        "Icon": "resources/actions/record/icon.png",
**                        "PropertyInspectorPath": "source/actions/record/action_record_inspector.html",**
                        "state": 0,
                        "States": [
                                {
                                       "Name": "Start",  //Required
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
                        "SupportedInKeyLogicActions": true,  //Whether the action is available in action-trigger plugins; defaults to true
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
                        "DisableAutomaticStates": true,    // Whether automatic state updates are supported
                        "Controllers": [ //Action controller types
                                    "Encoder",     //Encoder
                                    "Keypad"       //Keypad
                                ],
                        "Encoder": { //Encoder settings
                                "layout": "$B1", // "Layout"
                                ~~"TriggerDescription": { //Encoder interactions~~
~~                                    "Rotate": "Adjust volume", ~~
~~                                    "Push": "Mute/unmute",~~
~~                                    "Touch": "Mute/unmute" // Touch~~
~~                                    "LongTouch": "Mute/unmute" // Touch~~
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
                ~~"MinimumVersion": "6.1"~~   This field is deprecated
                "MinVersion":"2.1.0"    No restriction when this field is omitted
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
Field descriptions:
{
        "Author": "Ulanzi", //Developer
        "Name": "OBS Studio",//Plugin name shown in the host plugin list
        "Description": "OBS Studio Operation",//Plugin description
        "Icon": "resources/store_icon.png", //Plugin icon shown in the host plugin list; supports svg, png and jpg
        "Version": "1.0.1",//Version
        "Category": "OBS Studio",//Category
        "CategoryIcon": "resources/icon.png",//Plugin category icon
        "CodePath": "source/main.html",//Plugin entrypoint
        "Type": "JavaScript",//Plugin implementation language
        "PrivateAPI": true,//Plugin API type
        "UUID": "com.ulanzi.ulanzideck.obsstudio",//Plugin ID
        "Actions": [
                {
                        "Name": "Record",//  Action icon shown in the host plugin list
                        "Icon": "resources/actions/record/icon.png", //  Action name shown in the host plugin list
                        "PropertyInspectorPath": "source/actions/record/action_record_inspector.html",//(Path to the JavaScript action inspector HTML)
                        "state": 0,     //  Icon state index; defaults to 0
                        "States": [    //  Icon list
                                {
                                        "Name": "Start",//Not currently used by the host in this legacy example; used by the plugin
                                        "Image": "resources/actions/record/on.png"    // Icon path
                                },
                                {
                                        "Name": "Stop",
                                        "Image": "resources/actions/record/off.png"    // Icon path
                                }
                        ],
                        "Tooltip": "Start/Stop recording to file",//  Action tooltip shown in the host plugin list
                        "UUID": "com.ulanzi.ulanzideck.obsstudio.record"//  Action ID,
                        "SupportedInMultiActions": false, // Whether the action supports multi-actions
                        "DisableAutomaticStates": true,    // Whether automatic state updates are supported
                        "Controllers": [ //Action controller types
                                    "Encoder",     //Encoder
                                    "Keypad"       //Keypad
                                ],
                        "Encoder": { //Encoder settings
                                "layout": "$B1", //
                                ~~"TriggerDescription": { //Encoder interactions~~
~~                                    "Rotate": "Adjust volume", ~~
~~                                    "Push": "Mute/unmute",~~
~~                                    "Touch": "Mute/unmute" // Touch~~
~~                                    "LongTouch": "Mute/unmute" // Touch~~
~~                                }~~
                        }
                }
        ],
        "OS": [//Supported operating systems
                {
                        "Platform": "windows",//Platform
                        "MinimumVersion": "10"//Minimum OS version
                },
                {
                        "Platform": "mac", //Platform
                        "MinimumVersion": "10.11"//Minimum OS version
                }
        ],
        "Software": {//Host software
                "MinimumVersion": "6.1"//Minimum host software version
        },
        "ApplicationsToMonitor": { //The host monitors these applications for start/stop events
            "windows": [
                "obs32.exe",
                "obs64.exe"
            ],
            "mac": [
                "com.obsproject.obs-studio"
            ]
        },
        "Profiles": [//Profiles associated with the plugin
            {
                "Name": "My Cool Profile",
                "DeviceType": 0,
                "Readonly": false,
                "DontAutoSwitchWhenInstalled": false,
                "AutoInstall": true
            }
        ],
        "InstallToDepsApp": { //Plugin script to install into a third-party application
                "Type": "JavaScript",
                "CodePath": "install/test.js"// Script path inside the plugin package
        },
}
In com.ulanzi.ulanzideck.obsstudio.record:
com.ulanzi.ulanzideck.obsstudio identifies the plugin; record identifies the action.
```

## 3. Multi-device support

```JSON
manifest.json
{
    ...
    //Configure multi-device support separately for each action
    "Actions": [
    {
        ...
        //Controllers: supported control types. On Dial or D200X, an action appears only on the declared Keypad/Encoder surfaces. When omitted, it defaults to Keypad.
        "Controllers": [ //Action controller types
                    "Encoder",     //Encoder
                    "Keypad"       //Keypad
                ],

        //Devices: the action is visible only on the listed supported devices
        //An absent or empty Devices field accepts all devices
        "Devices": [],

        //List supported model identifiers: D200 | D200H | Dial | D200X | D100N
        "Devices": ["Dial", "D100N"],


        //Prefix a model with ~ to exclude it; exclusions may be combined with normal model identifiers
        "Devices": ["~Dial"]
        ...
}


    ],
    ....
}

```

## 4. D200X layout protocol

### 1. Declare the layout in the manifest

```JSON
manifest.json
{
    ...
    //Configure multi-device support separately for each action
    "Actions": [
    {
        ...
        {
            ...
            "Name": "Action One",
            "Encoder": { //Encoder settings
                    //Use a preset layout
                    "layout": "$UA1",

                    //Use a custom layout
                    "layout": "layout.json", //File path relative to the directory containing manifest.json
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

### 2. Set the layout through the communication protocol

[Set dial layout]

### 3. Layout coordinates

The layout is 126 × 140. Its top-left corner is (0, 0), and its bottom-right corner is (126, 140).

### 4. Preset layouts

#### 1. $UA1 (icon + text)

```Bash
{
    "id":"$UA1",
    "items": [
        {
            "type": "pixmap",
            "key": "icon",   //When key is icon, use the normal key icon; other keys are not automatically stored/restored and require explicit updates
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
            "key": "title",  //When key is title, use the normal key title; other keys are not automatically stored/restored and require explicit updates
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

#### 2. $UA2 (text + text)

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
            "key": "title",  //When key is title, use the normal key title; other keys are not automatically stored/restored and require explicit updates
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

## 5. D200X layout elements

### 1. Text element (Type: "text")

#### Purpose

Renders text with font styling, alignment, and overflow handling, for example status information or numeric feedback.

#### Properties

| Property | Type | Default | Required | Constraints | Description |
|---|---|---|---|---|---|
|type|string|\-|Yes|Fixed value "text"|Element type identifier|
|key|string|\-|Yes|Unique within the layout|Element identifier|
|background|string|\-|No|Named colors (e.g. "white"), hexadecimal colors (e.g. "\#204cde"), or gradients (e.g. "0:\#ff0000,1:\#00ff00")|Element background color or gradient<br>|
|enabled|boolean|true|No|\-|Whether the element is enabled (hidden when false)|
|opacity|number|1|No|Range 0.1–1, in increments of 0.1|Element opacity|
|rect|Rect|\-|Yes|x/y/width/height are nonnegative integers within 200×100|Element position and size|
|zOrder|number|0|No|Range 0–700|Stacking order (larger values are drawn above smaller values)|
|alignment|"center"/"left"/"right"|"center"|No|When key="title", the user's title settings in Ulanzi Studio take precedence|Horizontal text alignment|
|color|string|"white"|No|Named colors (e.g. "red") or hexadecimal colors (e.g. "\#ff6b6b")<br>When key="title", the user's title settings in Ulanzi Studio take precedence|Text color|
|font<br>|Font|\-|No|Nested object; size is required when font is specified<br>When key="title", the user's title settings in Ulanzi Studio take precedence|Font styling|
|text|string|\-|Yes|No length limit; use textOverflow to handle overflow|Text to display|

#### Example

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

### 2. Image element (Type: "pixmap")

#### Purpose

Renders images from local paths or Base64-encoded data, for example icons, logos, or status indicators.

#### Properties

| Property | Type | Default | Required | Constraints | Description |
|---|---|---|---|---|---|
|type|string|\-|Yes|Fixed value "pixmap"|Element type identifier|
|key|string|\-|Yes|Unique within the layout|Element identifier|
|background|string|\-<br>|No|Named colors (e.g. "white"), hexadecimal colors (e.g. "\#204cde"), or gradients (e.g. "0:\#ff0000,1:\#00ff00")|Element background color or gradient|
|enabled|boolean|true|No|\-|Whether the element is enabled (hidden when false)|
|opacity|number|1|No|Range 0.1–1, in increments of 0.1|Element opacity|
|rect|Rect|\-|Yes|x/y/width/height are nonnegative integers within 200×100|Element position and size|
|zOrder|number|0|No|Range 0–700|Stacking order (larger values are drawn above smaller values)|
|value|string|\-|Yes|Two accepted formats: 1. Local path relative to the plugin root; 2. Base64 string with a complete MIME type|Image source<br>|

#### Source formats

- Local path: supports PNG, JPEG, SVG, and other common formats. Paths are relative to the plugin root; for example, "icons/mute.png" refers to mute.png in the package's icons folder.

- Base64 data: use `data:[MIME type];base64,[encoded string]`, for example "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADIAAAAyCAMAAAAp4XiDAAAAUVBMVEWFhYWDg4N...".

#### Example (local file)

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

#### Example (Base64 data)

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

### 4. Rect type

```JSON
{
    x: number;    // Top-left x coordinate (0–200)
    y: number;    // Top-left y coordinate (0–100)
    width: number;// Element width (0–200-x)
    height: number;// Element height (0–100-y)
};
```

### 5. Range type

```JSON
{
  min: number; // Minimum progress value (required; integer or decimal)
  max: number; // Maximum progress value (required; integer or decimal)
};
```

- Examples: `{ "min": 0, "max": 200 }` for numeric progress from 0 to 200; `{ "min": 0.0, "max": 1.0 }` for normalized values.



# II. Communication

## 1. Server

### 1) Load the plugin main service

```JSON
Communication uses WebSocket.
IP  127.0.0.1 // Default
Server listening port: 3906 // Default; the host checks port availability and searches for an unused port

//Simplified Chinese: zh-CN; English: en-US
1. When loading a JavaScript script with Node, pass address, port and language arguments: node.exe "C:/1.js" "127.0.0.1" "3906" "en-US"

2. When loading an HTML main service, append key/value query parameters to the URL:
<"address", "127.0.0.1">,
<"port","3906">,
<"language","en-US">,
<"softwareVersion", "3.3.0">


Parsing examples
1. Load JavaScript with Node
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

2. Load HTML
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

### 2) Load the plugin Property Inspector

```JSON
When loading the Property Inspector HTML, append key/value query parameters to the URL:
<"address", "127.0.0.1">,
<"port","3906">,
<"language","en-US">,
<"uuid", "UUID from the manifest">,
<"actionid", "">,
<"key", "0_0">,
<"controller", "Keypad">,
<"device", "dial"> ,
<"softwareVersion", "3.3.0">,
<"isInMultiAction", false|true>,
<"multiActionState", 0|1>
```



### 3) Establish the client connection

```JSON
Immediately after connecting to the server, the plugin client sends:
{
    "code": 0,                                // 0 = "success"; nonzero = "fail"
    "cmd": "connected",                        //Connection command
    "uuid": "com.ulanzi.ulanzideck.obsstudio"    //Plugin UUID; must match the manifest UUID and identifies the plugin
}
```



## 2. Host → plugin

### 1) Execute an action

Equivalent to keydown. From protocol V2.0.x onward, prefer keydown/keyup for flexible press/release handling.

Sent when the user presses a key to execute an action.

```JSON
Request
{
    "cmd": "run",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1"                                     //Host key position
    "isInMultiAction": false|true,
    "multiActionState": 0|1 ,  // Index in the manifest States array
    "param":{
        // Plugin settings, or an empty object when absent; usually key/value pairs:
        "name": "Scene",
        "target": "output"
    }
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "run",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",                                     //Host key position
    "param":{}
}
```

### 2) Pass parameters to the plugin

Each action has storage in the current profile page JSON. param is the storage associated with the action on this key.

Sent when an action is loaded or its plugin UI is created.

```JSON
Request
{
    "cmd": "paramfromapp",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",                                     //Host key position
    "param":{
        // Plugin settings, or an empty object when absent; usually key/value pairs:
        "name": "Scene",
        "target": "output"
    }
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "paramfromapp",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",                                     //Host key position
    "param":{}
}
```

### 3) Assign an action to a key

Sent when the user drags a plugin action onto a key.

```JSON
Request
{
    "cmd": "add",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",                                     //Host key position
    "controller":"Keypad",                           //Current controller type: Keypad|Encoder
    "device":"dial",                                 //Current device type: d200|d200h|dial
    "isInMultiAction": false|true,
    "multiActionState": 0|1 ,  // Index in the manifest States array
    "param":{
         // Plugin settings
         // Parameters are empty when the instance is first created
         // On reload, the host reads saved parameters from its configuration and passes them here to the plugin
         "name": "Scene",
         "target": "output"
    }
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "add",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",                                    //Host key position
    "param":{}
}
```

### 4) Set action active state

An action instance is active when it is on the current page and inactive otherwise. A new instance (add) is active by default.

When active, send the latest execution result to the host. When inactive, no execution result needs to be sent.

```JSON
Request
{
    "cmd": "setactive",//
    "active"：true, // true -active, false = inactive
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "key": "0_1",                                     //Host key position
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "setactive",
    "active"：true, // true -active, false = inactive
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "key": "0_1",                                     //Host key position
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "param":{
         // Plugin settings
         // Parameters are empty when the instance is first created
         // On reload, the host reads saved parameters from its configuration and passes them here to the plugin
         "name": "Scene",
         "target": "output"
    }
}
```

### 5) Remove action configurations

Removes multiple action configurations, for example when deleting a page or profile.

```JSON
Request
{
    "cmd": "clear",
    "param":[
        {
            "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
            "key": "0_1",                                     //Host key position
            "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
        }
    ]
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "clear",
    "param":[
        {
            "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
            "key": "0_1",                                     //Host key position
            "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
        }
    ]
}
```

### 7) UI receives a main-service message

```JSON
Request
{
    "cmd": "sendToPropertyInspector",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",                                     //Host key position
    "payload": "JsonValue"
}
```

### 8) Main service receives a UI message

```JSON
Request
{
    "cmd": "sendToPlugin",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",                                     //Host key position
    "payload": "JsonValue"
}
```

### 9) Key down

The key is pressed.

[Execute an action] is equivalent to keydown. If long-press handling is unnecessary,
implement the behavior in [Execute an action]. Otherwise, use keydown and keyup to detect long presses and sustained presses in the plugin.

```JSON
Request
{
    "cmd": "keydown",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1"                                     //Host key position
    "isInMultiAction": false|true,  //Whether this instance is executing within a multi-action
    "multiActionState": 0|1 ,  // Selected States array index within the multi-action
    "param":{
        // Plugin settings, or an empty object when absent; usually key/value pairs:
        "name": "Scene",
        "target": "output"
    }
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "keydown",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",                                     //Host key position
    "param":{}
}
```

### 10) Key up

The key or dial is released.

```JSON
Request
{
    "cmd": "keyup",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1"                                     //Host key position
    "isInMultiAction": false|true,  //Whether this instance is executing within a multi-action
    "multiActionState": 0|1 ,  // Selected States array index within the multi-action
    "param":{
        // Plugin settings, or an empty object when absent; usually key/value pairs:
        "name": "Scene",
        "target": "output"
    }
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "keyup",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",                                     //Host key position
    "param":{}
}
```

### 11) Dial down

The dial is pressed.

```JSON
Request
{
    "cmd": "dialdown",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111",//Action instance UUID
    "key": "0_1",                                     //Host key position
    "isInMultiAction": false|true,  //Whether this instance is executing within a multi-action
    "multiActionState": 0|1 ,  // Selected States array index within the multi-action
    "param":{
        // Plugin settings, or an empty object when absent; usually key/value pairs:
        "name": "Scene",
        "target": "output"
    }
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "dialdown",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",                                     //Host key position
    "param":{}
}
```

### 12) Dial up

The key or dial is released.

```JSON
Request
{
    "cmd": "dialup",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111",//Action instance UUID
    "key": "0_1",                                     //Host key position
    "isInMultiAction": false|true,  //Whether this instance is executing within a multi-action
    "multiActionState": 0|1 ,  // Selected States array index within the multi-action
    "param":{
        // Plugin settings, or an empty object when absent; usually key/value pairs:
        "name": "Scene",
        "target": "output"
    }
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "dialup",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",                                     //Host key position
    "param":{}
}
```

### 13) Dial rotation

The dial rotates left.

```JSON
Request
{
    "cmd": "dialrotate",
    "rotateEvent": "left|right|hold-left|hold—right",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1"                                     //Host key position
    "param":{
        // Plugin settings, or an empty object when absent; usually key/value pairs:
        "name": "Scene",
        "target": "output"
    }
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "leftrotate",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.scene", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",                                     //Host key position
    "param":{}
}
```

### 14) Deliver action settings

Main service: sent when an action requests settings or the Property Inspector updates them through setSettings.
Property Inspector: sent when it requests settings or the main service updates them through setSettings.

```JSON
Request
{
    "cmd": "didReceiveSettings",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",
    "settings":"JsonValue"
}
```

### 15) Deliver global settings to an action

Main service: sent when an action requests global settings or the Property Inspector updates them through setGlobalSettings.
Property Inspector: sent when it requests global settings or the main service updates them through setGlobalSettings.

```JSON
Request
{
    "cmd": "didReceiveGlobalSettings",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",
    "settings":"JsonValue"
}
```

### 20) AI Agent state notification (main service)

After the main service subscribes to an AI Agent through subscribeAiAgentState, the host asynchronously pushes didReceiveAiAgentState when that agent changes state. This is an independent host-to-plugin notification, not the synchronous response to subscribeAiAgentState.

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

Allowed payload.state values:

```Plain Text
idle          Session established; the AI Agent is idle
thinking      The AI Agent is interpreting, reasoning, or preparing a response
working       The AI Agent is calling tools or processing a task
attention     A turn has completed or user attention is needed
notification  Notification or waiting for permission
error         Hook, tool call, or agent execution failed
sleeping      Session ended or the AI Agent is inactive
sweeping      Compacting, organizing, or cleaning up context
```

By default, the host omits the sensitive fields raw, tool_input, cwd, source_pid, agent_pid and pid_chain. The full hook payload is retained in didReceiveAiAgentState only when the plugin explicitly sets include_raw to true.



## 3. Plugin → host

### 1) Plugin parameters changed (JavaScript UI settings)

**Deprecated from protocol 2.0 onward. Use sendToPlugin and setSettings instead.**
**Reason: combining settings updates with plugin message forwarding caused tight coupling; these responsibilities were separated in protocol V2.0.**

Sent when settings in the plugin JavaScript UI change.

```JSON
Request
{
    "cmd": "paramfromplugin",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",                                     //Host key position
    "param":{
        // Plugin settings
        "name": "Scene",
        "target": "output"
    }
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "paramfromplugin",
    "cmdType": "NOTIFY",                             //Notification type; added 20240715
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",                                     //Host key position
    "param":{}
}
```

### 2) [New in V3.3] Update key display content (icons and text)

Sent when the plugin needs to change its displayed content.

```JSON
Request
{
    "cmd": "state",
    "param":{//Icon state update; empty if absent
        "statelist":[
            {
                "uuid": "com.ulanzi.ulanzideck.obsstudio.record" //Action UUID
                "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111",//Action instance UUID
                "key": 0_1,                                        //Host key position
                "type": 0,
                //type: omit the field or use -1 to leave the image unchanged
                //0 = use an icon state index from manifest.json
                //1 = use a custom icon
                //2 = use a local image file
                //3 = use custom animation data
                //4 = use a local GIF file
                "state": 1, // Icon state array index from manifest.json (0 or 1 in this example)
                "data":"Base64 image data",   //    Custom icon Base64 data
                "path":"D:/1.png" ， //Local image file; relative paths are supported when not beginning with ./ or /
                "gifdata":"Base64 GIF data" //Custom GIF Base64 data
                "gifpath":"D:/1.gif" //GIF file; relative paths are supported when not beginning with ./ or /
                "showtext": false,//Use true to update text; otherwise use false or omit this field
                "textdata":"test",    //Text content
            }
        ]
    }
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "state",
    "cmdType": "NOTIFY",                             //Notification type; added 20240715
    "param":{}
}
```



#### Set state

```JSON

{
    "cmd": "setState",
    "param":{//Icon state update; empty if absent
        "uuid": "com.ulanzi.ulanzideck.obsstudio.record" //Action UUID
        "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111",//Action instance UUID
        "key": 0_1,
        "state": 1,  // Required; 0 or 1
    }
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "setState",
    "cmdType": "NOTIFY",                             //Notification type; added 20240715
    "param":{}
}
```

#### Set image

```JSON

{
    "cmd": "setImage",
    "param":{
        "uuid": "com.ulanzi.ulanzideck.obsstudio.record" //Action UUID
        "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111",//Action instance UUID
        "key": "0_1",  //Host key position
        "isDefault": true,    //true updates default icons; false updates a temporary display; defaults to true when omitted
         //For a dice plugin, the idle image is the default icon and a roll result is temporary; resetting after a roll restores the default icon
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
        "uuid": "com.ulanzi.ulanzideck.obsstudio.record" //Action UUID
        "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111",//Action instance UUID
        "key": "0_1",  //Host key position
        "isDefault": false,  //Only the current state's temporary image can be updated
        "icons": {
            "source": "path",
            "path": "images/icon_off.png"
        }
    }
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "setImage",
    "cmdType": "NOTIFY",                             //Notification type; added 20240715
    "param":{}
}
```



```Plain Text
**Icon configuration**

source values
source=path is the default. Load the icon from path.
{
  "icons": [
    {
      "state": 0,
      "source": "path",
      "path": "images/icon_off.png"
    }
  ]
}
source may be omitted:
{
  "icons": [
    {
      "state": 0,
      "path": "images/icon_off.png"
    }
  ]
}

source=base64
Use Base64 data as the icon source.
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
Reuse a state's original default icon.
This reuses the action's original default icon path, not the current runtime icon cache or a user-customized icon.
Make state=1 reuse the default icon of state=0:
{
  "icons": [
    {
      "state": 1,
      "source": "state",
      "index": 0
    }
  ]
}

Combine path and state
state=0 uses the specified image; state=1 reuses the original default icon of state=0:
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
Clear the runtime default icon for a specified state.
{
  "icons": [
    {
      "state": 1,
      "source": "clear"
    }
  ]
}
After clearing, that state returns to its original default-icon behavior.

clear=true
Clear all runtime default icons for the current action.
{
  "clear": true
}
```





#### Set title

```JSON

{
    "cmd": "setTitle",
    "param":{//Icon state update; empty if absent
        "uuid": "com.ulanzi.ulanzideck.obsstudio.record" //Action UUID
        "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111",//Action instance UUID
        "key": 0_1,
        "text":"text",    //Text content
    }
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "setTitle",
    "cmdType": "NOTIFY",                             //Notification type; added 20240715
    "param":{}
}
```

### 3) Ask the host to open a URL in the browser for user login

```JSON
Request
{
    "cmd": "openurl",
    "url": "http://www.baidu.com", //URL
    "local": false  // Defaults to false when omitted; false = remote, true = local
    "param": {
        "key1":"value1",
        "key2":"value2",
    }
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "openurl",
    "cmdType": "NOTIFY",                             //Notification type; added 20240715
    "url": "http://www.baidu.com" //URL
    "local": false  // Defaults to false when omitted; false = remote, true = local
}
```

### 4) Ask the host to display a window

```JSON
Request
{
    "cmd": "openview",
    "url": "C:/test.html" //HTML file path
    "width": 200, // Window width
    "height": 200, // Window height
    "x": 100, // Window top-left x coordinate
    "y": 100, // Window top-left y coordinate
    "param": {
        "key1":"value1",
        "key2":"value2",
    }
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "openview"
    "cmdType": "NOTIFY",                             //Notification type; added 20240715
}
// The opened test.html must close itself; window.close() has been observed to close the window
```

### 5) Ask the host to show a file/folder selection dialog

```JSON
Request
{
    "cmd": "selectdialog",
    "type": "file", // file = file picker; folder = folder picker
    "filter": "image(*.jpg *.png *.gif)" // filter is used when type=file
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "selectdialog",
    "cmdType": "REQUEST",                             //Request type; added 20240715
    "type": "file",
    "filter": "image(*.jpg *.png *.gif)",
    "path": "C:/1.png"   // File/folder path
}
```

### 6) Toast notification

The plugin asks the host to display a toast notification.

```JSON
Request
{
    "cmd": "toast",
    "msg": "This is a toast notification"
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "toast",
    "cmdType": "NOTIFY",                             //Notification type; added 20240715
    "msg": "This is a toast notification"
}
```

### 7) Ask the host to execute a keyboard shortcut

On macOS, system permissions affect shortcut execution.

```JSON
Request
{
    "cmd": "hotkey",
    "keylist": "Ctrl+S"
}
Response
{
    "code": 0,                                       // 0 = "success"; nonzero = "fail"
    "cmd": "hotkey",
    "cmdType": "NOTIFY",                             //Notification type
    "keylist": "Ctrl+S"
}

macOS shortcut modifier symbols:
⇧
⌃
⌥
⌘
For example:
macOS copy: "⌘ C" // Separate with a space
Windows copy: "Ctrl+C" // Separate with +
```

> For shortcut issues, contact the SDK maintainers.
>
>

### 8) Write a log message to a file

Log location: \~/AppData\\Roaming\\Ulanzi\\UlanziDeck\\logs\\{mainServiceUUID}.log

```JSON
Request
{
    "cmd": "logMessage",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",                                     //Host key position
    "message": "string",     Saved to {pluginUUID}.txt
    "level": "info|debug|warn|error"    //Release builds default to debug and above; override with the startup argument --logLevel=info
                                        //Defaults to info when omitted
}
```

### 9) SendToPropertyInspector (main service)

Triggers [UI receives a main-service message].

```JSON
Request
{
    "cmd": "sendToPropertyInspector",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",                                     //Host key position
    "payload": "JsonValue"
}
```

### 10) SendToPlugin (UI)

Triggers [Main service receives a UI message].

```JSON
Request
{
    "cmd": "sendToPlugin",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",                                     //Host key position
    "payload": "JsonValue"
}
```

### 11) Show an error on the key

The error indication disappears automatically.

```JSON
Request
{
    "cmd": "showAlert",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",
}
```

### 12) Save action settings

Settings are not saved for inactive instances; take this into account for delayed operations.

```JSON
Request
{
    "cmd": "setSettings",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",
    "settings":"JsonValue"
}
```

### 13) Request action settings

Triggers delivery of action settings.
Not triggered for inactive instances.

```JSON
Request
{
    "cmd": "getSettings",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",
}
```



### 14) Set dial layout

```JSON
Request
{
    "cmd": "setFeedbackLayout",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",
    "layout":"$UA1",
    or
    "layout":"custom-layout.json" //Not yet implemented
}
```



### 15) Set dial layout elements

```JSON
Request
{
    "cmd": "setFeedback",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",
    "layout": {
        "title": {  //Key of a text element in a preset layout
            "text": "new text"
            ... //Any property of this element
        },
        "icon": {  //Key of a pixmap element in a preset layout
            "value": "Images/new.png"
            ... //Any property of this element
        }
    }
}
```



### 16) Set global settings (beta)

```JSON
When requested by an individual action:
Request
{
    "cmd": "setGlobalSettings",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
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

When requested by the main service, the host forwards the settings to child services connected to the host.
Request
{
    "cmd": "setGlobalSettings",
    "uuid": "com.ulanzi.ulanzideck.obsstudio", //Action UUID
    "settings": {
        "key1": {
            "value1": "new text"
        },
        "key2": {
            "value2": "Images/new.png"
        }
    }
}
Forwarded to child services:
{
    "cmd": "didReceiveGlobalSettings",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
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



### 17) Get global settings (beta)

Triggers [Deliver global settings to an action].

```JSON
Request
{
    "cmd": "getGlobalSettings",
    "uuid": "com.ulanzi.ulanzideck.obsstudio.record", //Action UUID
    "actionid": "0c513ceb-4185-4c6f-9f21-57623fe19111"//Action instance UUID
    "key": "0_1",
}
```



### 18) Subscribe to AI Agent state and context (main service)

The plugin main service must subscribe to an AI Agent before receiving its state notifications or querying its projects and sessions. Actions and Property Inspectors do not subscribe directly. The main service can forward received state to interfaces or action instances through sendToPropertyInspector / sendToPlugin.

Subscriptions last only for the current WebSocket connection. The host clears them after disconnection or restart; subscribe again after reconnecting and sending connected.

Request
```JSON
{
    "cmd": "subscribeAiAgentState",
    "uuid": "com.ulanzi.ulanzideck.ai", // Plugin main-service UUID
    "payload": {
        "agent_ids": ["claude-code", "codex"], // AI Agent IDs; an empty array or ["*"] subscribes to all supported agents
        "states": ["working", "idle"],         // Optional; an empty array disables state filtering
        "events": [],                           // Optional; an empty array disables event filtering
        "include_raw": false                    // Optional; defaults to false; whether to forward raw hook data
    }
}
```

Response
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

After subscription succeeds, the host asynchronously pushes AI Agent state through didReceiveAiAgentState in the Host → plugin section. By default, the host omits the sensitive fields raw, tool_input, cwd, source_pid, agent_pid and pid_chain. The full hook payload is retained in didReceiveAiAgentState only when the plugin explicitly sets include_raw to true.

### 19) Unsubscribe from AI Agent state and context (main service)

Request
```JSON
{
    "cmd": "unsubscribeAiAgentState",
    "uuid": "com.ulanzi.ulanzideck.ai",
    "payload": {
        "agent_ids": ["codex"] // An empty array or ["*"] cancels all AI Agent subscriptions for this main service
    }
}
```

Response
```JSON
{
    "code": 0,
    "cmd": "unsubscribeAiAgentState",
    "cmdType": "REQUEST",
    "uuid": "com.ulanzi.ulanzideck.ai",
}
```



### 20) Get AI Agent projects (main service)

The plugin must be subscribed to the corresponding agent_id before querying that agent's projects.

Request
```JSON
{
    "cmd": "getAiAgentProjects",
    "uuid": "com.ulanzi.ulanzideck.ai",
    "payload": {
        "agent_id": "codex"
    }
}
```

Response
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

Response when the plugin is not subscribed to the requested AI Agent:

```JSON
{
    "code": 403,
    "cmd": "getAiAgentProjects",
    "cmdType": "REQUEST",
    "uuid": "com.ulanzi.ulanzideck.ai",
    "error": "Plugin is not subscribed to this AI agent."
}
```

### 21) Get AI Agent sessions (main service)

The plugin must be subscribed to the corresponding agent_id before querying sessions in one of that agent's projects.

Request
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

Response
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

Response when the plugin is not subscribed to the requested AI Agent:

```JSON
{
    "code": 403,
    "cmd": "getAiAgentSessions",
    "cmdType": "REQUEST",
    "uuid": "com.ulanzi.ulanzideck.ai",
    "error": "Plugin is not subscribed to this AI agent."
}
```



# III. Startup arguments

```C++
//Startup arguments
//On Windows
Right-click the Ulanzi Studio shortcut, open Properties, and append arguments to the Target field.

//On macOS
//Console
cd /Applications/Ulanzi Studio.app/Contents/MacOS
//Known issue in this launch mode: granting Accessibility permission to the executable is not currently possible, which can prevent shortcuts from working; unresolved
open UlanziDeck --args --log or ./UlanziDeck --log

//Without a console
open /Applications/Ulanzi\ Studio.app --args --log --webRemoteDebug


/**
 *  Enable the console (off by default). Not supported as a separate console on macOS; launch from Terminal to use its console
 **/
#define ENABLE_CONSOLE          "--console"
/**
 *  Enable logging, including plugin logs (off by default)
 **/
#define ENABLE_LOG_PRINT        "--log"
/**
 *  Plugin logMessage output level; defaults to debug. Levels: info|debug|warn|error. Example: UlanziDeck.exe --logLevel=info
 **/
#define ENABLE_LOG_LEVEL        "--logLevel"
/**
 *  Enable double-click key activation, emitting run and keydown events (off by default)
 **/
#define ENABLE_DOUBLE_CLICK     "--doubleClick"

/**
 *  Enable the plugin load button
 **/
#define PLUGIN_PLUGIN_LOAD       "--pluginLoad"

/**
 *  Enable remote debugging for HTML plugins
 *  Default port: 9292. Open localhost:9292 in a browser to debug all loaded HTML plugins
 *  Before V2.1, enable remote debugging with the extra arguments --webEngineArgs --remote-debugging-port=<portnumber>
 **/
#define WEBVIEW_REMOTE_DEBUG    "--webRemoteDebug"

/**
 * Set the HTML plugin remote-debugging port; example: --webRemotePort=9292
**/
#define WEBVIEW_REMOTE_PORT     "--webRemotePort"

/**
 *  Enable remote debugging for NodeJS plugins
 *  Set "Inspect":"--inspect=[host:port]" in the NodeJS plugin manifest.json; default: 127.0.0.1:9229
 *  Open chrome://inspect in a browser; for a nondefault port, add it under Discover network targets.
 **/
#define NODEJS_REMOTE_DEBUG     "--nodeRemoteDebug"



```

# IV. Data types

## Localization filenames

```JSON
Simplified Chinese:   zh_CN.json
Traditional Chinese: zh_HK.json
English:   en.json
Japanese:    ja_JP.json
German:   de_DE.json
Korean:    ko_KR.json
Portuguese: pt_PT.json
Spanish: es_ES.json
```

## Device models

```JSON
D200
D200H
Dial
D200X
AU05
```
