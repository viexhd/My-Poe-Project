#include <windows.h>
#include <commctrl.h>
#include <string>
#include <vector>
#include <random>
#include <thread>
#include <atomic>
#include <sstream>
#include <iomanip>

#pragma comment(lib, "comctl32.lib")
#pragma comment(linker,"\"/manifestdependency:type='win32' name='Microsoft.Windows.Common-Controls' version='6.0.0.0' processorArchitecture='*' publicKeyToken='6595b64144ccf1df' language='*'\"")

// Global variables
HWND g_hMainWindow = NULL;
HWND g_hStartXEdit = NULL;
HWND g_hStartYEdit = NULL;
HWND g_hMinDelayEdit = NULL;
HWND g_hMaxDelayEdit = NULL;
HWND g_hLeftClickBtn = NULL;
HWND g_hRightClickBtn = NULL;
HWND g_hStatusLabel = NULL;

std::atomic<bool> g_isRunning(false);
std::atomic<bool> g_shouldStop(false);

// Configuration
struct Config {
    int startX = 1988;
    int startY = 612;
    int minDelay = 30;
    int maxDelay = 80;
} g_config;

// Window class name
const wchar_t CLASS_NAME[] = L"AutoClickerWindow";

// Control IDs
#define ID_STARTX_EDIT      1001
#define ID_STARTY_EDIT      1002
#define ID_MINDELAY_EDIT    1003
#define ID_MAXDELAY_EDIT    1004
#define ID_LEFTCLICK_BTN    1005
#define ID_RIGHTCLICK_BTN   1006
#define ID_HOTKEY_F2        1007

// Structure to hold coordinate
struct Coord {
    int x;
    int y;
};

// Generate coordinates based on the pattern
std::vector<Coord> GenerateCoordinates(int startX, int startY) {
    std::vector<Coord> coords;
    
    int x = startX;
    int y = startY;
    
    // 5 full columns
    for (int col = 0; col < 5; col++) {
        // Going down: 5 positions
        coords.push_back({x, y});
        for (int i = 0; i < 4; i++) {
            y += 55;
            coords.push_back({x, y});
        }
        
        // Move right
        x += 53;
        
        // Going up: 5 positions
        for (int i = 0; i < 4; i++) {
            coords.push_back({x, y});
            y -= 55;
        }
        coords.push_back({x, y});
        
        // Move right for next column
        x += 53;
    }
    
    // Final half column (just go down 5 times)
    coords.push_back({x, y});
    for (int i = 0; i < 4; i++) {
        y += 55;
        coords.push_back({x, y});
    }
    
    return coords;
}

// Update status label
void UpdateStatus(const std::wstring& status) {
    if (g_hStatusLabel) {
        SetWindowTextW(g_hStatusLabel, status.c_str());
    }
}

// Perform clicking operation
void PerformClicking(bool isLeftClick) {
    if (g_isRunning) {
        return;
    }
    
    g_isRunning = true;
    g_shouldStop = false;
    
    // Read configuration from UI
    wchar_t buffer[32];
    GetWindowTextW(g_hStartXEdit, buffer, 32);
    g_config.startX = _wtoi(buffer);
    
    GetWindowTextW(g_hStartYEdit, buffer, 32);
    g_config.startY = _wtoi(buffer);
    
    GetWindowTextW(g_hMinDelayEdit, buffer, 32);
    g_config.minDelay = _wtoi(buffer);
    
    GetWindowTextW(g_hMaxDelayEdit, buffer, 32);
    g_config.maxDelay = _wtoi(buffer);
    
    // Generate coordinates
    auto coords = GenerateCoordinates(g_config.startX, g_config.startY);
    int totalClicks = coords.size();
    
    // Random number generator
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> dis(g_config.minDelay, g_config.maxDelay);
    
    // Hold Ctrl down
    INPUT inputs[1] = {};
    inputs[0].type = INPUT_KEYBOARD;
    inputs[0].ki.wVk = VK_CONTROL;
    SendInput(1, inputs, sizeof(INPUT));
    
    for (size_t i = 0; i < coords.size() && !g_shouldStop; i++) {
        int x = coords[i].x;
        int y = coords[i].y;
        
        // Update status
        std::wstringstream ss;
        int progress = (int)(((i + 1) * 100.0) / totalClicks);
        ss << (isLeftClick ? L"Left" : L"Right") << L" Clicking " 
           << (i + 1) << L" of " << totalClicks << L" (" << progress << L"%)";
        UpdateStatus(ss.str());
        
        // Move mouse
        SetCursorPos(x, y);
        
        // Small delay
        Sleep(30);
        
        // Click
        INPUT clickInputs[2] = {};
        clickInputs[0].type = INPUT_MOUSE;
        clickInputs[1].type = INPUT_MOUSE;
        
        if (isLeftClick) {
            clickInputs[0].mi.dwFlags = MOUSEEVENTF_LEFTDOWN;
            clickInputs[1].mi.dwFlags = MOUSEEVENTF_LEFTUP;
        } else {
            clickInputs[0].mi.dwFlags = MOUSEEVENTF_RIGHTDOWN;
            clickInputs[1].mi.dwFlags = MOUSEEVENTF_RIGHTUP;
        }
        
        SendInput(2, clickInputs, sizeof(INPUT));
        
        // Random delay
        int delay = dis(gen);
        Sleep(delay);
    }
    
    // Release Ctrl
    inputs[0].ki.dwFlags = KEYEVENTF_KEYUP;
    SendInput(1, inputs, sizeof(INPUT));
    
    UpdateStatus(L"Ready");
    g_isRunning = false;
}

// Thread function for clicking
DWORD WINAPI ClickingThread(LPVOID lpParam) {
    bool isLeftClick = (bool)(intptr_t)lpParam;
    PerformClicking(isLeftClick);
    return 0;
}

// Window procedure
LRESULT CALLBACK WindowProc(HWND hwnd, UINT uMsg, WPARAM wParam, LPARAM lParam) {
    switch (uMsg) {
        case WM_CREATE: {
            // Create labels and edit controls
            int y = 20;
            
            // Start X
            CreateWindowW(L"STATIC", L"Start X:", WS_CHILD | WS_VISIBLE,
                         20, y, 80, 20, hwnd, NULL, NULL, NULL);
            g_hStartXEdit = CreateWindowW(L"EDIT", L"1988",
                         WS_CHILD | WS_VISIBLE | WS_BORDER | ES_NUMBER,
                         110, y, 100, 20, hwnd, (HMENU)ID_STARTX_EDIT, NULL, NULL);
            y += 30;
            
            // Start Y
            CreateWindowW(L"STATIC", L"Start Y:", WS_CHILD | WS_VISIBLE,
                         20, y, 80, 20, hwnd, NULL, NULL, NULL);
            g_hStartYEdit = CreateWindowW(L"EDIT", L"612",
                         WS_CHILD | WS_VISIBLE | WS_BORDER | ES_NUMBER,
                         110, y, 100, 20, hwnd, (HMENU)ID_STARTY_EDIT, NULL, NULL);
            y += 30;
            
            // Min Delay
            CreateWindowW(L"STATIC", L"Min Delay (ms):", WS_CHILD | WS_VISIBLE,
                         20, y, 80, 20, hwnd, NULL, NULL, NULL);
            g_hMinDelayEdit = CreateWindowW(L"EDIT", L"30",
                         WS_CHILD | WS_VISIBLE | WS_BORDER | ES_NUMBER,
                         110, y, 100, 20, hwnd, (HMENU)ID_MINDELAY_EDIT, NULL, NULL);
            y += 30;
            
            // Max Delay
            CreateWindowW(L"STATIC", L"Max Delay (ms):", WS_CHILD | WS_VISIBLE,
                         20, y, 80, 20, hwnd, NULL, NULL, NULL);
            g_hMaxDelayEdit = CreateWindowW(L"EDIT", L"80",
                         WS_CHILD | WS_VISIBLE | WS_BORDER | ES_NUMBER,
                         110, y, 100, 20, hwnd, (HMENU)ID_MAXDELAY_EDIT, NULL, NULL);
            y += 40;
            
            // Buttons
            g_hLeftClickBtn = CreateWindowW(L"BUTTON", L"Start Left Clicking",
                         WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                         20, y, 190, 30, hwnd, (HMENU)ID_LEFTCLICK_BTN, NULL, NULL);
            y += 40;
            
            g_hRightClickBtn = CreateWindowW(L"BUTTON", L"Start Right Clicking",
                         WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                         20, y, 190, 30, hwnd, (HMENU)ID_RIGHTCLICK_BTN, NULL, NULL);
            y += 40;
            
            // Status label
            g_hStatusLabel = CreateWindowW(L"STATIC", L"Ready",
                         WS_CHILD | WS_VISIBLE,
                         20, y, 190, 20, hwnd, NULL, NULL, NULL);
            
            // Register F2 hotkey
            RegisterHotKey(hwnd, ID_HOTKEY_F2, 0, VK_F2);
            
            return 0;
        }
        
        case WM_HOTKEY: {
            if (wParam == ID_HOTKEY_F2) {
                // Toggle window visibility
                if (IsWindowVisible(hwnd)) {
                    ShowWindow(hwnd, SW_HIDE);
                } else {
                    ShowWindow(hwnd, SW_SHOW);
                    SetForegroundWindow(hwnd);
                }
            }
            return 0;
        }
        
        case WM_COMMAND: {
            switch (LOWORD(wParam)) {
                case ID_LEFTCLICK_BTN: {
                    if (!g_isRunning) {
                        CreateThread(NULL, 0, ClickingThread, (LPVOID)true, 0, NULL);
                    }
                    break;
                }
                case ID_RIGHTCLICK_BTN: {
                    if (!g_isRunning) {
                        CreateThread(NULL, 0, ClickingThread, (LPVOID)false, 0, NULL);
                    }
                    break;
                }
            }
            return 0;
        }
        
        case WM_CLOSE: {
            // Instead of destroying, just hide the window
            ShowWindow(hwnd, SW_HIDE);
            return 0;
        }
        
        case WM_DESTROY: {
            UnregisterHotKey(hwnd, ID_HOTKEY_F2);
            PostQuitMessage(0);
            return 0;
        }
    }
    
    return DefWindowProc(hwnd, uMsg, wParam, lParam);
}

// WinMain entry point
int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow) {
    // Register window class
    WNDCLASSW wc = {};
    wc.lpfnWndProc = WindowProc;
    wc.hInstance = hInstance;
    wc.lpszClassName = CLASS_NAME;
    wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    
    RegisterClassW(&wc);
    
    // Create window
    g_hMainWindow = CreateWindowExW(
        0,
        CLASS_NAME,
        L"Auto Clicker",
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
        CW_USEDEFAULT, CW_USEDEFAULT, 250, 300,
        NULL,
        NULL,
        hInstance,
        NULL
    );
    
    if (g_hMainWindow == NULL) {
        return 0;
    }
    
    ShowWindow(g_hMainWindow, nCmdShow);
    UpdateWindow(g_hMainWindow);
    
    // Message loop
    MSG msg = {};
    while (GetMessage(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }
    
    return 0;
}