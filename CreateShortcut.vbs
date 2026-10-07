Option Explicit
Dim shell, fso, root, shortcut, tempLink, desktop
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
tempLink = root & "\Shorekeeper.lnk"
Set shortcut = shell.CreateShortcut(tempLink)
shortcut.TargetPath = root & "\Shorekeeper.exe"
shortcut.WorkingDirectory = root
shortcut.IconLocation = root & "\assets\shorekeeper.ico"
shortcut.Description = "Shorekeeper desktop companion"
shortcut.Save
desktop = shell.SpecialFolders("Desktop")
fso.CopyFile tempLink, desktop & "\Shorekeeper.lnk", True
