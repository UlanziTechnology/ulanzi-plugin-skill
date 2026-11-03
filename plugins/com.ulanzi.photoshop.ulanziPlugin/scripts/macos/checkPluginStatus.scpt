set infoUxpPlugin to "./UnifiedPluginInstallerAgent --list all"
    set excuteGetInfoUxp to do shell script "cd '/Library/Application Support/Adobe/Adobe Desktop Common/RemoteComponents/UPI/UnifiedPluginInstallerAgent/UnifiedPluginInstallerAgent.app/Contents/MacOS' ; " & infoUxpPlugin

    set tmp to my splitString(excuteGetInfoUxp as text, " ")

    set checkPluginIsEnable to my splitString(tmp as text, "Enabled")
    
    set numberPlugin to count checkPluginIsEnable

    if numberPlugin is equal to 2 then
	    return "Enabled"
    else
	    return "Disabled"
    end if

to splitString(aString, delimiter)
	set retVal to {}
	set prevDelimiter to AppleScript's text item delimiters
	log delimiter
	set AppleScript's text item delimiters to {delimiter}
	set retVal to every text item of aString
	set AppleScript's text item delimiters to prevDelimiter
	return retVal
end splitString

