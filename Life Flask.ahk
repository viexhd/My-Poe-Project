#NoEnv  ; Recommended for performance and compatibility with future AutoHotkey releases.
; #Warn  ; Enable warnings to assist with detecting common errors.
SendMode Input  ; Recommended for new scripts due to its superior speed and reliability.
SetWorkingDir %A_ScriptDir%  ; Ensures a consistent starting directory.
#Persistent
Toggle := false  ; Initially off

`::  ; Press ` to toggle on/off
    Toggle := !Toggle  ; Flip the state
    if (Toggle) {
        SetTimer, PressOne, % Random(4000, 5000)  ; Start pressing 1
        ToolTip, Auto-1: ON  ; Show a visual indicator
        SetTimer, RemoveToolTip, 1500  ; Remove tooltip after 1.5 sec
    } else {
        SetTimer, PressOne, Off  ; Stop pressing 1
        ToolTip, Auto-1: OFF
        SetTimer, RemoveToolTip, 1500
    }
return

PressOne:
    Send, 1  ; Press the "1" key
    SetTimer, PressOne, % Random(4000, 5000)  ; Reset timer with new random delay
return

RemoveToolTip:
    ToolTip  ; Clear the tooltip
    SetTimer, RemoveToolTip, Off
return

Random(min, max) {
    Random, rand, min, max
    return rand
}