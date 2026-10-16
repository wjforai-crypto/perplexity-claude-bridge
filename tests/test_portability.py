import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PortabilityTests(unittest.TestCase):
    def test_initialization_keeps_key_and_helper_uses_utf8(self):
        with tempfile.TemporaryDirectory(prefix='bridge portable ') as temp:
            state = Path(temp) / 'private'
            env = dict(os.environ, PWM_PRIVATE_DIR=str(state), PYTHONIOENCODING='gbk')
            for attempt in range(2):
                result = subprocess.run([sys.executable, str(ROOT / 'initialize.py')],
                                        env=env, capture_output=True, check=True)
                current = (state / 'api-key.txt').read_text(encoding='utf-8')
                self.assertNotIn(current.strip().encode(), result.stdout + result.stderr)
                if attempt == 0:
                    original = current
                else:
                    self.assertEqual(original, current)
            fixture = Path(temp) / 'sample.txt'
            fixture.write_text('local offline fixture', encoding='utf-8')
            code = '''import httpx,runpy,sys
class Response:
 status_code=200
 def json(self):return {'content':[{'text':'红色，然后蓝色。'}]}
class Client:
 def __init__(self,*a,**k):pass
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def post(self,*a,**k):return Response()
httpx.Client=Client
root=sys.argv[1]
fixture=sys.argv[2]
sys.path.insert(0,root)
sys.argv=['file_question.py','--file',fixture,'--prompt','encoding probe']
runpy.run_path(root+'/file_question.py',run_name='__main__')
'''
            result = subprocess.run([sys.executable, '-c', code, str(ROOT), str(fixture)],
                                    env=env, capture_output=True, check=True)
            self.assertEqual(json.loads(result.stdout.decode('utf-8'))['answer'], '红色，然后蓝色。')
            self.assertNotIn(original.strip().encode(), result.stdout + result.stderr)

    def test_tool_instruction_uses_this_installation(self):
        sys.path.insert(0, str(ROOT))
        from anthropic_bridge import PROTOCOL
        expected = shlex.join([Path(sys.executable).resolve().as_posix(), (ROOT / 'file_question.py').as_posix()])
        self.assertIn(expected, PROTOCOL)
        self.assertNotIn('__LOCAL_HELPER_COMMAND__', PROTOCOL)


if __name__ == '__main__':
    unittest.main(verbosity=2)
