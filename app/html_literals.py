"""Read declarative JavaScript object literals; never execute imported scripts."""
import ast
import re

TOKEN = re.compile(r'''\s+|//[^\n]*|/\*[\s\S]*?\*/|'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?|[A-Za-z_$][\w$]*|[\s\S]''')


def declared_fields(script):
    tokens = []
    def parse(index, depth=0):
        if depth > 30 or index >= len(tokens): raise ValueError('literal depth')
        token = tokens[index]
        if token in ('{', '['):
            result = {} if token == '{' else []
            close = '}' if token == '{' else ']'
            index += 1
            while index < len(tokens) and tokens[index] != close:
                if token == '{':
                    key = tokens[index]
                    key = ast.literal_eval(key) if key.startswith(('"', "'")) else key
                    if tokens[index+1] != ':': raise ValueError('nonliteral object')
                    value, index = parse(index+2, depth+1)
                    result[key] = value
                else:
                    value, index = parse(index, depth+1); result.append(value)
                if tokens[index] == ',': index += 1
                elif tokens[index] != close: raise ValueError('expression')
            if index >= len(tokens): raise ValueError('unclosed')
            return result, index+1
        if token.startswith(('"', "'")):
            return ast.literal_eval(token), index+1
        if re.fullmatch(r'-?\d+(?:\.\d+)?', token):
            return float(token) if '.' in token else int(token), index+1
        if token in ('true', 'false', 'null', 'undefined'):
            return {'true': True, 'false': False, 'null': None, 'undefined': None}[token], index+1
        raise ValueError('computed value')

    result = []
    # Start at a declarative field object, so unrelated JavaScript regex literals
    # do not confuse string/comment tokenization of the surrounding program.
    for candidate in list(re.finditer(r'''\{\s*(?:k|key|["'](?:k|key)["'])\s*:''', script))[:1500]:
        tokens = []
        balance = 0
        for m in TOKEN.finditer(script[candidate.start():candidate.start()+100000]):
            token = m.group()
            if token.isspace() or token.startswith(('//','/*')): continue
            tokens.append(token)
            if token in ('{','['): balance += 1
            elif token in ('}',']'): balance -= 1
            if balance == 0: break
        try:
            obj, _ = parse(0)
        except (ValueError, SyntaxError, IndexError, TypeError):
            continue
        if isinstance(obj, dict) and obj.get('type') and (obj.get('k') or obj.get('key')):
            result.append(obj)
    return result
