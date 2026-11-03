on run argv
    set theList to argv
    set pluginFilePath to item 1 of theList

    set sendCommandExec to do shell script "cd '/Library/Application Support/Adobe/Adobe Desktop Common/RemoteComponents/UPI/UnifiedPluginInstallerAgent/UnifiedPluginInstallerAgent.app/Contents/MacOS' ; ./UnifiedPluginInstallerAgent --remove 'UlanziDeck Plugin for Photoshop'"
    set excuteInstall to do shell script "cd '/Library/Application Support/Adobe/Adobe Desktop Common/RemoteComponents/UPI/UnifiedPluginInstallerAgent/UnifiedPluginInstallerAgent.app/Contents/MacOS' ; ./UnifiedPluginInstallerAgent --install " & "'" & pluginFilePath & "'"
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

