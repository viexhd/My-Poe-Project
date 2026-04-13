#Persistent
CoordMode, Mouse, Screen
CoordMode, ToolTip, Screen

; =============================
;  Configuration
; =============================
; Delay settings (in milliseconds)
MIN_DELAY := 30      ; Minimum delay between clicks
MAX_DELAY := 80      ; Maximum delay (0.08 seconds)

; Visual feedback
SHOW_PROGRESS := true      ; Show progress tooltip

; =============================
;  Generate coordinates based on pattern
; =============================
GenerateCoordinates() {
    coords := []
    startX := 1988
    startY := 612
    
    x := startX
    y := startY
    
    Loop, 5 {
        ; Going down: y += 55 (5 times total including starting position)
        coords.Push([x, y])  ; First position
        Loop, 4 {
            y += 55  ; Move down
            coords.Push([x, y])
        }
        
        ; Move right
        x += 53
        
        ; Going up: y -= 55 (4 times)
        Loop, 4 {
            coords.Push([x, y])
            y -= 55
        }
        coords.Push([x, y])
        
        ; Move right for next column
        x += 53
    }
    
    ; Final half column (just go down 5 times)
    coords.Push([x, y])  ; First position
    Loop, 4 {
        y += 55  ; Move down
        coords.Push([x, y])
    }
    
    return coords
}

coords := GenerateCoordinates()

; Global variable to track if script is running
isRunning := false

; =============================
;  F1 to run the LEFT clicking loop
; =============================
F1::
{
    global isRunning, MIN_DELAY, MAX_DELAY, SHOW_PROGRESS, coords
    
    if (isRunning) {
        return
    }
    
    isRunning := true
    
    totalClicks := coords.Length()
    
    ; Get screen width for positioning tooltip
    SysGet, screenWidth, 78
    
    ; Hold Ctrl down for the entire script
    Send, {Ctrl Down}
    
    for index, c in coords
    {
        x := c[1]
        y := c[2]
        
        ; Show progress at top right of screen
        if (SHOW_PROGRESS) {
            progress := Round((index / totalClicks) * 100)
            tipText := "Left Clicking " . index . " of " . totalClicks . " (" . progress . "%%)"
            ToolTip, %tipText%, screenWidth - 200, 10
        }
        
        ; Move mouse
        MouseMove, %x%, %y%, 0
        
        ; Small delay
        Sleep, 30
        
        ; Left click (Ctrl is already held down)
        Click, %x%, %y%
        
        ; Random delay
        Random, delay, MIN_DELAY, MAX_DELAY
        Sleep, %delay%
    }
    
    ; Release Ctrl when done
    Send, {Ctrl Up}
    
    ToolTip
    isRunning := false
}
return

; =============================
;  F2 to run the RIGHT clicking loop
; =============================
F2::
{
    global isRunning, MIN_DELAY, MAX_DELAY, SHOW_PROGRESS, coords
    
    if (isRunning) {
        return
    }
    
    isRunning := true
    
    totalClicks := coords.Length()
    
    ; Get screen width for positioning tooltip
    SysGet, screenWidth, 78
    
    ; Hold Ctrl down for the entire script
    Send, {Ctrl Down}
    
    for index, c in coords
    {
        x := c[1]
        y := c[2]
        
        ; Show progress at top right of screen
        if (SHOW_PROGRESS) {
            progress := Round((index / totalClicks) * 100)
            tipText := "Right Clicking " . index . " of " . totalClicks . " (" . progress . "%%)"
            ToolTip, %tipText%, screenWidth - 200, 10
        }
        
        ; Move mouse
        MouseMove, %x%, %y%, 0
        
        ; Small delay
        Sleep, 30
        
        ; Right click (Ctrl is already held down)
        Click, Right, %x%, %y%
        
        ; Random delay
        Random, delay, MIN_DELAY, MAX_DELAY
        Sleep, %delay%
    }
    
    ; Release Ctrl when done
    Send, {Ctrl Up}
    
    ToolTip
    isRunning := false
}
return

; =============================
;  F3 to exit script completely
; =============================
F3::ExitApp