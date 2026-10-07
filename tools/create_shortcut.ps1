param([string]$Destination = [Environment]::GetFolderPath('Desktop'))
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
[ComImport, Guid("00021401-0000-0000-C000-000000000046")] class ShellLink {}
[ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IShellLinkW {
    void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int count, IntPtr findData, uint flags);
    void GetIDList(out IntPtr list); void SetIDList(IntPtr list);
    void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder text, int count);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string text);
    void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder text, int count);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string text);
    void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder text, int count);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string text);
    void GetHotkey(out short key); void SetHotkey(short key);
    void GetShowCmd(out int command); void SetShowCmd(int command);
    void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder text, int count, out int index);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string text, int index);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string text, uint reserved);
    void Resolve(IntPtr window, uint flags);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string text);
}
public static class PetShortcut {
    public static void Create(string destination, string target, string directory) {
        var link=(IShellLinkW)new ShellLink();
        try {
            link.SetPath(target); link.SetWorkingDirectory(directory);
            link.SetIconLocation(target,0); link.SetDescription(System.IO.Path.GetFileNameWithoutExtension(target));
            ((IPersistFile)link).Save(destination,true);
        } finally { Marshal.FinalReleaseComObject(link); }
        var loaded=(IShellLinkW)new ShellLink();
        try {
            ((IPersistFile)loaded).Load(destination,0);
            var path=new StringBuilder(32768); loaded.GetPath(path,path.Capacity,IntPtr.Zero,4);
            if(path.ToString()!=target) throw new Exception("Shortcut target verification failed");
            var icon=new StringBuilder(32768); int index; loaded.GetIconLocation(icon,icon.Capacity,out index);
            if(icon.ToString()!=target || index!=0) throw new Exception("Shortcut icon verification failed");
        } finally { Marshal.FinalReleaseComObject(loaded); }
    }
}
'@
$root = Split-Path -Parent $PSScriptRoot
$exe = Get-ChildItem -LiteralPath $root -Filter *.exe | Where-Object { $_.VersionInfo.InternalName -eq 'shorekeeper_pet' } | Select-Object -First 1
if (-not $exe) { throw 'Run this tool inside the extracted Windows portable folder.' }
$link = Join-Path $Destination ($exe.BaseName + '.lnk')
[PetShortcut]::Create($link, $exe.FullName, $root)
Write-Output 'Shortcut created and verified.'
