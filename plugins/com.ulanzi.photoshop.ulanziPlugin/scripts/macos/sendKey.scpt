on run argv
    if (count of argv) = 0 then return
    set myAction to (item 1 of argv) as text
    
    tell application "System Events"
        try
            set psList to (every application process whose name contains "Photoshop")
            if (count of psList) > 0 then
                if not (frontmost of (item 1 of psList)) then
                    set frontmost of (item 1 of psList) to true
                end if
            end if
        end try
        
        if myAction is equal to "shortcut" then
            set myMenu to (item 2 of argv) as text
            if myMenu is equal to "hue-saturation" then
                keystroke "u" using command down
            else if myMenu is equal to "curves" then
                keystroke "m" using command down
            else if myMenu is equal to "levels" then
                keystroke "l" using command down
            end if
        else if myAction is equal to "adjust" then
            set myDir to (item 2 of argv) as text
            set myStepCount to 1
            if (count of argv) >= 3 then
                set myStepCount to (item 3 of argv as integer)
            end if
            set myUseShift to false
            if (count of argv) >= 4 and ((item 4 of argv) as text) is equal to "true" then
                set myUseShift to true
            end if
            
            if myDir is equal to "up" then
                if myUseShift then
                    repeat myStepCount times
                        key code 126 using shift down
                    end repeat
                else
                    repeat myStepCount times
                        key code 126
                    end repeat
                end if
            else if myDir is equal to "down" then
                if myUseShift then
                    repeat myStepCount times
                        key code 125 using shift down
                    end repeat
                else
                    repeat myStepCount times
                        key code 125
                    end repeat
                end if
            end if
        else if myAction is equal to "tab" then
            set myIsReverse to false
            if (count of argv) >= 2 and ((item 2 of argv) as text) is equal to "true" then
                set myIsReverse to true
            end if
            if myIsReverse then
                key code 48 using shift down
            else
                key code 48
            end if
        else if myAction is equal to "enter" then
            key code 36
        else if myAction is equal to "escape" then
            key code 53
        end if
    end tell
end run
