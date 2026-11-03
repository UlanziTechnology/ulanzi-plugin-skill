on run argv
    set theList to argv
    set pluginFilePath to item 1 of theList
    set uxpPluginVer to item 2 of theList
    set appName to item 3 of theList
    
    set infoUxpPlugin to "./UnifiedPluginInstallerAgent --list all"
    set excuteGetInfoUxp to do shell script "cd '/Library/Application Support/Adobe/Adobe Desktop Common/RemoteComponents/UPI/UnifiedPluginInstallerAgent/UnifiedPluginInstallerAgent.app/Contents/MacOS' ; " & infoUxpPlugin

    set tmp to my splitString(excuteGetInfoUxp as text, " ")

    set checkExistPlugin to my splitString(tmp as text, "UlanziDeck")
    
    set numberPlugin to count checkExistPlugin
    if numberPlugin is equal to 2 then
        if excuteGetInfoUxp contains (uxpPluginVer as text) then
	        return "plugin exist"
        else
	        set sendCommandExec to do shell script "cd '/Library/Application Support/Adobe/Adobe Desktop Common/RemoteComponents/UPI/UnifiedPluginInstallerAgent/UnifiedPluginInstallerAgent.app/Contents/MacOS' ; ./UnifiedPluginInstallerAgent --remove 'UlanziDeck Plugin for Photoshop'"
            set excuteInstall to do shell script "cd '/Library/Application Support/Adobe/Adobe Desktop Common/RemoteComponents/UPI/UnifiedPluginInstallerAgent/UnifiedPluginInstallerAgent.app/Contents/MacOS' ; ./UnifiedPluginInstallerAgent --install " & "'" & pluginFilePath & "'"
        end if
    else
        set sendCommandExec to do shell script "cd '/Library/Application Support/Adobe/Adobe Desktop Common/RemoteComponents/UPI/UnifiedPluginInstallerAgent/UnifiedPluginInstallerAgent.app/Contents/MacOS' ; ./UnifiedPluginInstallerAgent --remove 'UlanziDeck Plugin for Photoshop'"
	    set excuteInstall to do shell script "cd '/Library/Application Support/Adobe/Adobe Desktop Common/RemoteComponents/UPI/UnifiedPluginInstallerAgent/UnifiedPluginInstallerAgent.app/Contents/MacOS' ; ./UnifiedPluginInstallerAgent --install " & "'" & pluginFilePath & "'"
    end if
end run

to splitString(aString, delimiter)
	set retVal to {}
	set prevDelimiter to AppleScript's text item delimiters
	log delimiter
	set AppleScript's text item delimiters to {delimiter}
	set retVal to every text item of aString
	set AppleScript's text item delimiters to prevDelimiter
	return retVal
end splitString

