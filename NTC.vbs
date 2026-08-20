' NTC Telco Database - launches the app with NO black window.
' Runs the venv's windowless Python (pythonw) on desktop.py, hidden.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here
pyw = here & "\venv\Scripts\pythonw.exe"
If fso.FileExists(pyw) Then
    sh.Run """" & pyw & """ desktop.py", 0, False
Else
    MsgBox "Setup needed: the 'venv' folder is missing." & vbCrLf & _
           "Open Command Prompt in C:\NTC-App and run:" & vbCrLf & _
           "  python -m venv venv" & vbCrLf & _
           "  venv\Scripts\activate" & vbCrLf & _
           "  pip install fastapi uvicorn openpyxl pywin32 pywebview", , "NTC App"
End If
