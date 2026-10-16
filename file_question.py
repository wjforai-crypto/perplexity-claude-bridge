"""Read an explicitly selected local file and analyze it through this proxy.

Invoked by Claude's normal Bash tool, which retains its permission checks.
Credentials stay in the launcher and never appear in the command or tool output.
"""
import argparse,base64,json,mimetypes,pathlib,sys
from urllib.parse import unquote,urlsplit
import httpx
from anthropic_bridge import MIME_EXT,MAX_FILE_BYTES
from local_config import PRIVATE

# Claude's Bash tool decodes captured output as UTF-8 on Windows, while Python
# otherwise inherits the legacy system code page in non-interactive pipes.
sys.stdout.reconfigure(encoding='utf-8',errors='backslashreplace')
sys.stderr.reconfigure(encoding='utf-8',errors='backslashreplace')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--file',required=True)
    p.add_argument('--prompt',required=True)
    p.add_argument('--model',choices=['claude-opus-5-5','claude-sonnet-5-5'],default='claude-opus-5-5')
    args=p.parse_args()
    filename=args.file
    if filename.lower().startswith('file:'):
        url=urlsplit(filename)
        if url.netloc not in ('','localhost'):p.error('Only local file URLs are supported.')
        filename=unquote(url.path)
        if len(filename)>2 and filename[0]=='/' and filename[2]==':':filename=filename[1:]
    path=pathlib.Path(filename).resolve(strict=True)
    if not path.is_file() or path.stat().st_size>MAX_FILE_BYTES:
        p.error('Choose one regular file no larger than 50 MiB.')
    raw=path.read_bytes()
    if not raw:p.error('File is empty.')
    mime=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    if path.suffix.lower() in ('.md','.txt','.csv','.json','.py','.js','.ts','.html','.css','.log','.yaml','.yml'):
        try:text=raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig')
        except UnicodeError:p.error('Text file must use UTF-8 or BOM-marked UTF-16.')
        attachment={'type':'document','title':path.name,'source':{'type':'text','media_type':'text/plain','data':text}}
    else:
        if mime not in MIME_EXT:p.error('Supported binary formats: images, PDF, MP4/WebM, MP3/WAV. Convert other formats first.')
        attachment={'type':'image' if mime.startswith('image/') else 'document','title':path.name,'source':{'type':'base64','media_type':mime,'data':base64.b64encode(raw).decode()}}
    key=(PRIVATE/'api-key.txt').read_text(encoding='utf-8').strip()
    body={'model':args.model,'max_tokens':4000,'messages':[{'role':'user','content':[{'type':'text','text':args.prompt},attachment]}]}
    with httpx.Client(trust_env=False,timeout=240) as client:
        response=client.post('http://127.0.0.1:18080/v1/messages',headers={'Authorization':'Bearer '+key,'anthropic-version':'2023-06-01'},json=body)
    data=response.json()
    if response.status_code!=200:
        print(json.dumps({'ok':False,'status':response.status_code,'error':data.get('error')},ensure_ascii=False));return 1
    print(json.dumps({'ok':True,'source_file':path.name,'model':args.model,'answer':''.join(b.get('text','') for b in data['content'])},ensure_ascii=False))
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,httpx.HTTPError,ValueError) as ex:
        print(json.dumps({'ok':False,'error_type':type(ex).__name__},ensure_ascii=False));raise SystemExit(1)
