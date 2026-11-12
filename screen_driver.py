"""One native command for Android displays and the Windows console desktop."""
import argparse
import base64
import gzip
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import uuid

from attachments import phone_path, PHONE_HOME
from execution_images import announce

ROOT = Path(__file__).resolve().parent
HIDDEN = '/root/hidden-operator/scripts/hidden_display.sh'
PHONE = '127.0.0.1:5555'
YANA = '100.68.147.84:5555'


class ScreenError(ValueError): pass


def target_name(value):
    if value in ('phone', 'laptop', 'yana'): return value
    if re.fullmatch(r'hidden:[A-Za-z0-9_-]{1,64}', value): return value
    raise ScreenError('unknown target: ' + value)


def android_command(target, verb, values=(), display=None):
    """One shell argument for adb; never interpolate unquoted text remotely."""
    prefix = ['deb', 'adb', '-s', YANA] if target == 'yana' else ['adb', '-s', PHONE]
    remote = ['input']
    if target.startswith('hidden:'):
        if not display or not re.fullmatch(r'[1-9][0-9]*', str(display)):
            raise ScreenError('hidden display has no valid id')
        remote += ['-d', str(display)]
    remote += ['keyevent' if verb == 'key' else verb]
    if verb == 'text':
        # Android input's text path supports ASCII and treats %s as a space.
        # Reject Unicode and literal %s instead of silently typing other words.
        text = values[0]
        if any(ord(c) < 32 or ord(c) > 126 for c in text) or '%s' in text:
            raise ScreenError('Android text needs printable ASCII without literal %s')
        values = [text.replace(' ', '%s')]
    remote += [str(x) for x in values]
    return prefix + ['shell', shlex.join(remote)]


def powershell_body(verb, values):
    """Runs in the signed-in Windows user's interactive desktop, not SSH session 0."""
    if verb in ('snap', 'size'):
        return '''Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$image=New-Object System.Drawing.Bitmap($b.Width,$b.Height)
$g=[System.Drawing.Graphics]::FromImage($image)
try {$g.CopyFromScreen($b.Left,$b.Top,0,0,$b.Size); $image.Save($output,[System.Drawing.Imaging.ImageFormat]::Png)}
finally {$g.Dispose(); $image.Dispose()}'''
    common = '''Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class HarnessMouse { [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y); [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e); }'
'''
    if verb == 'tap':
        x, y = values
        return common + f'[HarnessMouse]::SetCursorPos({x},{y}) | Out-Null; [HarnessMouse]::mouse_event(2,0,0,0,[UIntPtr]::Zero); [HarnessMouse]::mouse_event(4,0,0,0,[UIntPtr]::Zero)'
    if verb == 'swipe':
        x, y, end_x, end_y, ms = values
        return common + f'''[HarnessMouse]::SetCursorPos({x},{y}) | Out-Null
[HarnessMouse]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
try {{ for($i=1;$i -le 20;$i++) {{ [HarnessMouse]::SetCursorPos([int]({x}+({end_x}-{x})*$i/20),[int]({y}+({end_y}-{y})*$i/20)) | Out-Null; Start-Sleep -Milliseconds {max(1, int(ms)//20)} }} }}
finally {{ [HarnessMouse]::mouse_event(4,0,0,0,[UIntPtr]::Zero) }}'''
    if verb == 'text':
        # SendKeys metacharacters must be escaped; no clipboard replacement.
        value = ''.join('{'+c+'}' if c in '+^%~()[]{}' else c for c in values[0])
        value = value.replace("'", "''")
        return common + "[System.Windows.Forms.SendKeys]::SendWait('" + value + "')"
    keys = {'KEYCODE_ENTER': 'ENTER', '66': 'ENTER', 'ENTER': 'ENTER',
            'KEYCODE_TAB': 'TAB', '61': 'TAB', 'TAB': 'TAB',
            'KEYCODE_ESCAPE': 'ESC', '111': 'ESC', 'ESC': 'ESC', 'ESCAPE': 'ESC',
            'KEYCODE_DEL': 'BACKSPACE', '67': 'BACKSPACE', 'BACKSPACE': 'BACKSPACE',
            'KEYCODE_DPAD_UP': 'UP', '19': 'UP', 'UP': 'UP', 'KEYCODE_DPAD_DOWN': 'DOWN', '20': 'DOWN', 'DOWN': 'DOWN',
            'KEYCODE_DPAD_LEFT': 'LEFT', '21': 'LEFT', 'LEFT': 'LEFT', 'KEYCODE_DPAD_RIGHT': 'RIGHT', '22': 'RIGHT', 'RIGHT': 'RIGHT'}
    key = keys.get(str(values[0]).upper())
    if key is None: raise ScreenError('laptop key is not supported')
    return common + "[System.Windows.Forms.SendKeys]::SendWait('{" + key + "}')"


def laptop_command(verb, values=()):
    body = powershell_body(verb, values)
    # Unique task/file names avoid crossing two harness sessions. All are removed.
    ident = 'harness-screen-' + uuid.uuid4().hex
    output = "$env:TEMP+'\\" + ident + ".png'"
    status = "$env:TEMP+'\\" + ident + ".status'"
    inner = "$ErrorActionPreference='Stop'; $output=" + output + '; $status=' + status + '; try {\n' + body + "\n'OK' | Set-Content $status} catch { $_.Exception.Message | Set-Content $status; exit 1 }"
    encoded = base64.b64encode(inner.encode('utf-16le')).decode()
    outer = f'''$ErrorActionPreference='Stop'
$name='{ident}'; $output={output}; $status={status}; $vbs=$env:TEMP+'\\{ident}.vbs'
try {{
 $script='Set sh=CreateObject("WScript.Shell")'+[Environment]::NewLine+'code=sh.Run("powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand {encoded}",0,True)'+[Environment]::NewLine+'WScript.Quit code'
 [IO.File]::WriteAllText($vbs,$script,[Text.Encoding]::ASCII)
 $action=New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('//B //Nologo "'+$vbs+'"')
 $user=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
 $principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
 $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
 Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings -Force | Out-Null
 Start-ScheduledTask -TaskName $name
 $end=(Get-Date).AddSeconds(35)
 while(!(Test-Path $status) -and (Get-Date) -lt $end) {{ Start-Sleep -Milliseconds 200 }}
 if(!(Test-Path $status)) {{ throw 'interactive desktop timeout' }}
 if((Get-Content $status -Raw).Trim() -ne 'OK') {{ throw (Get-Content $status -Raw) }}
 {'[Console]::Write([Convert]::ToBase64String([IO.File]::ReadAllBytes($output)))' if verb in ('snap','size') else "[Console]::Write('OK')"}
}} finally {{ Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue; Remove-Item $output,$status,$vbs -Force -ErrorAction SilentlyContinue }}'''
    compressed = base64.b64encode(gzip.compress(outer.encode('utf-8'))).decode()
    loader = "$b=[Convert]::FromBase64String('" + compressed + "'); $m=New-Object IO.MemoryStream(,$b); $g=New-Object IO.Compression.GZipStream($m,[IO.Compression.CompressionMode]::Decompress); $r=New-Object IO.StreamReader($g); Invoke-Expression $r.ReadToEnd()"
    arg = base64.b64encode(loader.encode('utf-16le')).decode()
    return ['deb', 'ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'wimlaptop',
            'powershell -NoProfile -NonInteractive -EncodedCommand ' + arg]


def capture_command(target, out, surface_id=None):
    if target == 'phone': return ['deb', 'shot', str(out)]
    if target.startswith('hidden:'):
        if not surface_id or not re.fullmatch(r'[1-9][0-9]*', str(surface_id)):
            raise ScreenError('hidden screen has no capture id')
        return ['adb', '-s', PHONE, 'exec-out', 'screencap', '-p', '-d', str(surface_id)]
    if target == 'yana': return ['deb', 'adb', '-s', YANA, 'exec-out', 'screencap', '-p']
    return laptop_command('snap')


def hidden_surface_id(display, run):
    """Join logical and capture IDs by exact virtual uniqueId, never by name/order."""
    displays = run(['adb','-s',PHONE,'shell','cmd display get-displays --type VIRTUAL']).decode(errors='replace')
    matches = []
    for line in displays.splitlines():
        if line.startswith(f'Display id {display}:') and 'type VIRTUAL,' in line and 'isValid=true' in line:
            match = re.search(r'\buniqueId "([^"\r\n]+)"', line)
            if match: matches.append(match.group(1))
    if len(matches) != 1: raise ScreenError('hidden screen has no capture id')
    surfaces = run(['adb','-s',PHONE,'shell','dumpsys SurfaceFlinger --display-id']).decode(errors='replace')
    ids = []
    for line in surfaces.splitlines():
        match = re.fullmatch(r'Display ([1-9][0-9]*) \(Virtual display\): .*uniqueId="([^"\r\n]+)"', line)
        if match and match.group(2) == matches[0]: ids.append(match.group(1))
    if len(ids) != 1: raise ScreenError('hidden screen has no capture id')
    return ids[0]


def run_command(argv, timeout=60):
    try:
        result = subprocess.run(argv, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc: raise ScreenError('timeout') from exc
    except FileNotFoundError as exc: raise ScreenError('required command is missing: ' + argv[0]) from exc
    if result.returncode:
        error = result.stderr.decode(errors='replace') + result.stdout[:1000].decode(errors='replace')
        if 'timed out' in error.lower() or 'timeout' in error.lower(): raise ScreenError('timeout')
        if any(s in error.lower() for s in ('not found', 'offline', 'no devices', 'connection refused', 'could not resolve')):
            raise ScreenError('target is unavailable')
        raise ScreenError('command failed (exit ' + str(result.returncode) + ')')
    return result.stdout


def inspect_png(path, run):
    output = run(['deb', 'python3', str(ROOT/'toolbox/debian/screen-inspect.py'), str(path)])
    try: info = json.loads(output)
    except (ValueError, TypeError): raise ScreenError('capture is not a readable PNG')
    if info.get('black'): raise ScreenError('screen is off or capture is all black')
    return int(info['width']), int(info['height'])


def drive(verb, target, values=(), out=None, run=run_command):
    target = target_name(target)
    display = None
    if target.startswith('hidden:'):
        try:
            run(['deb', 'bash', HIDDEN, 'status', '-n', target[7:]])
            display = run(['deb', 'bash', HIDDEN, 'id', '-n', target[7:]]).decode().strip()
        except ScreenError as exc:
            if str(exc) == 'timeout': raise
            raise ScreenError('target is missing: ' + target) from exc
        if not re.fullmatch(r'[1-9][0-9]*', display): raise ScreenError('target is missing: ' + target)
    if verb in ('snap', 'size'):
        folder = PHONE_HOME / '.local/state/harness-screens'
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination = phone_path(out) if out else folder / (uuid.uuid4().hex + '.png')
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Publish only a complete, nonblack PNG; never attach an old --out file.
        fd, temp_name = tempfile.mkstemp(prefix='capture-', suffix='.png', dir=destination.parent)
        os.close(fd); temp = Path(temp_name)
        try:
            surface_id = hidden_surface_id(display, run) if target.startswith('hidden:') else None
            output = run(capture_command(target, temp, surface_id))
            if target == 'yana' or target.startswith('hidden:'): temp.write_bytes(output)
            elif target == 'laptop':
                try: temp.write_bytes(base64.b64decode(output.strip(), validate=True))
                except ValueError as exc: raise ScreenError('laptop returned no PNG') from exc
            width, height = inspect_png(temp, run)
            if verb == 'size': return f'{width} {height}'
            os.replace(temp, destination)
            announce(destination)
            return str(destination)
        finally: temp.unlink(missing_ok=True)
    if target == 'laptop': command = laptop_command(verb, values)
    else: command = android_command(target, verb, values, display)
    run(command)
    return ''


class Parser(argparse.ArgumentParser):
    def error(self, message): raise ScreenError(message)


def main(argv=None):
    parser = Parser(prog='screen', description='Capture or drive one named screen. Coordinates use full-size image pixels.')
    parser.add_argument('verb', choices=['snap', 'tap', 'swipe', 'text', 'key', 'size'])
    parser.add_argument('values', nargs='*')
    parser.add_argument('--target', default='phone')
    parser.add_argument('--out')
    try:
        args = parser.parse_intermixed_args(argv)
        counts = {'snap':(0,), 'size':(0,), 'tap':(2,), 'swipe':(4,5), 'text':(1,), 'key':(1,)}
        if len(args.values) not in counts[args.verb]: raise ScreenError('wrong arguments for ' + args.verb)
        if args.out and args.verb != 'snap': raise ScreenError('--out is for snap')
        values = args.values
        if args.verb in ('tap', 'swipe'):
            try: values = [int(v) for v in values]
            except ValueError: raise ScreenError('coordinates and duration must be whole numbers')
            if any(v < 0 or v > 100000 for v in values): raise ScreenError('coordinates or duration are out of range')
            if args.verb == 'swipe' and len(values) == 4: values.append(300)
        if args.verb == 'key' and not re.fullmatch(r'[A-Za-z0-9_]+', values[0]): raise ScreenError('invalid key code')
        result = drive(args.verb, args.target, values, args.out)
        if result: print(result)
        return 0
    except (ScreenError, OSError, ValueError) as exc:
        print('screen: ' + (str(exc) if isinstance(exc, ScreenError) else 'capture or receipt failed') + '.', file=sys.stderr)
        return 1


if __name__ == '__main__': raise SystemExit(main())
