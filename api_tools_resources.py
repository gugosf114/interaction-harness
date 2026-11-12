"""File-ID transport and opt-in provider compaction; never change the frozen pages."""
import copy
import json
import hashlib
import re
from pathlib import Path

from attachments import describe
from api_tools_config import write_json


def prepare_files(runtime,client,messages):
    cache_path=runtime.state/'provider-files.json'
    cache=json.loads(cache_path.read_text()) if cache_path.exists() else {}
    engine=runtime.engine;mapping=cache.setdefault(engine,{})
    prepared=[]
    for message in messages:
        attached=message.get('attachments',[])
        clean={k:copy.deepcopy(v) for k,v in message.items() if k!='attachments'}
        if attached:
            blocks=[{'type':'input_text' if engine=='openai' else 'text','text':clean['content']}]
            for saved in attached:
                current=describe(saved['kind'],saved['path'],engine)
                if current!=saved:raise ValueError('A saved attachment changed before Files API upload.')
                digest=saved['sha256'];file_id=mapping.get(digest)
                if not file_id:
                    path=Path(saved['path'])
                    with path.open('rb') as stream:
                        if engine=='openai':uploaded=client.files.create(file=(path.name,stream,saved['media_type']),purpose='user_data')
                        else:uploaded=client.files.upload(file=(path.name,stream,saved['media_type']))
                    file_id=uploaded.id;mapping[digest]=file_id;write_json(cache_path,cache)
                    runtime.record('files',file_id,'success',operation='upload',attachment=saved)
                else:runtime.record('files',file_id,'success',operation='reference',attachment=saved)
                if engine=='openai':blocks.append({'type':'input_file' if saved['kind']=='file' else 'input_image','file_id':file_id})
                else:blocks.append({'type':'document' if saved['kind']=='file' else 'image','source':{'type':'file','file_id':file_id}})
            clean['content']=blocks
        prepared.append(clean)
    return prepared


def compact_messages(runtime,client,messages,system_pages):
    """Use the on-demand endpoints. Keep their complete returned context intact."""
    from senses import dump
    if runtime.prepared:return messages
    count=len(system_pages);past=messages[count:-1]
    if not any(m.get('role')=='assistant' for m in past) or len(json.dumps(past))<int(runtime.options['compaction_threshold']):return messages
    if runtime.engine=='openai':
        result=client.responses.compact(model=runtime.model,input=past,instructions='\n\n'.join(system_pages))
        context=result.model_dump(exclude_none=True,by_alias=True,warnings=False)['output']
        runtime.compacted={'engine':'openai','messages':context}
        runtime.record('compaction',result.id,'success',usage=dump(result.usage),context_items=len(context))
        # Endpoint output is the canonical context, including retained input items.
        return [*messages[:count],*context,messages[-1]]
    result=client.beta.messages.create(model=runtime.model,max_tokens=8192,
        betas=['compact-2026-09-04'],compaction={'type':'summarize'},
        system=[{'type':'text','text':text} for text in system_pages],messages=past)
    if result.stop_reason!='compaction':raise ValueError('Claude returned no compaction block.')
    context=[{'role':'assistant','content':dump(result.content)}]
    runtime.compacted={'engine':'anthropic','messages':context}
    runtime.record('compaction',result.id,'success',usage=dump(result.usage),context_items=len(context))
    return [*messages[:count],*context,messages[-1]]


def fetch_output_files(runtime,client,response):
    """Only provider-produced file blocks/citations can trigger output downloads."""
    from api_tools_runtime import block_data
    if not runtime.settings.on('files'):return
    def visit(value):
        if isinstance(value,dict):
            if value.get('file_id') and value.get('type') in ('bash_code_execution_output','code_execution_output','container_file_citation'):
                yield value
            for item in value.values():yield from visit(item)
        elif isinstance(value,list):
            for item in value:yield from visit(item)
    for file in visit(block_data(response)):
        ident=file['file_id']
        if ident in runtime.downloaded:continue
        runtime.downloaded.add(ident)
        try:
            if runtime.engine=='openai':
                content=client.containers.files.content.retrieve(ident,container_id=file['container_id'])
                filename=file.get('filename',ident)
            else:
                meta=client.files.retrieve_metadata(ident);filename=meta.filename
                content=client.files.download(ident)
            safe=re.sub(r'[^a-zA-Z0-9._-]','_',Path(filename).name)[:140] or 'output.bin'
            folder=runtime.state/'downloads'/re.sub(r'[^a-zA-Z0-9_-]','_',ident)
            folder.mkdir(parents=True,exist_ok=True,mode=0o700);path=folder/safe
            content.write_to_file(path)
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            runtime.record('files',ident,'success',operation='download',artifact=str(path),sha256=digest,size_bytes=path.stat().st_size)
        except Exception as exc:
            runtime.record('files',ident,'failed',operation='download',provider={'error':str(exc)})
