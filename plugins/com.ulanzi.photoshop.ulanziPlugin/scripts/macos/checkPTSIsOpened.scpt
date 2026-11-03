tell application "System Events"
	set listApp to (name of processes)
	set n to (count of listApp)
	set isExistApp to "NotRunning"
	repeat with i from 1 to n
		set appName to item {i} of listApp
		try
			set tempTID to AppleScript's text item delimiters -- save current delimiters
			set AppleScript's text item delimiters to " "
			set pieces to text items of appName -- split the string
			set AppleScript's text item delimiters to tempTID -- restore old delimiters
		on error errmess -- delimiter not found
			log errmess
			return "" -- empty string for missing item
		end try
		
		set counter to (count of pieces)
		
		repeat with i from 1 to counter
			set splitData to item {i} of pieces
			if splitData is equal to "Photoshop" then
				set isExistApp to "Running"
			else
				
			end if
			
		end repeat
	end repeat
	
	isExistApp
end tell
