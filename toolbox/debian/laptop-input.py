#!/usr/bin/python3
"""Debian side of laptop-click, laptop-move, laptop-type and laptop-key: mouse and keyboard on George's Windows laptop.

  laptop-input.py click X Y [--right|--double]
  laptop-input.py move X Y
  laptop-input.py type 'WORDS'
  laptop-input.py key KEY[+KEY...]          enter, tab, esc, ctrl+s, alt+f4, win+r, ctrl+shift+esc, a, f5 ...

Why a scheduled task: an ssh session on Windows runs in session 0, which has no desktop. Input sent from it fails:
SetCursorPos answers False with error 1459 (Windows error 1459: interactive desktop required). So each action runs as a
one-shot scheduled task in George's own logged-in desktop session (LogonType Interactive), the same door the
`screen` command uses for laptop pictures. The task and its files are removed after each action.
Input is Windows SendInput: real mouse events, real key events, and words as Unicode key events.
X Y are pixels of the primary screen at full size (the size `screen size --target laptop` prints).
"""
import base64
import os
import re
import subprocess
import sys
import tempfile
import uuid

REMOTE = 'C:/Users/georg/AppData/Local/Temp'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', 'wimlaptop']
USAGE = {
    'click': 'usage: laptop-click X Y [--right|--double]',
    'move': 'usage: laptop-move X Y',
    'type': "usage: laptop-type 'WORDS'",
    'key': 'usage: laptop-key KEY[+KEY...]   for example: enter, tab, esc, ctrl+s, alt+f4, win+r',
}
# Windows virtual-key codes (learn.microsoft.com/windows/win32/inputdev/virtual-key-codes).
VK = {'backspace': 0x08, 'tab': 0x09, 'enter': 0x0D, 'return': 0x0D, 'shift': 0x10, 'ctrl': 0x11, 'control': 0x11,
      'alt': 0x12, 'pause': 0x13, 'capslock': 0x14, 'esc': 0x1B, 'escape': 0x1B, 'space': 0x20, 'pageup': 0x21,
      'pagedown': 0x22, 'end': 0x23, 'home': 0x24, 'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28,
      'printscreen': 0x2C, 'insert': 0x2D, 'delete': 0x2E, 'del': 0x2E, 'win': 0x5B, 'windows': 0x5B, 'menu': 0x5D,
      'numlock': 0x90, 'scrolllock': 0x91, 'volumemute': 0xAD, 'volumedown': 0xAE, 'volumeup': 0xAF,
      'medianext': 0xB0, 'mediaprev': 0xB1, 'mediastop': 0xB2, 'mediaplay': 0xB3,
      ';': 0xBA, '=': 0xBB, ',': 0xBC, '-': 0xBD, '.': 0xBE, '/': 0xBF, '`': 0xC0, '[': 0xDB, '\\': 0xDC, ']': 0xDD, "'": 0xDE}
VK.update({f'f{n}': 0x6F + n for n in range(1, 25)})
VK.update({chr(c): c for c in range(ord('0'), ord('9') + 1)})
VK.update({chr(c).lower(): c for c in range(ord('A'), ord('Z') + 1)})
# Keys Windows needs the "extended" flag for, or it reads them as the number-pad keys.
EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5D, 0x90}

HELPER = r'''Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices; using System.ComponentModel;
public class HarnessInput {
  [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT { public int dx; public int dy; public uint mouseData; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT { public ushort wVk; public ushort wScan; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Explicit)] public struct UNION { [FieldOffset(0)] public MOUSEINPUT mi; [FieldOffset(0)] public KEYBDINPUT ki; }
  [StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public UNION u; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
  [DllImport("user32.dll", SetLastError=true)] static extern uint SendInput(uint n, INPUT[] inputs, int size);
  [DllImport("user32.dll", SetLastError=true)] static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll", SetLastError=true)] static extern bool GetCursorPos(out POINT p);
  [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h, System.Text.StringBuilder b, int n);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L; public int T; public int R; public int B; }
  [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
  public static string Front() {
    System.Threading.Thread.Sleep(400); IntPtr h = GetForegroundWindow();
    var b = new System.Text.StringBuilder(512); GetWindowText(h, b, 512); RECT r; GetWindowRect(h, out r);
    return b.ToString() + " (" + r.L + "," + r.T + " to " + r.R + "," + r.B + ")";
  }
  static void Send(INPUT[] inputs) {
    uint sent = SendInput((uint)inputs.Length, inputs, Marshal.SizeOf(typeof(INPUT)));
    if (sent != inputs.Length) throw new Win32Exception(Marshal.GetLastWin32Error(), "SendInput sent " + sent + " of " + inputs.Length);
  }
  static INPUT Mouse(uint flags) { INPUT i = new INPUT(); i.type = 0; i.u.mi.dwFlags = flags; return i; }
  static INPUT Key(ushort vk, ushort scan, uint flags) { INPUT i = new INPUT(); i.type = 1; i.u.ki.wVk = vk; i.u.ki.wScan = scan; i.u.ki.dwFlags = flags; return i; }
  public static string Move(int x, int y) {
    if (!SetCursorPos(x, y)) throw new Win32Exception(Marshal.GetLastWin32Error(), "SetCursorPos");
    POINT p; GetCursorPos(out p); return p.X + " " + p.Y;
  }
  public static void Click(string button, int times) {
    uint down = button == "right" ? 0x0008u : 0x0002u, up = button == "right" ? 0x0010u : 0x0004u;
    for (int n = 0; n < times; n++) Send(new INPUT[] { Mouse(down), Mouse(up) });
  }
  public static void Chord(ushort[] keys, bool[] extended) {
    INPUT[] all = new INPUT[keys.Length * 2];
    for (int n = 0; n < keys.Length; n++) {
      all[n] = Key(keys[n], 0, extended[n] ? 1u : 0u);
      all[keys.Length * 2 - 1 - n] = Key(keys[n], 0, (extended[n] ? 1u : 0u) | 2u);
    }
    Send(all);
  }
  public static void Words(string words) {
    foreach (char c in words) {
      if (c == '\n') { Chord(new ushort[] { 0x0D }, new bool[] { false }); continue; }
      if (c == '\r') continue;
      Send(new INPUT[] { Key(0, c, 4u), Key(0, c, 4u | 2u) });
      // A word ends at a space or a mark; apps such as Windows 11 Notepad check and correct the word there.
      // Typing on before that check is done loses or repeats letters, so the pause after a word is longer.
      System.Threading.Thread.Sleep(char.IsLetterOrDigit(c) ? 15 : 120);
    }
  }
}
"@
# Not DPI-aware on purpose: X Y are then the same pixels as `screen snap --target laptop` pictures.
'''


class InputError(Exception):
    pass


def ps_string(text):
    """A PowerShell single-quoted string."""
    return "'" + text.replace("'", "''") + "'"


def parse_key(spec):
    names = [part.strip().lower() for part in spec.split('+')] if spec not in ('+',) else ['=']
    if not names or any(not name for name in names):
        raise InputError(USAGE['key'])
    codes = []
    for name in names:
        if name not in VK:
            raise InputError(f'Unknown key {name!r}. Known: letters, digits, f1-f24, ' + ', '.join(sorted(k for k in VK if len(k) > 1 and not re.fullmatch(r'f[0-9]+', k))))
        codes.append(VK[name])
    return codes


def body(verb, args):
    """The PowerShell that runs on George's desktop, and what it reports back."""
    if verb in ('click', 'move'):
        flags = [a for a in args if a.startswith('--')]
        numbers = [a for a in args if not a.startswith('--')]
        if len(numbers) != 2 or not all(re.fullmatch(r'[0-9]{1,5}', n) for n in numbers) or verb == 'move' and flags \
                or any(f not in ('--right', '--double') for f in flags) or len(flags) > 1:
            raise InputError(USAGE[verb])
        x, y = (int(n) for n in numbers)
        code = f'$at=[HarnessInput]::Move({x},{y}); '
        if verb == 'click':
            button, times = ('right', 1) if '--right' in flags else ('left', 2 if '--double' in flags else 1)
            code += f"Start-Sleep -Milliseconds 60; [HarnessInput]::Click('{button}',{times}); "
            return code + f"'{button} click{' x2' if times == 2 else ''} at '+$at", f'{button} click' + (' x2' if times == 2 else '') + f' at {x} {y}'
        return code + "'cursor at '+$at", f'moved to {x} {y}'
    if verb == 'type':
        if len(args) != 1 or args[0] == '':
            raise InputError(USAGE['type'])
        encoded = base64.b64encode(args[0].encode('utf-8')).decode()
        return (f"$w=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}')); [HarnessInput]::Words($w); 'typed '+$w.Length+' characters'",
                f'typed {len(args[0])} characters')
    if verb == 'key':
        if len(args) != 1:
            raise InputError(USAGE['key'])
        codes = parse_key(args[0])
        keys = ','.join(str(c) for c in codes)
        ext = ','.join('$true' if c in EXTENDED else '$false' for c in codes)
        return f"[HarnessInput]::Chord([uint16[]]@({keys}),[bool[]]@({ext})); 'pressed {args[0]}'", f'pressed {args[0]}'
    raise InputError('usage: laptop-input.py click|move|type|key ...')


def command(inner_body):
    """(name, script): a one-shot interactive scheduled task runs inner_body on the logged-in desktop and reports back."""
    ident = 'harness-input-' + uuid.uuid4().hex
    status = "$env:TEMP+'\\" + ident + ".status'"
    inner = ("$ErrorActionPreference='Stop'; $status=" + status + "; try {\n" + HELPER + "$said=(& {" + inner_body
             + "}); ('OK '+$said+' | front window: '+[HarnessInput]::Front()) | Set-Content -Encoding UTF8 $status} catch { ('ERR '+$_.Exception.Message) | Set-Content -Encoding UTF8 $status; exit 1 }")
    encoded = base64.b64encode(inner.encode('utf-8')).decode()
    # The desktop script goes into a file: as one command line it is longer than Windows allows.
    outer = f'''$ErrorActionPreference='Stop'
$name='{ident}'; $status={status}; $vbs=$env:TEMP+'\\{ident}.vbs'; $ps1=$env:TEMP+'\\{ident}.ps1'
try {{
 [IO.File]::WriteAllText($ps1,[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}')),(New-Object Text.UTF8Encoding($true)))
 $script='Set sh=CreateObject("WScript.Shell")'+[Environment]::NewLine+'code=sh.Run("powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File ""'+$ps1+'""",0,True)'+[Environment]::NewLine+'WScript.Quit code'
 [IO.File]::WriteAllText($vbs,$script,[Text.Encoding]::ASCII)
 $action=New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('//B //Nologo "'+$vbs+'"')
 $user=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
 $principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
 $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds 120) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
 Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings -Force | Out-Null
 Start-ScheduledTask -TaskName $name
 $end=(Get-Date).AddSeconds(120)
 while(!(Test-Path $status) -and (Get-Date) -lt $end) {{ Start-Sleep -Milliseconds 150 }}
 if(!(Test-Path $status)) {{ throw 'no answer from the desktop in 120 s: nobody is logged in on the laptop screen, or it is locked' }}
 [Console]::Write((Get-Content -Encoding UTF8 $status -Raw).Trim())
}} catch {{ [Console]::Write('ERR '+$_.Exception.Message); exit 1 }} finally {{ Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue; Remove-Item $status,$vbs,$ps1 -Force -ErrorAction SilentlyContinue }}'''
    return ident, outer


def deliver(ident, script, run=subprocess.run):
    """Copy the script to the laptop with scp, run it, then delete it.
    It cannot go on the command line (the laptop's ssh shell is cmd.exe: 8,191 characters at most), and Windows
    OpenSSH stops passing stdin to PowerShell after 4,096 bytes, so it travels as a file."""
    with tempfile.TemporaryDirectory(prefix='laptop-input-') as folder:
        local = os.path.join(folder, ident + '-run.ps1')
        with open(local, 'w', encoding='utf-8-sig') as handle:
            handle.write(script)
        copied = run(['scp', '-q', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', local, f'wimlaptop:{REMOTE}/{ident}-run.ps1'],
                     capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        if copied.returncode != 0:
            return copied
    remote = REMOTE.replace('/', '\\') + '\\' + ident + '-run.ps1'
    return run(SSH + [f'powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{remote}" & del "{remote}"'],
               capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)


def main(argv, run=subprocess.run):
    if not argv or argv[0] not in USAGE:
        print('usage: laptop-input.py click|move|type|key ...', file=sys.stderr)
        return 2
    try:
        inner, _ = body(argv[0], argv[1:])
    except InputError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        done = deliver(*command(inner), run=run)
    except subprocess.TimeoutExpired:
        print('The laptop did not answer in 180 s.', file=sys.stderr)
        return 1
    said = (done.stdout or '').strip()
    if done.returncode == 0 and said.startswith('OK '):
        print(said[3:])
        return 0
    noise = re.sub(r'#< CLIXML.*', '', (done.stderr or ''), flags=re.S).strip()
    message = said[4:] if said.startswith('ERR ') else (noise.splitlines()[-1] if noise else said or f'ssh exit {done.returncode}')
    print('laptop: ' + message, file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
