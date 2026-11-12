"""CLI wiring kept separate from the core loop and operator-owned context pages."""
import json
from attachments import collect, chat_attachment
from lookup_gate import violation


def add_flags(parser):
    parser.add_argument('--no-web',action='store_true',help='Disable hosted web search and fetch.')
    parser.add_argument('--web-max',type=int,default=5,help='Total hosted lookup ceiling per model turn (2–50; default 5).')
    parser.add_argument('--image',dest='images',action='append',default=[],metavar='PATH',help='Attach PNG/JPEG/WebP/GIF bytes; repeatable.')
    parser.add_argument('--file',dest='files',action='append',default=[],metavar='PATH',help='Attach PDF bytes; repeatable.')


def validate_args(parser,args):
    if not 2<=args.web_max<=50:parser.error('--web-max must be between 2 and 50.')
    if args.recall is not None and (args.images or args.files):parser.error('--recall does not take attachments.')
    if args.chat and (args.images or args.files) and not args.text:parser.error('Give an initial question with chat attachments, or use /image or /file inside chat.')


def common_options(args):return ['--web-max',str(args.web_max)]+(['--no-web'] if args.no_web else [])


def attachment_options(args):return [v for flag,paths in [('--image',args.images),('--file',args.files)] for path in paths for v in (flag,path)]


def chat_input(raw):
    if raw.startswith(('/image ','/file ')):
        kind,path,question=chat_attachment(raw)
        return ['--'+kind,path],question
    return [],raw


def prepare(args):return collect(args.images,args.files,args.engine)


def saved_metadata(row):
    return {'sources':json.loads(row.get('sources_json') or '[]'),
            'lookup_counts':json.loads(row.get('lookup_counts_json') or '{"total":0}')}


def recall_violation(reply,row,metadata):
    allowed=(row.get('normalized_input') or row.get('raw_input') or '')+' '+' '.join(metadata['lookup_counts'].get('allowed_urls',[]))
    return violation(reply.direct_answer,metadata['lookup_counts'],metadata['sources'],allowed)
