#Persistent
CoordMode, Mouse, Screen

coords := []   ; array to store coordinates

; -----------------------------------------
; CTRL + ALT + C → capture current position
; -----------------------------------------
^!c::
MouseGetPos, x, y
coords.Push([x, y])
Tooltip, Saved: X:%x%  Y:%y%
SetTimer, RemoveTooltip, -700
return

RemoveTooltip:
Tooltip
return

; -----------------------------------------
; CTRL + ALT + V → display all coordinates
; -----------------------------------------
^!v::
output := ""
for index, c in coords
{
    output .= index ": (" c[1] ", " c[2] ")\n"
}
MsgBox, 0, Saved Coordinates, %output%
return
