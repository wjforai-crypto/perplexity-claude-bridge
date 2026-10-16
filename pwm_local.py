"""Local launcher; keeps credentials scoped to this installation."""
import json
import os
import sys

from local_config import ROOT, PRIVATE
os.environ['PWM_CONNECTORS_ENABLED'] = '0'
os.environ['PWM_SAVE_TO_LIBRARY'] = '0'
os.environ['PYTHONIOENCODING'] = 'utf-8'

from perplexity_web_mcp import token_store
token_store.CONFIG_DIR = PRIVATE
token_store.TOKEN_FILE = PRIVATE / 'session.token'
MODEL_IDS = {'claude-opus-5-5': ('pplx_asi_opus','pplx_asi_opus'),
             'claude-sonnet-5-5': ('claude55sonnet','claude55sonnetthinking')}

def configure_api():
    from upload_guard import install_upload_guard
    install_upload_guard()
    os.environ['PWM_API_KEY'] = (PRIVATE / 'api-key.txt').read_text(encoding='utf-8').strip()
    if not os.environ['PWM_API_KEY']:
        raise RuntimeError('Local API key is empty. Run initialize.py before starting the proxy.')
    from fastapi import HTTPException
    from fastapi.responses import JSONResponse
    from perplexity_web_mcp.api import server
    from perplexity_web_mcp.enums import SearchFocus
    from perplexity_web_mcp.models import Model
    from perplexity_web_mcp.core import Conversation
    from functools import partial
    server.ConversationConfig = partial(server.ConversationConfig, source_focus=[], search_focus=SearchFocus.WRITING)
    server.cached_search_identifiers = lambda: []
    original_execute = Conversation._execute
    def execute_with_short_url(self, query, model, files, stream=False, init_query=None):
        # Initialization is only a web-session handshake. The full conversation
        # remains untouched in the subsequent POST body.
        return original_execute(self, query, model, files, stream=stream, init_query='Claude Desktop conversation')
    Conversation._execute = execute_with_short_url
    def strict_model(name, thinking=False):
        if name not in MODEL_IDS:
            raise HTTPException(status_code=400, detail='Use claude-opus-5-5 or claude-sonnet-5-5; automatic fallback is disabled.')
        return Model(identifier=MODEL_IDS[name][1 if thinking else 0])
    server.get_model = strict_model
    server.AVAILABLE_MODELS = [{'id':m,'description':m+(' via Perplexity Computer' if 'opus' in m else ' via Perplexity Search')} for m in MODEL_IDS]
    from anthropic_bridge import install
    install(server, PRIVATE)
    @server.app.middleware('http')
    async def enforce_model(request, call_next):
        if request.method == 'POST' and request.url.path in ('/v1/messages','/v1/chat/completions','/v1/responses'):
            try:
                payload = await request.json()
            except ValueError:
                return JSONResponse({'type':'error','error':{'type':'invalid_request_error','message':'Invalid JSON'}},status_code=400)
            if not isinstance(payload,dict) or payload.get('model') not in MODEL_IDS:
                return JSONResponse({'type':'error','error':{'type':'invalid_request_error','message':'Use claude-opus-5-5 or claude-sonnet-5-5. Automatic fallback and mock-model replies are disabled.'}},status_code=400)
        return await call_next(request)
    return server

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'login':
        from perplexity_web_mcp.cli import auth
        def save_without_display(token):
            if not token_store.save_token(token):
                raise RuntimeError('Could not save the local login session.')
            state, info = auth.probe_session(token)
            result = {'authenticated': state.value == 'valid', 'state': state.value,
                      'tier': info.subscription_tier.value if info else None}
            (PRIVATE / 'login-status.json').write_text(json.dumps(result), encoding='utf-8')
            auth.console.print('[green]Login saved locally. Session token is not displayed.[/green]')
            auth.console.print('Account tier: ' + str(result['tier']))
        auth._display_and_save_token = save_without_display
        auth._show_exit_message = lambda: None
    if len(sys.argv) > 1 and sys.argv[1] == 'api':
        configure_api()
    from perplexity_web_mcp.cli.main import main
    main()
