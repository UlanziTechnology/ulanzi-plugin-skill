
import { Utils } from './ulanzi-api/index.js';

import { HOTKEYS } from './hotkey.js'
import { COLORS_PARAMS, BASIC_PARAMS, CURVE_PARAMS, BASIC_KEYPAD_PARAMS } from './params.js';
import { PHOTO_PARAMETERS, normalizePhotoSettings, getPhotoParameterKey } from '../../shared/photoParameters.js';

const PARAMETER_SWITCH_TAGS = {
    SwitchUp: '--',
    SwitchDown: '++',
    switchParameters: '++' // Compatibility with saved one-way switching settings.
};

export default class Action {

    constructor(context, $UD, $LRSERVER, selectedSliderState) {
        this.context = context;
        this.$UD = $UD;
        this.selectedSliderState = selectedSliderState;
        const { uuid } = $UD.decodeContext(context);
        this.uuidName = uuid.split('.').pop();
        Utils.log('-----uuidName:', this.uuidName);
        this.$LRSERVER = $LRSERVER;
        this.settings = {};
        this.debounceTimer = 0;
        this.longPressTimer = 0; //检测长按
        this.longPressTag = false; //是否处于长按
        this.autoSwitchTimer = 0; //自动切换参数
        this.lastBase64Str = '';
        this.lrEnums = {
            basic:"BASIC",
            basicDail:"BASIC",
            toneCurve:"CURVE",
            hslColorMixer:"HSL"
        }
        

        this.os = Utils.getSystemType();

        Utils.log('-----os:', this.os, process.platform)
    }
    add(settings) {
        this.settings = this.uuidName === 'editPhoto' ? normalizePhotoSettings(settings) : settings;
        if (this.uuidName === 'editPhoto') this.$UD.setSettings(this.settings, this.context);
        this.selectedSliderState.register(this);
        
    }
    async keyDown(settings) {
        this.setEventSettings(settings);
        this.clearTimers();

        const switchTag = PARAMETER_SWITCH_TAGS[settings.action];
        if(this.uuidName === 'basic' && switchTag){
            this.longPressTimer = setTimeout(() => {
                this.longPressTag = true;
                Utils.log('-----keyDown longPress detected:', JSON.stringify(settings),this.context);
                this.autoSwitchTimer = setInterval(() => {
                    this.changeIndexAndSendToPI(switchTag,'keypad');
                    this.lastKaypadChange(this.settings.keypad);
                }, 800);
            }, 500);
        }else{
            if(this.uuidName === 'basic'){
                Utils.log('-----keyDown basic in :');
                const { action, keypad } = settings;
                if(action === 'selectedParameter'){
                    this.lastKaypadChange(keypad);
                    this.autoChangeHSLpanel();
                    this.sendToast(`TOOL:TOAST:${this.$UD.t('Adjusting')} "${this.$UD.t(keypad)}"`);
                }else{
                    const tag = action === 'Increase' ? '++' : '--';
                    this.safeSendLine(tag);
                }
                
            }else{
                this.safeHotkey(settings.keypad);
            }
        }


        
    }

    async keyUp(settings) {
        Utils.log('-----keyUp:', JSON.stringify(settings),this.context);
        this.clearTimers();

        if(this.longPressTag){
            this.longPressTag = false;
            return;
        }

        this.setEventSettings(settings);
        // Short presses switch once on release; long presses repeat in keyDown.
        const switchTag = PARAMETER_SWITCH_TAGS[settings.action];
        if(this.uuidName === 'basic' && switchTag){
            this.changeIndexAndSendToPI(switchTag,'keypad');
            this.lastKaypadChange(this.settings.keypad);
        }
    }


    async dialDown(settings) {
        this.setEventSettings(settings);
        Utils.log('-----dialDown:', JSON.stringify(settings),this.context);
        if(this.uuidName === 'photoPreview'){
            this.safeHotkey(settings.press);
        }else if(settings.press){
           this.safeSendLine('=0');  
        }

    }
    async dialRotateLeft(settings) {
        this.setEventSettings(settings);
        Utils.log('-----dialRotateLeft:', JSON.stringify(settings),this.context);
        
        if(!this.safeHotkey(settings.rCCW)){
           this.safeSendLine('--');
        }
    }
    async dialRotateRight(settings) {
        this.setEventSettings(settings);
        Utils.log('-----dialRotateRight:', JSON.stringify(settings),this.context);
        if(!this.safeHotkey(settings.rCW)){
           this.safeSendLine('++');
        }
    }
    async dialRotateHoldLeft(settings) {
        this.setEventSettings(settings);
        Utils.log('-----dialRotateHoldLeft:', JSON.stringify(settings),this.context);
        if (this.uuidName === 'editPhoto') {
            this.changeIndexAndSendToPI('--');
            return;
        }
        if(settings.prCW === 'Decrease'){
            this.safeSendLine('--');
        }else if(!this.safeHotkey(settings.prCCW)){
            this.changeIndexAndSendToPI('--');
        }
    }
    async dialRotateHoldRight(settings) {
        this.setEventSettings(settings);
        Utils.log('-----dialRotateHoldRight:', JSON.stringify(settings),this.context);
        if (this.uuidName === 'editPhoto') {
            this.changeIndexAndSendToPI('++');
            return;
        }
        if(settings.prCW === 'Increase'){
            this.safeSendLine('--');
        }else if(!this.safeHotkey(settings.prCW)){
           this.changeIndexAndSendToPI('++');
        }
    }
    async didReceiveSettings(settings) {
        if (this.uuidName === 'editPhoto') {
            const previous = this.settings.press;
            this.settings = normalizePhotoSettings(settings);
            if (previous !== this.settings.press) this.announcePhotoParameter();
            return;
        }
        this.selectedSliderState.receiveSettings(this, settings);
        Utils.log('-----didReceiveSettings:', JSON.stringify(settings),this.context);
    }

    setEventSettings(settings) {
        const selectedSliderSteps = this.settings.selectedSliderSteps;
        this.settings = this.uuidName === 'editPhoto' ? normalizePhotoSettings(settings) : { ...settings };
        // Key-up / dial events may still carry the host's pre-save settings.
        if (this.uuidName === 'basic' && selectedSliderSteps) {
            this.settings.selectedSliderSteps = selectedSliderSteps;
        }
    }

   
    
    safeSendLine(tag){
        const key = this.getSendLineKey();

        if(!key) return false;

        this.autoChangeHSLpanel();
        
        Utils.log('-----safeSendLine tag:', `${key}:${tag}`);
        // if((tag == '++' || tag == '--') && (key.indexOf('HSL') < 0)){
        if(tag == '++' || tag == '--'){
            let num = (key.indexOf('EXPOSURE') > -1) ? 0.1 : 1;
            // if(this.uuidName === 'general' && key.indexOf('BASIC:') > -1){ //处理基础时才用default
            //     num = 'default';
            // }else{
                const steps = this.uuidName === 'general' ? this.selectedSliderState.getSteps(this) : this.settings;
                num = (key.indexOf('EXPOSURE') > -1) ? (steps.exposureStepSize || num) : (steps.stepSize || num);
            // }
            tag = tag === '++' ? `+${num}` : `-${num}`;

        }

        console.log('----===safeSendLine this.uuidName:',this.uuidName)
        
        this.$LRSERVER.sendLine(`${key}:${tag}`)
        return true;
    }

    getSendLineKey(){
        if (this.uuidName === 'editPhoto') return getPhotoParameterKey(this.settings.press);
        const prefix = this.lrEnums[this.uuidName];
        let key = ''
        const { keypad, press, color } = this.settings || {};
        if(this.uuidName === 'general'){
            if(this.$UD.lastKaypad){
                const lastKeypad = this.$UD.lastKaypad;
                if(lastKeypad.indexOf('_') > -1){
                    key = lastKeypad.split('_').join(':');
                }else{
                    key = `BASIC:${lastKeypad}`;
                }
            }else{

                //没有时，默认 色温
                key = 'BASIC:TEMPERATURE';
            }

        }else if(this.uuidName === 'basic' && keypad){
            if(keypad.indexOf('_') > -1){
                key = keypad.split('_').join(':');
            }else{
                key = `BASIC:${keypad}`;
            }
        }else{
            key = prefix === 'HSL' ? `${press.slice(0, 3).toUpperCase()}:${color.toUpperCase()}` : press;

            key = `${prefix}:${key}`;
        }

        return key;
    }

    autoChangeHSLpanel(){
        const key = this.getSendLineKey();
    
        
        const hslMode = [{
            tag:'HUE',
            value:'HueAdjustment'
        },{
            tag:'SAT',
            value:'SaturationAdjustment'
        },{
            tag:'LUM',
            value:'LuminanceAdjustment'
        }];

        for(let i=0; i<hslMode.length; i++){
            const item = hslMode[i];
            if(key.toUpperCase().indexOf(item.tag) > 0){
        // console.log('---this.$UD.currentHSLMode---key:', this.$UD.currentHSLMode, item.tag, this.uuidName);
                if(this.$UD.currentHSLMode !== item.tag){
        // console.log('---this.$UD.currentHSLMode---key in:', this.$UD.currentHSLMode, item.tag);
                    this.safeHotkey(item.value)
                    this.$UD.currentHSLMode = item.tag;
                }
                break;
            }
        }

        

        
        // if(key.toUpperCase().indexOf('HUE') > 0){
        //     this.$UD.
        //     this.safeHotkey('HueAdjustment')
        // }else if(key.toUpperCase().indexOf('SAT') > 0){
        //     this.safeHotkey('SaturationAdjustment')
        // }else if(key.toUpperCase().indexOf('LUM') > 0){
        //     this.safeHotkey('LuminanceAdjustment')
        // }

        console.log('---autoChangeHSLpanel---key:', key, this.uuidName);

    }

    safeHotkey(key){
        if(!key) return false;
        const hotkey = HOTKEYS[this.os][key];
        Utils.log('-----safeHotkey:', hotkey, this.uuidName);
        if(!hotkey) return false;
        this.$UD.hotkey(hotkey);
        return true;
    }
    
    changeIndexAndSendToPI(tag, key){

        console.log('--34141---changeIndexAndSendToPI:', tag, key,  this.uuidName);
        
        const paramArray = this.getParamsArray();
        Utils.log('--343434---changeIndexAndSendToPI:', paramArray && paramArray.length, this.uuidName);
        if(!paramArray || paramArray.length == 0) return;

        const target = key || (this.uuidName === 'hslColorMixer' ? 'color' : 'press');

        console.log('--34534---changeIndexAndSendToPI:', target, this.settings[target], JSON.stringify(this.settings));
        

        // Shortcut switch buttons navigate one shared selection, regardless of
        // each button's saved parameter or a stale host event snapshot.
        const currentValue = this.uuidName === 'basic' && target === 'keypad'
            ? (this.$UD.lastKaypad || 'TEMPERATURE') : this.settings[target];
        let index = this.getIndexFromParams(paramArray, currentValue);
        // Utils.log('--35252---changeIndexAndSendToPI:', target, index, this.settings[key], this.context);

        
        if(index < 0) return;
        
        const len = paramArray.length;
        if (tag === '++') {
            index = (index + 1) % len;
        } else if (tag === '--') {
            index = (index - 1 + len) % len; // +len 防止负数
        }

        const newValue = paramArray[index].value;

        Utils.log('--35656---changeIndexAndSendToPI showToast:', target, index, newValue, this.context);

        this.settings = {
            ...this.settings,
            [target]:newValue
        }
        
        this.$UD.setSettings(this.settings,this.context);

        // if(showToast){
        
            this.autoChangeHSLpanel();

            let trKey = this.getSendLineKey();
            if(trKey.indexOf('BASIC:') > -1){
                trKey = trKey.replace('BASIC:','');
            }else{
                trKey = trKey.replaceAll(':','_');
            }

            Utils.log('--35777---changeIndexAndSendToPI SENDLINE:',trKey);

            this.sendToast(`TOOL:TOAST:${this.$UD.t('Adjusting')} "${this.$UD.t(trKey)}"`);
        // }


        return newValue;
    }

    sendToast(message){
        Utils.log('--35858---sendToast SENDLINE:',`TOAST:${message}`);

        this.$LRSERVER.sendLine(message);
    }
    
    getParamsArray(){
        if (this.uuidName === 'editPhoto') {
            return PHOTO_PARAMETERS.filter(item => this.settings.selectedParameters.includes(item.value));
        }
        const { keypad } = this.settings || {};
        let paramArray = [];
        if(this.uuidName === 'basicDail'){
             paramArray = BASIC_PARAMS;
        }else if(this.uuidName === 'basic'){
            //兼容旧版本uuid,之前basic有按键和旋钮，旋钮后来改成basicDail，更明确是旋钮，basic改成按键，所以如果是basic就区分keypad参数，如果有keypad参数说明是新版本basic，是按键，否则是旧版本basic，是旋钮，默认显示旋钮的参数
            if(keypad){
                paramArray = BASIC_KEYPAD_PARAMS;
            }else{
                paramArray = BASIC_PARAMS;
            }
        }else if(this.uuidName === 'toneCurve'){
            paramArray = CURVE_PARAMS;
        }else if(this.uuidName === 'hslColorMixer'){
            paramArray = COLORS_PARAMS;
        }

        return paramArray;
    }
    

    getIndexFromParams(paramArray, value){
        let index = -1;
        for(let i=0; i<paramArray.length; i++){
            if(paramArray[i].value === value){
                index = i;
                break;
            }    
        }
        return index;
    }

    setActive(active) {
        Utils.log('-----setActive:', active,this.context);
    }


    clear() {
        this.clearTimers();
        this.selectedSliderState.remove(this.context);
    }

    clearTimers() {
        if(this.debounceTimer){
            clearTimeout(this.debounceTimer);
            this.debounceTimer = 0;
        }
        if(this.longPressTimer){
            clearTimeout(this.longPressTimer);
            this.longPressTimer = 0;
        }
        if(this.autoSwitchTimer){
            clearInterval(this.autoSwitchTimer);
            this.autoSwitchTimer = 0;
        }
    }
    paramFromApp(settings) {
        if (this.uuidName === 'editPhoto') {
            this.settings = normalizePhotoSettings(settings);
        } else {
            this.selectedSliderState.receiveSettings(this, settings, false);
        }
        Utils.log('--222---paramFromApp sendToPropertyInspector:', this.$LRSERVER.status,this.context);
        const updateObj = {
            connectStatus:this.$LRSERVER.status
        }
        if(this.uuidName === 'general' && this.$UD.lastKaypad){
            Object.assign(updateObj, this.settings);
        }
        this.$UD.sendToPropertyInspector(updateObj,this.context)
    }
    paramFromPlugin(settings) {
        if (this.uuidName === 'editPhoto') {
            this.settings = normalizePhotoSettings(settings);
            return;
        }
        this.selectedSliderState.receiveSettings(this, settings);
    }

    announcePhotoParameter() {
        this.autoChangeHSLpanel();
        this.sendToast(`TOOL:TOAST:${this.$UD.t('Adjusting')} "${this.$UD.t(this.settings.press)}"`);
    }

    lastKaypadChange(newKeypad){
        this.settings = {
            ...this.settings,
            keypad:newKeypad
        };
        this.$UD.setSettings(this.settings, this.context);
        this.selectedSliderState.select(this, newKeypad);
    }

}
