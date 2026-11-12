#!/data/data/com.termux/files/usr/bin/python
"""Client-tool jobs, entered only through the harness's approved native runner."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

from attachments import phone_path
from execution_images import announce


def bounded_path(root, value, virtual='/memories'):
    root=Path(root).resolve();value=str(value)
    if value==virtual:relative=''
    elif value.startswith(virtual+'/'):relative=value[len(virtual)+1:]
    else:raise ValueError('Memory paths must start with /memories.')
    path=(root/relative).resolve()
    if not path.is_relative_to(root):raise ValueError('Memory path leaves its notes folder.')
    return path


def file_operation(args, *, memory_root=None, workdir=None):
    command=args['command'];value=args.get('path','/memories' if memory_root else '.')
    path=bounded_path(memory_root,value) if memory_root else phone_path(value if Path(value).is_absolute() or value.startswith('~/') else str(Path(workdir or os.getcwd())/value))
    if command!='view' and '/root/.claude/projects/-root/memory' in str(path):
        raise ValueError('The canonical memory folder is read-only.')
    if memory_root:Path(memory_root).mkdir(parents=True,exist_ok=True,mode=0o700)
    if command=='view':
        if path.is_dir():
            lines=[]
            for item in sorted(path.rglob('*')):
                if item.is_symlink():continue
                lines.append(str(item.relative_to(path))+('/' if item.is_dir() else ''))
            return '\n'.join(lines) or '(empty folder)'
        text=path.read_text();lines=text.splitlines();span=args.get('view_range')
        if not lines:return '(empty file)'
        first,last=(span if span else (1,len(lines)))
        if first<1 or (last!=-1 and last<first):raise ValueError('Invalid view range.')
        last=len(lines) if last==-1 else last
        return '\n'.join(f'{i+first}: {line}' for i,line in enumerate(lines[first-1:last]))
    if command=='create':
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x') as stream:stream.write(args.get('file_text',''))
    elif command=='str_replace':
        old=args['old_str'];text=path.read_text()
        if not old or text.count(old)!=1:raise ValueError('Replacement needs exactly one match.')
        path.write_text(text.replace(old,args.get('new_str',''),1))
    elif command=='insert':
        text=path.read_text();lines=text.splitlines(keepends=True);line=args['insert_line']
        if not isinstance(line,int) or line<0 or line>len(lines):raise ValueError('Insert line is out of range.')
        insert=args['insert_text'] if 'insert_text' in args else args['new_str']
        if insert and not insert.endswith('\n'):insert+='\n'
        lines.insert(line,insert);path.write_text(''.join(lines))
    elif command=='delete' and memory_root:
        if path==Path(memory_root).resolve():raise ValueError('Cannot delete the notes root.')
        if path.is_dir():shutil.rmtree(path)
        else:path.unlink()
    elif command=='rename' and memory_root:
        target=bounded_path(memory_root,args['new_path']);target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():raise ValueError('Rename destination already exists.')
        path.rename(target)
    else:raise ValueError('Unsupported file command: '+str(command))
    return command+' completed: '+str(path)


def apply_diff(original, diff):
    """The documented apply_patch context format: exact hunks, no fuzzy edits."""
    lines=diff.splitlines();chunks=[];old=[];new=[]
    for line in lines:
        if line.startswith('@@'):
            if old or new:chunks.append((old,new));old=[];new=[]
        elif line=='*** End of File':continue
        elif line.startswith(' '):old.append(line[1:]);new.append(line[1:])
        elif line.startswith('-'):old.append(line[1:])
        elif line.startswith('+'):new.append(line[1:])
        elif line=='':continue
        else:raise ValueError('Patch has an invalid hunk line.')
    if old or new:chunks.append((old,new))
    content=original.splitlines();cursor=0
    for before,after in chunks:
        hits=[i for i in range(cursor,len(content)-len(before)+1) if content[i:i+len(before)]==before]
        if len(hits)!=1:raise ValueError('Patch context must match exactly once.')
        pos=hits[0];content[pos:pos+len(before)]=after;cursor=pos+len(after)
    return '\n'.join(content)+('\n' if original.endswith('\n') or diff.endswith('\n') else '')


def patch_operation(operation, workdir):
    root=Path(workdir).resolve();path=(root/operation['path']).resolve()
    if not path.is_relative_to(root):raise ValueError('Patch path leaves the working folder.')
    kind=operation['type']
    if kind=='delete_file':path.unlink()
    elif kind=='create_file':
        diff=operation.get('diff','');lines=diff.splitlines()
        if any(not line.startswith('+') for line in lines):raise ValueError('Create patch needs added lines.')
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x') as f:f.write('\n'.join(line[1:] for line in lines)+'\n')
    elif kind=='update_file':path.write_text(apply_diff(path.read_text(),operation['diff']))
    else:raise ValueError('Unknown patch operation.')
    return kind+' completed: '+str(path)


KEYS={'Return':'KEYCODE_ENTER','Enter':'KEYCODE_ENTER','ENTER':'KEYCODE_ENTER','Tab':'KEYCODE_TAB',
      'TAB':'KEYCODE_TAB','Escape':'KEYCODE_ESCAPE','ESC':'KEYCODE_ESCAPE','BackSpace':'KEYCODE_DEL',
      'BACKSPACE':'KEYCODE_DEL','Back':'KEYCODE_BACK','Home':'KEYCODE_MOVE_HOME','End':'KEYCODE_MOVE_END',
      'Up':'KEYCODE_DPAD_UP','Down':'KEYCODE_DPAD_DOWN','Left':'KEYCODE_DPAD_LEFT','Right':'KEYCODE_DPAD_RIGHT',
      'Page_Up':'KEYCODE_PAGE_UP','Page_Down':'KEYCODE_PAGE_DOWN','Delete':'KEYCODE_FORWARD_DEL','space':'KEYCODE_SPACE'}
MODIFIERS={'ctrl':'KEYCODE_CTRL_LEFT','control':'KEYCODE_CTRL_LEFT','shift':'KEYCODE_SHIFT_LEFT',
           'alt':'KEYCODE_ALT_LEFT','meta':'KEYCODE_META_LEFT','super':'KEYCODE_META_LEFT'}


def android_input(target,arguments,source='touchscreen'):
    import screen_driver as screen
    if target=='laptop':raise ValueError('This Android input action is unavailable on the laptop target.')
    display='0';prefix=['adb','-s',screen.PHONE]
    if target=='yana':prefix=['deb','adb','-s',screen.YANA]
    elif target.startswith('hidden:'):
        screen.run_command(['deb','bash',screen.HIDDEN,'status','-n',target[7:]])
        display=screen.run_command(['deb','bash',screen.HIDDEN,'id','-n',target[7:]]).decode().strip()
        if not re.fullmatch(r'[1-9][0-9]*',display):raise ValueError('The hidden input target is missing.')
    elif target!='phone':raise ValueError('Unknown input target.')
    return screen.run_command(prefix+['shell',shlex.join(['input',source,'-d',display,*map(str,arguments)])])


def computer_actions(job):
    import screen_driver as screen
    target=job['target'];state=Path(job['state']);state.mkdir(parents=True,exist_ok=True,mode=0o700)
    pointer_file=state/'computer-pointer.json'
    pointer=json.loads(pointer_file.read_text()) if pointer_file.exists() else [0,0]
    texts=[];images=[]
    actions=job['actions']
    for action in actions:
        kind=action.get('type') or action.get('name');args=action.get('input',action)
        coord=args.get('coordinate') or ([args['x'],args['y']] if 'x' in args else pointer)
        if args.get('text') and kind in ('left_click','double_click','triple_click','right_click','middle_click','scroll','left_click_drag'):
            raise ValueError('Modified pointer actions are unavailable on this touch-screen adapter.')
        if kind in ('screenshot','zoom'):
            image=screen.drive('snap',target)
            if kind=='zoom':
                region=args['region']
                out=state/('zoom-'+str(time.time_ns())+'.png')
                result=subprocess.run(['deb','python3',str(Path(__file__).with_name('api_tools_image.py')),image,str(out),json.dumps(region)],capture_output=True,text=True)
                if result.returncode:raise ValueError(result.stderr.strip() or 'Zoom failed.')
                image=str(out);announce(image)
            images.append(image)
        elif kind in ('click','left_click','double_click','triple_click','right_click','middle_click'):
            if kind=='click' and args.get('button','left')!='left':kind=args['button']+'_click'
            if kind in ('right_click','middle_click'):raise ValueError('This screen driver has no '+kind.split('_')[0]+' mouse button.')
            else:
                for _ in range({'double_click':2,'triple_click':3}.get(kind,1)):screen.drive('tap',target,coord)
            pointer=coord
        elif kind=='type':screen.drive('text',target,[args['text']])
        elif kind in ('key','keypress'):
            keys=args.get('keys') or [args.get('text','')]
            for _ in range(args.get('repeat',1)):
                chord=[]
                for key in keys:chord.extend(key.split('+'))
                mapped=[MODIFIERS.get(key.lower(),KEYS.get(key,key if key.startswith('KEYCODE_') else 'KEYCODE_'+key.upper())) for key in chord]
                if len(mapped)>1:android_input(target,['keycombination',*mapped],'keyboard')
                else:screen.drive('key',target,mapped)
        elif kind=='hold_key':
            chord=args['text'].split('+');mapped=[MODIFIERS.get(k.lower(),KEYS.get(k,k if k.startswith('KEYCODE_') else 'KEYCODE_'+k.upper())) for k in chord]
            duration=max(0,min(30000,int(args['duration']*1000)))
            if len(mapped)>1:android_input(target,['keycombination','-t',duration,*mapped],'keyboard')
            else:android_input(target,['keyevent','--duration',duration,*mapped],'keyboard')
        elif kind in ('drag','left_click_drag'):
            points=args.get('path')
            if points:points=[[p['x'],p['y']] for p in points]
            else:points=[args.get('start_coordinate',pointer),coord]
            if len(points)==2:screen.drive('swipe',target,[*points[0],*points[1],300])
            else:
                android_input(target,['motionevent','DOWN',*points[0]])
                try:
                    for point in points[1:]:android_input(target,['motionevent','MOVE',*point])
                finally:android_input(target,['motionevent','UP',*points[-1]])
            pointer=points[-1]
        elif kind=='scroll':
            amount=args.get('scroll_amount',3)*100
            direction=args.get('scroll_direction','down')
            dx=args.get('scroll_x',(-amount if direction=='left' else amount if direction=='right' else 0))
            dy=args.get('scroll_y',(-amount if direction=='up' else amount if direction=='down' else 0))
            width,height=map(int,screen.drive('size',target).split())
            start=[width//2,height//2]
            end=[max(1,min(width-1,start[0]-dx)),max(1,min(height-1,start[1]-dy))]
            screen.drive('swipe',target,[*start,*end,300]);pointer=end
        elif kind in ('move','mouse_move'):android_input(target,['motionevent','MOVE',*coord],'mouse');pointer=coord
        elif kind in ('left_mouse_down','left_mouse_up'):android_input(target,['motionevent','DOWN' if kind=='left_mouse_down' else 'UP',*coord]);pointer=coord
        elif kind=='cursor_position':raise ValueError('The touch-screen adapter cannot read a desktop cursor position.')
        elif kind=='wait':time.sleep(max(0,min(30,float(args.get('duration',1)))))
        else:raise ValueError('This screen driver does not implement '+str(kind)+'.')
    pointer_file.write_text(json.dumps(pointer))
    if job.get('final_screenshot') and not images:images.append(screen.drive('snap',target))
    return {'text':'\n'.join(texts) or 'OK','images':images}


def execute(job):
    kind=job['kind'];args=job.get('args',{})
    if kind=='memory':
        if args.get('command')=='rename' and 'path' not in args:args={**args,'path':args['old_path']}
        return {'text':file_operation(args,memory_root=Path(job['state'])/'memory')}
    if kind=='text_editor':return {'text':file_operation(args,workdir=job['workdir'])}
    if kind=='apply_patch':return {'text':patch_operation(args,job['workdir'])}
    if kind=='computer':return computer_actions(job)
    if kind=='browser':
        from api_browser import run
        output=run(job)
        for image in output.get('images',[]):announce(image)
        return output
    raise ValueError('Unknown native API tool job.')


def main():
    job=None
    try:
        job=json.loads(Path(sys.argv[1]).read_text())
        output=execute(job);print(json.dumps(output,ensure_ascii=False));return 0
    except Exception as exc:
        result={'error':str(exc)}
        if job and job.get('kind')=='computer' and job.get('final_screenshot'):
            try:
                import screen_driver
                result['images']=[screen_driver.drive('snap',job['target'])]
            except Exception:pass
        print(json.dumps(result));return 1


if __name__=='__main__':raise SystemExit(main())
